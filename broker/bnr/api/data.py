import asyncio
import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
import pandas as pd

from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

# Auto-detect eventlet environment (Docker/standalone uses gunicorn+eventlet)
# asyncio.run() cannot be called under eventlet's monkey-patched event loop
def _is_eventlet_patched():
    try:
        import eventlet.patcher
        return eventlet.patcher.is_monkey_patched("socket")
    except (ImportError, AttributeError):
        return False

USE_ASYNC = not _is_eventlet_patched()

from threading import Lock

logger = get_logger(__name__)

# Thread-safe cache to prevent hitting Bnr's strict rate limits (10/sec, 120/min)
_QUOTES_CACHE = {}
_CACHE_LOCK = Lock()
_CACHE_TTL = 10.0  # Cache quotes for 10 seconds

def get_cached_quote(symbol, exchange):
    with _CACHE_LOCK:
        entry = _QUOTES_CACHE.get((symbol, exchange))
        if entry:
            ts, data = entry
            if time.time() - ts < _CACHE_TTL:
                return data
    return None

def set_cached_quote(symbol, exchange, data):
    with _CACHE_LOCK:
        _QUOTES_CACHE[(symbol, exchange)] = (time.time(), data)


# BNR enforces 10 req/sec and 120 req/min per user, shared across EVERY
# endpoint (quotes, depth, orders, order book, etc.) - see
# broker/bnr/api/rate_limiter.py for why this must be a single shared
# throttle rather than a private per-file counter. Option Chain's polling
# (quotes + depth for every strike, refreshed every ~30s) can easily burst
# past both caps in a single poll cycle, causing BNR to reject requests
# with "Order Recieved N in a current minute exceeds Limit 120" - which
# then surfaces as failures on completely unrelated actions sharing the
# same account/quota (including order placement). Purely additive: no
# change to symbol mapping, request payloads, or response handling - only
# adds a short sleep before the HTTP call when needed.
from broker.bnr.api.rate_limiter import throttle_bnr_request


