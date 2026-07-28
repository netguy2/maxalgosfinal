"""Sharekhan (ShareConnect) authentication.

Sharekhan's login flow is a two-step encrypted token exchange, not a plain
OAuth code swap:

1. User is redirected to Sharekhan's login page. On success, Sharekhan
   redirects back with an encrypted `request_token` query param. That token
   is an AES-256-GCM ciphertext of "RequestId|CustomerId" using the app's
   secret key as the AES key and a fixed all-zero IV/nonce (per Sharekhan's
   published SDK - see https://github.com/Sharekhan-API/shareconnectpython).

2. To get an access token, the app must:
   a. Decrypt the request_token with the secret key.
   b. Swap the two pipe-separated fields (CustomerId|RequestId) and
      re-encrypt them with the same key/scheme.
   c. POST the re-encrypted string as `requestToken` to Sharekhan's
      /skapi/services/access/token endpoint, alongside apiKey and state.
   d. Sharekhan responds with the actual access_token.

The customerId embedded in the original request_token is required for
almost every other Sharekhan endpoint (positions, holdings, orders, funds),
so it is extracted here and packed into the auth string returned to the
caller, following the same "compound auth string" convention already used
by broker/kotak/api/auth_api.py: "access_token:::customer_id".
"""

import base64
import json

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger


logger = get_logger(__name__)

_ROOT_URL = "https://api.sharekhan.com"
_ACCESS_TOKEN_PATH = "/skapi/services/access/token"

# Fixed all-zero 16-byte IV/nonce - required by Sharekhan's own encryption
# scheme (see generate_session()/generate_session_without_versionId() in the
# published SDK). Not a security choice made here; must match exactly for
# Sharekhan's server-side decryption to succeed.
_IV = base64.b64decode("AAAAAAAAAAAAAAAAAAAAAA==")



def _aes_gcm_encrypt(secret_key: str, plaintext: str) -> str:
    """AES-256-GCM encrypt matching Sharekhan's generate_session_without_versionId:

    1. Encrypt with AES-GCM, all-zero 16-byte nonce, tag_length=16.
       No padding is applied (SDK's encryptAPIString does not pad the string).
    2. Encode ciphertext+tag with STANDARD base64 WITH padding (the SDK's
       encryptAPIString uses base64.b64encode, not the urlsafe variant).

    Using urlsafe base64 or stripping padding or adding PKCS7 padding
    produced a different representation that Sharekhan's access-token
    endpoint rejected as 'Request token is invalid'.
    """
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = secret_key.encode("utf-8")
    raw = plaintext.encode("utf-8")
    encryptor = Cipher(
        algorithms.AES(key), modes.GCM(_IV, None, 16), default_backend()
    ).encryptor()
    ciphertext = encryptor.update(raw) + encryptor.finalize()
    # Standard base64 WITH padding, matching SDK's base64.b64encode
    return base64.b64encode(ciphertext + encryptor.tag).decode("utf-8")


def _aes_gcm_decrypt(secret_key: str, ciphertext_b64url: str) -> str:
    """Decrypt Sharekhan's request_token (AES-256-GCM, all-zero 16-byte nonce).

    Tries urlsafe base64 first, then standard base64, since Sharekhan's
    redirect uses standard alphabet (+/) but URL-encoding can mangle it.
    The SDK's decryption_method uses base64.urlsafe_b64decode with the
    token received directly from the URL - we handle both.
    """
    key_bytes = secret_key.encode("utf-8")
    if len(key_bytes) not in (16, 24, 32):
        raise ValueError(
            f"Sharekhan secret_key must be 16, 24, or 32 bytes for AES-GCM, "
            f"got {len(key_bytes)} bytes - check BROKER_API_SECRET"
        )

    last_error: Exception | None = None
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            padding = "=" * (-len(ciphertext_b64url) % 4)
            raw = decoder(ciphertext_b64url + padding)
        except Exception as e:
            last_error = e
            continue
        try:
            # ciphertext is everything except last 16 bytes (GCM tag)
            ciphertext, tag = raw[:-16], raw[-16:]
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            decryptor = Cipher(
                algorithms.AES(key_bytes), modes.GCM(_IV, tag, 16), default_backend()
            ).decryptor()
            plaintext_bytes = decryptor.update(ciphertext) + decryptor.finalize()
            return plaintext_bytes.decode("utf-8")
        except Exception as e:
            last_error = e
            continue

    raise ValueError(f"Could not decrypt Sharekhan request_token: {last_error}")



def _parse_credentials():
    """BROKER_API_KEY holds `api_key:::vendor_key` (vendor_key optional,
    blank for non-vendor logins). BROKER_API_SECRET holds the plain
    secret_key."""
    from utils.config import get_broker_api_key, get_broker_api_secret

    full_api_key = get_broker_api_key() or ""
    secret_key = get_broker_api_secret() or ""

    parts = full_api_key.split(":::", 1)
    api_key = parts[0].strip().replace(" ", "+")
    vendor_key = parts[1].strip().replace(" ", "+") if len(parts) > 1 else ""
    secret_key = secret_key.strip().replace(" ", "+")

    return api_key, vendor_key, secret_key


