"""
React Frontend Serving Blueprint
Serves the pre-built React app for migrated routes.
"""

import mimetypes
from pathlib import Path

from flask import Blueprint, request, send_file, send_from_directory

react_bp = Blueprint("react", __name__)

# Pre-compressed encodings to negotiate, in preference order (best ratio first).
# The Vite build (vite-plugin-compression2) emits <asset>.br and <asset>.gz next
# to each hashed asset; CI commits them with frontend/dist/. Serving these lets
# no-nginx (laptop) installs ship compressed bytes with zero per-request CPU,
# and nginx-fronted servers pass the Content-Encoding through untouched.
_PRECOMPRESSED_ENCODINGS = ((".br", "br"), (".gz", "gzip"))

# Path to the pre-built React frontend
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def is_react_frontend_available():
    """Check if the React frontend build exists."""
    index_html = FRONTEND_DIST / "index.html"
    return FRONTEND_DIST.exists() and index_html.exists()


def serve_react_app():
    """Serve the React app's index.html."""
    if not is_react_frontend_available():
        return (
            """
        <html>
        <head><title>Max Algos - Frontend Not Available</title></head>
        <body style="font-family: system-ui; padding: 40px; max-width: 600px; margin: 0 auto;">
            <h1>Frontend Not Built</h1>
            <p>The React frontend is not available. To build it:</p>
            <pre style="background: #f4f4f4; padding: 16px; border-radius: 8px;">
cd frontend
npm install
npm run build</pre>
            <p>Or use the pre-built version from the repository.</p>
        </body>
        </html>
        """,
            503,
        )

    index_path = FRONTEND_DIST / "index.html"
    response = send_file(index_path, mimetype="text/html")
    # index.html references content-hashed asset URLs, so a stale shell
    # points at chunk files that no longer exist after a deploy -- the
    # user then gets stuck on "Loading new version" / chunk-load errors
    # because every reload keeps fetching the SAME stale HTML from a cache.
    #
    # "no-cache" alone only asks for revalidation and can still be stored by
    # an intermediary (browser bfcache, Cloudflare/nginx proxy) that then
    # serves it without revalidating. We harden this so no layer -- browser,
    # proxy, or CDN -- ever serves a stale index.html:
    #   - no-store: don't persist the response at all
    #   - no-cache + must-revalidate: if stored anyway, always revalidate
    #   - max-age=0: treat as immediately stale
    #   - Pragma/Expires: legacy HTTP/1.0 proxies that ignore Cache-Control
    # The hashed asset files themselves (/assets/*, served separately) keep
    # their long-lived immutable caching -- only this HTML shell is
    # no-store, so users still get fast asset caching between deploys.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # NOTE: we intentionally do NOT set Clear-Site-Data here. An earlier
    # attempt used `Clear-Site-Data: "storage"` to purge a stuck service
    # worker at the HTTP layer -- but the "storage" directive ALSO wipes
    # localStorage/sessionStorage/IndexedDB for the whole origin on EVERY
    # index.html load (this shell is served no-store, so that's every
    # navigation). That silently reset the user's persisted theme/settings
    # (maxalgos-theme) and auth state (maxalgos-auth) on every refresh --
    # the "my settings don't stick" bug. The stale-service-worker problem
    # is already handled without this collateral damage by the inline
    # kill-switch script in index.html's <head> plus the self-destructing
    # /sw.js, so the header is removed rather than narrowed (there is no
    # Clear-Site-Data value that targets only service workers without also
    # taking localStorage).
    return response


# ============================================================
# Phase 2 Migrated Routes - These are served by React
# ============================================================


# Index/Home route
@react_bp.route("/")
def react_index():
    return serve_react_app()


# Login route
@react_bp.route("/login")
def react_login():
    return serve_react_app()


# Setup route (initial admin setup)
@react_bp.route("/setup")
def react_setup():
    return serve_react_app()


# Self-service registration (multi-tenant SaaS signup)
@react_bp.route("/register")
def react_register():
    return serve_react_app()


# Email verification landing page (also hit directly via the emailed link,
# which redirects here with ?token=... -- see blueprints/auth.py
# verify_email_link())
@react_bp.route("/verify-email")
def react_verify_email():
    return serve_react_app()


# Subscription gate shown after a verified login with no active
# PlatformSubscription (see blueprints/auth.py login()'s
# subscription_required branch)
@react_bp.route("/subscribe")
def react_subscribe():
    return serve_react_app()


# Password reset
@react_bp.route("/reset-password")
def react_reset_password():
    return serve_react_app()


# FAQ page
@react_bp.route("/faq")
def react_faq():
    return serve_react_app()


# Error page
@react_bp.route("/error")
def react_error():
    return serve_react_app()


