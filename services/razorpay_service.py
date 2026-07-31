"""Thin wrapper around the Razorpay Python SDK.

Keeps all Razorpay-specific calls in one place so blueprints/payments.py
stays about request/response plumbing, not gateway details. Follows the
same thin-service pattern as services/funds_service.py.

SECURITY: the secret key and webhook secret are sourced from the DB-backed,
admin-configurable Settings row (database/settings_db.py
get_razorpay_credentials(), encrypted at rest, with an env-var fallback for
installs that still prefer .env-only config) and never returned to any
caller -- routes that need to expose config to the frontend
(GET /payments/config) must hand-pick the public key_id, never call
anything in this module that touches the secret.
"""

import razorpay

from database.settings_db import get_razorpay_credentials
from utils.logging import get_logger

logger = get_logger(__name__)

_client: razorpay.Client | None = None
_client_key_id: str | None = None  # credentials the cached client was built from


class RazorpayNotConfigured(RuntimeError):
    """Raised when Razorpay key_id / key_secret are not configured (neither
    in the admin Payment Settings panel nor via env vars)."""


def get_key_id() -> str:
    """Public key id -- safe to expose to the frontend."""
    key_id = get_razorpay_credentials().get("key_id")
    if not key_id:
        raise RazorpayNotConfigured(
            "Razorpay key_id is not configured. Set it in Admin > Payment Settings "
            "(or RAZORPAY_KEY_ID in .env)."
        )
    return key_id


def invalidate_client_cache() -> None:
    """Drop the cached Razorpay client so the next call rebuilds it from the
    latest credentials. Called by the admin settings-save route whenever
    key_id/key_secret change -- without this, an admin rotating a
    compromised key would have stale credentials in memory until the next
    process restart.
    """
    global _client, _client_key_id
    _client = None
    _client_key_id = None


def get_client() -> razorpay.Client:
    """Lazily build the Razorpay client from the current credentials.

    Raises RazorpayNotConfigured with a clear message rather than silently
    returning a client that will fail on every call -- callers (the payments
    blueprint) turn this into a clean 503 rather than a confusing traceback.

    Rebuilds automatically if the admin has changed key_id since the cached
    client was built (belt-and-suspenders alongside invalidate_client_cache
    -- catches the case where credentials changed via direct DB access or a
    code path that forgot to invalidate).
    """
    global _client, _client_key_id

    creds = get_razorpay_credentials()
    key_id = creds.get("key_id")
    if not key_id:
        raise RazorpayNotConfigured(
            "Razorpay key_id is not configured. Set it in Admin > Payment Settings "
            "(or RAZORPAY_KEY_ID in .env)."
        )

    if _client is not None and _client_key_id == key_id:
        return _client

    key_secret = creds.get("key_secret")
    if not key_secret:
        raise RazorpayNotConfigured(
            "Razorpay key_secret is not configured. Set it in Admin > Payment Settings "
            "(or RAZORPAY_KEY_SECRET in .env)."
        )

    _client = razorpay.Client(auth=(key_id, key_secret))
    _client_key_id = key_id
    return _client


def create_order(amount_paise: int, receipt: str, notes: dict | None = None) -> dict:
    """Create a Razorpay Order for the given amount (in paise).

    Returns the raw Razorpay order dict (contains 'id', 'amount', 'currency',
    'status', etc.) -- the caller persists the relevant fields via
    database/payment_db.create_payment_record.
    """
    client = get_client()
    order = client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
            # auto-capture: funds are captured immediately on successful
            # authorization rather than requiring a separate manual capture
            # step -- correct for a straightforward one-time-charge flow.
            "payment_capture": 1,
        }
    )
    return order


def verify_payment_signature(
    order_or_subscription_id: str, payment_id: str, signature: str, is_subscription: bool = False
) -> bool:
    """Verify the (id, payment_id, signature) triple returned by Razorpay
    Checkout's success callback. MUST pass before any account creation /
    subscription activation -- the frontend callback alone is never trusted
    (a forged callback could otherwise fake a payment).

    One-time orders sign (order_id|payment_id); recurring subscriptions sign
    (payment_id|subscription_id) instead -- same HMAC utility, different
    dict shape, per Razorpay's own SDK/API contract.
    """
    client = get_client()
    try:
        if is_subscription:
            # The SDK's verify_payment_signature() unconditionally reads
            # parameters['razorpay_order_id'] regardless of what keys are
            # passed in -- it is NOT subscription-aware despite accepting
            # an arbitrary dict, and raises a raw KeyError (not
            # SignatureVerificationError) for a subscription payload,
            # which was surfacing as an uncaught 500 on every subscription
            # payment. verify_subscription_payment_signature() is the
            # SDK's actual dedicated method for this (payment_id|subscription_id
            # signing), confirmed against razorpay/utility/utility.py.
            client.utility.verify_subscription_payment_signature(
                {
                    "razorpay_payment_id": payment_id,
                    "razorpay_subscription_id": order_or_subscription_id,
                    "razorpay_signature": signature,
                }
            )
        else:
            client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": order_or_subscription_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                }
            )
        return True
    except razorpay.errors.SignatureVerificationError:
        logger.warning(
            f"Razorpay signature verification failed for {'subscription' if is_subscription else 'order'} "
            f"{order_or_subscription_id}"
        )
        return False


def create_subscription(
    plan_id: str, customer_notify: bool = True, notes: dict | None = None
) -> dict:
    """Create a Razorpay recurring Subscription against an existing Plan
    (the Plan itself, created via the Razorpay dashboard/API, defines the
    amount + billing interval -- see database/settings_db.py
    platform_subscription_plan_id). Returns the raw Razorpay subscription
    dict (contains 'id', 'status', etc.); the caller persists the relevant
    fields via database/user_db.PlatformSubscription.
    """
    client = get_client()
    subscription = client.subscription.create(
        {
            "plan_id": plan_id,
            "customer_notify": 1 if customer_notify else 0,
            # total_count is required by Razorpay for most plan intervals;
            # 120 monthly cycles (10 years) is effectively "until cancelled"
            # without needing an indefinite/unbounded value.
            "total_count": 120,
            "notes": notes or {},
        }
    )
    return subscription


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify the X-Razorpay-Signature header on an incoming webhook POST
    against the configured webhook secret. This check IS the webhook
    route's authentication (it is CSRF-exempt because Razorpay's server
    can't carry a CSRF token) -- do not process any webhook event without
    this passing.
    """
    webhook_secret = get_razorpay_credentials().get("webhook_secret")
    if not webhook_secret:
        logger.warning("Razorpay webhook secret not configured -- rejecting webhook")
        return False

    client = get_client()
    try:
        client.utility.verify_webhook_signature(
            body.decode("utf-8") if isinstance(body, bytes) else body,
            signature,
            webhook_secret,
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        logger.warning("Razorpay webhook signature verification failed")
        return False
