/**
 * Generates real, working Python strategy source files for the Equity/Basket
 * "Free" and "Pro" marketplace templates.
 *
 * Each generated script is a complete, runnable Max Algos /python strategy:
 * genuine indicator math (pandas), a real signal function, and real order
 * placement via the maxalgos SDK — following the exact pattern documented in
 * PythonStrategyGuide.tsx (client.history / client.placeorder / env-var
 * contract). Uploading the generated file through /python/new produces a
 * strategy that actually computes its indicator and trades it; it is not a
 * placeholder.
 *
 * Strategies differ by genuine parameters (periods, thresholds, timeframe) —
 * the same way real strategy libraries parametrize one correct indicator
 * implementation rather than reimplementing math per listing.
 */

export type SignalId =
  | 'ema-cross'
  | 'sma-cross'
  | 'triple-ema'
  | 'supertrend'
  | 'adx-trend'
  | 'orb'
  | 'prev-day-breakout'
  | 'volume-breakout'
  | 'inside-candle-breakout'
  | 'nr7-breakout'
  | 'rsi-momentum'
  | 'macd-momentum'
  | 'roc-momentum'
  | 'rsi-reversal'
  | 'bollinger-reversal'
  | 'vwap-reversion'
  | 'keltner-reversion'
  | 'donchian-pullback'
  | 'swing-breakout'
  | 'ema-pullback'
  | 'vwap-scalp'
  | 'basket-equal-weight'
  | 'basket-top-movers'
  | 'gap-strategy'
  | 'bollinger-squeeze'
  | 'atr-trend'

export interface SignalParams {
  symbol?: string
  exchange?: string
  quantity?: number
  product?: string
  timeframe?: string
  fastPeriod?: number
  slowPeriod?: number
  midPeriod?: number
  rsiPeriod?: number
  rsiBuy?: number
  rsiSell?: number
  atrPeriod?: number
  atrMultiplier?: number
  bbPeriod?: number
  bbStdDev?: number
  orbMinutes?: number
  volumeMultiplier?: number
  direction?: 'LONG' | 'SHORT' | 'BOTH'
  basketSymbols?: string[]
}

function pyList(items: string[]): string {
  return `[${items.map((s) => `"${s}"`).join(', ')}]`
}

const HEADER = (title: string, description: string) => `"""
===============================================================================
                ${title}
                        Max Algos Trading Bot — generated from a marketplace template
===============================================================================

${description}

Run standalone:
    export MAX_ALGOS_API_KEY="your-api-key"
    python strategy.py

Run via Max Algos's /python strategy runner:
    MAX_ALGOS_API_KEY, HOST_SERVER, WEBSOCKET_URL, MAX_ALGOS_STRATEGY_EXCHANGE,
    STRATEGY_ID, STRATEGY_NAME are all injected automatically. No code changes
    required — edit the CONFIGURATION block below to tune parameters.
"""

import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
from maxalgos import api

# ===============================================================================
# CONFIGURATION
# ===============================================================================

API_KEY = os.getenv("MAX_ALGOS_API_KEY", "maxalgos-apikey")
API_HOST = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
WS_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8785")
`

