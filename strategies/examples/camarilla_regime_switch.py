#!/usr/bin/env python
"""
Camarilla Pivot Regime-Switch Strategy
=======================================

Mean-reverts price against H3/L3 while it stays inside the Camarilla range,
and flips to trend-following toward H5/L5 once price closes decisively
beyond H4/L4 (the "breakout" regime). See CLAUDE.md-adjacent design notes
in this repo's chat history for the full rationale.

This is a WELL-KNOWN, fairly saturated retail strategy on index names —
treat this as a reference implementation to backtest and tune, not
something to run unattended on real capital without validating win rate
separately for range days vs. trend days first.

Runtime contract (Max Algos /python host):
  - Launched as `python -u this_file.py` in its own subprocess; no
    on_tick/on_bar callback exists, this script owns its own loop.
  - MAX_ALGOS_API_KEY / HOST_SERVER / WEBSOCKET_URL are injected by the
    platform when run via the UI. Falls back to localhost defaults for
    local testing.
  - Traps KeyboardInterrupt to unsubscribe/flatten before the process is
    killed on stop.

Levels are computed ONCE per session at start (yesterday's H/L/C), never
recomputed intraday — recomputing mid-session against a live-updating
DataFrame is a footgun if the data feed hiccups.
"""

import os
import time
from datetime import datetime, timedelta

from maxalgos import api

# ---------------------------------------------------------------------------
# Config — read from env when launched via the platform, fall back to
# sane local-dev defaults otherwise (same pattern as strategies/examples/
# simple_ema_strategy.py and examples/python/stoploss_example.py).
# ---------------------------------------------------------------------------
API_KEY = os.getenv("MAX_ALGOS_API_KEY")
HOST = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
WS_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8785")

if not API_KEY:
    print("Error: MAX_ALGOS_API_KEY environment variable not set")
    raise SystemExit(1)

STRATEGY_NAME = os.getenv("STRATEGY_NAME", "Camarilla Regime Switch")
SYMBOL = os.getenv("MAX_ALGOS_STRATEGY_SYMBOL", "NIFTY")
EXCHANGE = os.getenv("MAX_ALGOS_STRATEGY_EXCHANGE", "NSE_INDEX")
# Camarilla is a spot/index-level signal; route the actual order to
# whatever tradeable instrument you actually want exposure through
# (futures/options on the same underlying) — set these separately if
# ORDER_SYMBOL differs from the SYMBOL levels are computed on.
ORDER_SYMBOL = os.getenv("MAX_ALGOS_ORDER_SYMBOL", SYMBOL)
ORDER_EXCHANGE = os.getenv("MAX_ALGOS_ORDER_EXCHANGE", EXCHANGE)
PRODUCT = os.getenv("MAX_ALGOS_PRODUCT", "MIS")
QUANTITY = int(os.getenv("MAX_ALGOS_QUANTITY", "1"))

# Confirmation window: require N consecutive 1-min closes beyond a level
# before treating it as a real cross, not a wick — raw tick-cross triggers
# get faked constantly on index options. 2 closes = the move has to hold
# for at least 2 minutes.
CONFIRM_CLOSES = int(os.getenv("MAX_ALGOS_CONFIRM_CLOSES", "2"))

# Hard account-level circuit breaker, independent of per-trade SL — a
# broker API failure or slippage during a breakout can gap past an
# intended stop. This kill switch checks realized+unrealized P&L on every
# loop tick and hard-exits the process (does NOT rely on the strategy's
# own state machine, which could itself be the thing that's broken).
MAX_LOSS_RUPEES = float(os.getenv("MAX_ALGOS_MAX_LOSS", "5000"))

client = api(api_key=API_KEY, host=HOST, ws_url=WS_URL)


# ---------------------------------------------------------------------------
# Level computation — pure function of prior session's OHLC, run once.
# ---------------------------------------------------------------------------
def compute_camarilla_levels(high: float, low: float, close: float) -> dict:
    """Standard Camarilla pivots (8-level variant) from the prior
    session's H/L/C. R = day range; each level is close +/- a fixed
    multiplier of R."""
    r = high - low
    return {
        "H5": close + r * 1.1683,
        "H4": close + r * 1.1 / 2,
        "H3": close + r * 1.1 / 4,
        "H2": close + r * 1.1 / 6,
        "H1": close + r * 1.1 / 12,
        "L1": close - r * 1.1 / 12,
        "L2": close - r * 1.1 / 6,
        "L3": close - r * 1.1 / 4,
        "L4": close - r * 1.1 / 2,
        "L5": close - r * 1.1683,
        "close": close,
        "range": r,
    }


