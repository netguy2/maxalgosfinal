from broker.sharekhan.mapping.transform_data import map_exchange
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_ROOT_URL = "https://api.sharekhan.com"


def get_margin_data(auth_token):
    """Fetch margin/funds data from Sharekhan using the compound auth token
    ("access_token:::customer_id"). Sharekhan's fund-details endpoint is
    per-exchange - queried against NC (NSE cash) as the default account
    exchange since funds are typically shared/reported at the account level."""
    from broker.sharekhan.api.order_api import _headers, _split_auth

    access_token, customer_id = _split_auth(auth_token)
    if not customer_id:
        logger.error("Sharekhan margin fetch: missing customer_id in auth token")
        return {}

    client = get_httpx_client()
    headers = _headers(access_token)

    try:
        response = client.get(
            f"{_ROOT_URL}/skapi/services/limitstmt/{map_exchange('NSE')}/{customer_id}",
            headers=headers,
        )
        margin_data = response.json()
    except Exception as e:
        logger.error(f"Error fetching Sharekhan margin data: {e}")
        return {}

    if not isinstance(margin_data, dict) or margin_data.get("error_type"):
        logger.error(f"Error fetching Sharekhan margin data: {margin_data}")
        return {}

    data = margin_data.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}

    try:
        available_cash = float(data.get("netAvailableMargin", data.get("availableCash", 0)) or 0)
        used_margin = float(data.get("marginUsed", data.get("utilisedAmount", 0)) or 0)
        collateral = float(data.get("collateral", 0) or 0)
        m2m_realized = float(data.get("realizedMtm", data.get("m2mRealized", 0)) or 0)
        m2m_unrealized = float(data.get("unrealizedMtm", data.get("m2mUnrealized", 0)) or 0)

        return {
            "availablecash": f"{available_cash:.2f}",
            "collateral": f"{collateral:.2f}",
            "m2munrealized": f"{m2m_unrealized:.2f}",
            "m2mrealized": f"{m2m_realized:.2f}",
            "utiliseddebits": f"{used_margin:.2f}",
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Unexpected Sharekhan margin response shape: {e} - {data}")
        return {}
