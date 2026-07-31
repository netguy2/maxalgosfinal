"""Platform-side trailing stop monitor.

A trailing stop cannot be expressed as a single broker order: the stop level
has to be *moved* as price advances. Most Indian brokers either don't expose
a trailing field or implement it inconsistently, so the first version of this
feature -- which stored the trail value on the mapping and logged "enforced
by the broker where supported" -- silently did nothing for most users. A risk
control that looks configured but never fires is worse than none at all,
because the trader sizes their position believing they are protected.

This module closes that gap: a background job polls the LTP of every armed
trailing stop, ratchets the stop toward profit, and sends a real exit order
the moment price crosses it.

Design notes:
  * Same BackgroundScheduler singleton convention as
    services/master_risk_monitor_service.py and
    services/historify_scheduler_service.py -- each polling job on the
    platform owns its own scheduler rather than sharing an unrelated one.
  * Polls every 3s. Fast enough that a stop is honoured within a few ticks,
    slow enough that a hundred armed stops don't hammer the broker; quotes
    are batched per (exchange, symbol) so N stops on the same instrument
    cost one lookup.
  * The ratchet itself lives on the model (TrailingStop.update_peak) so no
    code path can loosen a stop that has already tightened.
  * Never raises out of the tick: APScheduler drops a job on an uncaught
    exception, which would silently disable every trailing stop on the
    platform until the next restart. One position's failure must not stop
    the others being checked.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.strategy_db import (
    close_trailing_stop,
    commit_trailing_stop_move,
    get_active_trailing_stops,
)
from utils.logging import get_logger

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 3
JOB_ID = "trailing_stop_monitor_tick"

_scheduler: BackgroundScheduler | None = None


def _get_ltp(symbol: str, exchange: str, api_key: str | None) -> float | None:
    """Current price for one instrument, or None if unavailable.

    Returns None rather than 0.0 on failure -- a falsy price must never be
    mistaken for "price crashed to zero", which would fire every long stop
    simultaneously.
    """
    try:
        from services.market_data_service import get_ltp

        ltp = get_ltp(symbol, exchange, api_key=api_key)
        return float(ltp) if ltp else None
    except Exception:
        logger.debug(f"Trailing stop: LTP lookup failed for {symbol}/{exchange}", exc_info=True)
        return None


def _exit_position(ts, api_key: str | None) -> bool:
    """Send the exit order for a hit trailing stop.

    The exit is always the opposite side of the entry and always MARKET --
    a stop that has already been breached must not sit unfilled in the book
    waiting for a limit price.
    """
    from services.place_order_service import place_order

    exit_side = "SELL" if ts.is_long() else "BUY"
    order_data = {
        "apikey": api_key,
        "strategy": f"TrailingStop:{ts.symbol}",
        "symbol": ts.symbol,
        "exchange": ts.exchange,
        "action": exit_side,
        "quantity": ts.quantity,
        "pricetype": "MARKET",
        "product": ts.product or "MIS",
    }

    try:
        success, response, _status = place_order(order_data=order_data, api_key=api_key)
        if success:
            logger.info(
                f"Trailing stop HIT: exited {ts.symbol} {exit_side} qty={ts.quantity} "
                f"at stop {ts.stop_price} (peak was {ts.peak_price}, entry {ts.entry_price})"
            )
            return True
        logger.error(f"Trailing stop: exit order REJECTED for {ts.symbol}: {response}")
        return False
    except Exception:
        logger.exception(f"Trailing stop: exit order raised for {ts.symbol}")
        return False


def _notify(ts, username: str, message: str, status: str = "warning") -> None:
    """Tell the owner their stop moved or fired. Best-effort only."""
    try:
        from utils.socket_scope import emit_to_user

        emit_to_user(
            "order_notification",
            {"symbol": ts.symbol, "status": status, "message": message},
            username,
        )
    except Exception:
        logger.debug("Trailing stop: notification emit failed", exc_info=True)


def _process_one(ts, api_key: str | None, ltp: float | None) -> None:
    """Advance or fire a single trailing stop."""
    if ltp is None:
        return

    # Check the stop BEFORE ratcheting: within one tick both can be true,
    # and a breach must win. Ratcheting first could move the stop past the
    # very price that breached it and miss the exit entirely.
    if ts.is_hit(ltp):
        if _exit_position(ts, api_key):
            close_trailing_stop(ts.id, "exited", f"Trailing stop hit at {ltp}")
            _notify(
                ts,
                ts.username,
                f"Trailing stop hit for {ts.symbol} at {ltp} "
                f"(stop was {ts.stop_price}) -- position exited.",
                status="warning",
            )
        else:
            # Leave it active so the next tick retries. A stop that failed
            # to exit is still a live risk and must not be silently dropped.
            logger.warning(
                f"Trailing stop for {ts.symbol} was hit but the exit failed; "
                "will retry on the next tick"
            )
        return

    previous_stop = ts.stop_price
    if ts.update_peak(ltp) and ts.stop_price != previous_stop:
        commit_trailing_stop_move()
        logger.info(
            f"Trailing stop moved: {ts.symbol} stop {previous_stop} -> {ts.stop_price} "
            f"(price {ltp})"
        )


def _tick() -> None:
    """One monitor pass over every armed trailing stop."""
    try:
        stops = get_active_trailing_stops()
        if not stops:
            return

        # Batch the price lookups: N stops on the same instrument (a
        # multi-leg basket, say) should cost one quote, not N.
        api_key_cache: dict[str, str | None] = {}
        ltp_cache: dict[tuple[str, str], float | None] = {}

        for ts in stops:
            try:
                if ts.username not in api_key_cache:
                    from database.auth_db import get_api_key_for_tradingview

                    api_key_cache[ts.username] = get_api_key_for_tradingview(ts.username)
                api_key = api_key_cache[ts.username]

                key = (ts.symbol, ts.exchange)
                if key not in ltp_cache:
                    ltp_cache[key] = _get_ltp(ts.symbol, ts.exchange, api_key)

                _process_one(ts, api_key, ltp_cache[key])
            except Exception:
                logger.exception(
                    f"Trailing stop: tick failed for stop {getattr(ts, 'id', '?')} "
                    f"({getattr(ts, 'symbol', '?')})"
                )
    except Exception:
        logger.exception("Trailing stop monitor: tick raised unexpectedly")


def start_trailing_stop_monitor() -> None:
    """Start the background poller. Idempotent -- safe across dev-server
    autoreloads."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.debug("Trailing stop monitor: already running, skipping re-start")
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=POLL_INTERVAL_SECONDS),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let a slow tick overlap the next
        coalesce=True,
    )
    _scheduler.start()
    logger.info(f"Trailing stop monitor: started (polling every {POLL_INTERVAL_SECONDS}s)")


def stop_trailing_stop_monitor() -> None:
    """Stop the poller. Called from app.py's shutdown path -- an un-joined
    BackgroundScheduler thread is exactly the kind of leak that accumulates
    across dev-server autoreloads (see CLAUDE.md's FD hygiene note)."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.debug(f"Trailing stop monitor: shutdown raised (likely already stopped): {e}")
        _scheduler = None
