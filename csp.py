# csp.py

import os
from functools import wraps

from flask import current_app, request

# Hardcoded CSP script-src - deliberately NOT read from .env at all (see
# get_csp_config below). Every other CSP directive still supports a CSP_*
# .env override; script-src does not, because a stale or hand-edited .env
# value on any given server previously regressed this exact directive and
# broke the app (missing blob: support) with no code change involved. This
# way every deploy gets the correct, current policy automatically - no
# server-side configuration can override it, ever.
#
# 'self' does NOT implicitly permit blob: script loading - Vite's
# code-split chunks/lazy-loaded routes (e.g. React.lazy() pages like
# BrokerManage.tsx) are served as blob: URLs by the browser and are
# blocked without explicitly listing blob: here, which surfaces as a
# silent JS load failure that can cascade into broken session checks
# and an unexpected bounce to /login.
# https://checkout.razorpay.com is Razorpay's hosted Checkout.js, loaded on
# demand from frontend/src/lib/razorpay.ts whenever a payment/subscription
# flow opens. Without it here, the browser silently blocks the <script> tag
# (script.onerror fires) and the checkout promise rejects before the modal
# ever appears -- which surfaced as every payment attempt showing a generic
# "Payment was cancelled" with zero server-side errors, since the request
# never left the browser in the first place. checkout.js itself then loads
# a second script from https://cdn.razorpay.com (its risk-detection
# bundle) -- both origins are required, confirmed via the actual browser
# console CSP violations, not guessed.
HARDCODED_SCRIPT_SRC = (
    "'self' 'unsafe-inline' blob: https://cdn.socket.io https://static.cloudflareinsights.com "
    "https://checkout.razorpay.com https://cdn.razorpay.com"
)

# connect-src and frame-src are ALSO hardcoded here, for the same reason as
# script-src above: every server's .env (from .sample.env) already sets
# CSP_CONNECT_SRC/CSP_FRAME_SRC explicitly, so a Python default passed to
# os.getenv(..., default) never actually takes effect on any real
# deployment -- the .env value always wins. Adding Razorpay's domains as an
# os.getenv default (as a first attempt at this fix did) silently deployed
# with the OLD unmodified connect-src/frame-src still in effect, which is
# why the fix needs to be unconditional like script-src, not a default.
HARDCODED_CONNECT_SRC = (
    "'self' wss: ws: https://cdn.socket.io https://api.razorpay.com https://lumberjack.razorpay.com "
    "https://www.google-analytics.com https://*.google-analytics.com https://analytics.google.com https://*.analytics.google.com"
)
HARDCODED_FRAME_SRC = "'self' https://api.razorpay.com https://checkout.razorpay.com"


