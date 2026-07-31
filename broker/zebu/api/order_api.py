import json
import os

import httpx
import threading
import time

from broker.zebu.api.rate_limiter import throttle_zebu_request
from broker.zebu.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_zebu_userid(auth, fallback_userid=None):
    """
    Robustly resolve Zebu User ID / Client Code (uid / actid).
    Checks in priority order:
    1. Database lookup in AuthBrokerSession / Auth using auth token (saved during OAuth)
    2. UserBrokerCredential database lookup for broker_name="zebu"
    3. BROKER_API_KEY environment variable (format: userid:::client_id)
    4. fallback_userid ONLY if it's a valid Zebu ID (not 'admin', not starting with 'mak_')
    """
    def _is_valid_zebu_id(val: str) -> bool:
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        if not v or v == "admin" or v.startswith("mak_") or v == "internal-call":
            return False
        return True

    # 1. Search active DB session / auth records by auth_token
    if auth and isinstance(auth, str):
        auth_token = auth.strip()
        try:
            from database.auth_db import Auth, AuthBrokerSession, decrypt_token
            # Search active AuthBrokerSessions for zebu broker
            sessions = AuthBrokerSession.query.filter_by(broker="zebu", is_revoked=False).all()
            for s in sessions:
                if s.auth:
                    dec_token = decrypt_token(s.auth)
                    if dec_token == auth_token:
                        uid = (s.user_id or "").strip()
                        if uid:
                            resolved = uid.split(":::")[0].strip() if ":::" in uid else uid
                            if _is_valid_zebu_id(resolved):
                                return resolved

            # Search active Auth records
            auth_records = Auth.query.filter_by(is_revoked=False).all()
            for a in auth_records:
                if a.auth:
                    dec_token = decrypt_token(a.auth)
                    if dec_token == auth_token:
                        uid = (a.user_id or "").strip()
                        if uid:
                            resolved = uid.split(":::")[0].strip() if ":::" in uid else uid
                            if _is_valid_zebu_id(resolved):
                                return resolved
        except Exception as e:
            logger.debug(f"Could not resolve Zebu userid from DB: {e}")

    # 2. Fallback to UserBrokerCredential for saved broker_api_key (format: userid:::client_id)
    try:
        from database.user_db import UserBrokerCredential
        cred = UserBrokerCredential.query.filter_by(broker_name="zebu").first()
        if cred and cred.broker_api_key:
            val = cred.broker_api_key.strip()
            resolved = val.split(":::")[0].strip() if ":::" in val else val
            if _is_valid_zebu_id(resolved):
                return resolved
    except Exception:
        pass

    # 3. Fallback to BROKER_API_KEY environment variable
    full_api_key = os.getenv("BROKER_API_KEY", "") or ""
    if full_api_key:
        resolved = full_api_key.split(":::")[0].strip() if ":::" in full_api_key else full_api_key.strip()
        if _is_valid_zebu_id(resolved):
            return resolved

    # 4. Fallback: fallback_userid if provided and valid
    if fallback_userid and isinstance(fallback_userid, str):
        val = fallback_userid.strip()
        resolved = val.split(":::")[0].strip() if ":::" in val else val
        if _is_valid_zebu_id(resolved):
            return resolved

    return ""

    return ""


def get_api_response(endpoint, auth, method="POST", payload=""):
    throttle_zebu_request()  # shared per-account rate limit -- see rate_limiter.py
    AUTH_TOKEN = auth

    api_key = get_zebu_userid(AUTH_TOKEN)

    data = f'{{"uid": "{api_key}", "actid": "{api_key}"}}'

    if endpoint == "/NorenWClientAPI/Holdings":
        data = f'{{"uid": "{api_key}", "actid": "{api_key}", "prd": "C"}}'

    payload = "jData=" + data

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }
    url = f"https://go.mynt.in{endpoint}"

    response = client.request(method, url, content=payload, headers=headers)
    data = response.text

    if not data or not data.strip():
        raise ValueError(f"Zebu API returned an empty response for {endpoint} (HTTP {response.status_code})")
    try:
        res_json = json.loads(data)
        return res_json
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Zebu API returned a non-JSON response for {endpoint} "
            f"(HTTP {response.status_code}): {data[:200]!r}"
        ) from e


def get_order_book(auth):
    return get_api_response("/NorenWClientAPI/OrderBook", auth, method="POST")


def get_trade_book(auth):
    return get_api_response("/NorenWClientAPI/TradeBook", auth, method="POST")


def get_positions(auth):
    positions = get_api_response("/NorenWClientAPI/PositionBook", auth, method="POST")
    logger.debug(f"PositionBook raw response: {positions}")
    return positions


def get_holdings(auth):
    return get_api_response("/NorenWClientAPI/Holdings", auth, method="POST")


# --- Per-Symbol Smart Order Lock ---
# Ensures only one smart order per symbol executes at a time.
# Others queue and execute sequentially, each getting a fresh position book.
_symbol_locks = {}          # {symbol_key: threading.Lock}
_symbol_locks_lock = threading.Lock()

