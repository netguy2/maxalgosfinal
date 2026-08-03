"""Session Intelligence: builds the enriched fields stored on ActiveSession
at login time (database/auth_db.py::register_session()'s `intelligence`
dict) from three sources:

  1. Server-side User-Agent parsing (ua-parser) -- browser/OS family+version,
     coarse device type, and (mobile only) device brand.
  2. Server-side GeoIP (services/geoip_service.py, admin-configured MaxMind
     GeoLite2) -- country/region/city/ISP. All None if GeoIP is disabled,
     unconfigured, or the IP is private (see utils/ip_helper.py).
  3. Client hints the frontend sends in the login POST body (see
     frontend/src/utils/deviceIntel.ts) -- screen resolution, timezone,
     language, platform, hardware concurrency/memory, and (Windows only)
     the precise OS version via navigator.userAgentData, which resolves the
     Windows 10 vs 11 ambiguity that User-Agent alone cannot (both report
     "Windows NT 10.0").

Privacy note: deliberately does NOT attempt canvas/WebGL/audio
fingerprinting or any technique aimed at recovering the exact physical
device model (e.g. "Dell Inspiron 3520") -- modern browsers restrict that
information on purpose, and working around the restriction is out of scope
here. The fingerprint below is a hash of coarse, browser-volunteered
signals only, used solely to recognize a RETURNING device for the
is_trusted_device flag -- not a tracking identifier.
"""

import hashlib

from ua_parser import user_agent_parser

from utils.logging import get_logger

logger = get_logger(__name__)

# Client-hint keys accepted from the frontend's login POST body (see
# frontend/src/utils/deviceIntel.ts::collectClientHints()). Anything else in
# that object is ignored -- this is server-authoritative about what it will
# trust the browser to report, not a passthrough.
_CLIENT_HINT_KEYS = (
    "windows_version",
    "screen_resolution",
    "timezone",
    "language",
    "platform",
    "hardware_concurrency",
    "device_memory_gb",
)


def _parse_user_agent(ua: str) -> dict:
    """UA-parser output -> the flat fields ActiveSession stores. Never
    raises -- a malformed/empty UA yields all-None fields rather than
    failing the login."""
    empty = {
        "browser_family": None,
        "browser_version": None,
        "os_family": None,
        "os_version": None,
        "device_type": None,
        "device_brand": None,
    }
    if not ua:
        return empty

    try:
        parsed = user_agent_parser.Parse(ua)
    except Exception:
        logger.exception("Session Intelligence: UA parse failed")
        return empty

    browser = parsed.get("user_agent") or {}
    os_ = parsed.get("os") or {}
    device = parsed.get("device") or {}

    browser_version = ".".join(
        p for p in (browser.get("major"), browser.get("minor"), browser.get("patch")) if p
    ) or None
    os_version = ".".join(p for p in (os_.get("major"), os_.get("minor")) if p) or None

    device_family = (device.get("family") or "").lower()
    if "tablet" in device_family or "ipad" in device_family or "kindle" in device_family:
        device_type = "tablet"
    elif device_family and device_family not in ("other", "spider"):
        # ua-parser's regex set (regexes.yaml) only assigns a specific
        # device.family for recognized phones/tablets -- "Other" is its
        # catch-all for desktop browsers, which have no device entry at all.
        device_type = "phone"
    else:
        device_type = "desktop"

    return {
        "browser_family": browser.get("family") if browser.get("family") != "Other" else None,
        "browser_version": browser_version,
        "os_family": os_.get("family") if os_.get("family") != "Other" else None,
        "os_version": os_version,
        "device_type": device_type,
        "device_brand": device.get("brand"),
    }


def _extract_client_hints(client_hints: dict | None) -> dict:
    """Whitelist + coerce the frontend-reported client hints. Missing/
    malformed values become None rather than raising -- these are display
    fields, a bad value should never fail the login."""
    result = dict.fromkeys(_CLIENT_HINT_KEYS)
    if not client_hints or not isinstance(client_hints, dict):
        return result

    for key in ("windows_version", "screen_resolution", "timezone", "language", "platform"):
        value = client_hints.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()[:50]

    for key in ("hardware_concurrency", "device_memory_gb"):
        value = client_hints.get(key)
        if isinstance(value, int | float) and value > 0:
            result[key] = int(value)

    return result


def compute_fingerprint(
    browser_family: str | None,
    browser_version: str | None,
    os_family: str | None,
    os_version: str | None,
    screen_resolution: str | None,
    timezone: str | None,
    language: str | None,
    platform: str | None,
    hardware_concurrency: int | None,
) -> str:
    """SHA-256 of the coarse, non-identifying signals listed above, joined
    with a fixed delimiter so e.g. ("Chrome", "13") vs ("Chrome1", "3")
    can't collide. Two different physical machines with the same browser
    version, OS, screen size, timezone, language, platform, and core count
    WILL collide -- that's expected and acceptable: this is "does this look
    like a device we've seen for this user," not a unique hardware ID.
    """
    parts = [
        browser_family or "",
        browser_version or "",
        os_family or "",
        os_version or "",
        screen_resolution or "",
        timezone or "",
        language or "",
        platform or "",
        str(hardware_concurrency or ""),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_session_intelligence(
    username: str,
    user_agent: str,
    ip_address: str | None,
    client_hints: dict | None = None,
) -> dict:
    """Build the full `intelligence` dict passed to
    database.auth_db.register_session(). Combines UA parsing, GeoIP, client
    hints, and a fingerprint/trust lookup against this user's prior
    sessions. Never raises -- any sub-step failure degrades to None fields
    rather than blocking login, since none of this is a security gate, only
    a dashboard display + non-blocking new-device signal.
    """
    ua_fields = _parse_user_agent(user_agent)
    hint_fields = _extract_client_hints(client_hints)

    try:
        from services.geoip_service import lookup as geoip_lookup

        geo = geoip_lookup(ip_address)
    except Exception:
        logger.exception("Session Intelligence: GeoIP lookup failed")
        geo = {"country": None, "region": None, "city": None, "isp": None}

    fingerprint_hash = compute_fingerprint(
        browser_family=ua_fields["browser_family"],
        browser_version=ua_fields["browser_version"],
        os_family=ua_fields["os_family"],
        os_version=hint_fields["windows_version"] or ua_fields["os_version"],
        screen_resolution=hint_fields["screen_resolution"],
        timezone=hint_fields["timezone"],
        language=hint_fields["language"],
        platform=hint_fields["platform"],
        hardware_concurrency=hint_fields["hardware_concurrency"],
    )

    is_trusted = False
    try:
        from database.auth_db import ActiveSession

        is_trusted = (
            ActiveSession.query.filter_by(username=username, fingerprint_hash=fingerprint_hash)
            .first()
            is not None
        )
    except Exception:
        logger.exception("Session Intelligence: trusted-device lookup failed")

    return {
        **ua_fields,
        **hint_fields,
        "geo_country": geo.get("country"),
        "geo_region": geo.get("region"),
        "geo_city": geo.get("city"),
        "geo_isp": geo.get("isp"),
        "fingerprint_hash": fingerprint_hash,
        "is_trusted_device": is_trusted,
    }