def get_csp_config():
    """
    Get Content Security Policy configuration. Most directives support a
    CSP_* environment variable override; script-src, connect-src, and
    frame-src are hardcoded (see HARDCODED_SCRIPT_SRC / HARDCODED_CONNECT_SRC
    / HARDCODED_FRAME_SRC above) and always use the shipped value regardless
    of .env. Returns a dictionary with CSP directives.
    """
    csp_config = {}

    # Check if CSP is enabled
    csp_enabled = os.getenv("CSP_ENABLED", "TRUE").upper() == "TRUE"

    if not csp_enabled:
        return None

    # Default source directive
    default_src = os.getenv("CSP_DEFAULT_SRC", "'self'")
    if default_src:
        csp_config["default-src"] = default_src

    # Script source directive - intentionally NOT overridable via .env
    # (see HARDCODED_SCRIPT_SRC above).
    csp_config["script-src"] = HARDCODED_SCRIPT_SRC

    # Style source directive
    style_src = os.getenv("CSP_STYLE_SRC", "'self' 'unsafe-inline'")
    if style_src:
        csp_config["style-src"] = style_src

    # Image source directive
    img_src = os.getenv("CSP_IMG_SRC", "'self' data: blob:")
    if img_src:
        csp_config["img-src"] = img_src

    # Connect source directive - intentionally NOT overridable via .env
    # (see HARDCODED_CONNECT_SRC above).
    csp_config["connect-src"] = HARDCODED_CONNECT_SRC

    # Font source directive
    font_src = os.getenv("CSP_FONT_SRC", "'self'")
    if font_src:
        csp_config["font-src"] = font_src

    # Object source directive
    object_src = os.getenv("CSP_OBJECT_SRC", "'none'")
    if object_src:
        csp_config["object-src"] = object_src

    # Media source directive
    media_src = os.getenv("CSP_MEDIA_SRC", "'self'")
    if media_src:
        csp_config["media-src"] = media_src

    # Frame source directive - intentionally NOT overridable via .env
    # (see HARDCODED_FRAME_SRC above).
    csp_config["frame-src"] = HARDCODED_FRAME_SRC

    # Child source directive (deprecated but included for compatibility)
    child_src = os.getenv("CSP_CHILD_SRC")
    if child_src:
        csp_config["child-src"] = child_src

    # Form action directive
    form_action = os.getenv("CSP_FORM_ACTION", "'self'")
    if form_action:
        csp_config["form-action"] = form_action

    # Base URI directive
    base_uri = os.getenv("CSP_BASE_URI", "'self'")
    if base_uri:
        csp_config["base-uri"] = base_uri

    # Frame ancestors directive (clickjacking protection)
    frame_ancestors = os.getenv("CSP_FRAME_ANCESTORS", "'self'")
    if frame_ancestors:
        csp_config["frame-ancestors"] = frame_ancestors

    # Additional custom directives
    upgrade_insecure_requests = (
        os.getenv("CSP_UPGRADE_INSECURE_REQUESTS", "FALSE").upper() == "TRUE"
    )
    if upgrade_insecure_requests:
        csp_config["upgrade-insecure-requests"] = ""

    # Report URI for CSP violations
    report_uri = os.getenv("CSP_REPORT_URI")
    if report_uri:
        csp_config["report-uri"] = report_uri

    # Report-To directive for CSP violations reporting
    report_to = os.getenv("CSP_REPORT_TO")
    if report_to:
        csp_config["report-to"] = report_to

    return csp_config


def build_csp_header(csp_config):
    """
    Build the Content Security Policy header value from the configuration.
    """
    if not csp_config:
        return None

    directives = []
    for directive, value in csp_config.items():
        if value:
            directives.append(f"{directive} {value}")
        else:
            directives.append(directive)

    return "; ".join(directives)


def get_security_headers():
    """
    Get additional security headers configuration from environment variables.
    """
    headers = {}

    # X-Frame-Options: prevent clickjacking
    headers["X-Frame-Options"] = "DENY"

    # X-Content-Type-Options: prevent MIME-type sniffing
    headers["X-Content-Type-Options"] = "nosniff"

    # X-XSS-Protection: legacy XSS protection for older browsers
    headers["X-XSS-Protection"] = "1; mode=block"

    # Referrer Policy
    referrer_policy = os.getenv("REFERRER_POLICY", "strict-origin-when-cross-origin")
    if referrer_policy:
        headers["Referrer-Policy"] = referrer_policy

    # Permissions Policy
    permissions_policy = os.getenv(
        "PERMISSIONS_POLICY",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), screen-wake-lock=(), web-share=()",
    )
    if permissions_policy:
        headers["Permissions-Policy"] = permissions_policy

    return headers


def apply_csp_middleware(app):
    """
    Apply Content Security Policy and other security headers middleware to the Flask application.
    """

    @app.after_request
    def add_security_headers(response):
        # Add CSP header
        csp_config = get_csp_config()
        if csp_config:
            csp_header = build_csp_header(csp_config)
            if csp_header:
                # Use Content-Security-Policy-Report-Only for testing if configured
                header_type = "Content-Security-Policy"
                if os.getenv("CSP_REPORT_ONLY", "FALSE").upper() == "TRUE":
                    header_type = "Content-Security-Policy-Report-Only"

                # Respect a CSP header already set by the route handler.
                # The OAuth /authorize consent page sets a per-response
                # CSP that includes the registered redirect_uri origin
                # in form-action so the browser allows the OAuth code
                # redirect chain. Overwriting that here would block
                # the legitimate flow.
                if header_type not in response.headers:
                    response.headers[header_type] = csp_header

        # Add other security headers
        security_headers = get_security_headers()
        for header_name, header_value in security_headers.items():
            response.headers[header_name] = header_value

        return response
