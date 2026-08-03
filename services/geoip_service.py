"""GeoIP (MaxMind GeoLite2) lookup and database refresh service.

Session Intelligence: resolves a client IP to city/region/country/ASN for
the Active Sessions dashboard (blueprints/auth.py's register_session() call
site, frontend/src/pages/ActiveSessions.tsx). Credentials are admin-
configured (database/settings_db.py's geoip_enabled/maxmind_account_id/
maxmind_license_key_encrypted columns), not .env -- see PaymentSettings.tsx
for the equivalent Razorpay pattern this follows.

Two separate concerns, kept in one module since they're small and always
used together:
  1. Downloading/refreshing the GeoLite2-City.mmdb + GeoLite2-ASN.mmdb files
     from MaxMind (monthly, since MaxMind republishes GeoLite2 databases on
     that cadence) -- see download_databases() / start_refresh_scheduler().
  2. Looking up an IP against the local .mmdb files -- see lookup(). Pure
     local file read via the `geoip2`/`maxminddb` libraries, no per-request
     network call, so login latency is unaffected and no user IP is ever
     sent to a third party at request time.
"""

import ipaddress
import os
import tarfile
import tempfile
import threading

import geoip2.database
import geoip2.errors
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database.settings_db import get_geoip_settings
from utils.logging import get_logger

logger = get_logger(__name__)

GEOIP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "geoip")
CITY_DB_PATH = os.path.join(GEOIP_DIR, "GeoLite2-City.mmdb")
ASN_DB_PATH = os.path.join(GEOIP_DIR, "GeoLite2-ASN.mmdb")

MAXMIND_DOWNLOAD_URL = "https://download.maxmind.com/geoip/databases/{edition}/download"

# Re-opening geoip2.database.Reader on every login would re-mmap the file
# each call; these are small (few dozen MB), safe to keep open for the
# process lifetime, and geoip2.database.Reader is safe for concurrent reads
# from multiple threads (it wraps a read-only mmap). Guarded by a lock only
# around the swap-on-refresh, not around individual lookups.
_city_reader: geoip2.database.Reader | None = None
_asn_reader: geoip2.database.Reader | None = None
_reader_lock = threading.Lock()

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def _open_readers() -> None:
    """(Re)open the local .mmdb readers if the files exist. Called at
    startup and after every successful download_databases()."""
    global _city_reader, _asn_reader
    with _reader_lock:
        old_city, old_asn = _city_reader, _asn_reader
        _city_reader = geoip2.database.Reader(CITY_DB_PATH) if os.path.exists(CITY_DB_PATH) else None
        _asn_reader = geoip2.database.Reader(ASN_DB_PATH) if os.path.exists(ASN_DB_PATH) else None
        # Close the previous readers only after the new ones are live, so a
        # lookup running concurrently with a refresh never sees a closed
        # reader -- it either gets the old module-level reference (still
        # open) or the new one, never a torn state.
        if old_city is not None:
            old_city.close()
        if old_asn is not None:
            old_asn.close()


