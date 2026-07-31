"""Broker auto session refresh.

See docs/plans/2026-07-16-broker-auto-session-refresh-plan.md.

Indian broker tokens die daily (~3 AM IST) and normally require a fresh
interactive login with 2FA. For the small set of brokers whose login is a
direct clientcode+PIN+TOTP call (no OAuth browser redirect) -- angel,
fivepaisa, motilal -- a user can opt in to storing their broker TOTP seed
(encrypted) so this service can generate the code and re-authenticate
unattended each morning.

SECURITY: this reads decrypted broker 2FA seeds. It is background-only,
never exposes secret material, and on any failure marks the session as
needing manual re-login and notifies the user rather than silently leaving
a stale/false-connected state.
"""

import pyotp

from database.user_db import (
    get_broker_auto_refresh_secrets,
    is_auto_refresh_supported,
    list_enabled_auto_refresh_credentials,
    record_auto_refresh_result,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def _call_broker_auth(broker_name: str, totp_code: str, params: dict):
    """Invoke a broker's authenticate_broker() with the param shape it
    expects. Returns (auth_token, feed_token, error) uniformly -- brokers
    that don't return a feed token yield None for it. Raises for an
    unsupported broker so a config drift is loud, not silent."""
    import importlib

    auth_mod = importlib.import_module(f"broker.{broker_name}.api.auth_api")

    if broker_name in ("angel", "fivepaisa"):
        # authenticate_broker(clientcode, broker_pin, totp_code)
        clientcode = params.get("clientcode", "")
        pin = params.get("pin", "")
        result = auth_mod.authenticate_broker(clientcode, pin, totp_code)
    elif broker_name == "motilal":
        # authenticate_broker(userid, broker_pin, totp_code, date_of_birth)
        userid = params.get("userid", "")
        pin = params.get("pin", "")
        dob = params.get("dob", "")
        result = auth_mod.authenticate_broker(userid, pin, totp_code, dob)
    else:
        raise ValueError(f"Broker {broker_name} is not auto-refresh-capable")

    # Normalize the 2- or 3-tuple return shapes into (auth_token, feed, error).
    if len(result) == 3:
        auth_token, feed_token, error = result
    else:
        auth_token, error = result
        feed_token = None
    return auth_token, feed_token, error


def refresh_one(username: str, broker_name: str) -> dict:
    """Re-authenticate one (user, broker) unattended using their stored
    seed + params. Persists the fresh token via upsert_auth on success.
    Never raises -- returns a result dict and records the outcome. On
    failure, notifies the user to log in manually (fail-safe: we never
    pretend the session is fine)."""
    result = {"username": username, "broker": broker_name, "success": False, "error": None}

    if not is_auto_refresh_supported(broker_name):
        result["error"] = "broker not auto-refresh-capable"
        return result

    secrets = get_broker_auto_refresh_secrets(username, broker_name)
    if not secrets or not secrets.get("totp_seed"):
        result["error"] = "auto-refresh not enabled or seed missing"
        return result

    try:
        from utils.broker_context import broker_credential_context

        totp_code = pyotp.TOTP(secrets["totp_seed"]).now()
        params = secrets.get("login_params", {}) or {}

        # Scope BROKER_API_KEY/SECRET resolution (read via os.getenv inside
        # the broker's authenticate_broker) to THIS user's stored creds for
        # the duration of the call -- same mechanism blueprints/brlogin.py
        # uses, so the background job authenticates as the right user.
        with broker_credential_context(username, broker_name):
            auth_token, feed_token, error = _call_broker_auth(broker_name, totp_code, params)

        if error or not auth_token:
            result["error"] = str(error) if error else "broker returned no auth token"
            _handle_failure(username, broker_name, result["error"])
            return result

        from database.auth_db import upsert_auth

        upsert_auth(username, auth_token, broker_name, feed_token=feed_token)
        record_auto_refresh_result(username, broker_name, success=True)
        result["success"] = True
        logger.info(f"Auto-refresh succeeded for {username}/{broker_name}")
        return result

    except Exception as e:
        logger.exception(f"Auto-refresh raised for {username}/{broker_name}: {e}")
        result["error"] = str(e)
        _handle_failure(username, broker_name, str(e))
        return result


def _handle_failure(username: str, broker_name: str, reason: str) -> None:
    """Record the failure and surface it to the user so they log in
    manually. Fail-safe: the user must never assume they're connected when
    they aren't. The durable signal is the recorded 'failed' status (shown
    on the Broker Management page); the SocketIO emit is a live nudge for a
    user who happens to be online. Telegram is intentionally NOT used here
    -- that service is fully async and this runs in a sync scheduler
    thread; the recorded status + in-app event cover the requirement
    without a fragile sync/async bridge."""
    try:
        record_auto_refresh_result(username, broker_name, success=False)
    except Exception:
        logger.exception("Failed to record auto-refresh failure status")

    try:
        from extensions import socketio

        socketio.emit(
            "broker_auto_refresh_failed",
            {
                "broker": broker_name,
                "message": (
                    f"Automatic re-login for {broker_name} failed -- please connect it "
                    "manually. Reason: " + (reason or "unknown")
                ),
            },
            room=f"user_{username}",
        )
    except Exception:
        logger.exception("Failed to emit auto-refresh failure event")


def refresh_all_enabled() -> dict:
    """Refresh every (user, broker) with auto-refresh enabled. Intended to be
    the scheduled morning job's entry point. Returns a summary."""
    rows = list_enabled_auto_refresh_credentials()
    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "results": []}
    for row in rows:
        username = row["username"]
        broker_name = row["broker_name"]
        if not is_auto_refresh_supported(broker_name):
            continue  # defensive: skip anything no longer supported
        summary["attempted"] += 1
        res = refresh_one(username, broker_name)
        summary["succeeded" if res["success"] else "failed"] += 1
        summary["results"].append(res)

    if summary["attempted"]:
        logger.info(
            f"Auto-refresh run complete: {summary['succeeded']}/{summary['attempted']} succeeded"
        )
    return summary
