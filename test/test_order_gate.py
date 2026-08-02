"""Regression tests for the shared order gate (services/order_gate.py).

Five separate services call a broker's order API directly; only one of them
routed through place_order_service's checks. Before this gate, flipping the
master kill switch left basket, split, smart, and GTT orders reaching live
brokers from the REST API, the Flow builder, and Action Center approvals.

These tests pin the three properties that make the gate trustworthy:
  1. An active kill switch blocks live orders.
  2. The check fails OPEN on error, and raises an alarm when it does.
  3. Every one of the five call sites actually calls it (guards against a new
     order path being added without a gate -- the exact drift that caused this).
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import types

import pytest

from services import order_gate


TEST_API_KEY = "test-api-key"
TEST_USER = "testuser"


def _stub_kill_switch(monkeypatch, active=False, raises=False):
    """Stub the per-user kill-switch lookup.

    `is_kill_switch_active` takes a username now -- the switch is per-user
    (see database/settings_db.py), so the gate resolves the order's owner
    from its api_key before checking. The stub accepts (and ignores) that
    argument, returning the same flag for whichever user is asked about.
    """

    def is_kill_switch_active(username=None):
        if raises:
            raise RuntimeError("settings table unavailable")
        return active

    mod = types.ModuleType("database.settings_db")
    mod.is_kill_switch_active = is_kill_switch_active
    monkeypatch.setitem(sys.modules, "database.settings_db", mod)

    # The gate resolves api_key -> username before the check; stub that too
    # so these tests exercise the gate itself, not the auth lookup.
    monkeypatch.setattr(
        "utils.socket_scope.username_from_api_key", lambda key: TEST_USER if key else None
    )


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(
        order_gate, "_alert_gate_failed_open",
        lambda context, err: sent.append((context, str(err))),
    )
    return sent


def test_kill_switch_inactive_allows_order(monkeypatch):
    _stub_kill_switch(monkeypatch, active=False)
    allowed, err, status = order_gate.check_order_allowed(
        "order placement", api_key=TEST_API_KEY
    )
    assert allowed is True
    assert err is None


def test_kill_switch_active_blocks_order(monkeypatch):
    _stub_kill_switch(monkeypatch, active=True)
    allowed, err, status = order_gate.check_order_allowed(
        "basket order", api_key=TEST_API_KEY
    )
    assert allowed is False
    assert status == 403
    assert err["code"] == "KILL_SWITCH_ACTIVE"
    assert err["status"] == "error"


def test_explicit_username_is_honoured(monkeypatch):
    """Callers that already know the owner can pass it directly instead of
    an api_key."""
    _stub_kill_switch(monkeypatch, active=True)
    allowed, _err, status = order_gate.check_order_allowed(
        "order placement", username=TEST_USER
    )
    assert allowed is False
    assert status == 403


def test_unresolvable_owner_fails_open(monkeypatch):
    """An order with no resolvable owner must NOT be blocked by some other
    user's kill switch -- the switch is per-user, so with no identity there
    is no switch that legitimately applies."""
    _stub_kill_switch(monkeypatch, active=True)
    allowed, err, status = order_gate.check_order_allowed("order placement")
    assert allowed is True
    assert err is None


def test_blocked_response_names_the_calling_path(monkeypatch, caplog):
    """The log must identify WHICH path was blocked, so an operator can tell
    a blocked basket order from a blocked GTT."""
    _stub_kill_switch(monkeypatch, active=True)
    with caplog.at_level("WARNING"):
        order_gate.check_order_allowed("GTT order placement", api_key=TEST_API_KEY)
    assert "GTT order placement" in caplog.text


def test_lookup_error_fails_open_and_alerts(monkeypatch, alerts):
    _stub_kill_switch(monkeypatch, raises=True)
    allowed, err, status = order_gate.check_order_allowed(
        "split order", api_key=TEST_API_KEY
    )
    assert allowed is True, "a settings fault must not halt the platform"
    assert err is None
    assert len(alerts) == 1, "fail-open must raise a human-visible alarm"
    assert alerts[0][0] == "split order"


def test_alert_failure_never_breaks_order_placement(monkeypatch):
    """A broken alert dispatch must not turn a fail-open into an exception."""
    _stub_kill_switch(monkeypatch, raises=True)
    allowed, err, status = order_gate.check_order_allowed(
        "order placement", api_key=TEST_API_KEY
    )
    assert allowed is True


def test_gate_checks_the_orders_own_owner(monkeypatch):
    """The gate must consult the switch belonging to the user who placed
    the order, not a global flag -- User A's active switch must not block
    User B's order."""
    active_for = {"user_a": True, "user_b": False}

    mod = types.ModuleType("database.settings_db")
    mod.is_kill_switch_active = lambda username=None: active_for.get(username, False)
    monkeypatch.setitem(sys.modules, "database.settings_db", mod)
    monkeypatch.setattr(
        "utils.socket_scope.username_from_api_key", lambda key: key  # key IS the username
    )

    a_allowed, _e, _s = order_gate.check_order_allowed("order placement", api_key="user_a")
    b_allowed, _e, _s = order_gate.check_order_allowed("order placement", api_key="user_b")

    assert a_allowed is False, "the user who armed the switch must be blocked"
    assert b_allowed is True, "an unrelated user must be unaffected"


# --- coverage guard ------------------------------------------------------
# Not a behavior test: a static check that every service reaching a broker's
# order API also calls the gate. If someone adds a sixth order path, or drops
# the gate from an existing one, this fails.

GATED_SERVICES = [
    ("place_order_service.py", "place_order_api", "OrderFailedEvent"),
    ("basket_order_service.py", "place_order_api", "OrderFailedEvent"),
    ("split_order_service.py", "place_order_api", "OrderFailedEvent"),
    ("place_smart_order_service.py", "place_smartorder_api", "OrderFailedEvent"),
    ("place_gtt_order_service.py", "place_gtt_order", "GTTFailedEvent"),
]


def _service_source(filename):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", filename
    )
    return open(path, encoding="utf-8").read()


@pytest.mark.parametrize("filename,broker_call,_event", GATED_SERVICES)
def test_every_broker_order_path_calls_the_gate(filename, broker_call, _event):
    source = _service_source(filename)
    assert broker_call in source, f"{filename} no longer calls {broker_call} -- update this test"
    assert "check_order_allowed" in source, (
        f"{filename} reaches a broker via {broker_call} but does not call "
        "check_order_allowed() -- every live order path must be gated"
    )


@pytest.mark.parametrize("filename,_broker_call,event_name", GATED_SERVICES)
def test_blocked_order_publishes_a_failure_event(filename, _broker_call, event_name):
    """A gate that blocks silently is a gate the user cannot see.

    order.failed drives the red error toast and the notification-drawer entry
    in the React UI (subscribers/socketio_subscriber.py::on_order_failed), plus
    the log subscriber. basket and split originally returned
    the gate error without publishing, which would have made a kill-switched
    basket order vanish from the user's view while the other three reported
    correctly. This pins that every gated path publishes.
    """
    source = _service_source(filename)
    gate_index = source.index("check_order_allowed(")
    after_gate = source[gate_index:gate_index + 1200]
    assert event_name in after_gate, (
        f"{filename} blocks on the kill switch without publishing {event_name} -- "
        "the order would be blocked silently with no user-visible notification"
    )