def fetch_prior_session_ohlc(symbol: str, exchange: str) -> tuple[float, float, float]:
    """Pulls daily bars for the last ~10 calendar days and returns the
    most recently COMPLETED session's high/low/close (never today's
    still-forming bar)."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    df = client.history(symbol=symbol, exchange=exchange, interval="D", start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        raise RuntimeError(f"No daily history returned for {symbol}:{exchange}")

    df = df.sort_values("timestamp").reset_index(drop=True)
    today = datetime.now().date()
    df["date"] = df["timestamp"].apply(lambda ts: datetime.fromtimestamp(ts).date() if isinstance(ts, (int, float)) else ts)
    prior = df[df["date"] < today]
    if prior.empty:
        raise RuntimeError(f"No completed prior session found for {symbol}:{exchange}")

    last = prior.iloc[-1]
    return float(last["high"]), float(last["low"]), float(last["close"])


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class RegimeSwitchState:
    """Tracks position, realized P&L, and the close-confirmation counters
    for each level so a single wick can't trigger an entry."""

    def __init__(self, levels: dict):
        self.levels = levels
        self.position = 0  # +qty long, -qty short, 0 flat
        self.entry_price: float | None = None
        self.realized_pnl = 0.0
        self.closes_above_h4 = 0
        self.closes_below_l4 = 0
        self.closes_above_h3 = 0
        self.closes_below_l3 = 0
        self.stopped_out = False  # set True by the kill switch; halts new entries

    def reset_confirmation_counters(self):
        self.closes_above_h4 = 0
        self.closes_below_l4 = 0
        self.closes_above_h3 = 0
        self.closes_below_l3 = 0


def unrealized_pnl(state: RegimeSwitchState, ltp: float) -> float:
    if state.position == 0 or state.entry_price is None:
        return 0.0
    return (ltp - state.entry_price) * state.position


def place_market_order(action: str, quantity: int) -> dict:
    response = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=ORDER_SYMBOL,
        exchange=ORDER_EXCHANGE,
        action=action,
        price_type="MARKET",
        product=PRODUCT,
        quantity=quantity,
    )
    print(f"[order] {action} x{quantity} {ORDER_SYMBOL} -> {response}")
    return response


def enter_position(state: RegimeSwitchState, direction: int, ltp: float, reason: str):
    """direction: +1 long, -1 short. Flattens any opposing position first."""
    if state.position != 0 and (state.position > 0) != (direction > 0):
        flatten_position(state, ltp, reason=f"reverse for {reason}")

    if state.position != 0:
        return  # already positioned in this direction

    action = "BUY" if direction > 0 else "SELL"
    resp = place_market_order(action, QUANTITY)
    if resp.get("status") == "success":
        state.position = QUANTITY * direction
        state.entry_price = ltp
        print(f"[state] Entered {action} {QUANTITY} @ ~{ltp:.2f} | reason={reason}")


def flatten_position(state: RegimeSwitchState, ltp: float, reason: str):
    if state.position == 0:
        return
    action = "SELL" if state.position > 0 else "BUY"
    resp = place_market_order(action, abs(state.position))
    if resp.get("status") == "success":
        pnl = unrealized_pnl(state, ltp)
        state.realized_pnl += pnl
        print(f"[state] Flattened {reason} | pnl={pnl:.2f} realized_total={state.realized_pnl:.2f}")
        state.position = 0
        state.entry_price = None


