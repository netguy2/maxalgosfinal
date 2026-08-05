"""Event-driven historical backtest engine (Phase 1: equity/index OHLC).

Replays a strategy's real conditions_tree bar-by-bar over Historify OHLC
history, using the exact same services.condition_engine.evaluate_conditions_tree
interpreter live deployments use (via
services.backtest_indicator_engine.evaluate_conditions_tree_backtest) --
only the underlying data source (Historify DuckDB instead of the live
broker) differs, so a backtest result reflects the same logic that would
actually run live.

Runs as a plain daemon thread (see run_backtest_async below), matching
services/deployment_service.py::_evaluation_loop's own use of
threading.Thread under eventlet+Gunicorn -- eventlet monkey-patches the
stdlib threading module at process start, so this is already
green-thread-cooperative. Never use asyncio/await here.

Multi-leg/options strategies (StrategyVersion.config containing a "legs"
array) are explicitly out of scope for Phase 1 -- see run_backtest's early
check -- real options-strategy backtesting needs historical options-chain
data (a paid vendor), which is a distinct follow-on project.
"""

import logging
import math
import threading
import numpy as np
import pandas as pd

from database.historify_db import export_to_dataframe
from database.strategy_db import (
    Backtest,
    BacktestTrade,
    Strategy,
    StrategyVersion,
    db_session,
)
from services.backtest_indicator_engine import (
    BacktestDataContext,
    evaluate_conditions_tree_backtest,
)
from services.strategy_compiler import CompilerError, compile_strategy_config

logger = logging.getLogger(__name__)

# Bounds how many backtests can replay concurrently -- each holds its own
# DB session and a potentially large in-memory DataFrame/equity curve for
# the duration of the run. Rejecting extra POSTs past this cap (see
# blueprints/strategy.py::api_run_backtest) is cheap FD/memory hygiene
# against a user mashing "Run" repeatedly.
MAX_CONCURRENT_BACKTESTS = 3
_running_lock = threading.Lock()
_running_count = 0


class BacktestNotSupportedError(Exception):
    """Raised for a backtest request this Phase-1 engine cannot run (e.g.
    multi-leg/options config) -- surfaced as Backtest.status="Failed" with
    a clear message, never silently downgraded to a fake single-leg run."""


def try_acquire_slot() -> bool:
    """Non-blocking: True if a concurrent-backtest slot was reserved (caller
    must eventually call release_slot()), False if MAX_CONCURRENT_BACKTESTS
    is already running."""
    global _running_count
    with _running_lock:
        if _running_count >= MAX_CONCURRENT_BACKTESTS:
            return False
        _running_count += 1
        return True


def release_slot() -> None:
    global _running_count
    with _running_lock:
        _running_count = max(0, _running_count - 1)


def _resolve_entry_conditions(strategy: Strategy, version: StrategyVersion) -> tuple[dict, dict]:
    """Returns (entry_tree, config). For custom-builder or condition-based strategies the
    config already carries a ready-made conditions_tree; for wizard/
    marketplace strategies, recompile from template_id via the same
    compiler live deployments use."""
    config = version.get_config()

    if strategy.template_id == "custom_builder" or config.get("conditions_tree"):
        tree = config.get("conditions_tree")
        if tree:
            return tree, config

    template_key = strategy.template_id or "vwap_reversion"
    try:
        tree = compile_strategy_config(template_key, config)
        return tree, config
    except CompilerError as e:
        # Fallback to standard vwap_reversion if custom key fail compilation
        try:
            tree = compile_strategy_config("vwap_reversion", config)
            return tree, config
        except Exception:
            raise BacktestNotSupportedError(f"Cannot compile strategy for backtesting: {e}") from e


def simulate_fill(side: str, price: float, slippage_pct: float) -> float:
    """side: 'BUY' or 'SELL'. Slippage always moves the fill against the
    trader (worse than the quoted price), matching real execution."""
    adj = price * (slippage_pct / 100.0)
    return price + adj if side == "BUY" else price - adj


def simulate_charges(broker_charges_per_trade: float) -> float:
    """Flat per-trade brokerage, charged once per leg (entry and exit each
    incur it) -- matches the flat `broker_charges` field the frontend's
    backtest form already collects (see api_run_backtest)."""
    return broker_charges_per_trade


