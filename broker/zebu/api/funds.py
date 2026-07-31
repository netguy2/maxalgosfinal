# api/funds.py

import json
import os

import httpx

from broker.zebu.api.rate_limiter import throttle_zebu_request
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Zebu's API using the provided auth token with httpx connection pooling."""

    from broker.zebu.api.order_api import get_zebu_userid
    userid = get_zebu_userid(auth_token)
    actid = userid

    # Prepare the payload for the request
    data = {
        "uid": userid,  # User ID
        "actid": actid,  # Account ID
    }

    payload = "jData=" + json.dumps(data)

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {auth_token}",
    }

    # Zebu API endpoint URL
    url = "https://go.mynt.in/NorenWClientAPI/Limits"

    # Send the POST request to Zebu's API using httpx
    throttle_zebu_request()  # shared per-account rate limit -- see rate_limiter.py
    response = client.post(url, content=payload, headers=headers)

    # Zebu's API can return an empty body or an HTML error page instead of a
    # JSON error payload (transient gateway hiccup, or a token that isn't
    # fully live yet right after switching the data broker). Left unguarded,
    # json.loads() on that raises an opaque "Expecting value: line 1 column 1
    # (char 0)" that bubbles up as a raw 500 from the dashboard's funds call
    # and can look like a session-expiry problem when it's actually a
    # single failed HTTP call. Fail with a message that explains what
    # actually happened instead. Mirrors the same guard added to
    # get_api_response() in broker/zebu/api/data.py for the historical-data
    # endpoint.
    body_text = response.text
    if not body_text or not body_text.strip():
        raise ValueError(
            f"Zebu API returned an empty response for /Limits (HTTP {response.status_code})"
        )
    try:
        margin_data = json.loads(body_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Zebu API returned a non-JSON response for /Limits "
            f"(HTTP {response.status_code}): {body_text[:200]!r}"
        ) from e

    logger.info(f"Margin Data: {margin_data}")

    # Check if the request was successful. Returning {} here (as this used
    # to do) looks IDENTICAL to a real zero-balance account by the time it
    # reaches the dashboard: services/funds_service.py's get_funds_with_auth
    # wraps whatever this returns as {"status": "success", "data": {}}
    # (still success=True) and CACHES it for 3s, and blueprints/auth.py's
    # get_dashboard_data then substitutes an all-zero fallback dict since
    # `{}` is falsy -- so the user sees "Balance ₹0.00 / P&L ₹0.00" with no
    # error anywhere, indistinguishable from a genuinely empty account.
    # This happens for real right after a broker disconnect+reconnect: a
    # freshly-issued session token is not always immediately live on
    # Zebu's own servers, so /Limits legitimately answers "Not_Ok" for a
    # few seconds. Raising (instead of returning {}) surfaces this as the
    # real, transient "broker session not ready yet" error the dashboard
    # already has a code path for (BROKER_SESSION_EXPIRED-style handling),
    # and -- just as importantly -- an exception here means
    # get_funds_with_auth's `_funds_cache[cache_key] = funds` line is never
    # reached, so the bad {} result is never cached and the very next
    # dashboard poll (a few seconds later, once Zebu's session is fully
    # live) gets a fresh real answer instead of serving the cached zero for
    # the rest of the 3s TTL.
    if margin_data.get("stat") != "Ok":
        emsg = margin_data.get("emsg") or "Zebu returned stat=Not_Ok with no error message"
        logger.warning(f"Zebu /Limits request not OK: {emsg}")
        raise ValueError(f"Zebu margin request failed: {emsg}")

    try:
        # Calculate total_available_margin as the sum of 'cash' and 'payin'
        total_available_margin = (
            float(margin_data.get("cash", 0))
            + float(margin_data.get("payin", 0))
            - float(margin_data.get("marginused", 0))
        )
        total_collateral = float(margin_data.get("brkcollamt", 0))
        total_used_margin = float(margin_data.get("marginused", 0))
        total_realised = -float(margin_data.get("rpnl", 0))
        total_unrealised = float(margin_data.get("unmtom", 0))

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
        return processed_margin_data
    except KeyError as e:
        # Log the exception and return an empty dictionary if there's an unexpected error
        logger.error(f"Error processing margin data: {e}")
        return {}
