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

    # Check if the request was successful
    if margin_data.get("stat") != "Ok":
        # Log the error or return an empty dictionary to indicate failure
        logger.info(f"Error fetching margin data: {margin_data.get('emsg')}")
        return {}

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
