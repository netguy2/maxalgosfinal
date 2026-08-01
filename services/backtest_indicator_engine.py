"""Historical-replay counterpart to indicator_engine.py/indicator_registry.py.

Backtesting needs every indicator (EMA/RSI/MACD/... in indicator_registry.py)
to compute the exact same math against a bar window ending at a simulated
"current" bar, sourced from Historify/DuckDB instead of the live broker API.
Rather than forking 30+ calculate() implementations, this module provides a
BacktestDataContext and sets services.indicator_registry._backtest_context_var
for the duration of one evaluation -- the handful of shared data-fetch
helpers in indicator_registry.py (_fetch_broker_ohlcv_range, _fallback_ltp)
already check that contextvar and read from here when it's set, so every
indicator's calculate() body runs completely unmodified in both live and
backtest modes.

services.condition_engine.evaluate_conditions_tree is called directly
(imported, not reimplemented) so backtest and live share the exact same
tree-walking/comparison logic -- only the underlying data source differs.
"""

import logging

import pandas as pd

from services.condition_engine import evaluate_conditions_tree
from services.indicator_registry import _backtest_context_var

logger = logging.getLogger(__name__)


class BacktestDataContext:
    """Holds one backtest run's full preloaded OHLCV history for a single
    symbol/exchange/interval, plus a mutable "current bar" cursor. Preload
    the DataFrame ONCE per backtest run (see services/backtest_engine.py)
    -- never re-fetch per bar.

    Slicing is always up to and including `cursor`, matching what an
    indicator would have actually seen live at that point in time (no
    lookahead bias).
    """

    def __init__(self, df: pd.DataFrame, symbol: str, exchange: str):
        """`df` must be oldest-first with a 'close' column (and ideally
        open/high/low/volume), as returned by
        database/historify_db.py::export_to_dataframe."""
        self.df = df.reset_index(drop=True) if df.index.name else df.reset_index()
        # export_to_dataframe returns a datetime index; keep both the
        # index as a plain 'datetime' column and a 0..n-1 positional index
        # so cursor-based slicing (iloc) is unambiguous regardless of what
        # the caller passed in.
        if "datetime" not in self.df.columns and "timestamp" in self.df.columns:
            self.df["datetime"] = pd.to_datetime(self.df["timestamp"], unit="s")
        self.symbol = symbol
        self.exchange = exchange
        self.cursor = 0

    def __len__(self):
        return len(self.df)

    def set_cursor(self, cursor: int):
        self.cursor = cursor

    def ohlcv_range(self, _start_date: str, _end_date: str) -> pd.DataFrame | None:
        """Mirrors indicator_registry.py's _fetch_broker_ohlcv_range return
        contract (a DataFrame with an 'open'/'high'/'low'/'close'/'volume'
        columns, oldest first, or None). The date-string args are ignored --
        in backtest mode there is only ever one meaningful "as of now": the
        window ending at self.cursor. This also correctly handles VWAP's
        same-day "today, today" call pattern, since "today" here just means
        "up to the current simulated bar" without needing real calendar-date
        parsing.
        """
        if self.cursor < 0 or self.cursor >= len(self.df):
            return None
        window = self.df.iloc[: self.cursor + 1]
        if window.empty:
            return None
        return window

    def close_series_up_to(self, min_bars: int) -> pd.Series | None:
        window = self.ohlcv_range(None, None)
        if window is None or "close" not in window.columns or len(window) < min_bars:
            return None
        return window["close"]

    def current_close(self) -> float:
        """Last-resort value mirroring _fallback_ltp's live behavior: the
        real close price of the current bar rather than a fabricated
        indicator number."""
        if self.cursor < 0 or self.cursor >= len(self.df):
            return 0.0
        return float(self.df.iloc[self.cursor]["close"])

    def current_bar(self) -> pd.Series:
        return self.df.iloc[self.cursor]


def evaluate_conditions_tree_backtest(
    tree: dict, symbol: str, exchange: str, ctx: BacktestDataContext, cursor: int
) -> bool:
    """Backtest-mode equivalent of a live evaluate_conditions_tree(tree,
    symbol, exchange) call -- scopes ctx/cursor as the active backtest data
    context for the duration of this one evaluation, then calls the REAL
    condition_engine.evaluate_conditions_tree unchanged."""
    ctx.set_cursor(cursor)
    token = _backtest_context_var.set(ctx)
    try:
        return bool(tree) and evaluate_conditions_tree(tree, symbol, exchange)
    finally:
        _backtest_context_var.reset(token)
