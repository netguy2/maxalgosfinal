import base64
import io

import qrcode
from flask import Blueprint, flash, redirect, request, session, url_for

from blueprints.apikey import generate_api_key
from database.auth_db import upsert_api_key
from database.user_db import User, add_user, find_user_by_username
from utils.logging import get_logger

logger = get_logger(__name__)

core_bp = Blueprint("core_bp", __name__)


def create_admin_account(username: str, email: str, password: str) -> tuple[User | None, str]:
    """Validate + create the single admin account for this install, generate
    its API key and TOTP QR code, and stash the QR/username in the Flask
    session for the post-setup login page to pick up.

    Shared by the direct form-POST /setup route (used by non-interactive /
    Docker installs and, when payments are disabled, the normal browser
    flow) and blueprints/payments.py's paid setup-verify route -- both must
    create the account identically, so this is the single implementation.

    Returns (user_or_none, error_message). error_message is only meaningful
    when user is None.
    """
    if find_user_by_username() is not None:
        return None, "Setup has already been completed for this install"

    from utils.auth_utils import validate_password_strength

    is_valid, error_message = validate_password_strength(password)
    if not is_valid:
        return None, error_message

    user = add_user(username, email, password, is_admin=True)
    if not user:
        logger.error(f"Failed to create admin user {username}")
        return None, "User already exists or an error occurred"

    logger.info(f"New admin user {username} created successfully")

    # Automatically generate and save API key
    api_key = generate_api_key()
    key_id = upsert_api_key(username, api_key)
    if not key_id:
        logger.error(f"Failed to create API key for user {username}")
    else:
        logger.info(f"API key created successfully for user {username}")

    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(user.get_totp_uri())
    qr.make(fit=True)

    img_buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(img_buffer, format="PNG")
    qr_code = base64.b64encode(img_buffer.getvalue()).decode()

    # Store TOTP setup in session temporarily for later access if needed.
    # NB: deliberately not storing the TOTP secret in the Flask session.
    # The default session cookie is signed but NOT encrypted; placing the
    # secret there leaks it to anyone who reads the cookie value (browser
    # extension, HAR export, support-ticket attachment, etc.). The QR
    # code rendered above is sufficient for the user to enrol their
    # authenticator app; the secret then lives only in the encrypted
    # users.totp_secret column.
    session["totp_setup"] = True
    session["username"] = username
    session["qr_code"] = qr_code

    return user, ""


# Note: GET /setup is served by react_bp (React frontend)
# This route only handles POST for form submission from React
@core_bp.route("/setup", methods=["POST"])
def setup():
    if find_user_by_username() is not None:
        return redirect(url_for("auth.login"))

    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]

    user, error_message = create_admin_account(username, email, password)
    if user:
        flash(
            "Account created successfully! Please configure your SMTP credentials in Profile settings for password recovery.",
            "success",
        )
        return redirect(url_for("auth.login"))
    else:
        flash(error_message, "error")
        return redirect(url_for("react.react_setup"))