# Rate limited page
@react_bp.route("/rate-limited")
def react_rate_limited():
    return serve_react_app()


# Broker selection - serve React at /broker (alias for /auth/broker)
@react_bp.route("/broker")
def react_broker():
    return serve_react_app()


# Broker TOTP routes - serve React for broker authentication forms
@react_bp.route("/broker/<broker>/totp")
def react_broker_totp(broker):
    return serve_react_app()


# Broker Management (multi-broker connections list) - client-side route
# only existed in React Router until now. Without this Flask registration,
# any SERVER-SIDE redirect to /broker/manage (e.g. connecting an additional
# broker - see utils/auth_utils.py::handle_auth_success) had no matching
# route and fell through to whatever Flask's default/catch-all handling
# did, which could bounce the browser to /login instead of rendering the
# page. Sidebar/client-side navigation to this URL was unaffected (React
# Router handles that), which is why this only broke the OAuth-redirect
# path, not normal in-app navigation.
@react_bp.route("/broker/manage")
def react_broker_manage():
    return serve_react_app()


# Dashboard
@react_bp.route("/dashboard")
def react_dashboard():
    return serve_react_app()


# Trading pages
@react_bp.route("/positions")
def react_positions():
    return serve_react_app()


@react_bp.route("/orderbook")
def react_orderbook():
    return serve_react_app()


@react_bp.route("/tradebook")
def react_tradebook():
    return serve_react_app()


@react_bp.route("/holdings")
def react_holdings():
    return serve_react_app()


# Search pages
@react_bp.route("/search/token")
def react_search_token():
    return serve_react_app()


@react_bp.route("/search")
def react_search():
    return serve_react_app()


# API Key management - handled by api_key_bp (supports both JSON and React)


# Playground
@react_bp.route("/playground")
def react_playground():
    return serve_react_app()


# ============================================================
# Phase 4 Routes - Charts, WebSocket & Sandbox
# ============================================================


# Trading Platforms overview
@react_bp.route("/platforms")
def react_platforms():
    return serve_react_app()


# TradingView webhook configuration
@react_bp.route("/tradingview")
def react_tradingview():
    return serve_react_app()


# GoCharting webhook configuration
@react_bp.route("/gocharting")
def react_gocharting():
    return serve_react_app()


# P&L Tracker with real-time chart
@react_bp.route("/pnl-tracker")
def react_pnltracker():
    return serve_react_app()


# Tools overview (Option Chain, IV Chart, etc.)
@react_bp.route("/tools")
def react_tools():
    return serve_react_app()


# IV Chart for options implied volatility
@react_bp.route("/ivchart")
def react_ivchart():
    return serve_react_app()


# OI Tracker for open interest analysis
@react_bp.route("/oitracker")
def react_oitracker():
    return serve_react_app()


# Max Pain analysis
@react_bp.route("/maxpain")
def react_maxpain():
    return serve_react_app()


# Straddle Chart - Dynamic ATM Straddle analysis
@react_bp.route("/straddle")
def react_straddle():
    return serve_react_app()


# Vol Surface - 3D Implied Volatility surface
@react_bp.route("/volsurface")
def react_volsurface():
    return serve_react_app()


# GEX Dashboard - Gamma Exposure analysis
@react_bp.route("/gex")
def react_gex():
    return serve_react_app()


# IV Smile - Implied Volatility smile curve
@react_bp.route("/ivsmile")
def react_ivsmile():
    return serve_react_app()


# OI Profile - Open Interest Profile with futures candles
@react_bp.route("/oiprofile")
def react_oiprofile():
    return serve_react_app()


# WebSocket market data test page
@react_bp.route("/websocket/test")
def react_websocket_test():
    return serve_react_app()


# WebSocket depth test pages (broker dependent depth levels)
@react_bp.route("/websocket/test/20")
def react_websocket_test_20():
    return serve_react_app()


@react_bp.route("/websocket/test/30")
def react_websocket_test_30():
    return serve_react_app()


@react_bp.route("/websocket/test/50")
def react_websocket_test_50():
    return serve_react_app()


# Sandbox configuration
@react_bp.route("/sandbox")
def react_sandbox():
    return serve_react_app()


# Sandbox P&L history
@react_bp.route("/sandbox/mypnl")
def react_sandbox_mypnl():
    return serve_react_app()


# API Request Analyzer
@react_bp.route("/analyzer")
def react_analyzer():
    return serve_react_app()


# ============================================================
# Phase 6 Routes - Strategy & Automation
# ============================================================


# Webhook Strategies
# Note: Using strict_slashes=False to handle both /strategy and /strategy/
@react_bp.route("/strategy", strict_slashes=False)
def react_strategy_index():
    return serve_react_app()