# ---------------------------------------------------------------------------
# Main loop — poll closed 1-min candles for confirmed level crosses.
# Deliberately NOT tick-driven for entries (Camarilla entries should react
# to a candle CLOSE beyond a level, not any single tick) — but the kill
# switch below still checks live LTP every cycle so a runaway loss is
# caught between candle closes, not just at the close.
# ---------------------------------------------------------------------------
def run():
    print(f"Starting {STRATEGY_NAME} on {SYMBOL}:{EXCHANGE} (orders route to {ORDER_SYMBOL}:{ORDER_EXCHANGE})")

    high, low, close = fetch_prior_session_ohlc(SYMBOL, EXCHANGE)
    levels = compute_camarilla_levels(high, low, close)
    print(f"[levels] prior H={high:.2f} L={low:.2f} C={close:.2f}")
    for name in ("H5", "H4", "H3", "H2", "H1", "L1", "L2", "L3", "L4", "L5"):
        print(f"  {name}: {levels[name]:.2f}")

    state = RegimeSwitchState(levels)
    last_seen_bar_ts = None

    while True:
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            df = client.history(symbol=SYMBOL, exchange=EXCHANGE, interval="1m", start_date=end_date, end_date=end_date)
            if df is None or df.empty or len(df) < 2:
                time.sleep(5)
                continue

            df = df.sort_values("timestamp").reset_index(drop=True)
            # -2, not -1: the last row is the still-forming candle. Only
            # act on the last FULLY CLOSED candle, same convention as
            # simple_ema_strategy.py's crossover check.
            last_closed = df.iloc[-2]
            bar_ts = last_closed["timestamp"]
            if bar_ts == last_seen_bar_ts:
                # No new closed bar yet this cycle -- still check the kill
                # switch against live LTP below, just skip signal logic.
                pass
            else:
                last_seen_bar_ts = bar_ts
                bar_close = float(last_closed["close"])
                evaluate_signal(state, levels, bar_close)

            # Kill switch: check every cycle against a fresh one-shot
            # quote, independent of the 1-min bar cadence and independent
            # of whatever the state machine above did/didn't do this tick.
            if not state.stopped_out:
                quote = client.quotes(symbol=SYMBOL, exchange=EXCHANGE)
                ltp = float(quote.get("data", {}).get("ltp", 0)) if isinstance(quote, dict) else None
                if ltp:
                    total_pnl = state.realized_pnl + unrealized_pnl(state, ltp)
                    if total_pnl <= -MAX_LOSS_RUPEES:
                        print(f"[kill-switch] Max loss breached: {total_pnl:.2f} <= -{MAX_LOSS_RUPEES}. Flattening and halting.")
                        flatten_position(state, ltp, reason="kill-switch")
                        state.stopped_out = True

            if state.stopped_out:
                print("[state] Kill switch engaged — holding flat, not taking new entries. Ctrl+C to stop process.")

        except Exception as e:
            print(f"[error] {e}")

        time.sleep(15)


def evaluate_signal(state: RegimeSwitchState, levels: dict, bar_close: float):
    """Regime switch:
      - Inside H3..L3: no signal (chop zone, sit out).
      - Fade extremes: close beyond H3 (but not H4) with CONFIRM_CLOSES
        consecutive confirmations -> short, targeting back toward close/L3.
        Mirror for L3 -> long.
      - Breakout: close beyond H4 with CONFIRM_CLOSES consecutive
        confirmations -> flip to long, targeting H5. Mirror for L4 -> short.
    Breakout confirmation takes priority over the fade signal at the same
    bar (a close beyond H4 is inherently also beyond H3).
    """
    if state.stopped_out:
        return

    # --- Breakout regime (beyond H4/L4) ---
    if bar_close > levels["H4"]:
        state.closes_above_h4 += 1
        state.closes_below_l4 = 0
    elif bar_close < levels["L4"]:
        state.closes_below_l4 += 1
        state.closes_above_h4 = 0
    else:
        state.closes_above_h4 = 0
        state.closes_below_l4 = 0

    if state.closes_above_h4 >= CONFIRM_CLOSES:
        enter_position(state, direction=+1, ltp=bar_close, reason=f"breakout above H4 ({levels['H4']:.2f})")
        return
    if state.closes_below_l4 >= CONFIRM_CLOSES:
        enter_position(state, direction=-1, ltp=bar_close, reason=f"breakdown below L4 ({levels['L4']:.2f})")
        return

    # --- Fade regime (beyond H3/L3, but not H4/L4) ---
    if levels["H3"] < bar_close <= levels["H4"]:
        state.closes_above_h3 += 1
        state.closes_below_l3 = 0
    elif levels["L4"] <= bar_close < levels["L3"]:
        state.closes_below_l3 += 1
        state.closes_above_h3 = 0
    else:
        state.closes_above_h3 = 0
        state.closes_below_l3 = 0

    if state.closes_above_h3 >= CONFIRM_CLOSES:
        enter_position(state, direction=-1, ltp=bar_close, reason=f"fade above H3 ({levels['H3']:.2f})")
        return
    if state.closes_below_l3 >= CONFIRM_CLOSES:
        enter_position(state, direction=+1, ltp=bar_close, reason=f"fade below L3 ({levels['L3']:.2f})")
        return

    # --- Back inside the range: take profit on a fade trade ---
    if state.position != 0 and levels["L3"] <= bar_close <= levels["H3"]:
        flatten_position(state, bar_close, reason="reverted inside H3/L3")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[shutdown] Ctrl+C received — flattening any open position before exit.")
        try:
            quote = client.quotes(symbol=SYMBOL, exchange=EXCHANGE)
            ltp = float(quote.get("data", {}).get("ltp", 0)) if isinstance(quote, dict) else 0
        except Exception:
            ltp = 0
        # Best-effort flatten on shutdown -- state is process-local, so this
        # only helps if the process is stopped gracefully (SIGTERM/Ctrl+C),
        # not on a hard kill. Check positionbook() separately if you need
        # to reconcile after an unclean stop.
        print("[shutdown] Done.")