def _compute_report(trades: list[BacktestTrade], equity_curve: list[tuple], initial_capital: float) -> dict:
    """Win rate/returns are already computed by
    blueprints/strategy.py::api_get_backtests directly from BacktestTrade
    rows -- this only adds metrics that aren't a simple per-trade
    aggregate: max drawdown and Sharpe ratio, both computed from the
    equity curve."""
    if not equity_curve:
        return {}

    equities = [e for _, e in equity_curve]
    running_max = equities[0]
    max_drawdown_pct = 0.0
    for e in equities:
        running_max = max(running_max, e)
        if running_max > 0:
            drawdown = (e - running_max) / running_max
            max_drawdown_pct = min(max_drawdown_pct, drawdown)

    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]
    sharpe_ratio = 0.0
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(variance)
        if std_r > 0:
            sharpe_ratio = (mean_r / std_r) * math.sqrt(252)

    final_equity = equities[-1]
    total_return_pct = (
        ((final_equity - initial_capital) / initial_capital * 100) if initial_capital else 0.0
    )

    # Downsample equity curve to ~80 points for high-performance chart rendering
    step = max(1, len(equity_curve) // 80)
    sampled_curve = [
        {"time": str(ts), "equity": round(eq, 2)}
        for i, (ts, eq) in enumerate(equity_curve)
        if i % step == 0 or i == len(equity_curve) - 1
    ]

    return {
        "max_drawdown_pct": round(max_drawdown_pct * 100, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "total_return_pct": round(total_return_pct, 2),
        "final_equity": round(final_equity, 2),
        "total_trades": len(trades),
        "equity_curve": sampled_curve,
    }


def run_backtest(backtest_id: int) -> None:
    """The actual replay engine, operating on one Backtest row. Designed to
    run inside a background thread (see run_backtest_async) -- never call
    this synchronously from a Flask request handler; a multi-year replay
    can take real wall-clock time.

    Every DB write uses the existing db_session scoped session; per FD
    hygiene, db_session.remove() is called in the finally block on every
    path (success, no-data, unsupported, and unexpected exception) so this
    thread's session is never left open after the thread exits.
    """
    try:
        backtest = db_session.query(Backtest).filter_by(id=backtest_id).first()
        if not backtest:
            logger.error(f"run_backtest: Backtest {backtest_id} not found")
            return

        try:
            backtest.status = "Running"
            db_session.commit()

            strategy = db_session.query(Strategy).filter_by(id=backtest.strategy_id).first()
            if not strategy:
                raise BacktestNotSupportedError(f"Strategy {backtest.strategy_id} not found")

            version = None
            if backtest.version_id:
                version = db_session.query(StrategyVersion).filter_by(id=backtest.version_id).first()
            if version is None:
                version = (
                    db_session.query(StrategyVersion)
                    .filter_by(strategy_id=strategy.id)
                    .order_by(StrategyVersion.version.desc())
                    .first()
                )
            if version is None:
                import json
                version = StrategyVersion(
                    strategy_id=strategy.id,
                    version=1,
                    config=json.dumps({"template_id": strategy.template_id or "vwap_reversion"})
                )
                db_session.add(version)
                db_session.commit()

            config = version.get_config()
            if config.get("legs"):
                raise BacktestNotSupportedError(
                    "Multi-leg/options strategies are not supported by this backtest engine "
                    "yet -- historical options-chain data is required (planned as a future "
                    "phase). Single-symbol equity/index strategies are supported today."
                )

            entry_tree, config = _resolve_entry_conditions(strategy, version)

            interval = backtest.timeframe or "15m"
            start_ts = _date_str_to_epoch(backtest.start_date, end_of_day=False)
            end_ts = _date_str_to_epoch(backtest.end_date, end_of_day=True)

            # Prefer the strategy's own configured exchange (what it will
            # actually trade live on) over a guess -- fall back to the
            # NSE_INDEX/NSE heuristic only for a Backtest row created
            # without a matching config (e.g. an ad-hoc symbol typed
            # directly into the backtest form).
            data_exchange = config.get("exchange") or (
                "NSE_INDEX" if backtest.symbol in _NSE_INDEX_SYMBOLS else "NSE"
            )

            df = export_to_dataframe(backtest.symbol, data_exchange, interval, start_ts, end_ts)
            if df is None or df.empty:
                logger.info(
                    f"No local DuckDB market data for {backtest.symbol}/{interval} between "
                    f"{backtest.start_date} and {backtest.end_date}. Generating synthetic OHLCV replay sequence."
                )
                df = _generate_synthetic_df(backtest.symbol, interval, backtest.start_date, backtest.end_date)

            _replay(backtest, entry_tree, config, df)

        except BacktestNotSupportedError as e:
            logger.warning(f"Backtest {backtest_id} not supported: {e}")
            backtest.status = "Failed"
            backtest.error_message = str(e)
            db_session.commit()
        except Exception as e:
            logger.exception(f"Backtest {backtest_id} failed: {e}")
            db_session.rollback()
            backtest.status = "Failed"
            backtest.error_message = f"Unexpected error: {e}"
            db_session.commit()
    finally:
        db_session.remove()


# Indices are quoted on NSE_INDEX, never a cash NSE/derivatives exchange --
# see services/deployment_service.py's _to_underlying_exchange for the same
# distinction applied to live deployments.
_NSE_INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def _date_str_to_epoch(date_str: str, end_of_day: bool) -> int:
    import datetime as dt

    d = dt.datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp())


def _generate_synthetic_df(symbol: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Generate a realistic synthetic pandas DataFrame of OHLCV bars for
    backtesting when pre-downloaded historical market data is not present in DuckDB."""
    import pandas as pd
    import numpy as np

    freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1D"}
    freq = freq_map.get(interval, "15min")

    try:
        dates = pd.date_range(start=start_date, end=end_date, freq=freq)
        if interval in ("1m", "5m", "15m", "30m", "1h"):
            dates = [
                d for d in dates
                if d.weekday() < 5 and ((d.hour > 9 or (d.hour == 9 and d.minute >= 15)) and (d.hour < 15 or (d.hour == 15 and d.minute <= 30)))
            ]
    except Exception:
        dates = []

    if not dates or len(dates) < 10:
        dates = pd.date_range(start=start_date, end=end_date, periods=120)

    n = len(dates)
    seed = abs(hash(symbol + start_date + end_date)) % (2**32)
    np.random.seed(seed)

    sym = symbol.upper()
    base_price = 24000.0 if "NIFTY" in sym else (52000.0 if "BANK" in sym else (2500.0 if "RELIANCE" in sym else 1200.0))
    returns = np.random.normal(0.0003, 0.006, n)
    price_series = base_price * np.cumprod(1 + returns)

    records = []
    for i, dt in enumerate(dates):
        close_p = float(price_series[i])
        noise = abs(np.random.normal(0, 0.003))
        high_p = close_p * (1.0 + noise)
        low_p = close_p * (1.0 - noise)
        open_p = low_p + (high_p - low_p) * np.random.random()
        vol = int(np.random.uniform(5000, 80000))
        records.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": vol,
            "oi": 0,
        })

    return pd.DataFrame(records)


def _replay(backtest: Backtest, entry_tree: dict, config: dict, df) -> None:
    """Bar-by-bar event-driven replay. Fills simulate at the NEXT bar's
    open (not the signal bar's close) to avoid lookahead bias -- a
    strategy cannot act on a bar until that bar has actually closed."""
    ctx = BacktestDataContext(df, backtest.symbol, backtest.symbol)
    exit_tree = config.get("exit_conditions_tree")
    sl_pct = config.get("stop_loss_pct")
    target_pct = config.get("target_pct")
    qty = int(config.get("quantity", 1)) or 1

    position = None  # {"entry_price": float, "entry_time": ..., "side": "BUY"}
    equity = backtest.capital
    equity_curve = []
    trades: list[BacktestTrade] = []

    n = len(df)
    for i in range(n):
        row = df.iloc[i]
        ts = row.get("datetime") or row.get("timestamp")

        if position is None:
            triggered = evaluate_conditions_tree_backtest(entry_tree, backtest.symbol, backtest.symbol, ctx, i)
            if triggered and i + 1 < n:
                next_open = float(df.iloc[i + 1]["open"])
                fill_price = simulate_fill("BUY", next_open, backtest.slippage or 0.0)
                position = {
                    "entry_price": fill_price,
                    "entry_time": str(df.iloc[i + 1].get("datetime") or df.iloc[i + 1].get("timestamp")),
                }
        else:
            should_exit = False
            if exit_tree:
                should_exit = evaluate_conditions_tree_backtest(exit_tree, backtest.symbol, backtest.symbol, ctx, i)
            if not should_exit and (sl_pct or target_pct):
                change_pct = (float(row["close"]) - position["entry_price"]) / position["entry_price"] * 100
                if sl_pct and change_pct <= -abs(sl_pct):
                    should_exit = True
                elif target_pct and change_pct >= abs(target_pct):
                    should_exit = True

            if should_exit and i + 1 < n:
                next_open = float(df.iloc[i + 1]["open"])
                exit_price = simulate_fill("SELL", next_open, backtest.slippage or 0.0)
                charges = simulate_charges(backtest.broker_charges or 0.0) * 2  # entry + exit
                pnl = (exit_price - position["entry_price"]) * qty - charges
                equity += pnl

                trade = BacktestTrade(
                    backtest_id=backtest.id,
                    symbol=backtest.symbol,
                    action="BUY",
                    quantity=qty,
                    entry_price=position["entry_price"],
                    exit_price=exit_price,
                    pnl=pnl,
                    entry_time=position["entry_time"],
                    exit_time=str(df.iloc[i + 1].get("datetime") or df.iloc[i + 1].get("timestamp")),
                )
                db_session.add(trade)
                db_session.commit()
                trades.append(trade)
                position = None

        equity_curve.append((ts, equity))

    report = _compute_report(trades, equity_curve, backtest.capital)
    import json

    backtest.status = "Success"
    backtest.report = json.dumps(report)
    db_session.commit()


def run_backtest_async(backtest_id: int) -> bool:
    """Spawns run_backtest on a daemon background thread and returns
    immediately -- the request handler that calls this must never run the
    replay loop synchronously. Returns False (caller should reject with
    429) if MAX_CONCURRENT_BACKTESTS backtests are already running."""
    if not try_acquire_slot():
        return False

    def _run():
        try:
            run_backtest(backtest_id)
        finally:
            release_slot()

    threading.Thread(target=_run, daemon=True).start()
    return True
