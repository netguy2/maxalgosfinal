"""Razorpay-backed payment routes.

Two flows share the same Order -> Checkout -> verify-signature pattern:
  1. Setup activation fee: paid ONCE per install, before the single admin
     account exists. See create_admin_account() in blueprints/core.py.
  2. Marketplace subscription checkout: paid for priced listings only; free
     listings keep using strategy_bp's direct subscribe route.

SECURITY: every route that changes state (creates the admin account,
activates a subscription) verifies the Razorpay payment signature
server-side BEFORE the side effect runs. The frontend's Checkout success
callback is never trusted on its own -- a forged callback could otherwise
fake a payment. See services/razorpay_service.py for the verification calls.
"""

import os

from flask import Blueprint, jsonify, request, session

from database.payment_db import (
    create_payment_record,
    get_payment_by_order_id,
    list_recent_payments,
    mark_payment_captured,
    mark_payment_failed,
)
from database.settings_db import (
    get_payment_settings,
    get_razorpay_credentials,
    set_payment_settings,
    set_razorpay_credentials,
)
from database.user_db import (
    PlatformSubscription,
    find_user_by_exact_username,
    find_user_by_username,
)
from database.user_db import (
    db_session as user_db_session,
)
from limiter import limiter
from services.razorpay_service import (
    RazorpayNotConfigured,
    create_order,
    create_subscription,
    get_key_id,
    invalidate_client_cache,
    verify_payment_signature,
    verify_webhook_signature,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")
# Setup is unauthenticated (no account exists yet) -- tighter limit than the
# general API rate to blunt abuse of a public, no-session endpoint.
SETUP_RATE_LIMIT = "10 per minute"

payments_bp = Blueprint("payments_bp", __name__, url_prefix="/payments")


def _require_admin():
    """Returns (username, is_admin). Reuses admin_bp's session-lookup helper
    rather than duplicating it."""
    from blueprints.admin import _get_current_user_admin_status

    return _get_current_user_admin_status()


# ---------------------------------------------------------------------------
# Public config (safe to expose: key_id only, never the secret)
# ---------------------------------------------------------------------------


@payments_bp.route("/config", methods=["GET"])
def get_config():
    settings = get_payment_settings()
    try:
        key_id = get_key_id() if settings["payments_enabled"] else None
    except RazorpayNotConfigured:
        # Gateway not configured server-side -- report disabled rather than
        # erroring, so the frontend can fall back to the unpaid path.
        key_id = None
        settings = {**settings, "payments_enabled": False}

    return jsonify({
        "status": "success",
        "data": {
            "payments_enabled": bool(key_id) and settings["payments_enabled"],
            "key_id": key_id,
            "currency": "INR",
            "setup_fee_paise": settings["setup_fee_paise"],
            "subscription_configured": bool(settings.get("platform_subscription_plan_id")),
        },
    })


# ---------------------------------------------------------------------------
# Setup activation fee (no session -- runs before the account exists)
# ---------------------------------------------------------------------------


@payments_bp.route("/setup/create-order", methods=["POST"])
@limiter.limit(SETUP_RATE_LIMIT)
def setup_create_order():
    if find_user_by_username() is not None:
        return jsonify({"status": "error", "message": "Setup has already been completed"}), 409

    settings = get_payment_settings()
    if not settings["payments_enabled"]:
        return jsonify({
            "status": "error",
            "message": "Payments are disabled for this install",
            "code": "payments_disabled",
        }), 400

    try:
        order = create_order(
            amount_paise=settings["setup_fee_paise"],
            receipt="setup-activation",
            notes={"purpose": "setup"},
        )
    except RazorpayNotConfigured as e:
        logger.error(f"Razorpay not configured: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503
    except Exception as e:
        logger.exception(f"Error creating Razorpay order for setup: {e}")
        return jsonify({"status": "error", "message": "Failed to create payment order"}), 500

    create_payment_record(
        purpose="setup",
        razorpay_order_id=order["id"],
        amount_paise=order["amount"],
    )

    return jsonify({
        "status": "success",
        "data": {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": get_key_id(),
        },
    })


@payments_bp.route("/setup/verify", methods=["POST"])
@limiter.limit(SETUP_RATE_LIMIT)
def setup_verify():
    data = request.get_json(silent=True) or {}
    order_id = data.get("razorpay_order_id", "")
    payment_id = data.get("razorpay_payment_id", "")
    signature = data.get("razorpay_signature", "")
    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")

    if not all([order_id, payment_id, signature, username, email, password]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    payment = get_payment_by_order_id(order_id)
    if not payment or payment.purpose != "setup":
        return jsonify({"status": "error", "message": "Payment record not found"}), 404
    if payment.status == "captured":
        return jsonify({"status": "error", "message": "This payment has already been used"}), 409

    if not verify_payment_signature(order_id, payment_id, signature):
        return jsonify({"status": "error", "message": "Payment verification failed"}), 400

    # Payment is verified -- now create the account. If account creation
    # fails after a verified payment, the Payment row still gets marked
    # captured (the charge is real) but no account exists; this edge case is
    # surfaced via the admin payments list for manual follow-up.
    mark_payment_captured(order_id, payment_id)

    from blueprints.core import create_admin_account

    user, error_message = create_admin_account(username, email, password)
    if not user:
        logger.error(f"Account creation failed after verified setup payment {order_id}: {error_message}")
        return jsonify({"status": "error", "message": error_message}), 400

    mark_payment_captured(order_id, payment_id, user_id=username)

    try:
        from datetime import datetime

        from utils.email_utils import send_payment_confirmation_email

        send_payment_confirmation_email(
            recipient_email=email,
            user_name=username,
            purpose="setup",
            item_label="Max Algos Account Activation",
            amount_paise=payment.amount_paise,
            razorpay_payment_id=payment_id,
            paid_at_str=datetime.now().strftime("%d %b %Y, %H:%M"),
        )
    except Exception as email_err:
        # Never fail account creation over a confirmation email -- the
        # account exists and the payment is captured either way.
        logger.warning(f"Could not send setup payment confirmation email for {username}: {email_err}")

    return jsonify({"status": "success", "message": "Account created successfully"})


# ---------------------------------------------------------------------------
# Marketplace subscription checkout (priced listings only)
# ---------------------------------------------------------------------------


@payments_bp.route("/marketplace/<int:strategy_id>/create-order", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def marketplace_create_order(strategy_id):
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    from database.strategy_db import MarketplaceListing
    from database.strategy_db import db_session as strategy_db_session

    listing = strategy_db_session.query(MarketplaceListing).filter_by(
        strategy_id=strategy_id
    ).first()
    if not listing:
        return jsonify({"status": "error", "message": "Marketplace listing not found"}), 404
    if not listing.price or listing.price <= 0:
        return jsonify({
            "status": "error",
            "message": "This listing is free -- use the direct subscribe endpoint",
        }), 400

    amount_paise = int(listing.price) * 100

    try:
        order = create_order(
            amount_paise=amount_paise,
            receipt=f"sub-{strategy_id}-{user_id}",
            notes={"purpose": "subscription", "strategy_id": str(strategy_id), "user_id": user_id},
        )
    except RazorpayNotConfigured as e:
        logger.error(f"Razorpay not configured: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503
    except Exception as e:
        logger.exception(f"Error creating Razorpay order for subscription: {e}")
        return jsonify({"status": "error", "message": "Failed to create payment order"}), 500

    create_payment_record(
        purpose="subscription",
        razorpay_order_id=order["id"],
        amount_paise=order["amount"],
        user_id=user_id,
        strategy_id=strategy_id,
    )

    return jsonify({
        "status": "success",
        "data": {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": get_key_id(),
        },
    })


@payments_bp.route("/marketplace/verify", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def marketplace_verify():
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    data = request.get_json(silent=True) or {}
    order_id = data.get("razorpay_order_id", "")
    payment_id = data.get("razorpay_payment_id", "")
    signature = data.get("razorpay_signature", "")

    if not all([order_id, payment_id, signature]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    payment = get_payment_by_order_id(order_id)
    if not payment or payment.purpose != "subscription":
        return jsonify({"status": "error", "message": "Payment record not found"}), 404
    if payment.user_id != user_id:
        return jsonify({"status": "error", "message": "Payment does not belong to this user"}), 403
    if payment.status == "captured":
        return jsonify({"status": "error", "message": "This payment has already been used"}), 409

    if not verify_payment_signature(order_id, payment_id, signature):
        return jsonify({"status": "error", "message": "Payment verification failed"}), 400

    from blueprints.strategy import activate_subscription
    from database.strategy_db import db_session as strategy_db_session

    try:
        result = activate_subscription(user_id, payment.strategy_id)
    except Exception as e:
        logger.exception(f"Error activating subscription after verified payment {order_id}: {e}")
        strategy_db_session.rollback()
        return jsonify({"status": "error", "message": "Failed to activate subscription"}), 500

    if result.get("status") != "success":
        http_status = result.pop("http_status", 400)
        return jsonify(result), http_status

    mark_payment_captured(
        order_id, payment_id, user_id=user_id, subscription_id=result.get("subscription_id")
    )

    try:
        from datetime import datetime

        from database.strategy_db import Strategy
        from database.strategy_db import db_session as strategy_db_session
        from utils.email_utils import send_payment_confirmation_email

        buyer = find_user_by_exact_username(user_id)
        strategy = strategy_db_session.query(Strategy).filter_by(id=payment.strategy_id).first()
        if buyer and buyer.email:
            send_payment_confirmation_email(
                recipient_email=buyer.email,
                user_name=buyer.username or user_id,
                purpose="marketplace",
                item_label=strategy.name if strategy else "Marketplace strategy",
                amount_paise=payment.amount_paise,
                razorpay_payment_id=payment_id,
                paid_at_str=datetime.now().strftime("%d %b %Y, %H:%M"),
            )
    except Exception as email_err:
        logger.warning(f"Could not send marketplace payment confirmation email for {user_id}: {email_err}")

    return jsonify(result)


# ---------------------------------------------------------------------------
# Platform subscription (whole-app recurring billing, multi-tenant SaaS gate)
# ---------------------------------------------------------------------------


@payments_bp.route("/subscription/create", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def subscription_create():
    """Start a recurring Razorpay Subscription for the logged-in user.
    Called from the /subscribe screen shown when login succeeds but no
    active PlatformSubscription exists (see blueprints/auth.py login's
    subscription_required branch)."""
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    from database.user_db import get_active_platform_subscription

    if get_active_platform_subscription(username) is not None:
        return jsonify({"status": "error", "message": "You already have an active subscription"}), 409

    settings = get_payment_settings()
    plan_id = settings.get("platform_subscription_plan_id")
    if not settings["payments_enabled"] or not plan_id:
        return jsonify({
            "status": "error",
            "message": "Subscriptions are not configured for this install",
            "code": "subscription_not_configured",
        }), 400

    try:
        subscription = create_subscription(plan_id=plan_id, notes={"user_id": username})
    except RazorpayNotConfigured as e:
        logger.error(f"Razorpay not configured: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503
    except Exception as e:
        logger.exception(f"Error creating Razorpay subscription for {username}: {e}")
        return jsonify({"status": "error", "message": "Failed to create subscription"}), 500

    record = PlatformSubscription(
        user_id=username,
        razorpay_subscription_id=subscription["id"],
        plan="default",
        status="created",
    )
    user_db_session.add(record)
    user_db_session.commit()

    return jsonify({
        "status": "success",
        "data": {
            "subscription_id": subscription["id"],
            "key_id": get_key_id(),
        },
    })


@payments_bp.route("/subscription/verify", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def subscription_verify():
    """Verify the Razorpay Checkout success callback for a subscription
    payment. Mirrors setup_verify/marketplace_verify's signature-check
    pattern -- the client-side handler() callback is never trusted alone.

    NOTE: subscription signature verification uses (razorpay_payment_id +
    '|' + razorpay_subscription_id) as the signed payload, unlike one-time
    orders which sign (order_id + '|' + payment_id). Handled by
    verify_payment_signature via the subscription_id kwarg.
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    data = request.get_json(silent=True) or {}
    subscription_id = data.get("razorpay_subscription_id", "")
    payment_id = data.get("razorpay_payment_id", "")
    signature = data.get("razorpay_signature", "")

    if not all([subscription_id, payment_id, signature]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    record = PlatformSubscription.query.filter_by(
        razorpay_subscription_id=subscription_id
    ).first()
    if not record or record.user_id != username:
        return jsonify({"status": "error", "message": "Subscription record not found"}), 404

    if not verify_payment_signature(
        subscription_id, payment_id, signature, is_subscription=True
    ):
        return jsonify({"status": "error", "message": "Payment verification failed"}), 400

    # The webhook (subscription.activated/charged) is the authoritative
    # status source and will also flip this to "active" -- setting it here
    # too means the UI doesn't have to wait for webhook delivery to unblock
    # the user.
    was_already_active = record.status == "active"
    record.status = "active"
    user_db_session.commit()

    # Open the gate immediately -- check_session_validity caches the
    # blocked/allowed decision for 30s; without this the user who just paid
    # would keep getting 403s until the TTL expired.
    from utils.session import invalidate_subscription_cache

    invalidate_subscription_cache(username)

    # Confirmation email sent ONLY from this route (the user-driven
    # checkout completion), not from the webhook's
    # _activate_platform_subscription -- that also fires on every
    # subscription.charged renewal event with the same "active" status, so
    # emailing from both would double-send on first activation. was_already
    # _active guards a double /subscription/verify POST from the same
    # checkout (e.g. a retried request) from re-sending the receipt.
    if not was_already_active:
        try:
            from datetime import datetime

            from utils.email_utils import send_payment_confirmation_email

            buyer = find_user_by_exact_username(username)
            if buyer and buyer.email:
                send_payment_confirmation_email(
                    recipient_email=buyer.email,
                    user_name=buyer.username or username,
                    purpose="subscription",
                    item_label="Max Algos Platform Subscription",
                    razorpay_payment_id=payment_id,
                    paid_at_str=datetime.now().strftime("%d %b %Y, %H:%M"),
                )
        except Exception as email_err:
            logger.warning(f"Could not send subscription confirmation email for {username}: {email_err}")

    return jsonify({"status": "success", "message": "Subscription activated"})


@payments_bp.route("/subscription/status", methods=["GET"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def subscription_status():
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    from database.user_db import get_active_platform_subscription

    sub = get_active_platform_subscription(username)
    return jsonify({
        "status": "success",
        "data": {
            "has_active_subscription": sub is not None,
            "plan": sub.plan if sub else None,
            "subscription_status": sub.status if sub else None,
            "current_period_end": sub.current_period_end.isoformat()
            if sub and sub.current_period_end else None,
        },
    })


def _activate_platform_subscription(razorpay_subscription_id: str, new_status: str) -> None:
    """Webhook-driven status transition, keyed on the Razorpay subscription
    id (not order id -- subscriptions use their own webhook events, distinct
    from the one-time-order payment.captured/failed events above)."""
    record = PlatformSubscription.query.filter_by(
        razorpay_subscription_id=razorpay_subscription_id
    ).first()
    if not record:
        logger.warning(f"Webhook for unknown subscription {razorpay_subscription_id}")
        return
    record.status = new_status
    user_db_session.commit()

    # Refresh the gate decision for this user right away (covers both
    # activation -- unblock without waiting out the 30s TTL -- and
    # cancellation -- start blocking promptly).
    from utils.session import invalidate_subscription_cache

    invalidate_subscription_cache(record.user_id)

    logger.info(f"Platform subscription {razorpay_subscription_id} -> {new_status}")


# ---------------------------------------------------------------------------
# Webhook (server-to-server; defense-in-depth reconciliation)
# ---------------------------------------------------------------------------


@payments_bp.route("/webhook", methods=["POST"])
def webhook():
    """Razorpay server webhook. CSRF-exempt (registered in app.py alongside
    the other external webhook routes) because Razorpay's server cannot
    carry a CSRF token -- the HMAC signature check below IS this route's
    authentication and MUST pass before any event is processed."""
    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = request.get_data()

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected Razorpay webhook with invalid signature")
        return jsonify({"status": "error", "message": "Invalid signature"}), 400

    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")

    # Recurring-subscription events carry a "subscription" entity instead of
    # (or alongside) "payment" -- handle these first since they don't have
    # an order_id to key off of.
    if event.startswith("subscription."):
        sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        razorpay_subscription_id = sub_entity.get("id", "")
        if not razorpay_subscription_id:
            return jsonify({"status": "success"})

        if event in ("subscription.activated", "subscription.charged"):
            _activate_platform_subscription(razorpay_subscription_id, "active")
        elif event == "subscription.pending":
            _activate_platform_subscription(razorpay_subscription_id, "past_due")
        elif event in ("subscription.cancelled", "subscription.completed", "subscription.expired"):
            _activate_platform_subscription(razorpay_subscription_id, "cancelled")

        return jsonify({"status": "success"})

    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = entity.get("order_id", "")
    payment_id = entity.get("id", "")

    if not order_id:
        return jsonify({"status": "success"})  # nothing to reconcile

    if event == "payment.captured":
        payment = get_payment_by_order_id(order_id)
        if payment and payment.status != "captured":
            # The verify-callback route is the primary path and already runs
            # the account-creation / subscription-activation side effect;
            # this webhook only reconciles Payment.status for the case where
            # the browser closed before the verify callback completed. It
            # deliberately does NOT re-run the side effect here to avoid a
            # race with the verify route -- that gap is a known follow-up
            # (see plan's non-goals).
            mark_payment_captured(order_id, payment_id)
    elif event == "payment.failed":
        mark_payment_failed(order_id)

    return jsonify({"status": "success"})


# ---------------------------------------------------------------------------
# Admin: pricing config + payment log
# ---------------------------------------------------------------------------


@payments_bp.route("/admin/settings", methods=["GET"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def admin_get_settings():
    _username, is_admin = _require_admin()
    if not is_admin:
        return jsonify({"status": "error", "message": "Admin access required"}), 403
    return jsonify({"status": "success", "data": get_payment_settings()})


@payments_bp.route("/admin/settings", methods=["POST"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def admin_set_settings():
    _username, is_admin = _require_admin()
    if not is_admin:
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    try:
        set_payment_settings(
            payments_enabled=data.get("payments_enabled"),
            setup_fee_paise=data.get("setup_fee_paise"),
            default_subscription_price_paise=data.get("default_subscription_price_paise"),
            platform_subscription_plan_id=data.get("platform_subscription_plan_id"),
        )
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    return jsonify({"status": "success", "data": get_payment_settings()})


@payments_bp.route("/admin/credentials", methods=["GET"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def admin_get_credentials():
    """Return Razorpay credential status (admin only). key_secret and
    webhook_secret are NEVER sent to the client -- only booleans indicating
    whether each is set, same masking convention as SMTP's
    smtp_password_set (see blueprints/admin.py api_smtp_get)."""
    _username, is_admin = _require_admin()
    if not is_admin:
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    creds = get_razorpay_credentials()
    return jsonify({
        "status": "success",
        "data": {
            "key_id": creds.get("key_id"),
            "key_secret_set": bool(creds.get("key_secret")),
            "webhook_secret_set": bool(creds.get("webhook_secret")),
        },
    })


@payments_bp.route("/admin/credentials", methods=["POST"])
@check_session_validity
@limiter.limit("10 per minute")
def admin_set_credentials():
    """Update Razorpay credentials (admin only)."""
    username, is_admin = _require_admin()
    if not is_admin:
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    data = request.get_json(silent=True) or {}
    key_id = (data.get("key_id") or "").strip() or None
    key_secret = (data.get("key_secret") or "").strip()
    webhook_secret = (data.get("webhook_secret") or "").strip()

    set_razorpay_credentials(
        key_id=key_id,
        key_secret=key_secret or None,
        webhook_secret=webhook_secret or None,
    )
    # The cached razorpay.Client (if any) was built from the OLD
    # credentials -- drop it so the very next payment/order/subscription
    # call picks up whatever the admin just saved, instead of silently
    # continuing to use a stale or now-revoked key until process restart.
    invalidate_client_cache()

    logger.info(f"Razorpay credentials updated by admin: {username}")
    return jsonify({"status": "success", "message": "Razorpay credentials updated successfully"})


@payments_bp.route("/admin/list", methods=["GET"])
@check_session_validity
@limiter.limit(API_RATE_LIMIT)
def admin_list_payments():
    _username, is_admin = _require_admin()
    if not is_admin:
        return jsonify({"status": "error", "message": "Admin access required"}), 403

    payments = list_recent_payments(limit=100)
    return jsonify({
        "status": "success",
        "data": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "purpose": p.purpose,
                "razorpay_order_id": p.razorpay_order_id,
                "razorpay_payment_id": p.razorpay_payment_id,
                "amount_paise": p.amount_paise,
                "currency": p.currency,
                "status": p.status,
                "strategy_id": p.strategy_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "verified_at": p.verified_at.isoformat() if p.verified_at else None,
            }
            for p in payments
        ],
    })
