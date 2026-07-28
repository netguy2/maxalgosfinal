"""
Dynamic Per-User Broker Credentials Patch

Intercepts os.getenv and os.environ access for broker credential keys
(BROKER_API_KEY, BROKER_API_SECRET, BROKER_API_KEY_MARKET, BROKER_API_SECRET_MARKET, REDIRECT_URL)
and dynamically resolves them from database credentials based on:
1. Active broker_credential_context(username, broker) override (ContextVar)
2. Flask session/request context (if running inside a Flask app)

This allows both the Flask application and background processes (like the standalone WebSocket Proxy)
to access user-specific broker credentials seamlessly.
"""

import os

_installed = False
_orig_getenv = os.getenv
_orig_getitem = os.environ.__class__.__getitem__


def _custom_getenv(key, default=None):
    if key in (
        "BROKER_API_KEY",
        "BROKER_API_SECRET",
        "BROKER_API_KEY_MARKET",
        "BROKER_API_SECRET_MARKET",
        "REDIRECT_URL",
    ):
        try:
            # 1. Check for active broker_credential_context override (highest priority)
            from utils.broker_context import get_active_broker_override

            override = get_active_broker_override()
            if override:
                override_username, override_broker = override
                from database.user_db import get_user_broker_credentials

                db_creds = get_user_broker_credentials(override_username, override_broker)
                if db_creds and db_creds.get(key.lower()):
                    return db_creds[key.lower()]

            # 2. Check for Flask request context if available
            username = None
            try:
                from flask import has_request_context, request, session

                if has_request_context():
                    if "user" in session and session["user"]:
                        if isinstance(session["user"], dict):
                            username = session["user"].get("username")
                        else:
                            username = session["user"]
                    else:
                        api_key = None
                        if request.is_json:
                            try:
                                api_key = request.json.get("apikey")
                            except Exception:
                                pass
                        if not api_key:
                            api_key = (
                                request.headers.get("X-API-KEY")
                                or request.args.get("apikey")
                                or request.form.get("apikey")
                            )

                        if api_key:
                            from database.auth_db import verify_api_key

                            username = verify_api_key(api_key)
            except ImportError:
                pass

            if username:
                broker_name = None
                try:
                    from flask import has_request_context, session
                    if has_request_context() and session.get("broker"):
                        broker_name = session["broker"]
                except Exception:
                    pass

                if not broker_name:
                    from database.auth_db import get_auth_token_dbquery

                    auth_obj = get_auth_token_dbquery(username)
                    if auth_obj:
                        broker_name = auth_obj.broker

                if broker_name:
                    from database.user_db import get_user_broker_credentials

                    db_creds = get_user_broker_credentials(username, broker_name)
                    if db_creds and db_creds.get(key.lower()):
                        return db_creds[key.lower()]
        except Exception:
            pass

    try:
        return _orig_getitem(os.environ, key)
    except KeyError:
        return default


def _custom_getitem(self, key):
    val = _custom_getenv(key, None)
    if val is not None:
        return val
    return _orig_getitem(self, key)


def install_getenv_patch():
    """Install the dynamic os.getenv and os.environ credential patch once."""
    global _installed
    if not _installed:
        os.getenv = _custom_getenv
        os.environ.__class__.__getitem__ = _custom_getitem
        _installed = True
