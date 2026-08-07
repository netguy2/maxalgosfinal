"""Regression tests: `is_active` and `lifecycle_state` must never disagree.

A Strategy carries two independent flags:
  * is_active       -- the on/off switch, and the ONLY one any UI surfaces
                       (the green "Active" / "Paused" badge)
  * lifecycle_state  -- Draft / Ready / Archived, which signal_engine's
                       lifecycle gate reads to decide whether orders may be
                       placed at all

Production symptom: a strategy card showed a green **Active** badge while
every incoming signal was rejected in the Signal Delivery Log with
"Strategy is in 'Draft' state, which does not permit order placement"
(reason_code strategy_not_live). The user had no way to fix it, because no
screen exposes lifecycle_state.

Root cause, in two halves:
  1. create_strategy() defaulted lifecycle_state="Draft" while
     Strategy.is_active defaults to True -- so every strategy was BORN
     active-but-forbidden-to-trade.
  2. toggle_strategy() flipped only is_active and never promoted
     lifecycle_state, and NOTHING else in the codebase ever promoted a
     strategy out of Draft. So clicking Activate could not fix it either;
     the state was terminal.

Fixes pinned here: creation defaults to Ready, activation promotes out of
Draft, and a startup migration heals rows already stuck in the bad state.
Archived is never resurrected by any of them.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fall back to the project's OWN default DB, never a private scratch file.
# os.environ leaks across test modules in a single pytest run and every
# database/*_db.py binds its engine at import time, so pointing this file at
# a scratch DB silently redirected unrelated modules (e.g. test_kill_switch)
# to a database with none of their tables. Matching the default every other
# module already uses keeps the whole run on one consistent database.
os.environ.setdefault("DATABASE_URL", "sqlite:///db/maxalgos.db")

import pytest  # noqa: E402

import database.strategy_db as sdb  # noqa: E402

PREFIX = "__test_lifecycle_consistency__"


def _mk(name, is_active, lifecycle_state):
    s = sdb.Strategy(
        name=f"{PREFIX}{name}",
        webhook_id=str(uuid.uuid4()),
        user_id=f"{PREFIX}user",
        is_active=is_active,
        lifecycle_state=lifecycle_state,
    )
    sdb.db_session.add(s)
    sdb.db_session.commit()
    return s


@pytest.fixture(autouse=True, scope="module")
def _schema():
    """Ensure the tables exist -- this file may run against a fresh scratch
    DB that no other module has initialised."""
    sdb.Base.metadata.create_all(bind=sdb.engine)


@pytest.fixture(autouse=True)
def _clean():
    def purge():
        sdb.db_session.query(sdb.Strategy).filter(
            sdb.Strategy.name.like(f"{PREFIX}%")
        ).delete(synchronize_session=False)
        sdb.db_session.commit()

    purge()
    yield
    purge()


class TestCreationDefaultsAgree:
    def test_new_strategy_is_not_born_active_but_draft(self):
        """THE root cause: is_active defaults True, so defaulting
        lifecycle_state to Draft made every new strategy immediately
        active yet forbidden from placing any order."""
        import inspect

        sig = inspect.signature(sdb.create_strategy)
        assert sig.parameters["lifecycle_state"].default == "Ready", (
            "create_strategy must default lifecycle_state to 'Ready' to match "
            "Strategy.is_active's default of True -- otherwise every new "
            "strategy shows as Active while rejecting every signal as Draft."
        )


class TestActivationPromotesLifecycle:
    def test_activating_a_draft_promotes_it_to_ready(self):
        s = _mk("draft_off", is_active=False, lifecycle_state="Draft")
        sdb.toggle_strategy(s.id)
        sdb.db_session.expire_all()
        s = sdb.get_strategy(s.id)
        assert (s.is_active, s.lifecycle_state) == (True, "Ready")

    def test_pausing_does_not_send_it_back_to_draft(self):
        """Pausing is temporary; it must not undo the promotion, or the
        next activation would be needed twice to trade again."""
        s = _mk("ready_on", is_active=True, lifecycle_state="Ready")
        sdb.toggle_strategy(s.id)
        sdb.db_session.expire_all()
        s = sdb.get_strategy(s.id)
        assert (s.is_active, s.lifecycle_state) == (False, "Ready")

    def test_archived_is_never_resurrected_by_a_toggle(self):
        """Un-archiving must stay an explicit, separate decision."""
        s = _mk("archived", is_active=False, lifecycle_state="Archived")
        sdb.toggle_strategy(s.id)
        sdb.db_session.expire_all()
        s = sdb.get_strategy(s.id)
        assert s.lifecycle_state == "Archived"


class TestHealMigration:
    def test_heals_active_drafts_only(self):
        stuck = _mk("stuck", is_active=True, lifecycle_state="Draft")
        unfinished = _mk("unfinished", is_active=False, lifecycle_state="Draft")
        archived = _mk("arch", is_active=True, lifecycle_state="Archived")

        sdb._migrate_heal_active_draft_strategies()
        sdb.db_session.expire_all()

        assert sdb.get_strategy(stuck.id).lifecycle_state == "Ready", (
            "an already-active strategy stuck in Draft must be healed -- it was "
            "switched on by its owner but silently rejecting every signal"
        )
        assert sdb.get_strategy(unfinished.id).lifecycle_state == "Draft", (
            "a genuinely unfinished (inactive) draft must be left alone"
        )
        assert sdb.get_strategy(archived.id).lifecycle_state == "Archived", (
            "archived strategies must never be resurrected by the migration"
        )

    def test_is_idempotent(self):
        _mk("stuck2", is_active=True, lifecycle_state="Draft")
        sdb._migrate_heal_active_draft_strategies()
        sdb._migrate_heal_active_draft_strategies()  # must not raise
