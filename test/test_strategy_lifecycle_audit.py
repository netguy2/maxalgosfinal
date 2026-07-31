"""
Regression tests for the full strategy-lifecycle audit (creation -> signal ->
order placement) across all four independent strategy surfaces:

  1. Marketplace webhook engine  (blueprints/strategy.py, services/signal_engine.py)
  2. Flow no-code builder        (services/flow_executor_service.py, flow_maxalgos_client.py)
  3. Python Strategy Host        (blueprints/python_strategy.py)
  4. Strategy Builder/Portfolio  (blueprints/strategy_portfolio.py)

These tests target the highest-risk findings from the audit: could a user lose
money, place a wrong order, or NOT KNOW their strategy stopped working.

All broker HTTP calls / socketio emits are mocked. Nothing hits a live
endpoint or a real socket connection.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Same restx_api/place_order_service circular-import dodge used in the other
# order-flow test files in this suite.
import restx_api  # noqa: F401

from events.order_events import OrderFailedEvent, OrderPlacedEvent


# ---------------------------------------------------------------------------
# 1. Marketplace webhook engine: broker-order-failure notification is
#    silently dropped for signal_engine.py's internal auth_token+broker call
#    shape (no api_key). This is the #1 highest-risk finding: a user believes
#    their marketplace strategy is trading while orders silently fail.
# ---------------------------------------------------------------------------

class TestMarketplaceWebhookFailureVisibility:
    def test_order_failed_event_with_no_api_key_falls_back_to_username(self):
        """FIXED: signal_engine.py places orders via the internal
        auth_token+broker path, which never sets OrderFailedEvent's api_key
        field. Previously subscribers/socketio_subscriber.py's
        _room_for_event couldn't resolve a room without api_key and
        returned None, silently dropping the notification. Now OrderEvent
        carries an explicit `username` field (populated from
        strategy.user_id/dep.user_id at every signal_engine.py call site,
        see services/place_order_service.py's place_order(username=...)
        param) that _room_for_event falls back to when api_key is empty."""
        import subscribers.socketio_subscriber as sub

        event = OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data={"symbol": "SBIN", "exchange": "NSE"},
            response_data={"status": "error", "message": "RMS:Margin Exceeded"},
            api_key="",  # signal_engine.py's place_order(auth_token=..., broker=...) never sets this
            username="strategy_owner",  # ...but now sets this instead
            strategy="MarketplaceStrategy1",
            symbol="SBIN",
            exchange="NSE",
            error_message="RMS:Margin Exceeded",
        )

        room = sub._room_for_event(event)
        assert room == "user_strategy_owner", (
            "Expected _room_for_event to fall back to event.username when "
            "api_key is empty -- if this is None again, the username "
            "fallback regressed."
        )

    def test_order_failed_event_with_neither_api_key_nor_username_still_drops(self):
        """Contrast case: if NEITHER api_key nor username is set (should not
        happen for any real call site after the fix, but confirms the drop
        behavior is still the safe fallback rather than crashing)."""
        import subscribers.socketio_subscriber as sub

        event = OrderFailedEvent(
            mode="live", api_type="placeorder", api_key="", username="",
            strategy="MarketplaceStrategy1", symbol="SBIN", exchange="NSE",
            error_message="RMS:Margin Exceeded",
        )

        room = sub._room_for_event(event)
        assert room is None

    def test_emit_scoped_emits_when_username_fallback_resolves_a_room(self):
        """End-to-end: _emit_scoped must actually call socketio.emit with
        the username-derived room when api_key is empty but username is
        set -- confirms the fix works at the transport layer, not just in
        room-resolution."""
        import subscribers.socketio_subscriber as sub

        event = OrderFailedEvent(
            mode="live", api_type="placeorder", api_key="", username="strategy_owner",
            strategy="MarketplaceStrategy1", symbol="SBIN", exchange="NSE",
            error_message="RMS:Margin Exceeded",
        )

        with patch.object(sub, "socketio") as mock_socketio:
            sub._emit_scoped("order_event", {"foo": "bar"}, event)

        mock_socketio.emit.assert_called_once_with("order_event", {"foo": "bar"}, room="user_strategy_owner")

    def test_order_placed_event_with_valid_api_key_is_broadcast_correctly(self):
        """Contrast case: the normal REST/API-key path (external webhook
        callers, UI-initiated orders) DOES get a room and DOES emit --
        confirms the drop is specific to the internal auth_token+broker
        call shape, not a blanket regression."""
        import subscribers.socketio_subscriber as sub

        event = OrderPlacedEvent(
            mode="live", api_type="placeorder", api_key="validkey123",
            strategy="ManualOrder", symbol="SBIN", exchange="NSE",
        )

        with patch("database.auth_db.verify_api_key", return_value="testuser"):
            room = sub._room_for_event(event)

        assert room == "user_testuser"


# ---------------------------------------------------------------------------
# 2. Marketplace webhook engine: internal auth_token+broker calls are
#    exempt from place_order_service's duplicate-webhook dedup fingerprint
#    check by design (that dedup only applies to the api_key path). This
#    means signal_engine.py's OWN webhook-level dedup (webhook_delivery_service)
#    is the only protection -- confirm the exemption is real.
# ---------------------------------------------------------------------------

class TestSignalEngineExemptFromPlaceOrderDedup:
    def test_internal_call_bypasses_place_order_fingerprint_dedup(self):
        """Confirms signal_engine.py's calling convention (auth_token+broker,
        no api_key) is exempt from place_order_service.py's dedup, as
        documented in that module's own comment. This means a webhook-layer
        dedup failure (see webhook_delivery race, not covered here since it
        requires true DB-level concurrency to exercise meaningfully) has NO
        second line of defense on this surface."""
        import broker.zerodha.api.order_api as zerodha_order_api
        import services.place_order_service as place_order_service

        place_order_service._recent_order_fingerprints.clear()

        order_data = {
            "strategy": "MarketplaceStrategy1", "symbol": "SBIN", "exchange": "NSE",
            "action": "BUY", "quantity": "1", "pricetype": "MARKET", "product": "MIS",
        }

        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):

            success1, _, status1 = place_order_service.place_order(
                dict(order_data), auth_token="faketoken", broker="zerodha"
            )
            success2, _, status2 = place_order_service.place_order(
                dict(order_data), auth_token="faketoken", broker="zerodha"
            )

        assert success1 is True and status1 == 200
        assert success2 is True and status2 == 200, (
            "Two identical internal (auth_token+broker) calls both succeeded -- "
            "confirms this call path is exempt from place_order()'s fingerprint "
            "dedup. If this assertion fails, the exemption was removed and "
            "signal_engine.py's own webhook-level dedup may now be redundant "
            "(or conflicting) with this one."
        )


class TestPlaceOrderThreadsUsernameIntoEvents:
    def test_internal_call_username_reaches_published_order_failed_event(self):
        """FIXED, end-to-end: place_order(auth_token=..., broker=...,
        username=...) -- the exact call shape signal_engine.py now uses --
        must publish an OrderFailedEvent whose `username` field is set, so
        socketio_subscriber.py can scope the notification instead of
        dropping it. Verified by capturing the real Event object passed to
        bus.publish(), not by patching internals of place_order_service
        itself."""
        import broker.zerodha.api.order_api as zerodha_order_api
        import services.place_order_service as place_order_service

        order_data = {
            "strategy": "MarketplaceStrategy1", "symbol": "SBIN", "exchange": "NSE",
            "action": "BUY", "quantity": "1", "pricetype": "MARKET", "product": "MIS",
        }

        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "error", "message": "RMS:Margin Exceeded"}, None

        captured_events = []

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api), \
             patch.object(place_order_service.bus, "publish", side_effect=captured_events.append):
            place_order_service.place_order(
                dict(order_data), auth_token="faketoken", broker="zerodha",
                username="strategy_owner",
            )

        failed_events = [e for e in captured_events if isinstance(e, OrderFailedEvent)]
        assert len(failed_events) == 1
        assert failed_events[0].username == "strategy_owner"
        assert failed_events[0].api_key == ""


# ---------------------------------------------------------------------------
# 3. Flow: diamond/parallel-branch graphs can double-fire orders in one
#    execution pass. The place_order dedup only accidentally catches this
#    when both branches produce byte-identical orders (because Flow always
#    hardcodes strategy="flow_workflow"); any difference in a fingerprinted
#    field (quantity, price, symbol) lets both through.
# ---------------------------------------------------------------------------

class TestFlowDiamondBranchDoubleOrder:
    def _place_via_flow_client(self, symbol, quantity, api_key="flowkey"):
        import broker.zerodha.api.order_api as zerodha_order_api
        import services.place_order_service as place_order_service
        from services.flow_maxalgos_client import FlowMaxAlgosClient

        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        client = FlowMaxAlgosClient(api_key=api_key)

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch("services.order_router_service.should_route_to_pending", return_value=False), \
             patch.object(place_order_service, "get_auth_token_broker", return_value=("faketoken", "zerodha")), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):
            return client.place_order(
                symbol=symbol, exchange="NSE", action="BUY",
                quantity=quantity, product_type="MIS", price_type="MARKET",
            )

    def test_two_branches_producing_identical_orders_are_deduped_by_coincidence(self):
        """A diamond graph where both branches resolve to the SAME order
        (same symbol/qty/etc.) happens to get caught by place_order_service's
        fingerprint dedup -- both calls use strategy="flow_workflow"
        (FlowMaxAlgosClient's hardcoded default, services/flow_maxalgos_client.py:74),
        so the fingerprints collide."""
        import services.place_order_service as place_order_service
        place_order_service._recent_order_fingerprints.clear()

        result1 = self._place_via_flow_client("SBIN", 10)
        result2 = self._place_via_flow_client("SBIN", 10)

        assert result1.get("status") == "success"
        assert result2.get("status") == "error", (
            "Expected the second identical branch's order to be suppressed as a "
            "duplicate -- this is the ONLY protection Flow's diamond-graph "
            "double-fire risk currently has, and it only works because both "
            "branches happened to produce byte-identical orders."
        )

    def test_two_branches_producing_different_quantities_both_place_orders(self):
        """REGRESSION-DOCUMENTING (Flow finding #1, highest risk): if the two
        branches of a diamond graph resolve to orders that differ in ANY
        fingerprinted field (here: quantity), the dedup fingerprint differs
        and BOTH orders reach the broker -- there is no structural protection
        against a diamond/parallel-branch graph double-firing distinct
        orders. This is the actual money-risk scenario: a user's graph with
        two condition chains converging on similar-but-not-identical order
        configs (e.g. different position-sizing per branch) can silently
        double a position."""
        import services.place_order_service as place_order_service
        place_order_service._recent_order_fingerprints.clear()

        result1 = self._place_via_flow_client("SBIN", 10)
        result2 = self._place_via_flow_client("SBIN", 20)  # different quantity -> different fingerprint

        assert result1.get("status") == "success"
        assert result2.get("status") == "success", (
            "Both branch orders succeeded independently -- confirms Flow has "
            "NO structural double-fire protection beyond the coincidental "
            "fingerprint match for byte-identical orders. If this assertion "
            "starts failing, cross-branch dedup protection was added to Flow."
        )


class TestFlowExecuteNodeChainSkipsRepeatOrderNode:
    """FIXED: execute_node_chain (services/flow_executor_service.py) now
    tracks executed order-action nodes per run and skips a second
    execution of the SAME order node, regardless of what the two paths'
    upstream branches computed -- this is the structural fix for the
    diamond-graph double-fire risk (the two test classes above exercise
    the OLD place_order-layer-only mitigation, which is coincidental and
    still has gaps by design; this class exercises the actual graph-walk
    fix)."""

    def _build_diamond_graph(self):
        """start -> condA (True) -> order1
           start -> condB (True) -> order1   (same order node, two paths)
        """
        nodes = [
            {"id": "start", "type": "start", "data": {}},
            {"id": "condA", "type": "priceCondition", "data": {}},
            {"id": "condB", "type": "priceCondition", "data": {}},
            {"id": "order1", "type": "placeOrder", "data": {
                "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
                "quantity": "10", "product": "MIS", "priceType": "MARKET",
            }},
        ]
        edges = [
            {"source": "start", "target": "condA"},
            {"source": "start", "target": "condB"},
            {"source": "condA", "target": "order1"},
            {"source": "condB", "target": "order1"},
        ]
        edge_map: dict = {}
        incoming_edge_map: dict = {}
        for edge in edges:
            edge_map.setdefault(edge["source"], []).append(edge)
            incoming_edge_map.setdefault(edge["target"], []).append(edge)
        return nodes, edge_map, incoming_edge_map

    def test_diamond_graph_places_order_only_once(self):
        from services.flow_executor_service import (
            NodeExecutor,
            WorkflowContext,
            execute_node_chain,
        )

        nodes, edge_map, incoming_edge_map = self._build_diamond_graph()

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "success", "orderid": "1"}

        logs = []
        executor = NodeExecutor(client=mock_client, context=WorkflowContext(), logs=logs)
        visited_count: dict = {}
        executed_order_nodes: set = set()

        # Manually drive both branches to reach order1, as execute_workflow
        # would when both condA and condB evaluate True -- condition
        # evaluation itself isn't the fix under test here, direct-order-node
        # graph traversal is.
        execute_node_chain(
            "order1", nodes, edge_map, incoming_edge_map, executor,
            executor.context, visited_count, depth=1,
            executed_order_nodes=executed_order_nodes,
        )
        execute_node_chain(
            "order1", nodes, edge_map, incoming_edge_map, executor,
            executor.context, visited_count, depth=1,
            executed_order_nodes=executed_order_nodes,
        )

        assert mock_client.place_order.call_count == 1, (
            "Expected the order node to execute only once across both "
            "paths reaching it in the same run -- if this is 2, the "
            "double-fire fix regressed."
        )
        warning_logs = [entry for entry in logs if entry.get("level") == "warning"]
        assert any("already executed" in entry.get("message", "") for entry in warning_logs)

    def test_non_order_nodes_are_not_restricted_to_single_execution(self):
        """Contrast case: a data/read-only node reached via two paths in
        one run is NOT blocked by this fix -- only order-action node types
        are restricted to a single execution per run."""
        from services.flow_executor_service import (
            NodeExecutor,
            WorkflowContext,
            execute_node_chain,
        )

        nodes = [
            {"id": "quote1", "type": "getQuote", "data": {"symbol": "SBIN", "exchange": "NSE"}},
        ]
        edge_map: dict = {}
        incoming_edge_map: dict = {}

        mock_client = MagicMock()
        mock_client.get_quotes.return_value = {"status": "success", "ltp": 500}

        logs = []
        executor = NodeExecutor(client=mock_client, context=WorkflowContext(), logs=logs)
        visited_count: dict = {}
        executed_order_nodes: set = set()

        execute_node_chain(
            "quote1", nodes, edge_map, incoming_edge_map, executor,
            executor.context, visited_count, depth=1,
            executed_order_nodes=executed_order_nodes,
        )
        execute_node_chain(
            "quote1", nodes, edge_map, incoming_edge_map, executor,
            executor.context, visited_count, depth=1,
            executed_order_nodes=executed_order_nodes,
        )

        assert mock_client.get_quotes.call_count == 2, (
            "A read-only data node reached twice in one run should execute "
            "twice -- this fix is scoped to order-action node types only."
        )


# ---------------------------------------------------------------------------
# 4. Flow: execution failures are now persisted to FlowWorkflowExecution.
#    A broker-rejected order still doesn't raise inside execute_node_chain
#    (the graph walk correctly continues to sibling branches), but the
#    failure is now tracked precisely via order_failures and used to set
#    status="completed_with_errors" instead of a bare "completed", with the
#    full logs list saved to the DB in one write at the end of the run.
# ---------------------------------------------------------------------------

class TestFlowExecutionFailureNotPersisted:
    def test_execute_place_order_failure_does_not_raise_or_abort_chain(self):
        """A failed order inside execute_place_order must not raise --
        the graph walk must continue to sibling branches even after one
        order-action node fails. Failure detection is now precise
        (order_failures, checked below) rather than absent."""
        from services.flow_executor_service import NodeExecutor, WorkflowContext

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "error", "message": "Broker rejected: RMS Margin Exceeded"}

        logs = []
        executor = NodeExecutor(client=mock_client, context=WorkflowContext(), logs=logs)
        node_data = {
            "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
            "quantity": "10", "product": "MIS", "priceType": "MARKET",
        }

        # Must not raise despite the broker rejection.
        result = executor.execute_place_order(node_data)

        assert result is not None
        assert result.get("status") == "error"
        error_entries = [entry for entry in logs if entry.get("level") == "error"]
        assert len(error_entries) > 0, "expected an error entry in the in-memory logs list"

    def test_execute_node_chain_records_order_failure_precisely(self):
        """FIXED: execute_node_chain now populates an order_failures list
        directly from result.status for ORDER_ACTION_NODE_TYPES nodes, not
        by re-parsing log message text -- confirms the signal execute_workflow
        uses to decide completed vs completed_with_errors is populated."""
        from services.flow_executor_service import (
            NodeExecutor,
            WorkflowContext,
            execute_node_chain,
        )

        nodes = [{"id": "order1", "type": "placeOrder", "data": {
            "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
            "quantity": "10", "product": "MIS", "priceType": "MARKET",
        }}]

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "error", "message": "RMS:Margin Exceeded"}

        executor = NodeExecutor(client=mock_client, context=WorkflowContext(), logs=[])
        order_failures: list = []

        execute_node_chain(
            "order1", nodes, {}, {}, executor, executor.context, {}, depth=0,
            executed_order_nodes=set(), order_failures=order_failures,
        )

        assert len(order_failures) == 1
        assert order_failures[0]["node_id"] == "order1"
        assert order_failures[0]["node_type"] == "placeOrder"

    def test_execute_node_chain_does_not_record_success_as_a_failure(self):
        """Contrast case: a successful order-action node must not appear in
        order_failures."""
        from services.flow_executor_service import (
            NodeExecutor,
            WorkflowContext,
            execute_node_chain,
        )

        nodes = [{"id": "order1", "type": "placeOrder", "data": {
            "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
            "quantity": "10", "product": "MIS", "priceType": "MARKET",
        }}]

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "success", "orderid": "1"}

        executor = NodeExecutor(client=mock_client, context=WorkflowContext(), logs=[])
        order_failures: list = []

        execute_node_chain(
            "order1", nodes, {}, {}, executor, executor.context, {}, depth=0,
            executed_order_nodes=set(), order_failures=order_failures,
        )

        assert order_failures == []

    def test_execute_workflow_saves_logs_and_marks_completed_with_errors(self):
        """FIXED end-to-end: a workflow whose only node is a failing
        placeOrder must (a) persist the full logs list via
        save_execution_logs, and (b) set status='completed_with_errors',
        not a bare 'completed' that hides the failure."""
        import services.flow_executor_service as flow_executor_service

        fake_workflow = MagicMock()
        fake_workflow.nodes = [
            {"id": "start", "type": "start", "data": {}},
            {"id": "order1", "type": "placeOrder", "data": {
                "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
                "quantity": "10", "product": "MIS", "priceType": "MARKET",
            }},
        ]
        fake_workflow.edges = [{"source": "start", "target": "order1"}]
        fake_workflow.name = "Test Workflow"
        fake_workflow.broker = None

        fake_execution = MagicMock()
        fake_execution.id = 42

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "error", "message": "RMS:Margin Exceeded"}

        with patch.object(flow_executor_service, "is_kill_switch_active", return_value=False, create=True), \
             patch("database.settings_db.is_kill_switch_active", return_value=False), \
             patch("utils.socket_scope.username_from_api_key", return_value="testuser"), \
             patch.object(flow_executor_service, "get_workflow", return_value=fake_workflow), \
             patch.object(flow_executor_service, "create_execution", return_value=fake_execution), \
             patch.object(flow_executor_service, "get_flow_client", return_value=mock_client), \
             patch.object(flow_executor_service, "update_execution_status") as mock_update_status, \
             patch.object(flow_executor_service, "save_execution_logs") as mock_save_logs:

            result = flow_executor_service.execute_workflow(workflow_id=1, api_key="testkey")

        mock_update_status.assert_called_once_with(42, "completed_with_errors")
        mock_save_logs.assert_called_once()
        saved_execution_id, saved_logs = mock_save_logs.call_args[0]
        assert saved_execution_id == 42
        assert len(saved_logs) > 0
        assert result["status"] == "error"
        assert len(result["order_failures"]) == 1

    def test_execute_workflow_marks_completed_when_all_orders_succeed(self):
        """Contrast case: a fully successful run must still get plain
        'completed', not 'completed_with_errors'."""
        import services.flow_executor_service as flow_executor_service

        fake_workflow = MagicMock()
        fake_workflow.nodes = [
            {"id": "start", "type": "start", "data": {}},
            {"id": "order1", "type": "placeOrder", "data": {
                "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
                "quantity": "10", "product": "MIS", "priceType": "MARKET",
            }},
        ]
        fake_workflow.edges = [{"source": "start", "target": "order1"}]
        fake_workflow.name = "Test Workflow"
        fake_workflow.broker = None

        fake_execution = MagicMock()
        fake_execution.id = 43

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"status": "success", "orderid": "1"}

        with patch("database.settings_db.is_kill_switch_active", return_value=False), \
             patch("utils.socket_scope.username_from_api_key", return_value="testuser"), \
             patch.object(flow_executor_service, "get_workflow", return_value=fake_workflow), \
             patch.object(flow_executor_service, "create_execution", return_value=fake_execution), \
             patch.object(flow_executor_service, "get_flow_client", return_value=mock_client), \
             patch.object(flow_executor_service, "update_execution_status") as mock_update_status, \
             patch.object(flow_executor_service, "save_execution_logs"):

            result = flow_executor_service.execute_workflow(workflow_id=1, api_key="testkey")

        mock_update_status.assert_called_once_with(43, "completed")
        assert result["status"] == "success"
        assert result["order_failures"] == []


# ---------------------------------------------------------------------------
# 5. Strategy Portfolio: FIXED -- per-user scoping added to the
#    strategy_portfolio table (user_id column + _owned_by filter on every
#    read/write function, mirroring database/flow_db.py's FlowWorkflow
#    ownership convention exactly: NULL user_id = legacy/unowned, visible
#    to everyone; owned rows are only visible/mutable by their owner).
# ---------------------------------------------------------------------------

class TestStrategyPortfolioNoUserScoping:
    """Exercises the real functions against the actual configured DB
    (strategy_portfolio_db.py's own engine/session) rather than mocking --
    this table has no FK dependencies, so real create/read/update/delete
    round-trips are cheap and precise. Every row created by these tests is
    cleaned up in a finally block."""

    @classmethod
    def setup_class(cls):
        # Several other test modules in this suite do
        # os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:") at
        # import time (test_order_gate.py, test_mapping_conditions.py,
        # etc.) -- setdefault means whichever one is collected FIRST in
        # the full pytest run wins for every module that reads
        # DATABASE_URL lazily afterward, including
        # strategy_portfolio_db.py's own module-level engine. Combined
        # with the project-wide NullPool policy for SQLite (every
        # checkout is a fresh connection -- see database/engine_factory.py),
        # an in-memory DB effectively resets to empty on every single
        # operation, so create_all() from one connection is invisible to
        # a later save/get call on the next connection: "no such table"
        # regardless of how many times init_db() is called first. This is
        # a pre-existing test-isolation gap in the wider suite, not
        # something this fix introduced -- work around it here by
        # rebinding this module's engine/session to a dedicated,
        # real file-backed SQLite DB for the duration of this class,
        # independent of whatever DATABASE_URL another test file left
        # behind, then create the (now up-to-date-with-migrations) table
        # on it directly.
        import tempfile

        import database.strategy_portfolio_db as spdb
        from sqlalchemy.orm import scoped_session, sessionmaker

        from database.engine_factory import create_db_engine

        cls._tmp_db_fd, cls._tmp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls._tmp_db_fd)
        test_engine = create_db_engine(f"sqlite:///{cls._tmp_db_path}")
        spdb.engine = test_engine
        spdb.db_session = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        )
        spdb.Base.query = spdb.db_session.query_property()
        spdb.Base.metadata.create_all(bind=test_engine)

    @classmethod
    def teardown_class(cls):
        try:
            os.unlink(cls._tmp_db_path)
        except OSError:
            pass

    def _cleanup(self, entry_id, user_id):
        from database.strategy_portfolio_db import delete_portfolio_entry
        if entry_id is not None:
            delete_portfolio_entry(entry_id, user_id)

    def test_user_cannot_read_another_users_entry(self):
        from database.strategy_portfolio_db import get_portfolio_entry, save_portfolio_entry

        row = save_portfolio_entry(
            user_id="alice", name="Alice's Iron Condor", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs=[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}],
        )
        assert row is not None
        entry_id = row["id"]

        try:
            as_owner = get_portfolio_entry(entry_id, "alice")
            as_other_user = get_portfolio_entry(entry_id, "bob")

            assert as_owner is not None
            assert as_owner["name"] == "Alice's Iron Condor"
            assert as_other_user is None, (
                "bob must not be able to read alice's strategy -- if this is "
                "not None, per-user scoping regressed."
            )
        finally:
            self._cleanup(entry_id, "alice")

    def test_user_cannot_update_another_users_entry(self):
        from database.strategy_portfolio_db import get_portfolio_entry, save_portfolio_entry

        row = save_portfolio_entry(
            user_id="alice", name="Alice's Strategy", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs=[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}],
        )
        entry_id = row["id"]

        try:
            tampered = save_portfolio_entry(
                user_id="bob", entry_id=entry_id, name="Tampered By Bob",
                watchlist="mytrades", underlying="NIFTY", exchange="NFO",
                expiry="28-08-2026",
                legs=[{"strike": 99999, "optionType": "PE", "action": "BUY", "lots": 100}],
            )
            assert tampered is None, (
                "bob's update of alice's entry_id must fail (return None, "
                "same as 'not found') -- if this succeeded, another user "
                "could silently alter alice's saved legs."
            )

            unchanged = get_portfolio_entry(entry_id, "alice")
            assert unchanged["name"] == "Alice's Strategy"
        finally:
            self._cleanup(entry_id, "alice")

    def test_user_cannot_delete_another_users_entry(self):
        from database.strategy_portfolio_db import delete_portfolio_entry, get_portfolio_entry, save_portfolio_entry

        row = save_portfolio_entry(
            user_id="alice", name="Alice's Strategy 2", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs=[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}],
        )
        entry_id = row["id"]

        try:
            deleted_by_bob = delete_portfolio_entry(entry_id, "bob")
            assert deleted_by_bob is False, (
                "bob must not be able to delete alice's entry -- if this "
                "returned True, cross-user deletion is possible again."
            )
            assert get_portfolio_entry(entry_id, "alice") is not None
        finally:
            self._cleanup(entry_id, "alice")

    def test_list_portfolio_excludes_other_users_entries(self):
        from database.strategy_portfolio_db import list_portfolio, save_portfolio_entry

        row_a = save_portfolio_entry(
            user_id="alice", name="Alice Only", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs=[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}],
        )
        row_b = save_portfolio_entry(
            user_id="bob", name="Bob Only", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs=[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}],
        )

        try:
            alice_view = list_portfolio("alice")
            alice_names = {item["name"] for item in alice_view}
            assert "Alice Only" in alice_names
            assert "Bob Only" not in alice_names, (
                "alice's portfolio listing must not include bob's entries."
            )
        finally:
            self._cleanup(row_a["id"], "alice")
            self._cleanup(row_b["id"], "bob")

    def test_legacy_unowned_row_remains_visible_to_any_user(self):
        """Pre-migration rows have user_id=NULL -- confirms these stay
        readable/mutable by any user rather than becoming permanently
        inaccessible after the migration (matches database/flow_db.py's
        documented legacy-row behavior)."""
        from database.strategy_portfolio_db import (
            StrategyPortfolio,
            db_session,
            get_portfolio_entry,
        )

        legacy_row = StrategyPortfolio(
            user_id=None, name="Legacy Unowned Strategy", watchlist="mytrades",
            underlying="NIFTY", exchange="NFO", expiry="28-08-2026",
            legs_json='[{"strike": 24000, "optionType": "CE", "action": "SELL", "lots": 1}]',
        )
        db_session.add(legacy_row)
        db_session.commit()
        entry_id = legacy_row.id

        try:
            seen_by_alice = get_portfolio_entry(entry_id, "alice")
            seen_by_bob = get_portfolio_entry(entry_id, "bob")
            assert seen_by_alice is not None
            assert seen_by_bob is not None
        finally:
            db_session.delete(legacy_row)
            db_session.commit()

    def test_strategy_portfolio_model_has_user_id_column(self):
        """Confirms the schema-level fix: user_id column now exists."""
        from database.strategy_portfolio_db import StrategyPortfolio

        column_names = [c.name.lower() for c in StrategyPortfolio.__table__.columns]
        assert "user_id" in column_names


# ---------------------------------------------------------------------------
# 6. Marketplace webhook engine: FIXED -- toggle_strategy now invalidates
#    both _strategy_webhook_cache and _user_strategies_cache, mirroring
#    delete_strategy's existing cache-invalidation exactly. Previously a
#    paused strategy's cached is_active=True Strategy object could still be
#    served to the async signal-processing worker pool for up to the
#    cache's 5-minute TTL, meaning "pause" wasn't guaranteed to block the
#    very next incoming webhook signal.
# ---------------------------------------------------------------------------

class TestStrategyToggleCacheInvalidation:
    def test_toggle_strategy_clears_webhook_cache_entry(self):
        """End-to-end against the real cache object (a TTLCache instance)
        and the real toggle_strategy function, with get_strategy mocked to
        avoid a DB round-trip -- confirms a cache entry seeded before the
        toggle is gone immediately after."""
        import database.strategy_db as strategy_db

        fake_strategy = SimpleNamespace(
            id=1, webhook_id="wh-abc123", user_id="alice", is_active=True,
        )

        # Seed the cache the way get_strategy_by_webhook_id would after a
        # prior lookup, before the toggle happens.
        strategy_db._strategy_webhook_cache["wh-abc123"] = fake_strategy
        strategy_db._user_strategies_cache["user_alice"] = [fake_strategy]

        with patch.object(strategy_db, "get_strategy", return_value=fake_strategy), \
             patch.object(strategy_db.db_session, "commit"):
            strategy_db.toggle_strategy(1)

        assert "wh-abc123" not in strategy_db._strategy_webhook_cache, (
            "Expected toggle_strategy to invalidate the webhook cache entry -- "
            "if this is still present, a paused strategy's webhook lookup could "
            "keep returning the stale pre-toggle object for up to 5 minutes."
        )
        assert "user_alice" not in strategy_db._user_strategies_cache

    def test_delete_strategy_still_invalidates_cache_as_contrast(self):
        """Contrast case: delete_strategy's own cache invalidation (the
        pattern toggle_strategy now mirrors) must still work."""
        import inspect

        import database.strategy_db as strategy_db

        delete_source = inspect.getsource(strategy_db.delete_strategy)
        assert "_strategy_webhook_cache" in delete_source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
