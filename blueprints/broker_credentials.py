# blueprints/broker_credentials.py
"""
Broker credentials management API.
Handles reading and updating broker credentials in the .env file.
"""

import os
import re

from flask import Blueprint, jsonify, request

from utils.config import (
    get_valid_brokers,
    get_websocket_host,
    get_websocket_port,
    get_websocket_url,
    get_zmq_host,
    get_zmq_port,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

broker_credentials_bp = Blueprint("broker_credentials_bp", __name__, url_prefix="/api/broker")


def get_env_path():
    """Get the absolute path to the .env file."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, "..", ".env"))


def read_env_file():
    """Read and parse the .env file into a dictionary of lines."""
    env_path = get_env_path()
    if not os.path.exists(env_path):
        return None, "Environment file not found"

    try:
        # Use UTF-8 encoding for cross-platform compatibility
        with open(env_path, encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        logger.exception(f"Error reading .env file: {e}")
        return None, str(e)


def update_env_value(content: str, key: str, value: str) -> str:
    """Update a specific key's value in the .env content.

    Uses single quotes for values. This is compatible with python-dotenv
    and most .env parsers across platforms.
    """
    # Pattern to match the key with various formats
    # Handles: KEY = 'value', KEY = "value", KEY = value, KEY='value', etc.
    pattern = rf"^({re.escape(key)}\s*=\s*).*$"

    # Always wrap in single quotes for consistency
    # Single quotes in .env files don't require escaping in most parsers
    # If value contains single quotes, use double quotes instead
    if "'" in value:
        # Use double quotes, escape any existing double quotes and backslashes
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        new_value = f'"{escaped_value}"'
    else:
        # Use single quotes (no escaping needed)
        new_value = f"'{value}'"

    replacement = rf"\g<1>{new_value}"

    # Try to replace existing key
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)

    if count == 0:
        # Key doesn't exist, append it
        if not new_content.endswith("\n"):
            new_content += "\n"
        new_content += f"{key} = {new_value}\n"

    return new_content


def get_env_value(key: str) -> str:
    """Get a value from the .env file."""
    return os.getenv(key, "")


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only the first few characters.

    Returns a FIXED-length output (``prefix + '*' * 8``) regardless of the
    original secret's length. This intentionally hides the secret's true
    length so an over-the-shoulder viewer (or a screenshot) cannot infer
    "this is a 64-char Zerodha API secret" vs "this is a 32-char Fyers
    secret" from the asterisk count.

    The fixed-length mask also keeps the rendered value bounded so a long
    secret (some brokers issue 80+ char tokens) cannot overflow the
    Profile UI's column layout — the bug originally reported in the
    Current Configuration card where the asterisks ran past the right
    edge of the card.

    For empty values, returns "" so the frontend can detect "not set" and
    show its placeholder copy.
    """
    if not value:
        return ""
    if len(value) <= show_chars:
        # Edge case: secret shorter than the prefix budget. Show only the
        # mask suffix to avoid revealing the entire short value.
        return "*" * 8
    return value[:show_chars] + "*" * 8


def get_broker_from_redirect_url(redirect_url: str) -> str:
    """Extract broker name from redirect URL."""
    try:
        match = re.search(r"/([^/]+)/callback$", redirect_url)
        if match:
            return match.group(1).lower()
    except Exception:
        pass
    return ""


def _resolve_broker_name(username, requested_broker):
    """Resolve which broker's credentials to act on: the explicitly
    requested one (query/body param), or the user's current data broker
    (same fallback used by app.py's os.getenv patch) - so callers that
    don't pass `broker` (e.g. existing Profile.tsx requests) keep working
    exactly as before this endpoint became broker-aware."""
    if requested_broker:
        return requested_broker
    if not username:
        return None
    from database.auth_db import get_auth_token_dbquery
    auth_obj = get_auth_token_dbquery(username)
    return auth_obj.broker if auth_obj else None


@broker_credentials_bp.route("/credentials", methods=["GET"])
@check_session_validity
def get_credentials():
    """Get current broker credentials (masked)."""
    try:
        from flask import session
        username = session.get("user") if isinstance(session.get("user"), str) else None
        broker_name = _resolve_broker_name(username, request.args.get("broker"))
        from database.user_db import get_user_broker_credentials
        db_creds = get_user_broker_credentials(username, broker_name) if username and broker_name else {}

        # Get current values from database or fallback to environment
        broker_api_key = db_creds.get("broker_api_key") or get_env_value("BROKER_API_KEY")
        broker_api_secret = db_creds.get("broker_api_secret") or get_env_value("BROKER_API_SECRET")
        broker_api_key_market = db_creds.get("broker_api_key_market") or get_env_value("BROKER_API_KEY_MARKET")
        broker_api_secret_market = db_creds.get("broker_api_secret_market") or get_env_value("BROKER_API_SECRET_MARKET")
        redirect_url = db_creds.get("redirect_url") or get_env_value("REDIRECT_URL")

        ngrok_allow = get_env_value("NGROK_ALLOW")
        host_server = get_env_value("HOST_SERVER")
        websocket_url = get_env_value("WEBSOCKET_URL") or get_websocket_url()

        # Get port configuration. Defaults live in utils.config (8785/5575,
        # not the old 8765/5555) so unrelated Max Algos-based deployments on
        # the same host don't collide out of the box; .env can still
        # override per-instance (see install-multi.sh).
        flask_host = get_env_value("FLASK_HOST_IP") or "127.0.0.1"
        flask_port = get_env_value("FLASK_PORT") or "5000"
        websocket_host = get_websocket_host()
        websocket_port = str(get_websocket_port())
        zmq_host = get_zmq_host()
        zmq_port = str(get_zmq_port())

        # Get current broker from redirect URL
        current_broker = get_broker_from_redirect_url(redirect_url)

        # Auto-discovered from broker/*/plugin.json - not .env's VALID_BROKERS
        # (see utils.config.get_valid_brokers for why).
        brokers_list = get_valid_brokers()

        return jsonify(
            {
                "status": "success",
                "data": {
                    "broker_api_key": mask_secret(broker_api_key, 6),
                    "broker_api_key_raw_length": len(broker_api_key),
                    "broker_api_secret": mask_secret(broker_api_secret, 4),
                    "broker_api_secret_raw_length": len(broker_api_secret),
                    "broker_api_key_market": mask_secret(broker_api_key_market, 6),
                    "broker_api_key_market_raw_length": len(broker_api_key_market),
                    "broker_api_secret_market": mask_secret(broker_api_secret_market, 4),
                    "broker_api_secret_market_raw_length": len(broker_api_secret_market),
                    "redirect_url": redirect_url,
                    "current_broker": current_broker,
                    "valid_brokers": brokers_list,
                    "ngrok_allow": ngrok_allow.upper() == "TRUE",
                    "host_server": host_server,
                    "websocket_url": websocket_url,
                    # Server status info
                    "server_status": {
                        "flask": {"host": flask_host, "port": flask_port},
                        "websocket": {"host": websocket_host, "port": websocket_port},
                        "zmq": {"host": zmq_host, "port": zmq_port},
                    },
                },
            }
        )
    except Exception as e:
        logger.exception(f"Error getting broker credentials: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broker_credentials_bp.route("/credentials", methods=["POST"])
@check_session_validity
def update_credentials():
    """Update broker credentials in .env file."""
    try:
        # Support both JSON and form data
        if request.is_json:
            data = request.get_json() or {}
            broker_api_key = data.get("broker_api_key", "").strip()
            broker_api_secret = data.get("broker_api_secret", "").strip()
            broker_api_key_market = data.get("broker_api_key_market", "").strip()
            broker_api_secret_market = data.get("broker_api_secret_market", "").strip()
            redirect_url = data.get("redirect_url", "").strip()
            ngrok_allow = data.get("ngrok_allow", "")
            host_server = data.get("host_server", "").strip()
            websocket_url = data.get("websocket_url", "").strip()
            has_ngrok_key = "ngrok_allow" in data
        else:
            # Form data
            broker_api_key = request.form.get("broker_api_key", "").strip()
            broker_api_secret = request.form.get("broker_api_secret", "").strip()
            broker_api_key_market = request.form.get("broker_api_key_market", "").strip()
            broker_api_secret_market = request.form.get("broker_api_secret_market", "").strip()
            redirect_url = request.form.get("redirect_url", "").strip()
            ngrok_allow = request.form.get("ngrok_allow", "").strip()
            host_server = request.form.get("host_server", "").strip()
            websocket_url = request.form.get("websocket_url", "").strip()
            has_ngrok_key = "ngrok_allow" in request.form

        from flask import session
        username = session.get("user") if isinstance(session.get("user"), str) else None

        # Which broker these credentials belong to: derived from the
        # redirect_url if one was submitted this request, otherwise the
        # explicit `broker` field, otherwise falls back to the user's
        # current data broker (mirrors app.py's os.getenv patch fallback) -
        # so partial updates (e.g. secret-only edits that don't resend
        # redirect_url) still land on the right row.
        requested_broker = data.get("broker") if request.is_json else request.form.get("broker")
        broker_name = get_broker_from_redirect_url(redirect_url) if redirect_url else None
        broker_name = _resolve_broker_name(username, broker_name or requested_broker)

        # Validate redirect URL format
        if redirect_url:
            if not re.match(r"^https?://.+/[^/]+/callback$", redirect_url):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Invalid redirect URL format. Must end with /<broker>/callback",
                    }
                ), 400

            # Validate broker name - auto-discovered from broker/*/plugin.json,
            # not .env's VALID_BROKERS (see utils.config.get_valid_brokers).
            valid_brokers = set(get_valid_brokers())

            if broker_name and broker_name not in valid_brokers:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"Invalid broker '{broker_name}'. Valid brokers: {', '.join(sorted(valid_brokers))}",
                    }
                ), 400

            # Validate broker-specific API key formats
            if broker_name == "fivepaisa" and broker_api_key:
                if ":::" not in broker_api_key or broker_api_key.count(":::") != 2:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "5paisa API key must be in format: 'User_Key:::User_ID:::client_id'",
                        }
                    ), 400

            elif broker_name == "flattrade" and broker_api_key:
                if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Flattrade API key must be in format: 'client_id:::api_key'",
                        }
                    ), 400

            elif broker_name == "dhan" and broker_api_key:
                if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Dhan API key must be in format: 'client_id:::api_key'",
                        }
                    ), 400

            elif broker_name == "zebu" and broker_api_key:
                if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "Zebu API key must be in format: 'userid:::client_id' (e.g. Z56004:::Z56004_U)",
                        }
                    ), 400

            elif broker_name == "bnr" and broker_api_key:
                if ":::" not in broker_api_key or broker_api_key.count(":::") != 1:
                    return jsonify(
                        {
                            "status": "error",
                            "message": "BNR API key must be configured in format 'userid:::client_id' (e.g. ITC1441:::ITC1441_U). Please update it on the Credentials tab.",
                        }
                    ), 400

        if not username:
            return jsonify({"status": "error", "message": "User session not found"}), 400
        if not broker_name:
            return jsonify(
                {
                    "status": "error",
                    "message": "Could not determine which broker these credentials belong to. "
                    "Provide a redirect_url or broker field.",
                }
            ), 400

        from database.user_db import update_user_broker_credentials

        # Track what was updated
        updated_fields = []
        cred_update = {}

        # Update values in database
        if broker_api_key:
            cred_update["broker_api_key"] = broker_api_key
            updated_fields.append("BROKER_API_KEY")

        if broker_api_secret:
            cred_update["broker_api_secret"] = broker_api_secret
            updated_fields.append("BROKER_API_SECRET")

        if broker_api_key_market:
            cred_update["broker_api_key_market"] = broker_api_key_market
            updated_fields.append("BROKER_API_KEY_MARKET")

        if broker_api_secret_market:
            cred_update["broker_api_secret_market"] = broker_api_secret_market
            updated_fields.append("BROKER_API_SECRET_MARKET")

        if redirect_url:
            cred_update["redirect_url"] = redirect_url
            updated_fields.append("REDIRECT_URL")

        if cred_update:
            success = update_user_broker_credentials(username, broker_name, cred_update)
            if not success:
                return jsonify({"status": "error", "message": "Failed to update credentials in database"}), 500

        # Read current .env content for server-level configs
        content, error = read_env_file()
        if error:
            return jsonify(
                {"status": "error", "message": f"Failed to read .env file: {error}"}
            ), 500

        env_updated_fields = []

        # Check for ngrok_allow by key presence, not value truthiness
        # This allows setting it to FALSE (disabling ngrok)
        if has_ngrok_key:
            ngrok_allow_str = str(ngrok_allow).strip().upper()
            ngrok_value = "TRUE" if ngrok_allow_str == "TRUE" else "FALSE"
            content = update_env_value(content, "NGROK_ALLOW", ngrok_value)
            env_updated_fields.append("NGROK_ALLOW")

        if host_server:
            # Validate host_server URL format
            if not re.match(r"^https?://.+", host_server):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Invalid HOST_SERVER format. Must start with http:// or https://",
                    }
                ), 400
            content = update_env_value(content, "HOST_SERVER", host_server)
            env_updated_fields.append("HOST_SERVER")

        if websocket_url:
            # Validate websocket_url format
            if not re.match(r"^wss?://.+", websocket_url):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Invalid WEBSOCKET_URL format. Must start with ws:// or wss://",
                    }
                ), 400
            content = update_env_value(content, "WEBSOCKET_URL", websocket_url)
            env_updated_fields.append("WEBSOCKET_URL")

        if env_updated_fields:
            # Write updated content back to .env
            env_path = get_env_path()
            try:
                # Use UTF-8 encoding for cross-platform compatibility
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.info(f"Updated server config in .env: {', '.join(env_updated_fields)}")
            except Exception as e:
                logger.exception(f"Error writing .env file: {e}")
                return jsonify({"status": "error", "message": f"Failed to write .env file: {e}"}), 500

        all_updated = updated_fields + env_updated_fields
        if not all_updated:
            return jsonify({"status": "error", "message": "No credentials or configuration provided to update"}), 400

        return jsonify(
            {
                "status": "success",
                "message": f"Credentials updated successfully. Updated: {', '.join(all_updated)}",
                "updated_fields": all_updated,
                "restart_required": len(env_updated_fields) > 0,
            }
        )

    except Exception as e:
        logger.exception(f"Error updating broker credentials: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broker_credentials_bp.route("/capabilities", methods=["GET"])
@check_session_validity
def get_capabilities():
    """Return broker capabilities (supported exchanges, type, features) from cached plugin.json."""
    from flask import session

    from utils.plugin_loader import get_broker_capabilities

    broker = session.get("broker")
    if not broker:
        return jsonify({"status": "error", "message": "No broker in session"}), 400

    capabilities = get_broker_capabilities(broker)
    if not capabilities:
        # Fallback for brokers without plugin.json capabilities
        return jsonify(
            {
                "status": "success",
                "data": {
                    "broker_name": broker,
                    "broker_type": "IN_stock",
                    "supported_exchanges": [],
                    "leverage_config": False,
                },
            }
        )

    return jsonify({"status": "success", "data": capabilities})


@broker_credentials_bp.route("/connections", methods=["GET"])
@check_session_validity
def get_broker_connections():
    """List every broker this user has set up, merging three sources so the
    Broker Management page reflects reality rather than only live logins:

      - configured: has saved credentials in UserBrokerCredential (may or
        may not be logged in right now)
      - connected:  has a live, non-revoked AuthBrokerSession token
      - is_data_broker: is the current Auth-row broker (powers quotes)

    A broker the user has saved credentials for but never logged into still
    appears (configured=True, connected=False) so it's actionable. Purely
    additive/read-only - never modifies any of the three tables."""
    from flask import session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.auth_db import get_auth_token_dbquery, list_broker_sessions
    from database.user_db import list_user_broker_credentials

    data_broker_obj = get_auth_token_dbquery(username)
    data_broker = data_broker_obj.broker if data_broker_obj else None

    # Brokers with a live/persisted session token (keyed by broker name).
    sessions_by_broker = {
        s["broker"]: s for s in list_broker_sessions(username)
    }
    # Brokers the user has saved credentials for (may not be logged in).
    configured_brokers = set(list_user_broker_credentials(username))

    # The data broker may be connected (Auth valid) without a matching
    # AuthBrokerSession row yet - include it so it never silently vanishes.
    all_brokers = set(sessions_by_broker) | configured_brokers
    if data_broker:
        all_brokers.add(data_broker)

    connections = []
    for broker in sorted(all_brokers):
        s = sessions_by_broker.get(broker)
        is_data_broker = broker == data_broker
        # "connected" = has a valid live token: either a non-revoked
        # AuthBrokerSession, or it's the current data broker (Auth valid).
        connected = bool(s and not s["is_revoked"]) or is_data_broker
        connections.append(
            {
                "broker": broker,
                "configured": broker in configured_brokers,
                "connected": connected,
                "connected_at": s["connected_at"] if s else None,
                "is_data_broker": is_data_broker,
            }
        )

    return jsonify({"status": "success", "connections": connections})


@broker_credentials_bp.route("/connections/<broker>/disconnect", methods=["POST"])
@check_session_validity
def disconnect_broker_connection(broker):
    """Disconnect a single connected broker without touching any other
    connected broker or the current data broker's Auth row (unless the
    broker being disconnected IS the data broker, in which case only that
    Auth row is revoked too - the user still keeps their other connected
    brokers)."""
    from flask import session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.auth_db import decrypt_token, get_auth_token_dbquery, revoke_broker_session, upsert_auth

    success = revoke_broker_session(username, broker)

    data_broker_obj = get_auth_token_dbquery(username)
    if data_broker_obj and data_broker_obj.broker == broker:
        # This broker is also the current data broker - revoke its Auth
        # row too (existing revoke mechanism), so quote/order code paths
        # that read Auth correctly see "no valid session" rather than a
        # stale token for a broker the user just disconnected. upsert_auth
        # re-encrypts internally, so decrypt first to avoid double-encrypting.
        upsert_auth(
            username,
            decrypt_token(data_broker_obj.auth),
            broker,
            feed_token=decrypt_token(data_broker_obj.feed_token) if data_broker_obj.feed_token else None,
            user_id=data_broker_obj.user_id,
            revoke=True,
        )

    # NOTE: this used to also set session["logged_in"] = False here to stop
    # brlogin.py's stale-session shortcut (session["broker"] == broker, no
    # auth params -> "already logged in, redirect to dashboard") from
    # bouncing a re-click of "Connect" straight back to the dashboard
    # instead of letting real re-auth happen. But session["logged_in"] is
    # the ENTIRE APP's login flag, not a broker-specific one -- every
    # session-authenticated route (utils/session.py::is_session_valid,
    # check_session_validity, app.py's before_request) reads it, and all of
    # them respond to False by clearing the whole Flask session and
    # bouncing the user to /login. So disconnecting a broker was logging
    # the user out of Max Algos entirely, not just unlinking the broker.
    #
    # The actual fix now lives in blueprints/brlogin.py's callback route:
    # it verifies the broker's Auth row is still valid in the DB before
    # taking the "already logged in" shortcut, instead of trusting the
    # session["broker"] scalar (which is what goes stale after a disconnect
    # this route already handles correctly above by revoking the DB row).
    # Nothing needs to be mutated on the Flask session here at all.

    if not success:
        return jsonify({"status": "error", "message": f"Not connected to {broker}"}), 404
    return jsonify({"status": "success", "message": f"Disconnected {broker}"})


@broker_credentials_bp.route("/connections/clear-all", methods=["POST"])
@check_session_validity
def clear_all_broker_connections():
    """Force-clear every broker session for this user - both the
    AuthBrokerSession rows (all connected brokers) and the Auth row (the
    data broker). Used as a recovery button when a session gets into a
    corrupted/stuck state and normal reconnect stops working.

    Deliberately does NOT touch UserBrokerCredential (saved API
    keys/secrets) - only session/token state is cleared, so the user can
    immediately reconnect each broker from Broker Management without
    re-entering credentials from scratch."""
    from flask import session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.auth_db import (
        decrypt_token,
        get_auth_token_dbquery,
        list_broker_sessions,
        revoke_broker_session,
        upsert_auth,
    )

    cleared = []

    # Revoke every AuthBrokerSession row.
    for s in list_broker_sessions(username):
        broker = s["broker"]
        if not s["is_revoked"]:
            revoke_broker_session(username, broker)
        cleared.append(broker)

    # Revoke the data broker's Auth row too (same decrypt-then-revoke
    # pattern as disconnect_broker_connection, to avoid double-encrypting).
    data_broker_obj = get_auth_token_dbquery(username)
    if data_broker_obj:
        upsert_auth(
            username,
            decrypt_token(data_broker_obj.auth),
            data_broker_obj.broker,
            feed_token=decrypt_token(data_broker_obj.feed_token) if data_broker_obj.feed_token else None,
            user_id=data_broker_obj.user_id,
            revoke=True,
        )
        if data_broker_obj.broker not in cleared:
            cleared.append(data_broker_obj.broker)

    # Also clear the session's own broker pointer so app.py's os.getenv
    # patch doesn't keep resolving credentials for a now-revoked broker.
    session.pop("broker", None)
    session.pop("logged_in", None)

    logger.info(f"Cleared all broker sessions for {username}: {cleared}")

    return jsonify(
        {
            "status": "success",
            "message": f"Cleared {len(cleared)} broker session(s). Saved credentials are untouched - reconnect from Broker Management.",
            "cleared": cleared,
        }
    )


@broker_credentials_bp.route("/connections/<broker>/set-data-broker", methods=["POST"])
@check_session_validity
def set_data_broker(broker):
    """Make `broker` the user's data broker (the one powering quotes,
    option chain, strategy builder LTP, etc. via the existing Auth-table
    code path). Requires `broker` to already be connected (a valid
    AuthBrokerSession row) - this action re-points Auth at that broker's
    already-stored token rather than requiring a fresh OAuth/TOTP login."""
    from flask import session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.auth_db import get_broker_session, upsert_auth

    broker_session = get_broker_session(username, broker)
    if not broker_session:
        return jsonify(
            {"status": "error", "message": f"{broker} is not connected - connect it first"}
        ), 400

    auth_token, feed_token, user_id = broker_session
    upsert_auth(username, auth_token, broker, feed_token=feed_token, user_id=user_id)
    session["broker"] = broker

    # Trigger master contract sync for the newly promoted data broker.
    # When a second broker is connected it skips the master contract step
    # (it runs only for the data broker). Switching the data broker here
    # without re-running the master contract download leaves the symtoken
    # table pointing at the OLD broker's instruments, causing the option
    # chain to return 404 "No strikes found".
    try:
        from threading import Thread
        from utils.auth_utils import (
            async_master_contract_download,
            load_existing_master_contract,
            should_download_master_contract,
            init_broker_status,
        )
        from database.master_contract_status_db import init_broker_status

        init_broker_status(broker)
        should_dl, reason = should_download_master_contract(broker)
        logger.info(
            f"set_data_broker: master contract check for {broker}: "
            f"should_download={should_dl}, reason={reason}"
        )
        if should_dl:
            # username scopes the completion toast to whoever switched their
            # data broker (see utils/socket_scope.py).
            thread = Thread(
                target=async_master_contract_download, args=(broker, username), daemon=True
            )
        else:
            thread = Thread(
                target=load_existing_master_contract, args=(broker,), daemon=True
            )
        thread.start()
    except Exception as mc_err:
        logger.warning(f"set_data_broker: master contract sync failed for {broker}: {mc_err}")

    return jsonify({"status": "success", "message": f"{broker} is now your data broker"})


# ---------------------------------------------------------------------------
# Broker auto session refresh (opt-in, angel/fivepaisa/motilal only)
# See docs/plans/2026-07-16-broker-auto-session-refresh-plan.md.
# ---------------------------------------------------------------------------


@broker_credentials_bp.route("/auto-refresh/status", methods=["GET"])
@check_session_validity
def auto_refresh_status():
    """Return per-broker auto-refresh status (enabled + last outcome). Never
    returns any secret material. Query param: ?broker=<name>."""
    from flask import request, session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    broker = request.args.get("broker")
    if not broker:
        return jsonify({"status": "error", "message": "broker query param required"}), 400

    from database.user_db import get_broker_auto_refresh_status

    return jsonify({"status": "success", "data": get_broker_auto_refresh_status(username, broker)})


@broker_credentials_bp.route("/auto-refresh/enable", methods=["POST"])
@check_session_validity
def auto_refresh_enable():
    """Enable auto session refresh for a supported broker. Requires an
    explicit acknowledgement of the security tradeoff, the broker TOTP seed,
    and the broker-specific login params (clientcode/userid, pin, dob)."""
    from flask import request, session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.user_db import enable_broker_auto_refresh, is_auto_refresh_supported

    data = request.get_json(silent=True) or {}
    broker = data.get("broker")
    if not broker or not is_auto_refresh_supported(broker):
        return jsonify(
            {"status": "error", "message": "Auto-refresh is not available for this broker"}
        ), 400

    # Explicit acknowledgement gate -- the frontend warning modal sets this;
    # without it the request is refused, so auto-refresh can never be
    # enabled without the user having seen the security warning.
    if not data.get("acknowledged"):
        return jsonify(
            {"status": "error", "message": "Security acknowledgement is required to enable this"}
        ), 400

    totp_seed = (data.get("totp_seed") or "").strip()
    if not totp_seed:
        return jsonify({"status": "error", "message": "Broker TOTP seed is required"}), 400

    # Validate the seed actually generates a code before storing it, so a
    # typo is caught now rather than silently at 8:30 tomorrow morning.
    try:
        import pyotp

        pyotp.TOTP(totp_seed).now()
    except Exception:
        return jsonify({"status": "error", "message": "Invalid TOTP seed"}), 400

    login_params = {}
    for field in ("clientcode", "userid", "pin", "dob"):
        val = (data.get(field) or "").strip()
        if val:
            login_params[field] = val

    ok = enable_broker_auto_refresh(username, broker, totp_seed, login_params)
    if not ok:
        return jsonify(
            {
                "status": "error",
                "message": "Could not enable auto-refresh (save broker credentials first)",
            }
        ), 400

    logger.info(f"Auto-refresh enabled by {username} for {broker}")
    return jsonify({"status": "success", "message": f"Auto-refresh enabled for {broker}"})


@broker_credentials_bp.route("/auto-refresh/disable", methods=["POST"])
@check_session_validity
def auto_refresh_disable():
    """Disable auto-refresh and clear the stored seed/params."""
    from flask import request, session

    username = session.get("user") if isinstance(session.get("user"), str) else None
    if not username:
        return jsonify({"status": "error", "message": "User session not found"}), 400

    from database.user_db import disable_broker_auto_refresh

    data = request.get_json(silent=True) or {}
    broker = data.get("broker")
    if not broker:
        return jsonify({"status": "error", "message": "broker is required"}), 400

    disable_broker_auto_refresh(username, broker)
    logger.info(f"Auto-refresh disabled by {username} for {broker}")
    return jsonify({"status": "success", "message": f"Auto-refresh disabled for {broker}"})