def authenticate_broker(request_token):
    """Exchange Sharekhan's encrypted request_token for an access_token.

    Args:
        request_token: The (URL-encoded) encrypted request_token query
            param Sharekhan appended to the redirect callback.

    Returns:
        (auth_string, error_message) - auth_string is
        "access_token:::customer_id" on success, matching the compound
        auth-string convention already used elsewhere (see
        broker/kotak/api/auth_api.py). customer_id is required by nearly
        every other Sharekhan endpoint.
    """
    try:
        if not request_token:
            return None, "Missing request_token from Sharekhan callback"

        api_key, vendor_key, secret_key = _parse_credentials()

        if not api_key:
            return None, "BROKER_API_KEY (api_key) is not configured"
        if not secret_key:
            return None, "BROKER_API_SECRET (secret_key) is not configured"

        # request_token arrives here already URL-decoded by Flask/Werkzeug's
        # query-string parser (request.args.get() in blueprints/brlogin.py).
        #
        # Confirmed from production logs: Sharekhan's redirect embeds the
        # encrypted token using STANDARD base64 (which can contain literal
        # "+" characters) without percent-encoding it first (a "+" should be
        # sent as "%2B" in a query string). Per the
        # application/x-www-form-urlencoded convention, Werkzeug's query
        # string parser treats a literal "+" as an encoded space and
        # converts it - by the time request.args.get() returns the value,
        # any "+" in the original token has already been silently replaced
        # with a space, e.g. observed token:
        #   "...eBQko6pJ r72M6TSehZKs6hFSvlbXq7gqUA=" (space where "+" was)
        # This is irreversible information loss UNLESS we reverse the
        # substitution before decoding - which is safe here because base64
        # (standard or urlsafe) never legitimately contains a literal space.
        token = request_token.replace(" ", "+")

        logger.info(
            f"Sharekhan request_token diagnostics: len={len(request_token)} "
            f"raw_repr={request_token!r} corrected_repr={token!r}"
        )

        # Step 1: decrypt to get "RequestId|CustomerId"
        decrypted = _aes_gcm_decrypt(secret_key, token)
        parts = decrypted.split("|")
        if len(parts) != 2:
            logger.error(f"Unexpected request_token payload shape after decrypt: {decrypted!r}")
            return None, "Invalid request_token received from Sharekhan"

        request_id, customer_id = parts[0], parts[1]
        logger.info(f"Sharekhan decrypt OK: request_id={request_id!r} customer_id={customer_id!r}")

        # Step 2: swap to "CustomerId|RequestId" and re-encrypt - this is
        # the exact transformation Sharekhan's own SDK performs before
        # submitting it as the session/requestToken parameter.

        swapped = f"{customer_id}|{request_id}"
        encrypted_session_token = _aes_gcm_encrypt(secret_key, swapped)

        client = get_httpx_client()
        url = f"{_ROOT_URL}{_ACCESS_TOKEN_PATH}"
        payload = {
            "apiKey": api_key,
            "requestToken": encrypted_session_token,
            # Integer, not string - the SDK's own sample.py uses state=12345
            # (int). Sharekhan's access-token endpoint appears to validate
            # this field's type strictly; sending it as a string produced
            # "Request token is invalid" (input_error) even with a
            # correctly decrypted/re-encrypted token.
            "state": 12345,
        }
        if vendor_key:
            payload["vendorkey"] = vendor_key

        # Sharekhan's own SDK (SharekhanConnect.requestHeaders()) sends the
        # api_key in an "api-key" HTTP header on every request, not just in
        # the JSON body. Without this header, the access-token endpoint
        # rejects the request as {"message": "Request token is invalid",
        # "errorType": "input_error"} even with a correctly decrypted and
        # re-encrypted requestToken.
        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }
        if vendor_key:
            headers["vendor-key"] = vendor_key

        response = client.post(
            url,
            headers=headers,
            content=json.dumps(payload),
        )

        try:
            data = response.json()
        except ValueError:
            logger.error(f"Non-JSON response from Sharekhan access-token endpoint: {response.text}")
            return None, "Invalid response from Sharekhan while generating access token"

        if data.get("error_type") or response.status_code >= 400:
            message = data.get("message") or data.get("error_type") or "Access token exchange failed"
            logger.error(f"Sharekhan access-token error: {data}")
            return None, message

        access_token = None
        if isinstance(data.get("data"), dict):
            access_token = (
                data["data"].get("accessToken")
                or data["data"].get("access_token")
                or data["data"].get("token")
            )
        access_token = (
            access_token
            or data.get("accessToken")
            or data.get("access_token")
            or data.get("token")
        )

        if not access_token:
            logger.error(f"Sharekhan access-token response missing access token: {data}")
            return None, "Sharekhan did not return an access token"

        # Update customer_id from API response if available, falling back to decrypted value
        response_customer_id = None
        if isinstance(data.get("data"), dict):
            response_customer_id = data["data"].get("customerId") or data["data"].get("loginId")
        response_customer_id = response_customer_id or data.get("customerId") or data.get("loginId")
        if response_customer_id:
            customer_id = str(response_customer_id)

        auth_string = f"{access_token}:::{customer_id}"
        return auth_string, None

    except Exception as e:
        logger.exception(f"Sharekhan authentication error: {e}")
        return None, f"Sharekhan authentication error: {str(e)}"


def get_login_url(api_key: str = None, vendor_key: str = None, version_id: str = None) -> str:
    """Get Sharekhan login URL matching official SharekhanConnect SDK."""
    if not api_key:
        parsed_api_key, parsed_vendor_key, _ = _parse_credentials()
        api_key = api_key or parsed_api_key
        vendor_key = vendor_key or parsed_vendor_key

    base_url = f"https://api.sharekhan.com/skapi/auth/login.html?api_key={api_key}&state=12345"
    if vendor_key:
        base_url += f"&vendor_key={vendor_key}"
    if version_id:
        base_url += f"&version_id={version_id}"
    return base_url
