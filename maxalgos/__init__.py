"""
Max Algos Official Python SDK (`maxalgos`)
==========================================

This SDK is **bundled with the Max Algos platform** — do NOT ``pip install``
it. When the /python runner launches a strategy subprocess it automatically
injects the project root into ``PYTHONPATH`` so ``from maxalgos import api``
resolves out of the box.

Provides the :class:`api` class for REST-based order execution, market data,
and account queries, plus the :class:`ta` class for technical analysis helpers.
"""

import logging
import os
import time
from typing import Any, Optional

import pandas as pd
import requests

logger = logging.getLogger("maxalgos.api")


class api:
    """
    Max Algos Python SDK Client.
    Supports strategy execution, HTTP REST API endpoints, and market data queries.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        ws_url: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("MAX_ALGOS_API_KEY") or os.getenv("API_KEY") or ""
        self.host = (
            host
            or os.getenv("MAX_ALGOS_HOST")
            or os.getenv("HOST_SERVER")
            or "http://127.0.0.1:5000"
        ).rstrip("/")
        self.ws_url = ws_url or os.getenv("WEBSOCKET_URL") or "ws://127.0.0.1:8785"
        self.user_id = user_id

        self.headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key,
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> Any:
        url = f"{self.host}{endpoint}"
        if json_data is not None and isinstance(json_data, dict):
            if "apikey" not in json_data and self.api_key:
                json_data["apikey"] = self.api_key

        try:
            res = requests.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json_data,
                headers=self.headers,
                timeout=10,
            )
            try:
                return res.json()
            except Exception:
                return {"status": "error", "message": res.text, "code": res.status_code}
        except Exception as e:
            logger.error(f"Request error to {url}: {e}")
            return {"status": "error", "message": str(e)}

    # --- Market Data & Quotes ---

    def history(
        self,
        symbol: str,
        exchange: str,
        interval: str = "5m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch historical candle data as a pandas DataFrame.

        start_date/end_date default to the last 5 calendar days (YYYY-MM-DD)
        when omitted -- the real /api/v1/history endpoint requires both, so
        a caller-omitted date range would otherwise fail schema validation.
        """
        if not start_date or not end_date:
            today = time.strftime("%Y-%m-%d")
            five_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 5 * 86400))
            start_date = start_date or five_days_ago
            end_date = end_date or today

        payload = {
            "apikey": self.api_key,
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
        }

        data = self._request("POST", "/api/v1/history/", json_data=payload)
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            return pd.DataFrame(data["data"])
        elif isinstance(data, list):
            return pd.DataFrame(data)
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])

    def get_history(self, *args, **kwargs) -> pd.DataFrame:
        return self.history(*args, **kwargs)

    def ltp(self, symbol: str, exchange: str) -> float:
        """Get Last Traded Price for a symbol."""
        res = self._request(
            "POST",
            "/api/v1/quotes/",
            json_data={"symbol": symbol, "exchange": exchange, "apikey": self.api_key},
        )
        if isinstance(res, dict):
            if "data" in res and isinstance(res["data"], dict) and "ltp" in res["data"]:
                return float(res["data"]["ltp"])
            if "ltp" in res:
                return float(res["ltp"])
        return 0.0

    def quote(self, symbol: str, exchange: str) -> dict:
        """Get full quote object."""
        return self._request(
            "POST",
            "/api/v1/quotes/",
            json_data={"symbol": symbol, "exchange": exchange, "apikey": self.api_key},
        )

    def depth(self, symbol: str, exchange: str) -> dict:
        """Get market depth object."""
        return self._request(
            "POST",
            "/api/v1/depth/",
            json_data={"symbol": symbol, "exchange": exchange, "apikey": self.api_key},
        )

    def multiquotes(self, symbols: list) -> list:
        """Get quotes for multiple symbols.

        symbols: list of {"symbol": ..., "exchange": ...} dicts.
        """
        return self._request(
            "POST",
            "/api/v1/multiquotes/",
            json_data={"symbols": symbols, "apikey": self.api_key},
        )

    # --- Orders ---

    def placeorder(
        self,
        strategy: str,
        symbol: str,
        action: str,
        exchange: str,
        price_type: str = "MARKET",
        product: str = "MIS",
        quantity: int = 1,
        price: float = 0.0,
        trigger_price: float = 0.0,
        disclosed_quantity: int = 0,
        broker: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Place a standard order.

        broker: optional -- which of your connected brokers to route this
        order to (see the Broker Management page for your connected broker
        names). Omit to use your account's default/primary broker. Pass it
        when your script trades across more than one connected broker and
        needs to pick per-call which one an order goes to.
        """
        payload = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": int(quantity),
            "pricetype": price_type,
            "product": product,
            "price": float(price),
            "trigger_price": float(trigger_price),
            "disclosed_quantity": int(disclosed_quantity),
        }
        if broker:
            payload["broker"] = broker
        payload.update(kwargs)
        return self._request("POST", "/api/v1/placeorder/", json_data=payload)

    def placesmartorder(
        self,
        strategy: str,
        symbol: str,
        action: str,
        exchange: str,
        price_type: str = "MARKET",
        product: str = "MIS",
        quantity: int = 1,
        position_size: int = 0,
        price: float = 0.0,
        trigger_price: float = 0.0,
        broker: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Place a smart order with position tracking.

        broker: optional -- see placeorder()'s broker= docstring.
        """
        payload = {
            "apikey": self.api_key,
            "strategy": strategy,
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": int(quantity),
            "position_size": int(position_size),
            "pricetype": price_type,
            "product": product,
            "price": float(price),
            "trigger_price": float(trigger_price),
        }
        if broker:
            payload["broker"] = broker
        payload.update(kwargs)
        return self._request("POST", "/api/v1/placesmartorder/", json_data=payload)

    def modifyorder(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price_type: str = "MARKET",
        product: str = "MIS",
        price: float = 0.0,
        trigger_price: float = 0.0,
        disclosed_quantity: int = 0,
        strategy: str = "python_strategy",
        **kwargs,
    ) -> dict:
        """Modify an existing order."""
        payload = {
            "apikey": self.api_key,
            "strategy": strategy,
            "orderid": str(order_id),
            "symbol": symbol,
            "exchange": exchange,
            "action": action.upper(),
            "quantity": int(quantity),
            "pricetype": price_type,
            "product": product,
            "price": float(price),
            "trigger_price": float(trigger_price),
            "disclosed_quantity": int(disclosed_quantity),
        }
        payload.update(kwargs)
        return self._request("POST", "/api/v1/modifyorder/", json_data=payload)

    def cancelorder(self, order_id: str, strategy: str = "python_strategy") -> dict:
        """Cancel an order by order ID."""
        payload = {"apikey": self.api_key, "strategy": strategy, "orderid": str(order_id)}
        return self._request("POST", "/api/v1/cancelorder/", json_data=payload)

    def cancelallorders(self, strategy: str = "python_strategy") -> dict:
        """Cancel all open orders."""
        return self._request(
            "POST",
            "/api/v1/cancelallorder/",
            json_data={"apikey": self.api_key, "strategy": strategy},
        )

    def closeposition(
        self,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        product: str = "MIS",
        strategy: str = "python_strategy",
    ) -> dict:
        """Close all open positions for this strategy.

        NOTE: the platform's /closeposition endpoint closes every open
        position under `strategy` -- it has no concept of closing a single
        symbol's position. symbol/exchange/product are accepted for
        backward-compatible call signatures but are NOT sent to the
        backend and do NOT limit which positions get closed.
        """
        payload = {"apikey": self.api_key, "strategy": strategy}
        return self._request("POST", "/api/v1/closeposition/", json_data=payload)

    def closeallpositions(self, strategy: str = "python_strategy") -> dict:
        """Close all open positions (alias for closeposition -- the
        backend has a single "close all positions for this strategy"
        operation, not a separate single-vs-all distinction)."""
        return self.closeposition(strategy=strategy)

    # --- Reports ---

    def orderbook(self) -> list:
        """Get list of orders."""
        res = self._request("POST", "/api/v1/orderbook/", json_data={"apikey": self.api_key})
        # The /orderbook endpoint returns {"data": {"orders": [...],
        # "statistics": {...}}} -- a dict, not a flat list. Extract the
        # orders list so callers can iterate `for o in client.orderbook()`.
        if isinstance(res, dict):
            data = res.get("data", [])
            if isinstance(data, dict):
                return data.get("orders", [])
            if isinstance(data, list):
                return data
        return []

    def orderstatus(self, orderid: str, strategy: str = "python_strategy") -> dict:
        """Get the status of a single order by ID -- use this instead of
        filtering orderbook() yourself when you only need one order's fill
        status (e.g. confirming an entry/exit filled before deciding the
        next action). Returns the order dict (with keys like
        'order_status'/'orderid'/'symbol'/'quantity'/'average_price') on
        success, or {} if the order wasn't found / the call failed --
        check truthiness before reading fields, same as other methods here.
        """
        payload = {"apikey": self.api_key, "strategy": strategy, "orderid": str(orderid)}
        res = self._request("POST", "/api/v1/orderstatus/", json_data=payload)
        if isinstance(res, dict) and res.get("status") == "success":
            data = res.get("data", {})
            return data if isinstance(data, dict) else {}
        return {}

    def tradebook(self) -> list:
        """Get list of today's executed trades."""
        res = self._request("POST", "/api/v1/tradebook/", json_data={"apikey": self.api_key})
        return res.get("data", []) if isinstance(res, dict) else []

    def positions(self) -> list:
        """Get list of current open positions."""
        res = self._request("POST", "/api/v1/positionbook/", json_data={"apikey": self.api_key})
        return res.get("data", []) if isinstance(res, dict) else []

    def positionbook(self) -> list:
        """Alias for positions() -- matches the platform's endpoint name."""
        return self.positions()

    def funds(self) -> dict:
        """Get account funds / margin details.

        Returns a dict with available cash, used margin, and total balance.
        Structure varies by broker.
        """
        return self._request(
            "POST",
            "/api/v1/funds/",
            json_data={"apikey": self.api_key},
        )


class ta:
    """Technical Analysis helpers.

    All methods accept a :class:`pandas.Series` and return a
    :class:`pandas.Series` of the same length.
    """

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index (RSI)."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """MACD — returns DataFrame with columns ``macd``, ``signal``, ``histogram``."""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        })

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range — df must have ``high``, ``low``, ``close`` columns."""
        high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> pd.DataFrame:
        """Bollinger Bands — returns DataFrame with columns ``upper``, ``middle``, ``lower``."""
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        return pd.DataFrame({
            "upper": middle + std_dev * std,
            "middle": middle,
            "lower": middle - std_dev * std,
        })