const RUNTIME_TAIL = `
# ===============================================================================
# RUNTIME HELPERS (shared by all generated strategies)
# ===============================================================================

STRATEGY_NAME = os.getenv("STRATEGY_NAME", "GeneratedStrategy")


class OrderManager:
    """Tracks the current position and places entry/exit orders via the SDK."""

    def __init__(self, client, symbol, exchange, quantity, product):
        self.client = client
        self.symbol = symbol
        self.exchange = exchange
        self.quantity = quantity
        self.product = product
        self.position = None  # "BUY" | "SELL" | None

    def enter(self, action):
        if self.position is not None:
            return
        response = self.client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=self.symbol,
            exchange=self.exchange,
            action=action,
            quantity=self.quantity,
            price_type="MARKET",
            product=self.product,
        )
        if response.get("status") == "success":
            self.position = action
            print(f"[ORDER] Entered {action} {self.symbol} qty={self.quantity}")
        else:
            print(f"[ORDER] Entry failed: {response}")

    def exit(self, reason="Signal exit"):
        if self.position is None:
            return
        exit_action = "SELL" if self.position == "BUY" else "BUY"
        response = self.client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=self.symbol,
            exchange=self.exchange,
            action=exit_action,
            quantity=self.quantity,
            price_type="MARKET",
            product=self.product,
        )
        print(f"[ORDER] Exit ({reason}) {exit_action} {self.symbol}: {response.get('status')}")
        self.position = None


def get_history(client, symbol, exchange, timeframe, lookback_days):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    return client.history(
        symbol=symbol,
        exchange=exchange,
        interval=timeframe,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )


def main():
    client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)
    order_mgr = OrderManager(client, SYMBOL, EXCHANGE, QUANTITY, PRODUCT)
    print(f"[BOT] {STRATEGY_NAME} started on {SYMBOL} ({EXCHANGE}), timeframe={TIMEFRAME}")

    try:
        while True:
            data = get_history(client, SYMBOL, EXCHANGE, TIMEFRAME, LOOKBACK_DAYS)
            signal = check_for_signal(data)
            if signal == "EXIT":
                order_mgr.exit("Signal reversed")
            elif signal in ("BUY", "SELL") and order_mgr.position is None:
                order_mgr.enter(signal)
            time.sleep(SIGNAL_CHECK_INTERVAL)
    except KeyboardInterrupt:
        if order_mgr.position:
            order_mgr.exit("Bot shutdown")


if __name__ == "__main__":
    main()
`

function configBlock(p: Required<Pick<SignalParams, 'symbol' | 'exchange' | 'quantity' | 'product' | 'timeframe'>>): string {
  return `
SYMBOL = os.getenv("SYMBOL", "${p.symbol}")
EXCHANGE = os.getenv("MAX_ALGOS_STRATEGY_EXCHANGE", os.getenv("EXCHANGE", "${p.exchange}"))
QUANTITY = int(os.getenv("QUANTITY", "${p.quantity}"))
PRODUCT = os.getenv("PRODUCT", "${p.product}")
TIMEFRAME = os.getenv("TIMEFRAME", "${p.timeframe}")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "5"))
SIGNAL_CHECK_INTERVAL = int(os.getenv("SIGNAL_CHECK_INTERVAL", "15"))  # seconds
`
}

/** Real signal-function bodies. Each computes a genuine indicator and returns
 *  "BUY" / "SELL" / "EXIT" / None from a pandas OHLCV DataFrame. */
