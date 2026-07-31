# api/funds.py

import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "CLIENT_LOCAL_IP",
        "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
        "X-MACAddress": "MAC_ADDRESS",
        "X-PrivateKey": api_key,
    }

    response = client.get(
        "https://apiconnect.angelone.in/rest/secure/angelbroking/user/v1/getRMS",
        headers=headers,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    # Angel's API can return an empty body or an HTML error page instead of
    # a JSON error payload -- guard the same way as order_api.py's
    # place/cancel/modify order functions in this same broker plugin.
    body_text = response.text
    if not body_text or not body_text.strip():
        raise ValueError(f"Angel API returned an empty response for getRMS (HTTP {response.status_code})")
    try:
        margin_data = json.loads(body_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Angel API returned a non-JSON response for getRMS "
            f"(HTTP {response.status_code}): {body_text[:200]!r}"
        ) from e

    logger.info(f"Margin Data: {margin_data}")

    if margin_data.get("data"):
        data = margin_data["data"]

        # Calculate collateral as availablecash - utilisedpayout
        availablecash = 0.0
        calculated_collateral = 0.0
        try:
            availablecash = float(data.get("availablecash", 0) or 0)
            utilisedpayout = float(data.get("utilisedpayout", 0) or 0)
            calculated_collateral = availablecash - utilisedpayout
        except (ValueError, TypeError):
            pass

        filtered_data = {
            "availablecash": f"{availablecash:.2f}",
            "collateral": f"{calculated_collateral:.2f}",
            "m2mrealized": "{:.2f}".format(float(data.get("m2mrealized", 0) or 0)),
            "m2munrealized": "{:.2f}".format(float(data.get("m2munrealized", 0) or 0)),
            "utiliseddebits": "{:.2f}".format(float(data.get("utiliseddebits", 0) or 0)),
        }

        logger.info(
            f"Calculated collateral (availablecash - utilisedpayout): {calculated_collateral}"
        )
        return filtered_data
    else:
        return {}
