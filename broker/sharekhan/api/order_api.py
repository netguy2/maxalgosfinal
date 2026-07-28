import os
import json


from broker.sharekhan.mapping.transform_data import (
    reverse_map_exchange,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_ROOT_URL = "https://api.sharekhan.com"


def _split_auth(auth: str) -> tuple[str, str]:
    """auth is "access_token:::customer_id" (see auth_api.authenticate_broker)."""
    parts = auth.split(":::", 1)
    access_token = parts[0]
    customer_id = parts[1] if len(parts) > 1 else ""
    return access_token, customer_id


def _headers(access_token, username=None):
    from database.user_db import get_user_broker_credentials
    from flask import has_request_context, session, request

    # If username was explicitly passed (e.g. from a background task that already
    # resolved it from the Auth table), skip the request-context lookup entirely.
    if not username:
        # Resolve username dynamically from request context
        username = os.getenv("LOGIN_USERNAME")
        if not username:
            if has_request_context():
                if "user" in session and session["user"]:
                    if isinstance(session["user"], dict):
                        username = session["user"].get("username")
                    else:
                        username = session["user"]
                else:
                    # Try getting from API key
                    api_key = request.headers.get("X-API-KEY") or request.args.get("apikey") or request.form.get("apikey")
                    if request.is_json:
                        try:
                            api_key = api_key or request.json.get("apikey")
                        except Exception:
                            pass
                    if api_key:
                        from database.auth_db import verify_api_key
                        username = verify_api_key(api_key)

            # Fallback to default user
            if not username:
                username = "admin"

    # Get credentials from database
    db_creds = get_user_broker_credentials(username, "sharekhan")
    full_api_key = db_creds.get("broker_api_key") if db_creds else ""

    # Fallback to env var if database is empty or not configured
    if not full_api_key:
        full_api_key = os.getenv("SHAREKHAN_API_KEY") or ""

    api_key = full_api_key.split(":::", 1)[0].strip().replace(" ", "+")
    vendor_key = full_api_key.split(":::", 1)[1].strip().replace(" ", "+") if ":::" in full_api_key else ""

    headers = {
        "api-key": api_key,
        "access-token": access_token,
        "Authorization": access_token,
        "Content-type": "application/json",
    }
    if vendor_key:
        headers["vendor-key"] = vendor_key
    return headers


def get_api_response(endpoint, auth, method="GET", payload=None, username=None):
    access_token, _customer_id = _split_auth(auth)
    client = get_httpx_client()
    headers = _headers(access_token, username=username)
    url = f"{_ROOT_URL}{endpoint}"

    try:
        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        elif method.upper() in ("POST", "PUT"):
            response = client.request(method.upper(), url, headers=headers, content=json.dumps(payload or {}))
        elif method.upper() == "DELETE":
            response = client.request(method.upper(), url, headers=headers, content=json.dumps(payload or {}))
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        try:
            return response.json()
        except Exception as json_err:
            logger.warning(
                f"Sharekhan API returned non-JSON response for {endpoint} "
                f"(status={response.status_code}): {json_err}"
            )
            return {
                "status": "error",
                "errorType": "api_error",
                "message": f"Non-JSON response (status {response.status_code}): {response.text[:100]}"
            }
    except Exception as e:
        logger.exception(f"Sharekhan API request failed: {e}")
        raise



def get_order_book(auth):
    _access_token, customer_id = _split_auth(auth)
    return get_api_response(f"/skapi/services/reports/{customer_id}", auth)


def get_trade_book(auth):
    _access_token, customer_id = _split_auth(auth)
    return get_api_response(f"/skapi/services/trades/{customer_id}", auth)


def get_positions(auth):
    # Sharekhan's `trades()` endpoint doubles as the positions/net-position
    # report per the SDK docs ("Retrieves all positions").
    _access_token, customer_id = _split_auth(auth)
    return get_api_response(f"/skapi/services/trades/{customer_id}", auth)


def get_holdings(auth):
    _access_token, customer_id = _split_auth(auth)
    return get_api_response(f"/skapi/services/holdings/{customer_id}", auth)


def place_order_api(data, auth):
    access_token, customer_id = _split_auth(auth)
    try:
        payload = transform_data(data, customer_id)
    except ValueError as val_err:
        logger.warning(f"Sharekhan order transform validation failed: {val_err}")
        class _Res:
            status = 400
        return _Res(), {"status": "error", "message": str(val_err)}, None

    logger.info(f"Sharekhan place_order payload: {payload}")

    response_data = get_api_response("/skapi/services/orders", auth, method="POST", payload=payload)
    logger.info(f"Sharekhan place_order response: {response_data}")

    order_id = None
    if isinstance(response_data, dict):
        # Check for any error indicator — Sharekhan uses camelCase 'errorType'
        # in its REST responses (confirmed from master contract error payloads).
        # Also guard snake_case 'error_type' as a safety net.
        has_error = (
            response_data.get("errorType")
            or response_data.get("error_type")
            or response_data.get("status") in ("error", "failed", "fail")
        )
        if not has_error:
            inner = response_data.get("data") or {}
            # Try all known field names Sharekhan may use for the order ID
            order_id = (
                response_data.get("orderId")
                or response_data.get("orderid")
                or response_data.get("order_id")
                or response_data.get("id")
            )
            if not order_id and isinstance(inner, dict):
                order_id = (
                    inner.get("orderId")
                    or inner.get("orderid")
                    or inner.get("order_id")
                    or inner.get("id")
                )
            if order_id:
                order_id = str(order_id).strip()
                if order_id == "0":
                    order_id = None

            # If order placement failed (either orderId is missing or is '0'),
            # pull out the error message details.
            if not order_id:
                err_msg = (
                    inner.get("errormsg")
                    or inner.get("errorMsg")
                    or response_data.get("message")
                    or response_data.get("emsg")
                )
                if err_msg:
                    response_data["message"] = err_msg

    if not order_id:
        logger.warning(
            f"Sharekhan order placement returned no orderId. "
            f"Symbol={data.get('symbol')}, Exchange={data.get('exchange')}, "
            f"Response={response_data}"
        )

    class _Res:
        status = 200 if order_id else 400

    return _Res(), response_data, order_id


def modify_order(data, auth):
    access_token, customer_id = _split_auth(auth)
    try:
        payload = transform_modify_order_data(data, customer_id)
    except ValueError as val_err:
        logger.warning(f"Sharekhan modify order transform validation failed: {val_err}")
        return {"status": "error", "message": str(val_err)}, 400


    response_data = get_api_response("/skapi/services/orders", auth, method="PUT", payload=payload)
    logger.debug(f"Sharekhan modify_order response: {response_data}")

    order_id = None
    if isinstance(response_data, dict):
        has_error = (
            response_data.get("errorType")
            or response_data.get("error_type")
            or response_data.get("status") in ("error", "failed", "fail")
        )
        if not has_error:
            inner = response_data.get("data") or {}
            order_id = response_data.get("orderId") or inner.get("orderId")
            if order_id:
                order_id = str(order_id).strip()
                if order_id == "0":
                    order_id = None
            if not order_id:
                err_msg = inner.get("errormsg") or inner.get("errorMsg") or response_data.get("message") or response_data.get("emsg")
                if err_msg:
                    response_data["message"] = err_msg

    if order_id:
        return {"status": "success", "orderid": str(order_id)}, 200
    return {
        "status": "error",
        "message": response_data.get("message", "Failed to modify order")
        if isinstance(response_data, dict)
        else "Failed to modify order",
    }, 400


def cancel_order(orderid, auth):
    access_token, customer_id = _split_auth(auth)
    payload = {
        "orderId": str(orderid),
        "customerId": customer_id,
        "channelUser": customer_id,
        "requestType": "CANCEL",
    }

    try:
        response_data = get_api_response("/skapi/services/orders", auth, method="DELETE", payload=payload)
        logger.debug(f"Sharekhan cancel_order response: {response_data}")

        has_error = (
            response_data.get("errorType")
            or response_data.get("error_type")
            or response_data.get("status") in ("error", "failed", "fail")
        )
        if isinstance(response_data, dict) and not has_error:
            inner = response_data.get("data") or {}
            err_msg = inner.get("errormsg") or inner.get("errorMsg")
            if err_msg:
                return {"status": "error", "message": err_msg}, 400
            return {"status": "success", "orderid": str(orderid)}, 200

        inner = response_data.get("data") or {} if isinstance(response_data, dict) else {}
        message = (
            inner.get("errormsg")
            or inner.get("errorMsg")
            or response_data.get("message")
            or response_data.get("emsg")
            if isinstance(response_data, dict)
            else "Failed to cancel order"
        )
        return {"status": "error", "message": message or "Failed to cancel order"}, 400
    except Exception as e:
        logger.exception(f"Error canceling Sharekhan order {orderid}: {e}")
        return {"status": "error", "message": f"Failed to cancel order: {e}"}, 500


def cancel_all_orders_api(data, auth):
    order_book_response = get_order_book(auth)
    orders = order_book_response.get("data") if isinstance(order_book_response, dict) else None
    if not orders:
        return [], []
    if isinstance(orders, dict):
        orders = [orders]

    orders_to_cancel = [
        o for o in orders if (o.get("orderStatus") or o.get("status") or "").upper() in ("OPEN", "TRIGGER PENDING", "PENDING")
    ]

    canceled_orders = []
    failed_cancellations = []
    for order in orders_to_cancel:
        orderid = order.get("orderId")
        _resp, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations


def close_all_positions(current_api_key, auth):
    positions_response = get_positions(auth)
    positions = positions_response.get("data") if isinstance(positions_response, dict) else None
    if not positions:
        return {"message": "No Open Positions Found"}, 200
    if isinstance(positions, dict):
        positions = [positions]

    for position in positions:
        net_qty = int(position.get("netQuantity", position.get("quantity", 0)) or 0)
        if net_qty == 0:
            continue

        action = "SELL" if net_qty > 0 else "BUY"
        quantity = abs(net_qty)
        # Position rows here carry Sharekhan's own exchange code since this
        # list comes straight from get_positions(), not map_position_data() -
        # convert to Max Algos exchange before the OA symbol lookup.
        oa_exchange = reverse_map_exchange(position.get("exchange", ""))
        symbol = get_oa_symbol(position.get("tradingSymbol", ""), oa_exchange) or position.get(
            "tradingSymbol", ""
        )

        place_order_payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": action,
            "exchange": oa_exchange,
            "pricetype": "MARKET",
            "product": reverse_map_product_type(position.get("productType", ""), oa_exchange),
            "quantity": str(quantity),
        }

        _res, _resp, _oid = place_order_api(place_order_payload, auth)

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200
