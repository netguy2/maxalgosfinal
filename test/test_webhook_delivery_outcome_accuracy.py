"""Regression tests for: a MaxHook webhook signal that never actually
placed/attempted an order must NOT be recorded as "processed" in the
webhook delivery log.

Root cause: _process_signal_event() (services/signal_engine.py) called
_record_delivery_outcome(..., "processed", ...) unconditionally after
dispatching to whichever of the three webhook signal handlers
(_process_legacy_webhook_signal / _process_unified_webhook_signal /
_process_leg_group_webhook_signal) applied, regardless of what happened
INSIDE that handler. Each handler has several early-exit paths (no symbol
mappings, no mapping matching the incoming action, an unresolvable
FUT/OPT instrument -- e.g. the current_month/next_month expiry rollover
bug in services/expiry_service.py -- missing API key, a blocked
condition) that only logged a warning/info line and returned, without
ever reaching place_order(). The delivery log showed "Processed" for all
of these, indistinguishable from a real, successful order attempt, which
is exactly the reported symptom: "webhook signal is received (Processed)
but no order shows up in the broker orderbook at all -- not even
Rejected."

Fix: each handler now returns {"attempted": bool, "reason_code": str,
"reason_detail": str}, and _process_signal_event() records "processed"
only when attempted is True, else "rejected" with the specific reason.

All DB/broker calls are mocked -- these tests only exercise the handlers'
control flow and return values.
"""

import os
import sys
import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

import services.signal_engine as se


def _stub_module(monkeypatch, module_name, **attrs):
    mod = types.ModuleType(module_name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, module_name, mod)
    return mod


class FakeStrategy:
    def __init__(self, name="S1", user_id="u1", brokers=""):
        self.id = 1
        self.name = name
        self.user_id = user_id
        self.brokers = brokers


class FakeMapping:
    def __init__(self, action="BUY", instrument_type="EQ", instrument="SBIN",
                 exchange="NSE", quantity=1, product_type="MIS", symbol=None):
        self.action = action
        self.symbol = symbol
        self.instrument_type = instrument_type
        self.instrument = instrument
        self.exchange = exchange
        self.quantity = quantity
        self.product_type = product_type


def _event():
    return se.SignalEvent(webhook_id="wh-1", signal="BUY", delivery_id=42)


@pytest.fixture(autouse=True)
def _no_emit(monkeypatch):
    monkeypatch.setattr(se, "_emit_scoped", lambda *a, **k: None)


class TestLegacyHandlerReportsAttempted:
    def test_no_symbol_mappings_reports_not_attempted(self, monkeypatch):
        _stub_module(
            monkeypatch, "database.strategy_db",
            get_symbol_mappings=lambda strategy_id: [],
        )
        _stub_module(
            monkeypatch, "database.auth_db",
            get_api_key_for_tradingview=lambda uid: None,
            get_broker_session=lambda uid, broker: None,
            list_broker_sessions=lambda uid: [],
        )
        _stub_module(monkeypatch, "services.place_order_service", place_order=lambda **k: (True, {}, 200))

        result = se._process_legacy_webhook_signal(FakeStrategy(), _event())

        assert result["attempted"] is False
        assert result["reason_code"] == "no_mappings"

    def test_unresolvable_option_instrument_reports_not_attempted(self, monkeypatch):
        """This is the exact shape of the current_month expiry rollover bug:
        a FUT/OPT mapping exists and matches the signal, but
        _resolve_live_instrument() (which calls resolve_expiry_type())
        returns None. The old code silently `continue`d past every mapping
        and then reported "processed" anyway."""
        mapping = FakeMapping(action="BUY", instrument_type="OPT", exchange="NFO")
        _stub_module(
            monkeypatch, "database.strategy_db",
            get_symbol_mappings=lambda strategy_id: [mapping],
        )
        _stub_module(
            monkeypatch, "database.auth_db",
            get_api_key_for_tradingview=lambda uid: "fake-api-key",
            get_broker_session=lambda uid, broker: None,
            list_broker_sessions=lambda uid: [],
        )
        _stub_module(monkeypatch, "services.place_order_service", place_order=lambda **k: (True, {}, 200))
        monkeypatch.setattr(se, "_filter_active_mappings", lambda mappings, name: mappings)
        monkeypatch.setattr(se, "_resolve_live_instrument", lambda mapping, api_key, error_detail=None: None)

        result = se._process_legacy_webhook_signal(FakeStrategy(), _event())

        assert result["attempted"] is False
        assert result["reason_code"] == "instrument_resolution_failed"

    def test_reports_the_specific_underlying_expiry_failure_reason(self, monkeypatch):
        """The delivery log must show WHICH underlying/exchange/expiry
        failed, not just the generic 'instrument_resolution_failed' code --
        this is what lets a user self-diagnose a bad mapping from the
        MaxHook UI without needing server log access."""
        mapping = FakeMapping(action="BUY", instrument_type="OPT", exchange="NFO")
        _stub_module(
            monkeypatch, "database.strategy_db",
            get_symbol_mappings=lambda strategy_id: [mapping],
        )
        _stub_module(
            monkeypatch, "database.auth_db",
            get_api_key_for_tradingview=lambda uid: "fake-api-key",
            get_broker_session=lambda uid, broker: None,
            list_broker_sessions=lambda uid: [],
        )
        _stub_module(monkeypatch, "services.place_order_service", place_order=lambda **k: (True, {}, 200))
        monkeypatch.setattr(se, "_filter_active_mappings", lambda mappings, name: mappings)

        def fake_resolve(mapping, api_key, error_detail=None):
            if error_detail is not None:
                error_detail.append("Could not resolve 'current_month' expiry for NIFTY on NFO")
            return None

        monkeypatch.setattr(se, "_resolve_live_instrument", fake_resolve)

        result = se._process_legacy_webhook_signal(FakeStrategy(), _event())

        assert result["attempted"] is False
        assert result["reason_code"] == "instrument_resolution_failed"
        assert "current_month" in result["reason_detail"]
        assert "NIFTY" in result["reason_detail"]

    def test_successful_order_attempt_reports_attempted(self, monkeypatch):
        mapping = FakeMapping(action="BUY", instrument_type="EQ", instrument="SBIN", exchange="NSE")
        _stub_module(
            monkeypatch, "database.strategy_db",
            get_symbol_mappings=lambda strategy_id: [mapping],
        )
        _stub_module(
            monkeypatch, "database.auth_db",
            get_api_key_for_tradingview=lambda uid: None,
            get_broker_session=lambda uid, broker: ("token", "feed", "brid"),
            list_broker_sessions=lambda uid: [{"broker": "zerodha", "is_revoked": False}],
        )
        _stub_module(
            monkeypatch, "services.place_order_service",
            place_order=lambda **k: (True, {"status": "success"}, 200),
        )
        monkeypatch.setattr(se, "_filter_active_mappings", lambda mappings, name: mappings)

        import contextlib

        monkeypatch.setattr(se, "broker_credential_context", lambda *a, **k: contextlib.nullcontext())

        result = se._process_legacy_webhook_signal(FakeStrategy(), _event())

        assert result["attempted"] is True

    def test_no_matching_mapping_for_action_reports_not_attempted(self, monkeypatch):
        mapping = FakeMapping(action="SELL")  # signal below is BUY
        _stub_module(
            monkeypatch, "database.strategy_db",
            get_symbol_mappings=lambda strategy_id: [mapping],
        )
        _stub_module(
            monkeypatch, "database.auth_db",
            get_api_key_for_tradingview=lambda uid: None,
            get_broker_session=lambda uid, broker: None,
            list_broker_sessions=lambda uid: [],
        )
        _stub_module(monkeypatch, "services.place_order_service", place_order=lambda **k: (True, {}, 200))
        monkeypatch.setattr(se, "_filter_active_mappings", lambda mappings, name: mappings)

        result = se._process_legacy_webhook_signal(FakeStrategy(), _event())

        assert result["attempted"] is False
        assert result["reason_code"] == "no_matching_mappings"