# --- Position Book Cache ---
# Caches get_positions() for 1 second. Invalidated after each smart order placement.
_position_cache = {}        # {auth_token: {"data": ..., "timestamp": ...}}
_position_cache_lock = threading.Lock()
_POSITION_CACHE_TTL = 1.0   # seconds


def _get_symbol_lock(symbol, exchange, product):
    """Get or create a per-symbol lock for serializing smart orders."""
    key = f"{symbol}:{exchange}:{product}"
    with _symbol_locks_lock:
        if key not in _symbol_locks:
            _symbol_locks[key] = threading.Lock()
        return _symbol_locks[key]


def _get_cached_positions(auth):
    """Get positions from cache if fresh, otherwise fetch from broker API."""
    with _position_cache_lock:
        now = time.monotonic()
        cached = _position_cache.get(auth)
        if cached and (now - cached["timestamp"]) < _POSITION_CACHE_TTL:
            return cached["data"]

    # Cache miss or expired - fetch from broker
    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}

    return positions_data


def _invalidate_position_cache(auth):
    """Invalidate the position cache so the next queued order fetches fresh data."""
    with _position_cache_lock:
        _position_cache.pop(auth, None)



def get_open_position(tradingsymbol, exchange, producttype, auth):
    # Convert Trading Symbol from Max Algos Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = _get_cached_positions(auth)

    logger.debug(f"{positions_data}")

    net_qty = "0"

    if positions_data is None or (
        isinstance(positions_data, dict) and (positions_data["stat"] == "Not_Ok")
    ):
        # Handle the case where there is no data
        logger.debug("No data available.")
        net_qty = "0"

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if (
                position.get("tsym") == tradingsymbol
                and position.get("exch") == exchange
                and position.get("prd") == producttype
            ):
                net_qty = position.get("netqty", "0")
                break  # Assuming you need the first match

    return net_qty


def place_order_api(data, auth):
    AUTH_TOKEN = auth
    zebu_userid = get_zebu_userid(AUTH_TOKEN, fallback_userid=data.get("apikey") or data.get("user_id"))
    if not zebu_userid:
        logger.error("PlaceOrder Error: Zebu Client Code (User ID) is missing or unresolvable")
        return None, {
            "stat": "Not_Ok",
            "emsg": "Zebu Client Code (User ID) is missing. Please reconnect Zebu on Broker Management.",
        }, None
    data["apikey"] = zebu_userid
    data["uid"] = zebu_userid
    data["actid"] = zebu_userid
    token = get_token(data["symbol"], data["exchange"])
    # zebu_userid was just resolved above -- pass it through so transform_data
    # doesn't redundantly re-scan every AuthBrokerSession/Auth row and
    # re-decrypt tokens to derive the same value a second time on every order.
    newdata = transform_data(data, token, AUTH_TOKEN, zebu_uid=zebu_userid)
    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }

    payload = "jData=" + json.dumps(newdata)

    logger.debug(f"PlaceOrder payload: {payload}")

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://go.mynt.in/NorenWClientAPI/PlaceOrder"

    throttle_zebu_request()  # shared per-account rate limit -- see rate_limiter.py
    res = client.post(url, content=payload, headers=headers)
    # Add status attribute for compatibility with existing code
    res.status = res.status_code
    response_data = json.loads(res.text)

    logger.debug(f"PlaceOrder Response: {response_data}")

    if response_data.get("stat") == "Ok":
        orderid = response_data.get("norenordno")
    else:
        orderid = None
        logger.error(f"PlaceOrder Error: {response_data.get('emsg', 'Unknown error')}")
    return res, response_data, orderid


def place_smartorder_api(data, auth):
    AUTH_TOKEN = auth

    # If no API call is made in this function then res will return None
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    # Per-symbol lock: serialize smart orders per symbol
    symbol_lock = _get_symbol_lock(symbol, exchange, product)

    with symbol_lock:
        position_size = int(data.get("position_size", "0"))

        # Get current open position for the symbol
        current_position = int(
            get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN)
        )

        logger.debug(f"position_size : {position_size}")
        logger.debug(f"Open Position : {current_position}")

        # Determine action based on position_size and current_position
        action = None
        quantity = 0

        # If both position_size and current_position are 0, do nothing
        if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
            action = data["action"]
            quantity = data["quantity"]
            # logger.debug(f"action : {action}")
            # logger.debug(f"Quantity : {quantity}")
            res, response, orderid = place_order_api(data, AUTH_TOKEN)
            _invalidate_position_cache(AUTH_TOKEN)
            # logger.debug(f"{res}")
            # logger.debug(f"{response}")

            return res, response, orderid

        elif position_size == current_position:
            if int(data["quantity"]) == 0:
                response = {
                    "status": "success",
                    "message": "No OpenPosition Found. Not placing Exit order.",
                }
            else:
                response = {
                    "status": "success",
                    "message": "No action needed. Position size matches current position",
                }
            orderid = None
            return res, response, orderid  # res remains None as no API call was made

        if position_size == 0 and current_position > 0:
            action = "SELL"
            quantity = abs(current_position)
        elif position_size == 0 and current_position < 0:
            action = "BUY"
            quantity = abs(current_position)
        elif current_position == 0:
            action = "BUY" if position_size > 0 else "SELL"
            quantity = abs(position_size)
        else:
            if position_size > current_position:
                action = "BUY"
                quantity = position_size - current_position
                # logger.debug(f"smart buy quantity : {quantity}")
            elif position_size < current_position:
                action = "SELL"
                quantity = current_position - position_size
                # logger.debug(f"smart sell quantity : {quantity}")

        if action:
            # Prepare data for placing the order
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)

            # logger.debug(f"{order_data}")
            # Place the order
            res, response, orderid = place_order_api(order_data, auth)
            _invalidate_position_cache(AUTH_TOKEN)
            # logger.debug(f"{res}")
            logger.debug(f"{response}")
            logger.debug(f"{orderid}")

            return res, response, orderid