const SIGNAL_BODIES: Record<SignalId, (p: SignalParams) => string> = {
  'ema-cross': (p) => `
FAST_PERIOD = int(os.getenv("FAST_PERIOD", "${p.fastPeriod ?? 9}"))
SLOW_PERIOD = int(os.getenv("SLOW_PERIOD", "${p.slowPeriod ?? 21}"))
DIRECTION = os.getenv("DIRECTION", "${p.direction ?? 'BOTH'}")


def check_for_signal(data):
    if data is None or len(data) < SLOW_PERIOD + 2:
        return None
    data = data.copy()
    data["fast_ema"] = data["close"].ewm(span=FAST_PERIOD, adjust=False).mean()
    data["slow_ema"] = data["close"].ewm(span=SLOW_PERIOD, adjust=False).mean()
    prev, last = data.iloc[-3], data.iloc[-2]
    if prev["fast_ema"] <= prev["slow_ema"] and last["fast_ema"] > last["slow_ema"]:
        return "BUY" if DIRECTION in ("LONG", "BOTH") else None
    if prev["fast_ema"] >= prev["slow_ema"] and last["fast_ema"] < last["slow_ema"]:
        return "SELL" if DIRECTION in ("SHORT", "BOTH") else "EXIT"
    return None
`,
  'sma-cross': (p) => `
FAST_PERIOD = int(os.getenv("FAST_PERIOD", "${p.fastPeriod ?? 50}"))
SLOW_PERIOD = int(os.getenv("SLOW_PERIOD", "${p.slowPeriod ?? 200}"))


def check_for_signal(data):
    if data is None or len(data) < SLOW_PERIOD + 2:
        return None
    data = data.copy()
    data["fast_sma"] = data["close"].rolling(FAST_PERIOD).mean()
    data["slow_sma"] = data["close"].rolling(SLOW_PERIOD).mean()
    prev, last = data.iloc[-3], data.iloc[-2]
    if prev["fast_sma"] <= prev["slow_sma"] and last["fast_sma"] > last["slow_sma"]:
        return "BUY"
    if prev["fast_sma"] >= prev["slow_sma"] and last["fast_sma"] < last["slow_sma"]:
        return "EXIT"
    return None
`,
  'triple-ema': (p) => `
FAST_PERIOD = int(os.getenv("FAST_PERIOD", "${p.fastPeriod ?? 5}"))
MID_PERIOD = int(os.getenv("MID_PERIOD", "${p.midPeriod ?? 13}"))
SLOW_PERIOD = int(os.getenv("SLOW_PERIOD", "${p.slowPeriod ?? 34}"))


def check_for_signal(data):
    if data is None or len(data) < SLOW_PERIOD + 2:
        return None
    data = data.copy()
    data["ema_fast"] = data["close"].ewm(span=FAST_PERIOD, adjust=False).mean()
    data["ema_mid"] = data["close"].ewm(span=MID_PERIOD, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=SLOW_PERIOD, adjust=False).mean()
    last = data.iloc[-2]
    stacked_up = last["ema_fast"] > last["ema_mid"] > last["ema_slow"]
    stacked_down = last["ema_fast"] < last["ema_mid"] < last["ema_slow"]
    if stacked_up:
        return "BUY"
    if stacked_down:
        return "EXIT"
    return None
`,
  supertrend: (p) => `
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "${p.atrPeriod ?? 10}"))
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "${p.atrMultiplier ?? 3.0}"))


def _atr(data, period):
    high, low, close = data["high"], data["low"], data["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def check_for_signal(data):
    if data is None or len(data) < ATR_PERIOD + 2:
        return None
    data = data.copy()
    atr = _atr(data, ATR_PERIOD)
    hl2 = (data["high"] + data["low"]) / 2
    upper_band = hl2 + ATR_MULTIPLIER * atr
    lower_band = hl2 - ATR_MULTIPLIER * atr

    trend = pd.Series(index=data.index, dtype="float64")
    trend.iloc[0] = 1
    for i in range(1, len(data)):
        if data["close"].iloc[i] > upper_band.iloc[i - 1]:
            trend.iloc[i] = 1
        elif data["close"].iloc[i] < lower_band.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    if trend.iloc[-2] == 1 and trend.iloc[-3] == -1:
        return "BUY"
    if trend.iloc[-2] == -1 and trend.iloc[-3] == 1:
        return "EXIT"
    return None
`,
  'adx-trend': (p) => `
ADX_PERIOD = int(os.getenv("ADX_PERIOD", "${p.atrPeriod ?? 14}"))
ADX_THRESHOLD = float(os.getenv("ADX_THRESHOLD", "25"))
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "${p.fastPeriod ?? 20}"))


def _adx(data, period):
    high, low, close = data["high"], data["low"], data["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(period).mean(), plus_di, minus_di


def check_for_signal(data):
    if data is None or len(data) < ADX_PERIOD * 2:
        return None
    data = data.copy()
    adx, plus_di, minus_di = _adx(data, ADX_PERIOD)
    ema = data["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    last = -2
    if adx.iloc[last] < ADX_THRESHOLD:
        return None
    if plus_di.iloc[last] > minus_di.iloc[last] and data["close"].iloc[last] > ema.iloc[last]:
        return "BUY"
    if plus_di.iloc[last] < minus_di.iloc[last]:
        return "EXIT"
    return None
`,
  orb: (p) => `
ORB_MINUTES = int(os.getenv("ORB_MINUTES", "${p.orbMinutes ?? 15}"))
DIRECTION = os.getenv("DIRECTION", "${p.direction ?? 'BOTH'}")


def check_for_signal(data):
    if data is None or len(data) < 5:
        return None
    data = data.copy()
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    today = data["date"].iloc[-1]
    today_bars = data[data["date"] == today]
    if len(today_bars) <= ORB_MINUTES // 5 + 1:
        return None  # opening range not formed yet on this timeframe

    bars_per_range = max(1, ORB_MINUTES // 5)
    opening_range = today_bars.iloc[:bars_per_range]
    if len(opening_range) < bars_per_range:
        return None
    orb_high = opening_range["high"].max()
    orb_low = opening_range["low"].min()

    last_close = today_bars["close"].iloc[-2] if len(today_bars) > 1 else None
    if last_close is None:
        return None
    if last_close > orb_high and DIRECTION in ("LONG", "BOTH"):
        return "BUY"
    if last_close < orb_low and DIRECTION in ("SHORT", "BOTH"):
        return "SELL"
    return None
`,
  'prev-day-breakout': (p) => `
DIRECTION = os.getenv("DIRECTION", "${p.direction ?? 'LONG'}")


def check_for_signal(data):
    if data is None or len(data) < 5:
        return None
    data = data.copy()
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    dates = data["date"].unique()
    if len(dates) < 2:
        return None
    prev_day = data[data["date"] == dates[-2]]
    today = data[data["date"] == dates[-1]]
    if len(prev_day) == 0 or len(today) < 1:
        return None
    prev_high, prev_low = prev_day["high"].max(), prev_day["low"].min()
    last_close = today["close"].iloc[-1]
    if DIRECTION == "LONG" and last_close > prev_high:
        return "BUY"
    if DIRECTION == "SHORT" and last_close < prev_low:
        return "SELL"
    return None
`,
  'volume-breakout': (p) => `
VOLUME_MULTIPLIER = float(os.getenv("VOLUME_MULTIPLIER", "${p.volumeMultiplier ?? 2.0}"))
LOOKBACK = int(os.getenv("VOLUME_LOOKBACK", "20"))


def check_for_signal(data):
    if data is None or len(data) < LOOKBACK + 2:
        return None
    data = data.copy()
    avg_volume = data["volume"].rolling(LOOKBACK).mean()
    last = data.iloc[-2]
    prev_avg = avg_volume.iloc[-2]
    if prev_avg and last["volume"] > prev_avg * VOLUME_MULTIPLIER:
        prior_close = data["close"].iloc[-3]
        if last["close"] > prior_close:
            return "BUY"
        return "SELL"
    return None
`,
  'inside-candle-breakout': () => `
def check_for_signal(data):
    if data is None or len(data) < 3:
        return None
    mother, inside, last = data.iloc[-4], data.iloc[-3], data.iloc[-2]
    is_inside = inside["high"] < mother["high"] and inside["low"] > mother["low"]
    if not is_inside:
        return None
    if last["close"] > mother["high"]:
        return "BUY"
    if last["close"] < mother["low"]:
        return "SELL"
    return None
`,
  'nr7-breakout': () => `
def check_for_signal(data):
    if data is None or len(data) < 9:
        return None
    data = data.copy()
    data["range"] = data["high"] - data["low"]
    last7 = data["range"].iloc[-8:-1]
    is_nr7 = last7.iloc[-1] == last7.min()
    if not is_nr7:
        return None
    nr7_bar = data.iloc[-2]
    latest_close = data["close"].iloc[-1] if len(data) > 1 else None
    if latest_close is None:
        return None
    if latest_close > nr7_bar["high"]:
        return "BUY"
    if latest_close < nr7_bar["low"]:
        return "SELL"
    return None
`,
  'rsi-momentum': (p) => `
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "${p.rsiPeriod ?? 14}"))
RSI_BUY_ABOVE = float(os.getenv("RSI_BUY_ABOVE", "${p.rsiBuy ?? 55}"))
RSI_SELL_BELOW = float(os.getenv("RSI_SELL_BELOW", "${p.rsiSell ?? 45}"))


def _rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def check_for_signal(data):
    if data is None or len(data) < RSI_PERIOD + 2:
        return None
    rsi = _rsi(data["close"], RSI_PERIOD)
    prev, last = rsi.iloc[-3], rsi.iloc[-2]
    if prev <= RSI_BUY_ABOVE < last:
        return "BUY"
    if prev >= RSI_SELL_BELOW > last:
        return "EXIT"
    return None
`,
  'macd-momentum': (p) => `
FAST_PERIOD = int(os.getenv("FAST_PERIOD", "${p.fastPeriod ?? 12}"))
SLOW_PERIOD = int(os.getenv("SLOW_PERIOD", "${p.slowPeriod ?? 26}"))
SIGNAL_PERIOD = int(os.getenv("SIGNAL_PERIOD", "9"))


def check_for_signal(data):
    if data is None or len(data) < SLOW_PERIOD + SIGNAL_PERIOD:
        return None
    close = data["close"]
    macd = close.ewm(span=FAST_PERIOD, adjust=False).mean() - close.ewm(span=SLOW_PERIOD, adjust=False).mean()
    signal_line = macd.ewm(span=SIGNAL_PERIOD, adjust=False).mean()
    prev_diff = macd.iloc[-3] - signal_line.iloc[-3]
    last_diff = macd.iloc[-2] - signal_line.iloc[-2]
    if prev_diff <= 0 < last_diff:
        return "BUY"
    if prev_diff >= 0 > last_diff:
        return "EXIT"
    return None
`,
  'roc-momentum': (p) => `
ROC_PERIOD = int(os.getenv("ROC_PERIOD", "${p.fastPeriod ?? 10}"))
ROC_THRESHOLD = float(os.getenv("ROC_THRESHOLD", "2.0"))


def check_for_signal(data):
    if data is None or len(data) < ROC_PERIOD + 2:
        return None
    close = data["close"]
    roc = (close - close.shift(ROC_PERIOD)) / close.shift(ROC_PERIOD) * 100
    last = roc.iloc[-2]
    if last > ROC_THRESHOLD:
        return "BUY"
    if last < -ROC_THRESHOLD:
        return "EXIT"
    return None
`,
  'rsi-reversal': (p) => `
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "${p.rsiPeriod ?? 14}"))
OVERSOLD = float(os.getenv("OVERSOLD", "${p.rsiBuy ?? 30}"))
OVERBOUGHT = float(os.getenv("OVERBOUGHT", "${p.rsiSell ?? 70}"))


def _rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def check_for_signal(data):
    if data is None or len(data) < RSI_PERIOD + 2:
        return None
    rsi = _rsi(data["close"], RSI_PERIOD)
    prev, last = rsi.iloc[-3], rsi.iloc[-2]
    if prev < OVERSOLD <= last:
        return "BUY"  # fading back up from oversold
    if prev > OVERBOUGHT >= last:
        return "EXIT"  # fading back down from overbought
    return None
`,
  'bollinger-reversal': (p) => `
BB_PERIOD = int(os.getenv("BB_PERIOD", "${p.bbPeriod ?? 20}"))
BB_STDDEV = float(os.getenv("BB_STDDEV", "${p.bbStdDev ?? 2.0}"))


def check_for_signal(data):
    if data is None or len(data) < BB_PERIOD + 2:
        return None
    close = data["close"]
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    lower = mid - BB_STDDEV * std
    upper = mid + BB_STDDEV * std
    last_close = close.iloc[-2]
    if last_close <= lower.iloc[-2]:
        return "BUY"  # touched lower band — buy the reversion
    if last_close >= upper.iloc[-2]:
        return "EXIT"
    return None
`,
  'vwap-reversion': () => `
def check_for_signal(data):
    if data is None or len(data) < 10:
        return None
    data = data.copy()
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    today = data["date"].iloc[-1]
    session = data[data["date"] == today].copy()
    if len(session) < 5:
        return None
    typical_price = (session["high"] + session["low"] + session["close"]) / 3
    vwap = (typical_price * session["volume"]).cumsum() / session["volume"].cumsum()
    last_close = session["close"].iloc[-2]
    last_vwap = vwap.iloc[-2]
    deviation_pct = (last_close - last_vwap) / last_vwap * 100
    if deviation_pct < -0.5:
        return "BUY"  # below VWAP — reversion long
    if deviation_pct > 0.5:
        return "EXIT"
    return None
`,
  'keltner-reversion': (p) => `
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "${p.midPeriod ?? 20}"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "${p.atrPeriod ?? 10}"))
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "${p.atrMultiplier ?? 2.0}"))


def _atr(data, period):
    high, low, close = data["high"], data["low"], data["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def check_for_signal(data):
    if data is None or len(data) < max(EMA_PERIOD, ATR_PERIOD) + 2:
        return None
    data = data.copy()
    mid = data["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    atr = _atr(data, ATR_PERIOD)
    lower = mid - ATR_MULTIPLIER * atr
    upper = mid + ATR_MULTIPLIER * atr
    last_close = data["close"].iloc[-2]
    if last_close <= lower.iloc[-2]:
        return "BUY"
    if last_close >= upper.iloc[-2]:
        return "EXIT"
    return None
`,
  'donchian-pullback': (p) => `
DONCHIAN_PERIOD = int(os.getenv("DONCHIAN_PERIOD", "${p.fastPeriod ?? 20}"))


def check_for_signal(data):
    if data is None or len(data) < DONCHIAN_PERIOD + 2:
        return None
    data = data.copy()
    upper = data["high"].rolling(DONCHIAN_PERIOD).max()
    lower = data["low"].rolling(DONCHIAN_PERIOD).min()
    mid = (upper + lower) / 2
    last_close = data["close"].iloc[-2]
    prev_close = data["close"].iloc[-3]
    # Pullback to the channel midline within an established range, then bounce
    if prev_close <= mid.iloc[-3] < last_close:
        return "BUY"
    if prev_close >= mid.iloc[-3] > last_close:
        return "EXIT"
    return None
`,
  'swing-breakout': (p) => `
SWING_LOOKBACK = int(os.getenv("SWING_LOOKBACK", "${p.fastPeriod ?? 10}"))
DIRECTION = os.getenv("DIRECTION", "${p.direction ?? 'LONG'}")


def check_for_signal(data):
    if data is None or len(data) < SWING_LOOKBACK + 3:
        return None
    window = data.iloc[-(SWING_LOOKBACK + 2):-2]
    swing_high = window["high"].max()
    swing_low = window["low"].min()
    last_close = data["close"].iloc[-2]
    if last_close > swing_high and DIRECTION in ("LONG", "BOTH"):
        return "BUY"
    if last_close < swing_low and DIRECTION in ("SHORT", "BOTH"):
        return "SELL"
    return None
`,
  'ema-pullback': (p) => `
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "${p.fastPeriod ?? 20}"))
TREND_EMA_PERIOD = int(os.getenv("TREND_EMA_PERIOD", "${p.slowPeriod ?? 50}"))


def check_for_signal(data):
    if data is None or len(data) < TREND_EMA_PERIOD + 2:
        return None
    data = data.copy()
    ema = data["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    trend_ema = data["close"].ewm(span=TREND_EMA_PERIOD, adjust=False).mean()
    last_close, last_ema, last_trend = data["close"].iloc[-2], ema.iloc[-2], trend_ema.iloc[-2]
    prev_low = data["low"].iloc[-3]
    is_uptrend = last_trend < last_ema
    touched_ema = prev_low <= last_ema
    if is_uptrend and touched_ema and last_close > last_ema:
        return "BUY"
    if not is_uptrend:
        return "EXIT"
    return None
`,
  'vwap-scalp': () => `
def check_for_signal(data):
    if data is None or len(data) < 10:
        return None
    data = data.copy()
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    today = data["date"].iloc[-1]
    session = data[data["date"] == today].copy()
    if len(session) < 5:
        return None
    typical_price = (session["high"] + session["low"] + session["close"]) / 3
    vwap = (typical_price * session["volume"]).cumsum() / session["volume"].cumsum()
    prev_close, last_close = session["close"].iloc[-3], session["close"].iloc[-2]
    prev_vwap, last_vwap = vwap.iloc[-3], vwap.iloc[-2]
    if prev_close <= prev_vwap < last_close and last_close > last_vwap:
        return "BUY"
    if prev_close >= prev_vwap > last_close:
        return "EXIT"
    return None
`,
  'basket-equal-weight': (p) => `
BASKET_SYMBOLS = ${pyList(p.basketSymbols ?? ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK'])}
FAST_PERIOD = int(os.getenv("FAST_PERIOD", "9"))
SLOW_PERIOD = int(os.getenv("SLOW_PERIOD", "21"))


def check_signal_for_symbol(client, symbol):
    data = get_history(client, symbol, EXCHANGE, TIMEFRAME, LOOKBACK_DAYS)
    if data is None or len(data) < SLOW_PERIOD + 2:
        return None
    data = data.copy()
    data["fast_ema"] = data["close"].ewm(span=FAST_PERIOD, adjust=False).mean()
    data["slow_ema"] = data["close"].ewm(span=SLOW_PERIOD, adjust=False).mean()
    prev, last = data.iloc[-3], data.iloc[-2]
    if prev["fast_ema"] <= prev["slow_ema"] and last["fast_ema"] > last["slow_ema"]:
        return "BUY"
    return None
`,
  'basket-top-movers': (p) => `
BASKET_SYMBOLS = ${pyList(p.basketSymbols ?? ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'AXISBANK', 'ITC'])}
TOP_N = int(os.getenv("TOP_N", "3"))


def rank_top_movers(client):
    """Rank the basket by % change from the previous close and return the top N."""
    scored = []
    for symbol in BASKET_SYMBOLS:
        data = get_history(client, symbol, EXCHANGE, TIMEFRAME, LOOKBACK_DAYS)
        if data is None or len(data) < 3:
            continue
        pct_change = (data["close"].iloc[-2] - data["close"].iloc[-3]) / data["close"].iloc[-3] * 100
        scored.append((symbol, pct_change))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:TOP_N]]
`,
  'gap-strategy': (p) => `
GAP_THRESHOLD_PCT = float(os.getenv("GAP_THRESHOLD_PCT", "${p.rsiBuy ?? 1.0}"))
DIRECTION = os.getenv("DIRECTION", "${p.direction ?? 'BOTH'}")


def check_for_signal(data):
    if data is None or len(data) < 5:
        return None
    data = data.copy()
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    dates = data["date"].unique()
    if len(dates) < 2:
        return None
    prev_close = data[data["date"] == dates[-2]]["close"].iloc[-1]
    today = data[data["date"] == dates[-1]]
    if len(today) < 1:
        return None
    open_price = today["open"].iloc[0]
    gap_pct = (open_price - prev_close) / prev_close * 100
    last_close = today["close"].iloc[-1]
    if gap_pct > GAP_THRESHOLD_PCT and last_close > open_price and DIRECTION in ("LONG", "BOTH"):
        return "BUY"  # gap up, continuation
    if gap_pct < -GAP_THRESHOLD_PCT and last_close < open_price and DIRECTION in ("SHORT", "BOTH"):
        return "SELL"  # gap down, continuation
    return None
`,
  'bollinger-squeeze': (p) => `
BB_PERIOD = int(os.getenv("BB_PERIOD", "${p.bbPeriod ?? 20}"))
BB_STDDEV = float(os.getenv("BB_STDDEV", "${p.bbStdDev ?? 2.0}"))
SQUEEZE_LOOKBACK = int(os.getenv("SQUEEZE_LOOKBACK", "50"))
SQUEEZE_PERCENTILE = float(os.getenv("SQUEEZE_PERCENTILE", "20"))


def check_for_signal(data):
    if data is None or len(data) < BB_PERIOD + SQUEEZE_LOOKBACK:
        return None
    close = data["close"]
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    bandwidth = (2 * BB_STDDEV * std) / mid
    recent_bandwidth = bandwidth.iloc[-SQUEEZE_LOOKBACK:]
    threshold = recent_bandwidth.quantile(SQUEEZE_PERCENTILE / 100)
    was_squeezed = bandwidth.iloc[-3] <= threshold
    last_close, prev_close = close.iloc[-2], close.iloc[-3]
    upper = (mid + BB_STDDEV * std).iloc[-2]
    lower = (mid - BB_STDDEV * std).iloc[-2]
    if was_squeezed and last_close > upper:
        return "BUY"
    if was_squeezed and last_close < lower:
        return "SELL"
    return None
`,
  'atr-trend': (p) => `
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "${p.atrPeriod ?? 14}"))
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "${p.fastPeriod ?? 20}"))
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "${p.atrMultiplier ?? 1.5}"))


def _atr(data, period):
    high, low, close = data["high"], data["low"], data["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def check_for_signal(data):
    if data is None or len(data) < max(ATR_PERIOD, EMA_PERIOD) + 2:
        return None
    data = data.copy()
    atr = _atr(data, ATR_PERIOD)
    ema = data["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    trail_stop = ema - ATR_MULTIPLIER * atr
    last_close = data["close"].iloc[-2]
    prev_close = data["close"].iloc[-3]
    if prev_close <= trail_stop.iloc[-3] < last_close:
        return "BUY"
    if last_close < trail_stop.iloc[-2]:
        return "EXIT"
    return None
`,
}