def _download_edition(edition: str, account_id: str, license_key: str, dest_path: str) -> bool:
    """Download and extract one GeoLite2 edition's .mmdb from MaxMind into
    dest_path. Returns True on success. MaxMind ships the .mmdb inside a
    dated tar.gz (e.g. GeoLite2-City_20260101/GeoLite2-City.mmdb), so this
    extracts just that one file rather than keeping the whole archive."""
    url = MAXMIND_DOWNLOAD_URL.format(edition=edition)
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.get(url, params={"suffix": "tar.gz"}, auth=(account_id, license_key))
            resp.raise_for_status()

        os.makedirs(GEOIP_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                member = next(
                    (m for m in tar.getmembers() if m.name.endswith(".mmdb")), None
                )
                if member is None:
                    logger.error(f"GeoIP: no .mmdb file found in downloaded {edition} archive")
                    return False
                extracted = tar.extractfile(member)
                if extracted is None:
                    logger.error(f"GeoIP: could not extract .mmdb member from {edition} archive")
                    return False
                # Write to a temp file in the target directory first, then
                # atomically replace -- a reader mid-open must never see a
                # half-written .mmdb.
                tmp_dest = dest_path + ".tmp"
                with open(tmp_dest, "wb") as out:
                    out.write(extracted.read())
                os.replace(tmp_dest, dest_path)
        finally:
            os.unlink(tmp_path)

        logger.info(f"GeoIP: downloaded and installed {edition} -> {dest_path}")
        return True
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error("GeoIP: MaxMind rejected the account ID / license key (401)")
        else:
            logger.error(f"GeoIP: download failed for {edition}: HTTP {e.response.status_code}")
        return False
    except Exception:
        logger.exception(f"GeoIP: download failed for {edition}")
        return False


def download_databases() -> bool:
    """Download both GeoLite2-City and GeoLite2-ASN using the admin-
    configured MaxMind credentials. Returns True only if both succeeded.
    No-ops (returns False) if GeoIP is disabled or credentials are unset --
    this is the state a fresh install starts in, so it's an expected,
    silent path, not an error."""
    settings = get_geoip_settings()
    if not settings["enabled"]:
        logger.debug("GeoIP: disabled, skipping database refresh")
        return False
    if not settings["account_id"] or not settings["license_key"]:
        logger.warning("GeoIP: enabled but MaxMind credentials are not configured, skipping refresh")
        return False

    city_ok = _download_edition(
        "GeoLite2-City", settings["account_id"], settings["license_key"], CITY_DB_PATH
    )
    asn_ok = _download_edition(
        "GeoLite2-ASN", settings["account_id"], settings["license_key"], ASN_DB_PATH
    )
    if city_ok or asn_ok:
        _open_readers()
    return city_ok and asn_ok


def start_refresh_scheduler() -> None:
    """Start a monthly background job that refreshes the GeoLite2 databases.
    MaxMind republishes GeoLite2 weekly, but city/ISP boundaries change
    slowly enough that a monthly refresh is more than sufficient for a
    session-dashboard display -- not used for any security-blocking
    decision, so staleness has no functional impact. Safe to call
    unconditionally at app startup: internally re-checks geoip_enabled on
    every scheduled run, so it's a no-op fire-and-forget when GeoIP is off.
    Idempotent -- a second call is a no-op if already started, same pattern
    as HistorifyScheduler.init().
    """
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            return
        _scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}
        )
        _scheduler.add_job(
            download_databases,
            trigger=CronTrigger(day=1, hour=3, minute=0),  # 1st of each month, 03:00 server time
            id="geoip_database_refresh",
            replace_existing=True,
        )
        _scheduler.start()
        logger.info("GeoIP: monthly database refresh scheduler started")

    # Opportunistic first load: if GeoIP is enabled but the .mmdb files
    # don't exist yet (freshly enabled, never downloaded), fetch them now
    # rather than waiting for the 1st of next month.
    settings = get_geoip_settings()
    if settings["enabled"] and not (os.path.exists(CITY_DB_PATH) and os.path.exists(ASN_DB_PATH)):
        threading.Thread(target=download_databases, daemon=True).start()
    elif os.path.exists(CITY_DB_PATH) or os.path.exists(ASN_DB_PATH):
        _open_readers()


_PRIVATE_IP_RESULT = {
    "country": None,
    "region": None,
    "city": None,
    "isp": None,
    "is_private": True,
}


def lookup(ip: str | None) -> dict:
    """Resolve an IP to {country, region, city, isp, is_private}. Every
    field is None if GeoIP isn't configured/enabled, the .mmdb files
    haven't been downloaded yet, or the IP isn't found in the database
    (private/reserved ranges, which always applies to request.remote_addr
    when trust_proxy_headers is off -- see utils/ip_helper.py). Never
    raises -- this enriches a display field, never something a login should
    fail over.
    """
    empty = {"country": None, "region": None, "city": None, "isp": None, "is_private": False}
    if not ip:
        return empty

    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return _PRIVATE_IP_RESULT
    except ValueError:
        return empty

    result = dict(empty)

    if _city_reader is not None:
        try:
            city_resp = _city_reader.city(ip)
            result["country"] = city_resp.country.name
            result["region"] = city_resp.subdivisions.most_specific.name
            result["city"] = city_resp.city.name
        except geoip2.errors.AddressNotFoundError:
            pass
        except Exception:
            logger.exception(f"GeoIP: city lookup failed for {ip}")

    if _asn_reader is not None:
        try:
            asn_resp = _asn_reader.asn(ip)
            result["isp"] = asn_resp.autonomous_system_organization
        except geoip2.errors.AddressNotFoundError:
            pass
        except Exception:
            logger.exception(f"GeoIP: ASN lookup failed for {ip}")

    return result


# Load any already-downloaded .mmdb files at import time so the very first
# login after an app restart gets GeoIP data without waiting for
# start_refresh_scheduler() (which app.py calls during startup, but import
# order across modules isn't guaranteed relative to the first request).
_open_readers()