def close_all_positions(current_api_key, auth):
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Check if the positions data is null or empty. The broker's error
    # shape is a dict like {"stat": "Not_Ok", "emsg": "..."} rather than a
    # list -- positions_response[0] used to assume a non-empty list and
    # raised TypeError/IndexError on that shape (or on an empty list)
    # before this guard ever completed.
    if not positions_response or not isinstance(positions_response, list):
        return {"message": "No Open Positions Found"}, 200

    net_positions = positions_response

    closed = []
    failed = []
    # Loop through each position to close. A malformed entry (missing
    # netqty/token/exch/prd) must not abort the whole square-off -- every
    # other valid position in the same response still needs its close
    # order placed, so isolate failures per-position instead of letting
    # one bad entry crash the loop and leave the rest of the account's
    # positions open with no attempt made.
    for position in net_positions:
        try:
            netqty_raw = position["netqty"]
            if int(netqty_raw) == 0:
                continue

            action = "SELL" if int(netqty_raw) > 0 else "BUY"
            quantity = abs(int(netqty_raw))

            symbol = get_symbol(position["token"], position["exch"])
            logger.debug(f"The Symbol is {symbol}")

            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["exch"],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["prd"]),
                "quantity": str(quantity),
            }

            logger.debug(f"{place_order_payload}")

            res, response, orderid = place_order_api(place_order_payload, auth)

            if orderid:
                closed.append(symbol)
            else:
                failed.append(symbol)
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Skipping malformed position entry during close_all_positions: {position} ({e})")
            failed.append(position.get("token") if isinstance(position, dict) else str(position))

    if failed:
        return {
            "status": "error",
            "message": f"Squared off {len(closed)} position(s); failed for: {', '.join(str(f) for f in failed)}",
        }, 200

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    AUTH_TOKEN = auth
    api_key = get_zebu_userid(AUTH_TOKEN)
    data = {"uid": api_key, "norenordno": orderid}

    payload = "jData=" + json.dumps(data)
    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://go.mynt.in/NorenWClientAPI/CancelOrder"

    # Send the request using httpx
    throttle_zebu_request()  # shared per-account rate limit -- see rate_limiter.py
    res = client.post(url, content=payload, headers=headers)
    data = json.loads(res.text)
    logger.debug(f"CancelOrder Response: {data}")

    # Check if the request was successful
    if data.get("stat") == "Ok":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {
            "status": "error",
            "message": data.get("message", "Failed to cancel order"),
        }, res.status_code


def modify_order(data, auth):
    AUTH_TOKEN = auth
    api_key = get_zebu_userid(AUTH_TOKEN, fallback_userid=data.get("apikey"))

    token = get_token(data["symbol"], data["exchange"])
    data["symbol"] = get_br_symbol(data["symbol"], data["exchange"])
    data["apikey"] = api_key
    data["uid"] = api_key

    transformed_data = transform_modify_order_data(
        data, token
    )  # You need to implement this function

    logger.debug(f"Modify Order Request Data: {transformed_data}")

    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }
    payload = "jData=" + json.dumps(transformed_data)

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://go.mynt.in/NorenWClientAPI/ModifyOrder"

    throttle_zebu_request()  # shared per-account rate limit -- see rate_limiter.py
    res = client.post(url, content=payload, headers=headers)
    response = json.loads(res.text)

    logger.debug(f"Modify Order Response: {response}")

    if response.get("stat") == "Ok":
        return {"status": "success", "orderid": data["orderid"]}, 200
    else:
        return {
            "status": "error",
            "message": response.get("emsg", "Failed to modify order"),
        }, res.status_code


def cancel_all_orders_api(data, auth):
    # Get the order book

    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)
    # logger.debug(f"{order_book_response}")
    if not order_book_response or not isinstance(order_book_response, list):
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state. A
    # malformed order entry missing "status" must not crash the whole
    # comprehension -- that would cancel ZERO orders instead of just
    # skipping the one bad entry.
    orders_to_cancel = [
        order for order in order_book_response if order.get("status") in ["OPEN", "TRIGGER PENDING"]
    ]
    # logger.debug(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders. Same isolation principle: one order
    # missing "norenordno" must not abort cancellation of every other order.
    for order in orders_to_cancel:
        orderid = order.get("norenordno")
        if not orderid:
            logger.error(f"Skipping order with no norenordno during cancel_all_orders_api: {order}")
            continue
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