@react_bp.route("/strategy/new", strict_slashes=False)
def react_strategy_new():
    return serve_react_app()


@react_bp.route("/strategy/<int:strategy_id>", strict_slashes=False)
def react_strategy_view(strategy_id):
    return serve_react_app()


@react_bp.route("/strategy/<int:strategy_id>/configure", strict_slashes=False)
def react_strategy_configure(strategy_id):
    return serve_react_app()


# Python Strategies
# Note: Using strict_slashes=False to handle both /python and /python/
@react_bp.route("/python", strict_slashes=False)
def react_python_index():
    return serve_react_app()


@react_bp.route("/python/new", strict_slashes=False)
def react_python_new():
    return serve_react_app()


@react_bp.route("/python/<strategy_id>/edit", strict_slashes=False)
def react_python_edit(strategy_id):
    return serve_react_app()


@react_bp.route("/python/<strategy_id>/logs", strict_slashes=False)
def react_python_logs(strategy_id):
    return serve_react_app()


# Chartink Strategies
# Note: Using strict_slashes=False to handle both /chartink and /chartink/
@react_bp.route("/chartink", strict_slashes=False)
def react_chartink_index():
    return serve_react_app()


@react_bp.route("/chartink/new", strict_slashes=False)
def react_chartink_new():
    return serve_react_app()


@react_bp.route("/chartink/<int:strategy_id>", strict_slashes=False)
def react_chartink_view(strategy_id):
    return serve_react_app()


@react_bp.route("/chartink/<int:strategy_id>/configure", strict_slashes=False)
def react_chartink_configure(strategy_id):
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Admin & Settings
# ============================================================


# Admin Dashboard
@react_bp.route("/admin", strict_slashes=False)
def react_admin_index():
    return serve_react_app()


# Admin - Freeze Quantities
@react_bp.route("/admin/freeze", strict_slashes=False)
def react_admin_freeze():
    return serve_react_app()


# Admin - Market Holidays
@react_bp.route("/admin/holidays", strict_slashes=False)
def react_admin_holidays():
    return serve_react_app()


# Admin - Market Timings
@react_bp.route("/admin/timings", strict_slashes=False)
def react_admin_timings():
    return serve_react_app()


# Admin - User Management
@react_bp.route("/admin/users", strict_slashes=False)
def react_admin_users():
    return serve_react_app()


# Admin - Payment Settings
@react_bp.route("/admin/payments", strict_slashes=False)
def react_admin_payments():
    return serve_react_app()


# Admin - Email Settings (SMTP)
@react_bp.route("/admin/email", strict_slashes=False)
def react_admin_email():
    return serve_react_app()


# Leverage Configuration (Crypto)
@react_bp.route("/leverage", strict_slashes=False)
def react_leverage():
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Monitoring Dashboards
# ============================================================


# Security Dashboard
@react_bp.route("/security", strict_slashes=False)
def react_security():
    return serve_react_app()


# Traffic Dashboard
@react_bp.route("/traffic", strict_slashes=False)
def react_traffic():
    return serve_react_app()


# Latency Dashboard
@react_bp.route("/latency", strict_slashes=False)
def react_latency():
    return serve_react_app()


# ============================================================
# Phase 7 Routes - Settings & Action Center
# ============================================================


# Logs Index
@react_bp.route("/logs", strict_slashes=False)
def react_logs():
    return serve_react_app()


# Live Logs
@react_bp.route("/logs/live", strict_slashes=False)
def react_logs_live():
    return serve_react_app()


# Sandbox Logs (Analyzer)
@react_bp.route("/logs/sandbox", strict_slashes=False)
def react_logs_sandbox():
    return serve_react_app()


# Security Logs
@react_bp.route("/logs/security", strict_slashes=False)
def react_logs_security():
    return serve_react_app()


# Traffic Monitor
@react_bp.route("/logs/traffic", strict_slashes=False)
def react_logs_traffic():
    return serve_react_app()


# Latency Monitor
@react_bp.route("/logs/latency", strict_slashes=False)
def react_logs_latency():
    return serve_react_app()


# Profile Settings
@react_bp.route("/profile", strict_slashes=False)
def react_profile():
    return serve_react_app()


# Action Center (Semi-automated trading)
@react_bp.route("/action-center", strict_slashes=False)
def react_action_center():
    return serve_react_app()


# Historify (Historical Data Management)
@react_bp.route("/historify", strict_slashes=False)
def react_historify():
    return serve_react_app()


# ============================================================
# Flow Routes - Visual Workflow Automation
# ============================================================


# Flow Dashboard (Workflow List)
@react_bp.route("/flow", strict_slashes=False)
def react_flow_index():
    return serve_react_app()