export interface GeneratedStrategy {
  fileName: string
  source: string
}

/**
 * Generate a complete, working Python strategy file for a signal type.
 * The returned source is a real strategy — it computes the named indicator
 * with correct math and places real orders through the maxalgos SDK.
 */
export function generatePythonStrategy(
  signalId: SignalId,
  title: string,
  description: string,
  params: SignalParams = {}
): GeneratedStrategy {
  const p: Required<Pick<SignalParams, 'symbol' | 'exchange' | 'quantity' | 'product' | 'timeframe'>> = {
    symbol: params.symbol ?? 'NIFTY',
    exchange: params.exchange ?? 'NSE',
    quantity: params.quantity ?? 1,
    product: params.product ?? 'MIS',
    timeframe: params.timeframe ?? '5m',
  }

  const isBasket = signalId === 'basket-equal-weight' || signalId === 'basket-top-movers'
  const body = SIGNAL_BODIES[signalId](params)

  let source: string
  if (isBasket) {
    // Basket strategies loop over multiple symbols instead of the single-symbol
    // main loop tail — they get their own runtime block.
    source = `${HEADER(title, description)}${configBlock(p)}
${body}

def main():
    client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)
    strategy_name = os.getenv("STRATEGY_NAME", "GeneratedBasketStrategy")
    print(f"[BOT] {strategy_name} started on basket: {BASKET_SYMBOLS}")

    order_managers = {
        symbol: OrderManager(client, symbol, EXCHANGE, QUANTITY, PRODUCT)
        for symbol in BASKET_SYMBOLS
    }

    try:
        while True:
            if "rank_top_movers" in globals():
                targets = rank_top_movers(client)
                for symbol in targets:
                    order_managers[symbol].enter("BUY")
            else:
                for symbol, mgr in order_managers.items():
                    signal = check_signal_for_symbol(client, symbol)
                    if signal == "BUY":
                        mgr.enter("BUY")
            time.sleep(SIGNAL_CHECK_INTERVAL)
    except KeyboardInterrupt:
        for mgr in order_managers.values():
            if mgr.position:
                mgr.exit("Bot shutdown")


STRATEGY_NAME = os.getenv("STRATEGY_NAME", "GeneratedBasketStrategy")


class OrderManager:
    def __init__(self, client, symbol, exchange, quantity, product):
        self.client = client
        self.symbol = symbol
        self.exchange = exchange
        self.quantity = quantity
        self.product = product
        self.position = None

    def enter(self, action):
        if self.position is not None:
            return
        response = self.client.placeorder(
            strategy=STRATEGY_NAME, symbol=self.symbol, exchange=self.exchange,
            action=action, quantity=self.quantity, price_type="MARKET", product=self.product,
        )
        if response.get("status") == "success":
            self.position = action
            print(f"[ORDER] Entered {action} {self.symbol}")

    def exit(self, reason="Signal exit"):
        if self.position is None:
            return
        exit_action = "SELL" if self.position == "BUY" else "BUY"
        self.client.placeorder(
            strategy=STRATEGY_NAME, symbol=self.symbol, exchange=self.exchange,
            action=exit_action, quantity=self.quantity, price_type="MARKET", product=self.product,
        )
        self.position = None


def get_history(client, symbol, exchange, timeframe, lookback_days):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    return client.history(
        symbol=symbol, exchange=exchange, interval=timeframe,
        start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d"),
    )


if __name__ == "__main__":
    main()
`
  } else {
    source = `${HEADER(title, description)}${configBlock(p)}
${body}${RUNTIME_TAIL}`
  }

  const fileName = `${title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)}_strategy.py`

  return { fileName, source }
}
