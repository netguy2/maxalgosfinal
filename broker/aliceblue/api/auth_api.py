import hashlib
import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(userid, authCode):
    """
    Authenticate with AliceBlue using the V2 vendor API.

    Returns:
        Tuple of (userSession, clientId, error_message)

    Flow:
      1. Compute SHA-256 checksum of: userId + authCode + apiSecret
      2. POST {"checkSum": checksum} to https://a3.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails
      3. Return the userSession from the response

    Environment variables:
      BROKER_API_KEY    = App Code (appCode)
      BROKER_API_SECRET = API Secret (apiSecret)
    """
    try:
        BROKER_API_SECRET = (os.environ.get("BROKER_API_SECRET") or "").strip()

        if not BROKER_API_SECRET:
            logger.error("BROKER_API_SECRET not found in environment variables")
            return None, None, "API secret (BROKER_API_SECRET) is missing in credentials."

        userid = (userid or "").strip()
        authCode = (authCode or "").strip()

        if not userid or not authCode:
            logger.error(f"Missing userid ({userid!r}) or authCode ({authCode!r})")
            return None, None, "User ID or Auth Code missing from authentication callback."

        logger.info(f"Authenticating with AliceBlue for user {userid}")

        client = get_httpx_client()

        # Step 1: Generate SHA-256 checksum = hash(userId + authCode + apiSecret)
        def _get_user_details(uid_str):
            checksum_input = f"{uid_str}{authCode}{BROKER_API_SECRET}"
            checksum = hashlib.sha256(checksum_input.encode("utf-8")).hexdigest()
            payload = {"checkSum": checksum}
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            url = "https://a3.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails"
            return client.post(url, json=payload, headers=headers, timeout=15.0)

        response = _get_user_details(userid)

        try:
            data_dict = response.json()
        except Exception:
            logger.error(f"AliceBlue raw response non-JSON (HTTP {response.status_code}): {response.text}")
            return None, None, f"Invalid non-JSON response from AliceBlue (HTTP {response.status_code})."

        logger.info(f"AliceBlue API response (HTTP {response.status_code}): {json.dumps(data_dict)}")

        def _try_extract_session(data):
            if not isinstance(data, dict):
                return None, None, None

            stat = str(data.get("stat") or data.get("status") or "").lower()
            user_session = (
                data.get("userSession")
                or data.get("user_session")
                or data.get("session")
                or data.get("token")
            )
            client_id = (
                data.get("clientId")
                or data.get("client_id")
                or data.get("userId")
                or userid
            )

            if user_session and stat not in ("not_ok", "error", "failed", "false"):
                return str(user_session), str(client_id), None

            return None, None, None

        user_session, client_id, _ = _try_extract_session(data_dict)
        if user_session:
            logger.info(f"AliceBlue authentication successful for user {userid} (clientId={client_id})")
            return user_session, client_id, None

        # Fallback: if userid case differed (e.g. lowercase vs uppercase), try uppercase userid
        if userid != userid.upper():
            logger.info(f"Retrying AliceBlue auth with uppercase userId: {userid.upper()}")
            try:
                alt_response = _get_user_details(userid.upper())
                alt_data = alt_response.json()
                alt_session, alt_client_id, _ = _try_extract_session(alt_data)
                if alt_session:
                    logger.info(f"AliceBlue auth successful with uppercase userId {userid.upper()}")
                    return alt_session, alt_client_id, None
            except Exception as e:
                logger.warning(f"Uppercase fallback retry failed: {e}")

        # Extract error message if session retrieval failed
        error_msg = (
            data_dict.get("emsg")
            or data_dict.get("message")
            or data_dict.get("msg")
            or data_dict.get("error")
            or data_dict.get("error_description")
            or data_dict.get("detail")
        )

        if error_msg:
            logger.error(f"AliceBlue API returned error: {error_msg}")
            return None, None, f"AliceBlue error: {error_msg}"

        if not response.is_success:
            return None, None, f"AliceBlue HTTP {response.status_code} error."

        logger.error(f"Could not extract userSession from response: {data_dict}")
        return None, None, f"Failed to extract session from AliceBlue response: {data_dict}"

    except json.JSONDecodeError:
        return None, None, "Invalid JSON response format from AliceBlue API."
    except httpx.HTTPError as e:
        logger.exception(f"AliceBlue HTTP connection error: {e}")
        return None, None, f"HTTP connection error with AliceBlue: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in AliceBlue authentication: {e}")
        return None, None, f"Authentication exception: {str(e)}"