# Flow Editor (Visual Workflow Builder)
@react_bp.route("/flow/editor/<int:workflow_id>", strict_slashes=False)
def react_flow_editor(workflow_id):
    return serve_react_app()


# ============================================================
# Static Assets - Always served for React app
# ============================================================


@react_bp.route("/assets/<path:filename>")
def serve_assets(filename):
    """Serve static assets with long cache headers.

    Negotiates pre-compressed variants: if the client advertises ``br``/``gzip``
    and a ``<filename>.br``/``.gz`` exists, serve that with the matching
    ``Content-Encoding`` and the original file's ``Content-Type``. Otherwise
    fall back to the raw asset (i.e. worst case == previous behavior). All paths
    go through ``send_from_directory`` so traversal protection is preserved.
    """
    assets_dir = FRONTEND_DIST / "assets"
    if not assets_dir.exists():
        return "Assets not found", 404

    accept_encoding = request.headers.get("Accept-Encoding", "")
    response = None
    for ext, encoding in _PRECOMPRESSED_ENCODINGS:
        if encoding in accept_encoding and (assets_dir / (filename + ext)).is_file():
            response = send_from_directory(assets_dir, filename + ext)
            response.headers["Content-Encoding"] = encoding
            # Type must reflect the ORIGINAL asset, not the .br/.gz wrapper.
            content_type = mimetypes.guess_type(filename)[0]
            if content_type:
                response.headers["Content-Type"] = content_type
            # Caches must key on encoding so a br copy is never sent to a
            # client that only speaks gzip (or none).
            response.headers["Vary"] = "Accept-Encoding"
            break
    if response is None:
        response = send_from_directory(assets_dir, filename)

    # Cache assets for 1 year — safe because filenames are content-hashed, so a
    # new build produces new URLs and users never need to clear their cache.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@react_bp.route("/favicon.ico")
def serve_favicon():
    """Serve favicon."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "favicon.ico")


@react_bp.route("/logo.png")
def serve_logo():
    """Serve logo."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "logo.png")


@react_bp.route("/sw.js")
def serve_service_worker():
    """Serve the self-destructing service worker (frontend/public/sw.js ->
    dist/sw.js). MUST be an explicit route: without it, /sw.js falls through
    to the SPA HTML catch-all and returns index.html, so a browser holding a
    stale service worker from an older build never receives valid JS to
    replace it and stays stuck serving cached chunks forever.

    Served with no-store so the browser's periodic SW update check always
    re-fetches this file from the network (never a cache), runs the
    unregister/purge, and frees the tab. JS content-type is required or the
    browser refuses to treat it as a service worker.
    """
    sw_path = FRONTEND_DIST / "sw.js"
    if not sw_path.exists():
        return "Not found", 404
    response = send_from_directory(FRONTEND_DIST, "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@react_bp.route("/max-icon.png")
def serve_max_icon():
    """Serve max icon (used by login page, sidebar, navbar)."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "max-icon.png")


@react_bp.route("/maxalgos.png")
def serve_maxalgos_logo():
    """Serve full maxalgos logo."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "maxalgos.png")


@react_bp.route("/apple-touch-icon.png")
def serve_apple_touch_icon():
    """Serve Apple touch icon."""
    if not is_react_frontend_available():
        return "Not found", 404
    return send_from_directory(FRONTEND_DIST, "apple-touch-icon.png")


@react_bp.route("/fonts/<path:filename>")
def serve_fonts(filename):
    """Serve the self-hosted brand fonts (Geist variable woff2) from React
    dist. Long-lived immutable caching -- the variable font files are stable
    and their content only changes if the font itself is swapped, in which
    case the filename would change too."""
    fonts_dir = FRONTEND_DIST / "fonts"
    if not fonts_dir.exists():
        return "Fonts not found", 404
    response = send_from_directory(fonts_dir, filename)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@react_bp.route("/images/<path:filename>")
def serve_images(filename):
    """Serve images from React dist."""
    images_dir = FRONTEND_DIST / "images"
    if not images_dir.exists():
        return "Images not found", 404
    return send_from_directory(images_dir, filename)


@react_bp.route("/sounds/<path:filename>")
def serve_sounds(filename):
    """Serve sounds from React dist."""
    sounds_dir = FRONTEND_DIST / "sounds"
    if not sounds_dir.exists():
        return "Sounds not found", 404
    return send_from_directory(sounds_dir, filename)


@react_bp.route("/docs/<path:filename>")
def serve_docs(filename):
    """Serve docs from React dist."""
    docs_dir = FRONTEND_DIST / "docs"
    if not docs_dir.exists():
        return "Docs not found", 404
    return send_from_directory(docs_dir, filename)
