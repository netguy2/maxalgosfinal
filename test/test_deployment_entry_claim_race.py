"""
Concurrency regression test for: services/signal_engine.py's
_process_deployment_signal_event had a check-then-act race on
Deployment.status -- two threads could both read status == "Waiting"
before either committed "Entering", so two near-simultaneous webhook
deliveries for the SAME deployment (a genuine TradingView retry, or a
strategy condition that legitimately re-fires) could both proceed to place
a full set of orders for what should be one signal. This is the exact
Knight-Capital-style failure mode: a small timing bug turning into a
runaway duplicate-order burst, since signal_engine.py dispatches on an
8-worker ThreadPoolExecutor, not a single serial queue.

Fix: database/strategy_db.py::try_claim_deployment_for_entry() uses
SELECT...FOR UPDATE to atomically check-and-flip status in one locked
transaction, so only one concurrent caller can ever win the claim for a
given deployment -- matching the same pattern already used by
database/settings_db.py::set_kill_switch for the equivalent
concurrent-activation race.

This test proves the fix with REAL concurrent threads hitting the REAL
database function (not a mock) -- fault-injection style, not a happy-path
unit test, since the whole point of the bug was thread interleaving that a
single-threaded test would never exercise.
"""

import atexit
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_deployment_entry_claim_race.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import pytest  # noqa: E402

import restx_api  # noqa: F401,E402
from database.strategy_db import (  # noqa: E402
    Deployment,
    Strategy,
    StrategyVersion,
    db_session,
    init_db,
    try_claim_deployment_for_entry,
)

USER = "__test_race_user__"


@pytest.fixture(autouse=True)
def _setup_and_teardown():
    init_db()
    yield
    db_session.rollback()
    db_session.query(Deployment).filter(Deployment.user_id == USER).delete()
    db_session.query(StrategyVersion).filter(
        StrategyVersion.strategy_id.in_(
            db_session.query(Strategy.id).filter(Strategy.user_id == USER)
        )
    ).delete(synchronize_session=False)
    db_session.query(Strategy).filter(Strategy.user_id == USER).delete()
    db_session.commit()
    db_session.remove()


def _make_waiting_deployment() -> int:
    strategy = Strategy(
        name="race-test-strategy",
        webhook_id=f"race-test-{threading.get_ident()}-{os.urandom(4).hex()}",
        user_id=USER,
    )
    db_session.add(strategy)
    db_session.commit()

    version = StrategyVersion(strategy_id=strategy.id, version=1, config="{}")
    db_session.add(version)
    db_session.commit()

    deployment = Deployment(
        name="race-test-deployment",
        strategy_id=strategy.id,
        version_id=version.id,
        status="Waiting",
        broker="Paper Trading",
        capital=100000.0,
        user_id=USER,
    )
    db_session.add(deployment)
    db_session.commit()
    return deployment.id


def test_only_one_of_ten_concurrent_signals_wins_the_claim():
    """The actual regression: fire 10 threads at the SAME deployment
    simultaneously (simulating 10 near-simultaneous webhook deliveries
    landing on signal_engine's 8-worker thread pool) and confirm exactly
    ONE claims it -- not zero (deadlock/over-blocking) and not more than
    one (the original race)."""
    deployment_id = _make_waiting_deployment()

    results: list[bool] = []
    results_lock = threading.Lock()
    start_barrier = threading.Barrier(10)

    def worker():
        # Each thread needs its own scoped session identity in SQLAlchemy's
        # thread-local scoped_session -- db_session is already a
        # scoped_session, so calling it from a new native thread
        # transparently gets its own session, same as real request threads.
        start_barrier.wait()  # maximize actual overlap, not just "close in time"
        claimed = try_claim_deployment_for_entry(deployment_id, "BUY", "test entry")
        with results_lock:
            results.append(claimed)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 10, "not all threads completed -- possible deadlock"
    assert sum(results) == 1, (
        f"expected exactly 1 winner, got {sum(results)} -- "
        f"{'multiple threads placed duplicate orders (the bug)' if sum(results) > 1 else 'no thread won (over-blocking)'}"
    )

    db_session.expire_all()
    final = db_session.query(Deployment).filter_by(id=deployment_id).first()
    assert final.status == "Entering"


def test_claim_fails_when_not_waiting():
    deployment_id = _make_waiting_deployment()
    dep = db_session.query(Deployment).filter_by(id=deployment_id).first()
    dep.status = "Managing"
    db_session.commit()

    claimed = try_claim_deployment_for_entry(deployment_id, "BUY", "test entry")
    assert claimed is False


def test_claim_succeeds_exactly_once_sequentially():
    """Sanity check without threading: first call wins, second call (same
    deployment, now 'Entering') correctly loses."""
    deployment_id = _make_waiting_deployment()

    first = try_claim_deployment_for_entry(deployment_id, "BUY", "first")
    second = try_claim_deployment_for_entry(deployment_id, "BUY", "second")

    assert first is True
    assert second is False


def test_claim_missing_deployment_returns_false():
    claimed = try_claim_deployment_for_entry(999_999_999, "BUY", "test entry")
    assert claimed is False