def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Bnr using httpx with connection pooling
    """
    throttle_bnr_request()
    AUTH_TOKEN = auth
    from broker.bnr.api.order_api import get_bnr_userid

    api_key = get_bnr_userid(AUTH_TOKEN)

    if payload is None:
        data = {"uid": api_key}
    else:
        data = payload
        data["uid"] = api_key

    # Bnr's REST endpoints (Noren API, same family as Zebu/Shoonya/
    # Flattrade) do not accept the session token via an Authorization:
    # Bearer header -- they require it embedded as jKey=<token> in the
    # form-urlencoded body. Sending it as a Bearer header silently drops
    # the token, so Bnr treats every request as unauthenticated and
    # returns an empty body, which surfaces as the opaque
    # "Expecting value: line 1 column 1 (char 0)" JSON decode error further
    # up the stack. Same fix already applied to broker/zebu/api/data.py.
    payload_str = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    url = f"https://prime.bnrsecurities.com{endpoint}"

    response = client.request(method, url, content=payload_str, headers=headers)
    data = response.text

    # Bnr's API can return an empty body or an HTML error page instead of a
    # JSON error payload. Left unguarded, json.loads() on that raises an
    # opaque "Expecting value: line 1 column 1 (char 0)" that bubbles up as
    # a raw 500 -- fail with a message that explains what actually
    # happened instead. Mirrors the same guard already added to
    # get_margin_data() in broker/bnr/api/funds.py and the equivalent
    # Zebu functions (bnr and zebu are both Noren-API-vendor templates
    # sharing this exact unguarded-parse bug).
    if not data or not data.strip():
        raise ValueError(f"Bnr API returned an empty response for {endpoint} (HTTP {response.status_code})")
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Bnr API returned a non-JSON response for {endpoint} "
            f"(HTTP {response.status_code}): {data[:200]!r}"
        ) from e


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Bnr data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Bnr resolutions
        # Note: Weekly and Monthly intervals are not supported
        self.timeframe_map = {
            # Minutes
            "1m": "1",  # 1 minute
            "3m": "3",  # 3 minutes
            "5m": "5",  # 5 minutes
            "10m": "10",  # 10 minutes
            "15m": "15",  # 15 minutes
            "30m": "30",  # 30 minutes
            # Hours
            "1h": "60",  # 1 hour (60 minutes)
            "2h": "120",  # 2 hours (120 minutes)
            "4h": "240",  # 4 hours (240 minutes)
            # Daily
            "D": "D",  # Daily data
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Simplified quote data with required fields
        """
        # Check cache first
        cached = get_cached_quote(symbol, exchange)
        if cached:
            return cached

        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            # Convert Max Algos exchange to broker exchange for API calls
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            payload = {"exch": api_exchange, "token": token}

            response = get_api_response(
                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
            )

            if response.get("stat") != "Ok":
                raise Exception(f"Error from Bnr API: {response.get('emsg', 'Unknown error')}")

            # Return simplified quote data
            quote_data = {
                "bid": float(response.get("bp1", 0)),
                "ask": float(response.get("sp1", 0)),
                "open": float(response.get("o", 0)),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(response.get("v", 0)),
                "oi": int(response.get("oi", 0)),
                "tick_size": float(response.get("ti", 0)) if response.get("ti") else None,
            }

            # Cache the successful quote
            set_cached_quote(symbol, exchange, quote_data)
            return quote_data

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Bnr API Rate Limit: 10 requests per second per user

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            results_map = {}
            symbols_to_fetch = []

            # Step 1: Check cache for each symbol
            for item in symbols:
                symbol = item["symbol"]
                exchange = item["exchange"]
                cached = get_cached_quote(symbol, exchange)
                if cached:
                    results_map[(symbol, exchange)] = {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": cached
                    }
                else:
                    symbols_to_fetch.append(item)

            # Step 2: Fetch any missing symbols in batches
            if symbols_to_fetch:
                # Bnr API rate limit: 10 requests per second per user
                BATCH_SIZE = 10  # Process 10 symbols per batch (matches rate limit)
                RATE_LIMIT_DELAY = 1.0  # 1 second delay between batches

                fetched_results = []
                if len(symbols_to_fetch) > BATCH_SIZE:
                    logger.debug(f"Processing {len(symbols_to_fetch)} symbols in batches of {BATCH_SIZE}")
                    for i in range(0, len(symbols_to_fetch), BATCH_SIZE):
                        batch = symbols_to_fetch[i : i + BATCH_SIZE]
                        logger.info(
                            f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols_to_fetch))}"
                        )
                        batch_results = self._process_quotes_batch(batch)
                        fetched_results.extend(batch_results)
                        if i + BATCH_SIZE < len(symbols_to_fetch):
                            time.sleep(RATE_LIMIT_DELAY)
                else:
                    fetched_results = self._process_quotes_batch(symbols_to_fetch)

                # Step 3: Cache the successfully fetched quotes and add to results map
                for result in fetched_results:
                    symbol = result["symbol"]
                    exchange = result["exchange"]
                    if "data" in result and not result.get("error"):
                        set_cached_quote(symbol, exchange, result["data"])
                    results_map[(symbol, exchange)] = result

            # Step 4: Reconstruct final results in the original order
            final_results = []
            for item in symbols:
                symbol = item["symbol"]
                exchange = item["exchange"]
                final_results.append(results_map.get((symbol, exchange)))

            return final_results

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _fetch_single_quote_sync(
        self, symbol: str, exchange: str, api_exchange: str, token: str, api_key: str
    ) -> dict:
        """
        Fetch quote for a single symbol synchronously (for ThreadPoolExecutor)
        """
        try:
            data = {"uid": api_key, "exch": api_exchange, "token": token}

            # jKey form-encoding, not Authorization: Bearer -- see the
            # comment in get_api_response() above; this batch path builds
            # its own request and was still using the header form the
            # broker silently ignores.
            payload_str = "jData=" + json.dumps(data) + "&jKey=" + self.auth_token
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            url = "https://prime.bnrsecurities.com/NorenWClientAPI/GetQuotes"

            # Use httpx.post for sync requests
            http_response = httpx.post(url, content=payload_str, headers=headers, timeout=10.0)
            # Bnr's GetQuotes endpoint can return an empty body or an HTML
            # error page instead of a JSON error payload -- this batch path
            # builds its own request and bypasses get_api_response(), so it
            # needs its own guard (same fix as broker/zebu's equivalent).
            body_text = http_response.text
            if not body_text or not body_text.strip():
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": f"Bnr API returned an empty response (HTTP {http_response.status_code})",
                }
            try:
                response = http_response.json()
            except json.JSONDecodeError:
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": f"Bnr API returned a non-JSON response (HTTP {http_response.status_code})",
                }

            if response.get("stat") != "Ok":
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": response.get("emsg", "Unknown error"),
                }

            return {
                "symbol": symbol,
                "exchange": exchange,
                "data": {
                    "bid": float(response.get("bp1", 0)),
                    "ask": float(response.get("sp1", 0)),
                    "open": float(response.get("o", 0)),
                    "high": float(response.get("h", 0)),
                    "low": float(response.get("l", 0)),
                    "ltp": float(response.get("lp", 0)),
                    "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                    "volume": int(response.get("v", 0)),
                    "oi": int(response.get("oi", 0)),
                },
            }

        except Exception as e:
            return {"symbol": symbol, "exchange": exchange, "error": str(e)}

    async def _fetch_single_quote_async(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        exchange: str,
        api_exchange: str,
        token: str,
        api_key: str,
    ) -> dict:
        """
        Fetch quote for a single symbol asynchronously
        """
        try:
            data = {"uid": api_key, "exch": api_exchange, "token": token}

            # jKey form-encoding, not Authorization: Bearer -- same fix as
            # get_api_response() and _fetch_single_quote_sync() above.
            payload_str = "jData=" + json.dumps(data) + "&jKey=" + self.auth_token
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            url = "https://prime.bnrsecurities.com/NorenWClientAPI/GetQuotes"

            # Use async httpx client
            http_response = await client.post(url, content=payload_str, headers=headers)
            body_text = http_response.text
            if not body_text or not body_text.strip():
                logger.warning(
                    f"Bnr returned empty response for {symbol}@{exchange} "
                    f"(HTTP {http_response.status_code})"
                )
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": f"Bnr API returned an empty response (HTTP {http_response.status_code})",
                }
            try:
                response = http_response.json()
            except json.JSONDecodeError:
                logger.warning(
                    f"Bnr returned non-JSON response for {symbol}@{exchange} "
                    f"(HTTP {http_response.status_code})"
                )
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": f"Bnr API returned a non-JSON response (HTTP {http_response.status_code})",
                }

            if response.get("stat") != "Ok":
                logger.warning(
                    f"Error fetching quote for {symbol}@{exchange}: {response.get('emsg', 'Unknown error')}"
                )
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": response.get("emsg", "Unknown error"),
                }

            return {
                "symbol": symbol,
                "exchange": exchange,
                "data": {
                    "bid": float(response.get("bp1", 0)),
                    "ask": float(response.get("sp1", 0)),
                    "open": float(response.get("o", 0)),
                    "high": float(response.get("h", 0)),
                    "low": float(response.get("l", 0)),
                    "ltp": float(response.get("lp", 0)),
                    "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                    "volume": int(response.get("v", 0)),
                    "oi": int(response.get("oi", 0)),
                },
            }

        except Exception as e:
            logger.warning(f"Error processing quote for {symbol}@{exchange}: {str(e)}")
            return {"symbol": symbol, "exchange": exchange, "error": str(e)}

    async def _process_quotes_batch_async(self, symbols: list, api_key: str) -> list:
        """
        Process a batch of symbols using async httpx
        """
        results = []

        # High connection limits for maximum concurrency
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
        async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
            tasks = [
                self._fetch_single_quote_async(
                    client,
                    item["symbol"],
                    item["exchange"],
                    item["api_exchange"],
                    item["token"],
                    api_key,
                )
                for item in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dicts
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    {
                        "symbol": symbols[i]["symbol"],
                        "exchange": symbols[i]["exchange"],
                        "error": str(result),
                    }
                )
            else:
                final_results.append(result)

        return final_results

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols using concurrent API calls
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 40)
        Returns:
            list: List of quote data for the batch
        """
        skipped_symbols = []
        prepared_symbols = []

        # Pre-fetch API key (userid part) via get_bnr_userid -- see the
        # matching comment in broker/bnr/api/order_api.py for why a naive
        # os.getenv("BROKER_API_KEY") read isn't reliable here.
        from broker.bnr.api.order_api import get_bnr_userid

        api_key = get_bnr_userid(self.auth_token)

        # Step 1: Pre-resolve all tokens sequentially (database access)
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if not br_symbol or not token:
                logger.warning(
                    f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol or token"
                )
                skipped_symbols.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": "Could not resolve broker symbol or token",
                    }
                )
                continue

            # Map exchange to API format
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            prepared_symbols.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "api_exchange": api_exchange,
                    "token": token,
                }
            )

        if not prepared_symbols:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Make concurrent API calls
        # Runtime check: even if USE_ASYNC is True, asyncio.run() will crash
        # if called from within an already-running event loop
        use_async = USE_ASYNC
        if use_async:
            try:
                asyncio.get_running_loop()
                use_async = False
            except RuntimeError:
                pass

        if use_async:
            # Async approach with httpx.AsyncClient
            results = asyncio.run(self._process_quotes_batch_async(prepared_symbols, api_key))
        else:
            # ThreadPoolExecutor approach
            with ThreadPoolExecutor(max_workers=min(len(prepared_symbols), 20)) as executor:
                futures = [
                    executor.submit(
                        self._fetch_single_quote_sync,
                        item["symbol"],
                        item["exchange"],
                        item["api_exchange"],
                        item["token"],
                        api_key,
                    )
                    for item in prepared_symbols
                ]
                results = [f.result() for f in futures]

        return skipped_symbols + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            # Convert Max Algos exchange to broker exchange for API calls
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            payload = {"exch": api_exchange, "token": token}

            response = get_api_response(
                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
            )

            if response.get("stat") != "Ok":
                raise Exception(f"Error from Bnr API: {response.get('emsg', 'Unknown error')}")

            # Format bids and asks data
            bids = []
            asks = []

            # Process top 5 bids and asks
            for i in range(1, 6):
                bids.append(
                    {
                        "price": float(response.get(f"bp{i}", 0)),
                        "quantity": int(response.get(f"bq{i}", 0)),
                    }
                )
                asks.append(
                    {
                        "price": float(response.get(f"sp{i}", 0)),
                        "quantity": int(response.get(f"sq{i}", 0)),
                    }
                )

            # Return depth data
            return {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": sum(bid["quantity"] for bid in bids),
                "totalsellqty": sum(ask["quantity"] for ask in asks),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "ltq": int(response.get("ltq", 0)),  # Last Traded Quantity
                "open": float(response.get("o", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(response.get("v", 0)),
                "oi": int(response.get("oi", 0)),  # Open Interest from Bnr
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def _get_history_chunk_seconds(self, interval: str) -> int:
        """
        Per-request window size for TPSeries, in seconds. Bnr (same
        go.mynt.in/Noren backend family as Shoonya/Zebu) can time out when
        the range produces too many candles in a single call. These values
        keep each request under roughly a few thousand candles (empirically
        safe -- mirrored from broker/shoonya/api/data.py's table, which has
        been running against the same broker family without incident).
        """
        minute_windows = {
            "1m": 5 * 24 * 3600,
            "3m": 10 * 24 * 3600,
            "5m": 20 * 24 * 3600,
            "10m": 40 * 24 * 3600,
            "15m": 60 * 24 * 3600,
            "30m": 90 * 24 * 3600,
            "1h": 180 * 24 * 3600,
            "2h": 180 * 24 * 3600,
            "4h": 365 * 24 * 3600,
        }
        return minute_windows.get(interval, 30 * 24 * 3600)

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Check if interval is supported
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}"
                )

            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Convert Max Algos exchange to broker exchange for API calls
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"
            
            token = get_token(symbol, exchange)

            # Convert dates to epoch timestamps
            # Handle both string and date object inputs
            if isinstance(start_date, str):
                start_ts = int(
                    datetime.strptime(start_date + " 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
                )
            else:
                # If it's a date object, combine with time
                start_dt = datetime.combine(start_date, datetime.min.time())
                start_ts = int(start_dt.timestamp())

            if isinstance(end_date, str):
                end_ts = int(
                    datetime.strptime(end_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
                )
            else:
                # If it's a date object, combine with end of day time
                end_dt = datetime.combine(end_date, datetime.max.time().replace(microsecond=0))
                end_ts = int(end_dt.timestamp())

            # For daily data, use EODChartData endpoint
            if interval == "D":
                payload = {
                    "sym": f"{api_exchange}:{br_symbol}",
                    "from": str(start_ts),
                    "to": str(end_ts),
                }

                logger.debug(f"EOD Payload: {payload}")  # Debug print
                try:
                    response = get_api_response(
                        "/NorenWClientAPI/EODChartData", self.auth_token, payload=payload
                    )
                    logger.debug(f"EOD Response: {response}")  # Debug print
                except Exception as e:
                    logger.error(f"Error in EOD request: {e}")
                    response = []  # Continue with empty response to try quotes
            else:
                # For intraday data, use TPSeries endpoint. TPSeries can time
                # out on long ranges, so the window is split into safe,
                # interval-dependent chunks (see _get_history_chunk_seconds)
                # -- same fix already proven on broker/shoonya/api/data.py
                # against this same broker family.
                chunk_seconds = self._get_history_chunk_seconds(interval)
                response = []
                chunk_start = start_ts
                while chunk_start <= end_ts:
                    chunk_end = min(chunk_start + chunk_seconds, end_ts)
                    payload = {
                        "exch": api_exchange,
                        "token": token,
                        "st": str(chunk_start),
                        "et": str(chunk_end),
                        "intrv": self.timeframe_map[interval],
                    }
                    logger.debug(f"Intraday Payload: {payload}")  # Debug print
                    try:
                        chunk_response = get_api_response(
                            "/NorenWClientAPI/TPSeries", self.auth_token, payload=payload
                        )
                        logger.debug(f"Intraday Response: {chunk_response}")  # Debug print
                    except Exception as e:
                        logger.error(
                            f"TPSeries chunk request failed ({chunk_start}-{chunk_end}): {e}"
                        )
                        chunk_start = chunk_end + 1
                        continue

                    # TPSeries normally returns a LIST of candles. On error
                    # it returns a DICT like {"stat":"Not_Ok","emsg":"..."} --
                    # detect that before extending (iterating dict keys would
                    # otherwise crash trying to json.loads a key like "stat").
                    if isinstance(chunk_response, dict):
                        emsg = (
                            chunk_response.get("emsg")
                            or chunk_response.get("message")
                            or "unknown"
                        )
                        logger.warning(
                            f"TPSeries returned error for chunk {chunk_start}-{chunk_end}: "
                            f"stat={chunk_response.get('stat')} emsg={emsg}"
                        )
                        chunk_start = chunk_end + 1
                        continue

                    if not isinstance(chunk_response, list):
                        logger.warning(
                            f"Unexpected TPSeries response type "
                            f"{type(chunk_response).__name__}: {str(chunk_response)[:200]}"
                        )
                        chunk_start = chunk_end + 1
                        continue

                    response.extend(chunk_response)
                    chunk_start = chunk_end + 1

            # Convert response to DataFrame
            data = []
            for candle in response:
                try:
                    if isinstance(candle, str):
                        # Bnr's TPSeries/EODChartData occasionally emits a
                        # malformed element within an otherwise-valid array
                        # (empty string, truncated JSON) -- this used to be
                        # parsed outside the try/except below, so one bad
                        # candle raised JSONDecodeError and aborted the
                        # entire request instead of just skipping that row.
                        # Same fix already applied to broker/zebu/api/data.py.
                        candle = json.loads(candle)

                    if interval == "D":
                        # EOD data format
                        timestamp = int(candle.get("ssboe", 0))
                        data.append(
                            {
                                "timestamp": timestamp,
                                "open": float(candle.get("into", 0)),
                                "high": float(candle.get("inth", 0)),
                                "low": float(candle.get("intl", 0)),
                                "close": float(candle.get("intc", 0)),
                                "volume": float(candle.get("intv", 0)),
                                "oi": float(candle.get("oi", 0)),
                            }
                        )
                    else:
                        # Skip candles with all zero values
                        if (
                            float(candle.get("into", 0)) == 0
                            and float(candle.get("inth", 0)) == 0
                            and float(candle.get("intl", 0)) == 0
                            and float(candle.get("intc", 0)) == 0
                        ):
                            continue

                        # Intraday format
                        timestamp = int(
                            datetime.strptime(candle["time"], "%d-%m-%Y %H:%M:%S").timestamp()
                        )
                        data.append(
                            {
                                "timestamp": timestamp,
                                "open": float(candle.get("into", 0)),
                                "high": float(candle.get("inth", 0)),
                                "low": float(candle.get("intl", 0)),
                                "close": float(candle.get("intc", 0)),
                                "volume": float(candle.get("intv", 0)),
                                "oi": float(candle.get("oi", 0)),
                            }
                        )
                except (KeyError, ValueError) as e:
                    logger.error(f"Error parsing candle data: {e}, Candle: {candle}")
                    continue

            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )

            # For daily data, append today's data from quotes if it's missing
            if interval == "D":
                today_ts = int(
                    datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                )

                # Only get today's data if it's within the requested range
                if today_ts >= start_ts and today_ts <= end_ts:
                    if df.empty or df["timestamp"].max() < today_ts:
                        try:
                            # Get today's data from quotes
                            payload = {"exch": api_exchange, "token": token}
                            quotes_response = get_api_response(
                                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
                            )
                            logger.debug(f"Quotes Response: {quotes_response}")  # Debug print

                            if quotes_response and quotes_response.get("stat") == "Ok":
                                today_data = {
                                    "timestamp": today_ts,
                                    "open": float(quotes_response.get("o", 0)),
                                    "high": float(quotes_response.get("h", 0)),
                                    "low": float(quotes_response.get("l", 0)),
                                    "close": float(
                                        quotes_response.get("lp", 0)
                                    ),  # Use LTP as close
                                    "volume": float(quotes_response.get("v", 0)),
                                    "oi": float(quotes_response.get("oi", 0)),
                                }
                                logger.info(f"Today's quote data: {today_data}")
                                # Append today's data
                                df = pd.concat([df, pd.DataFrame([today_data])], ignore_index=True)
                                logger.info("Added today's data from quotes")
                        except Exception as e:
                            logger.info(f"Error fetching today's data from quotes: {e}")
                else:
                    logger.info(
                        f"Today ({today_ts}) is outside requested range ({start_ts} to {end_ts})"
                    )

            # Sort by timestamp
            df = df.sort_values("timestamp")
            return df

        except Exception as e:
            logger.error(f"Error in get_history: {e}")  # Add debug logging
            raise Exception(f"Error fetching historical data: {str(e)}")