class TestDispatchRecordsAccurateOutcome:
    """_process_signal_event must record 'rejected' (not 'processed') when
    the dispatched handler reports attempted=False."""

    def test_records_rejected_when_handler_reports_not_attempted(self, monkeypatch):
        recorded = []
        monkeypatch.setattr(
            se, "_record_delivery_outcome",
            lambda event, method, *a, **k: recorded.append((a, k)),
        )
        monkeypatch.setattr(se, "_kill_switch_blocks_signal", lambda strategy, event: False)
        monkeypatch.setattr(se, "_market_hours_blocks_signal", lambda strategy, event: False)
        monkeypatch.setattr(se, "_resolve_execution_model", lambda strategy: "legacy")
        monkeypatch.setattr(
            se, "_process_legacy_webhook_signal",
            lambda strategy, event: {
                "attempted": False,
                "reason_code": "instrument_resolution_failed",
                "reason_detail": "could not resolve expiry",
            },
        )

        class FakeStrategyFull(FakeStrategy):
            platform = "webhook"
            is_active = True

        monkeypatch.setattr(se, "get_strategy_by_webhook_id", lambda wh_id: FakeStrategyFull())

        se._process_signal_event(_event())

        assert len(recorded) == 1
        args, kwargs = recorded[0]
        assert args[0] == "rejected"
        assert kwargs.get("reason_code") == "instrument_resolution_failed"

    def test_records_processed_when_handler_reports_attempted(self, monkeypatch):
        recorded = []
        monkeypatch.setattr(
            se, "_record_delivery_outcome",
            lambda event, method, *a, **k: recorded.append((a, k)),
        )
        monkeypatch.setattr(se, "_kill_switch_blocks_signal", lambda strategy, event: False)
        monkeypatch.setattr(se, "_market_hours_blocks_signal", lambda strategy, event: False)
        monkeypatch.setattr(se, "_resolve_execution_model", lambda strategy: "legacy")
        monkeypatch.setattr(
            se, "_process_legacy_webhook_signal",
            lambda strategy, event: {"attempted": True, "reason_code": "", "reason_detail": ""},
        )

        class FakeStrategyFull(FakeStrategy):
            platform = "webhook"
            is_active = True

        monkeypatch.setattr(se, "get_strategy_by_webhook_id", lambda wh_id: FakeStrategyFull())

        se._process_signal_event(_event())

        assert len(recorded) == 1
        args, kwargs = recorded[0]
        assert args[0] == "processed"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
