import hashlib
import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


import urllib.parse


def authenticate_broker(code):
    """
    Authenticate with Bnr using OAuth 2.0 flow.
    Exchanges the authorization code for an access token.
    """
    # BROKER_API_KEY format: userid:::client_id (e.g., ITC1441:::ITC1441_U)
    full_api_key = os.getenv("BROKER_API_KEY")
    if not full_api_key:
        return None, "BNR API key is missing. Please configure credentials on the Credentials tab."

    if ":::" in full_api_key:
        parts = full_api_key.split(":::", 1)
        userid = parts[0].strip()
        client_id = parts[1].strip()
    else:
        userid = full_api_key.strip()
        client_id = full_api_key.strip()

    secret_key = (os.getenv("BROKER_API_SECRET") or "").strip()

    if not code:
        return None, "Authorization code is required"

    code = urllib.parse.unquote(str(code)).strip()

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # Bnr OAuth token exchange endpoint
        url = "https://prime.bnrsecurities.com/NorenWClientAPI/GenAcsTok"

        # Compute checksum as per Noren OMS spec: SHA256(client_id + secret_key + code)
        checksum_input = f"{client_id}{secret_key}{code}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        # Prepare token exchange payload as required by Noren spec
        payload = {
            "code": code,
            "checksum": checksum,
        }

        payload_str = "jData=" + json.dumps(payload)
        # Noren OMS endpoints require application/x-www-form-urlencoded to parse jData parameter
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        logger.info(f"Bnr OAuth token exchange request to {url} for client_id={client_id}")
        response = client.post(url, content=payload_str, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if data.get("stat") == "Ok" and "access_token" in data:
                logger.info("Bnr OAuth authentication successful")
                resp_userid = data.get("actid") or data.get("uid") or userid
                return data["access_token"], resp_userid, None
            else:
                error_msg = data.get("emsg", "Authentication failed. Please try again.")
                logger.error(f"Bnr OAuth auth error: {error_msg} (raw_response={data})")
                return None, None, error_msg
        else:
            error_msg = f"Error: {response.status_code}, {response.text}"
            logger.error(f"Bnr OAuth HTTP error: {error_msg}")
            return None, None, error_msg

    except Exception as e:
        logger.error(f"Bnr OAuth exception: {e}")
        return None, None, str(e)
