"""Regression tests: automation that no human can see or stop must never trade.

Two background paths place real broker orders without anyone clicking
anything -- services/deployment_service.py's _evaluation_loop and
services/signal_engine.py's webhook processing. Both read rows straight from
the database, while every UI screen reads through a user-scoped query
(get_user_deployments(user_id) / the strategies list for the logged-in user).

That asymmetry means a row whose user_id does not resolve to a real account
is INVISIBLE in the product yet still evaluated, and still able to place
orders, on every cycle -- forever, with no way for any human to find it,
pause it, or stop it. This is not hypothetical: a production incident had
auto-seeded "MaxAlgosSystem" marketplace strategies (owned by a synthetic
user nobody can log in as) firing repeated live NIFTY orders across multiple
real accounts while every strategy screen showed nothing running.

Both gates deliberately FAIL CLOSED -- the opposite of the kill-switch and
market-hours gates, which fail open so a transient settings/calendar fault
cannot halt the whole platform. Here the trade-off inverts: proceeding means
placing real orders for something we could not confirm anyone owns.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import services.deployment_service as dsvc  # noqa: E402
import services.signal_engine as se  # noqa: E402


class FakeStrategy:
    def __init__(self, user_id="realuser", name="S1"):
        self.user_id = user_id
        self.name = name


class FakeDeployment:
    def __init__(self, user_id="realuser", did=1, name="D1"):
        self.user_id = user_id
        self.id = did
        self.name = name


@pytest.fixture
def known_users(monkeypatch):
    """Only 'realuser' exists as an account."""
    import database.user_db as user_db

    monkeypatch.setattr(
        user_db,
        "find_user_by_exact_username",
        lambda u: object() if u == "realuser" else None,
    )


# --- webhook / signal engine -------------------------------------------

class TestSignalEngineOwnershipGate:
    def test_real_owner_is_allowed(self, known_users):
        assert se._strategy_owner_exists(FakeStrategy(user_id="realuser")) is True

    def test_deleted_account_is_blocked(self, known_users):
        """THE regression test: the synthetic 'MaxAlgosSystem' seed user and
        any deleted account must not be able to trade."""
        assert se._strategy_owner_exists(FakeStrategy(user_id="MaxAlgosSystem")) is False

    def test_empty_owner_is_blocked(self, known_users):
        assert se._strategy_owner_exists(FakeStrategy(user_id="")) is False
        assert se._strategy_owner_exists(FakeStrategy(user_id=None)) is False

    def test_fails_closed_when_lookup_raises(self, monkeypatch):
        """A DB fault must block the order, not wave it through."""
        import database.user_db as user_db

        def _boom(_u):
            raise RuntimeError("user table unavailable")

        monkeypatch.setattr(user_db, "find_user_by_exact_username", _boom)
        assert se._strategy_owner_exists(FakeStrategy(user_id="realuser")) is False


# --- deployment engine --------------------------------------------------

class TestDeploymentEngineOwnershipGate:
    def test_real_owner_is_allowed(self, known_users, monkeypatch):
        called = []
        monkeypatch.setattr(
            dsvc, "update_deployment_status", lambda *a, **k: called.append(a)
        )
        assert dsvc._deployment_owner_exists(FakeDeployment(user_id="realuser")) is True
        assert called == [], "a valid deployment must not be quarantined"

    def test_orphaned_deployment_is_quarantined_not_just_skipped(
        self, known_users, monkeypatch
    ):
        """Skipping alone would leave it silently looping every cycle
        forever; it must be moved to Error so it stops being evaluated and
        becomes visible."""
        statuses = []
        monkeypatch.setattr(
            dsvc,
            "update_deployment_status",
            lambda did, status, msg=None: statuses.append(status),
        )

        assert dsvc._deployment_owner_exists(FakeDeployment(user_id="ghost")) is False
        assert statuses == ["Error"], f"expected quarantine to Error, got {statuses}"

    def test_empty_owner_is_quarantined(self, known_users, monkeypatch):
        statuses = []
        monkeypatch.setattr(
            dsvc,
            "update_deployment_status",
            lambda did, status, msg=None: statuses.append(status),
        )
        assert dsvc._deployment_owner_exists(FakeDeployment(user_id=None)) is False
        assert statuses == ["Error"]

    def test_fails_closed_when_lookup_raises(self, monkeypatch):
        import database.user_db as user_db

        def _boom(_u):
            raise RuntimeError("user table unavailable")

        monkeypatch.setattr(user_db, "find_user_by_exact_username", _boom)
        monkeypatch.setattr(dsvc, "update_deployment_status", lambda *a, **k: None)
        assert dsvc._deployment_owner_exists(FakeDeployment(user_id="realuser")) is False


# --- cross-user control surface ----------------------------------------

class TestNoCrossUserStrategyControl:
    """Every route that mutates a specific strategy must verify the caller
    owns it. The legacy form-post /toggle/<id> route checked only that the
    caller was logged in AS SOMEONE, so any authenticated user could
    ACTIVATE another user's strategy by id -- starting real orders on that
    person's broker account."""

    def test_toggle_route_checks_ownership(self):
        import inspect

        import blueprints.strategy as sbp

        source = inspect.getsource(sbp.toggle_strategy_route)
        assert "existing.user_id != user_id" in source, (
            "toggle_strategy_route must verify the strategy belongs to the "
            "session user before activating/deactivating it."
        )

    def test_all_mutating_strategy_routes_are_ownership_scoped(self):
        """Catches any NEW route added without an ownership check."""
        import re

        src = open("blueprints/strategy.py", encoding="utf-8").read()
        # Marketplace routes act on another user's public listing by design.
        allowed = {
            "api_subscribe_marketplace",
            "api_start_marketplace_trial",
            "api_unsubscribe_marketplace",
        }

        offenders = []
        for block in re.split(r"\n(?=@strategy_bp\.route)", src):
            m = re.search(r"@strategy_bp\.route\((.*?)\)", block)
            fn = re.search(r"\ndef (\w+)\(", block)
            if not m or not fn or "strategy_id" not in m.group(1):
                continue
            if not re.search(r'methods=\[["\'](POST|DELETE|PATCH|PUT)', block):
                continue
            if fn.group(1) in allowed:
                continue
            if not re.search(r"\.user_id\s*!=\s*(user_id|username|current_user\w*)", block):
                offenders.append(fn.group(1))

        assert offenders == [], (
            "These routes mutate a specific strategy without verifying the "
            f"caller owns it: {offenders}"
        )
