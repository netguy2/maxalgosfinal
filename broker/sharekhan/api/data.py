from datetime import timedelta

import pandas as pd

from broker.sharekhan.database.master_contract_db import SymToken, db_session
from broker.sharekhan.mapping.transform_data import map_exchange
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_ROOT_URL = "https://api.sharekhan.com"


class SharekhanAPIError(Exception):
    pass


class SharekhanNotSupportedError(Exception):
    """Raised for capabilities Sharekhan's REST API does not expose at all
    (live quotes/market depth - see module docstring below)."""

    pass


def get_api_response(endpoint, auth, method="GET", payload=None):
    from broker.sharekhan.api.order_api import _headers, _split_auth

    access_token, _customer_id = _split_auth(auth)
    client = get_httpx_client()
    headers = _headers(access_token)
    url = f"{_ROOT_URL}{endpoint}"

    try:
        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        else:
            response = client.request(method.upper(), url, headers=headers, json=payload or {})
        return response.json()
    except Exception as e:
        logger.exception(f"Sharekhan data API request failed: {e}")
        raise


class BrokerData:
    """Sharekhan market-data handler.

    IMPORTANT LIMITATION: Sharekhan's REST API has no live quotes or market
    depth endpoint (confirmed against the published SDK - see
    https://github.com/Sharekhan-API/shareconnectpython). Live LTP/depth is
    only available via their WebSocket feed. The streaming adapter
    (broker/sharekhan/streaming/sharekhan_adapter.py) is built and publishes
    normalized ticks to ZeroMQ like every other broker's adapter, which
    services.market_data_service.MarketDataService consumes into a
    broker-agnostic (exchange, symbol) cache.

    get_quotes()/get_market_depth() read from that live cache (populated the
    moment the symbol is subscribed over WS) instead of hitting a REST
    endpoint that doesn't exist. This mirrors how the option-chain/dashboard
    tools already get live prices for every broker - Sharekhan just sources
    them from the WS cache instead of a REST quote call. If the symbol
    hasn't ticked yet (not subscribed, or market closed with no cached
    value), this returns the same all-zero shape as before so callers don't
    crash - it just won't be stale-zero once the feed is live.

    Historical OHLC data IS available via REST (`/skapi/services/historical`)
    and is fully implemented in get_history().
    """

    def __init__(self, auth_token):
        self.auth_token = auth_token

        # Sharekhan's historicaldata() interval values are not documented
        # precisely beyond the SDK's "daily" example - "1minute"/"5minute"
        # etc. mirror the convention used by Sharekhan's own OMS-family
        # brokers (Kotak/Motilal) until confirmed otherwise against a real
        # account.
        self.timeframe_map = {
            "1m": "1minute",
            "3m": "3minute",
            "5m": "5minute",
            "10m": "10minute",
            "15m": "15minute",
            "30m": "30minute",
            "60m": "60minute",
            "1h": "60minute",
            "D": "daily",
        }

        self.market_timings = {
            "NSE": {"start": "09:15:00", "end": "15:30:00"},
            "BSE": {"start": "09:15:00", "end": "15:30:00"},
            "NFO": {"start": "09:15:00", "end": "15:30:00"},
            "BFO": {"start": "09:15:00", "end": "15:30:00"},
            "CDS": {"start": "09:00:00", "end": "17:00:00"},
            "MCX": {"start": "09:00:00", "end": "23:30:00"},
        }
        self.default_market_timings = {"start": "00:00:00", "end": "23:59:59"}

    def get_market_timings(self, exchange: str) -> dict:
        return self.market_timings.get(exchange, self.default_market_timings)

    def _get_scripcode(self, symbol: str, exchange: str) -> str:
        with db_session() as session:
            symbol_info = (
                session.query(SymToken)
                .filter(SymToken.exchange == exchange, SymToken.symbol == symbol)
                .first()
            )
            if not symbol_info:
                raise SharekhanAPIError(f"Could not find scrip code for {exchange}:{symbol}")
            return symbol_info.token


    def get_quotes(self, symbol: str, exchange: str) -> dict:
        # Sharekhan has no REST quotes endpoint - read the live WS tick cache
        # instead (see class docstring). Falls back to the zero-filled shape
        # only when nothing has ticked yet for this symbol.
        from services.market_data_service import get_quote as get_cached_quote

        cached = get_cached_quote(symbol, exchange)
        if cached:
            return {
                "ask": 0.0,
                "bid": 0.0,
                "high": float(cached.get("high", 0) or 0),
                "low": float(cached.get("low", 0) or 0),
                "ltp": float(cached.get("ltp", 0) or 0),
                "open": float(cached.get("open", 0) or 0),
                "prev_close": float(cached.get("close", 0) or 0),
                "volume": int(cached.get("volume", 0) or 0),
                "oi": 0,
            }
        return {
            "ask": 0.0,
            "bid": 0.0,
            "high": 0.0,
            "low": 0.0,
            "ltp": 0.0,
            "open": 0.0,
            "prev_close": 0.0,
            "volume": 0,
            "oi": 0
        }

    def get_multiquotes(self, symbols: list) -> list:
        # Return mock quotes for all requested symbols
        results = []
        for s in symbols:
            results.append({
                "symbol": s.get("symbol"),
                "exchange": s.get("exchange"),
                "data": self.get_quotes(s.get("symbol"), s.get("exchange"))
            })
        return results

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        # Sharekhan has no REST market depth endpoint - read the live WS tick
        # cache instead (see class docstring). Requires the symbol to have
        # been subscribed in DEPTH mode; falls back to the zero-filled shape
        # if no depth packet has arrived yet.
        from services.market_data_service import get_market_depth as get_cached_depth
        from services.market_data_service import get_quote as get_cached_quote

        cached_depth = get_cached_depth(symbol, exchange)
        cached_quote = get_cached_quote(symbol, exchange) or {}

        def _levels(raw_levels: list, count: int = 5) -> list:
            out = []
            for lvl in (raw_levels or [])[:count]:
                if isinstance(lvl, dict):
                    price = lvl.get("price", lvl.get("p", 0))
                    qty = lvl.get("quantity", lvl.get("qty", lvl.get("q", 0)))
                else:
                    price, qty = 0.0, 0
                out.append({"price": float(price or 0), "quantity": int(qty or 0)})
            while len(out) < count:
                out.append({"price": 0.0, "quantity": 0})
            return out

        if cached_depth:
            return {
                "asks": _levels(cached_depth.get("sell")),
                "bids": _levels(cached_depth.get("buy")),
                "high": float(cached_quote.get("high", 0) or 0),
                "low": float(cached_quote.get("low", 0) or 0),
                "ltp": float(cached_depth.get("ltp", cached_quote.get("ltp", 0)) or 0),
                "ltq": 0,
                "oi": 0,
                "open": float(cached_quote.get("open", 0) or 0),
                "prev_close": float(cached_quote.get("close", 0) or 0),
                "totalbuyqty": 0,
                "totalsellqty": 0,
                "volume": int(cached_quote.get("volume", 0) or 0),
            }
        return {
            "asks": [{"price": 0.0, "quantity": 0} for _ in range(5)],
            "bids": [{"price": 0.0, "quantity": 0} for _ in range(5)],
            "high": 0.0,
            "low": 0.0,
            "ltp": 0.0,
            "ltq": 0,
            "oi": 0,
            "open": 0.0,
            "prev_close": 0.0,
            "totalbuyqty": 0,
            "totalsellqty": 0,
            "volume": 0
        }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        return self.get_market_depth(symbol, exchange)

    def get_history(
        self, symbol: str, exchange: str, timeframe: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        try:
            resolution = self.timeframe_map.get(timeframe)
            if not resolution:
                raise SharekhanAPIError(f"Unsupported timeframe: {timeframe}")

            scripcode = self._get_scripcode(symbol, exchange)
            br_exchange = map_exchange(exchange)

            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)

            dfs = []
            # No documented per-request day limit for Sharekhan's historical
            # endpoint - chunk conservatively at 100 days to avoid oversized
            # single requests until real limits are confirmed.
            chunk_days = 100
            current_start = start_date
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)

                endpoint = f"/skapi/services/historical/{br_exchange}/{scripcode}/{resolution}"
                response = get_api_response(endpoint, self.auth_token)

                if not isinstance(response, dict) or response.get("error_type"):
                    logger.error(f"Sharekhan historical API error: {response}")
                    raise SharekhanAPIError(
                        f"Error from Sharekhan API: {response.get('message', 'Unknown error') if isinstance(response, dict) else response}"
                    )

                candles = response.get("data", [])
                if candles:
                    df = pd.DataFrame(candles)
                    # Best-effort column normalisation - Sharekhan's exact
                    # historical response schema is undocumented publicly;
                    # adjust these renames once verified against a real
                    # account response.
                    rename_map = {
                        "dateTime": "timestamp",
                        "date": "timestamp",
                        "openPrice": "open",
                        "highPrice": "high",
                        "lowPrice": "low",
                        "closePrice": "close",
                        "totalTradedQty": "volume",
                        "openInterest": "oi",
                    }
                    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
                    for col in ["timestamp", "open", "high", "low", "close", "volume", "oi"]:
                        if col not in df.columns:
                            df[col] = 0
                    dfs.append(df[["timestamp", "open", "high", "low", "close", "volume", "oi"]])

                current_start = current_end + timedelta(days=1)

            if not dfs:
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])

            final_df = pd.concat(dfs, ignore_index=True)
            final_df["timestamp"] = pd.to_datetime(final_df["timestamp"], errors="coerce")
            final_df["timestamp"] = final_df["timestamp"].astype("int64") // 10**9
            final_df = (
                final_df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )
            final_df["volume"] = final_df["volume"].astype(int)
            final_df["oi"] = final_df["oi"].astype(int)

            return final_df

        except SharekhanAPIError:
            raise
        except Exception as e:
            logger.exception(f"Error fetching Sharekhan historical data: {e}")
            raise SharekhanAPIError(f"Error fetching historical data: {e}") from e
