# SEBI Algo Trading Circular Compliance Audit

**Date:** 2026-07-16
**Circular:** SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, "Safer participation of retail
investors in Algorithmic trading" (Feb 4, 2025; effective Aug 1, 2025)
**Scope:** Max Algos as "Algo Provider" under the circular's framework (broker is a
separate registered entity the user connects to via `broker/*/api/`).

## Summary

The circular's requirements at the Algo Provider layer, and the platform's current
standing against each:

| # | Requirement | Status | Fix applied this pass |
|---|---|---|---|
| 1 | Unique per-order identifier for audit trail | Was missing | **Fixed** — see below |
| 2 | Vendor-specific API key + static IP whitelisting | Partial | API key: already compliant. Static IP: still open — see Open Items |
| 3 | OAuth-only broker authentication | Non-compliant | Open — see Open Items |
| 4 | Mandatory 2FA for API access | Was missing | **Partially fixed** — opt-in support added; mandatory-by-default is a rollout decision, not shipped |
| 5 | Order-rate threshold → categorize & register with Exchange | Partial | Not addressed this pass — see Open Items |
| 6 | 5-year audit trail retention | Was undocumented | **Fixed** — explicit policy + guard added |

Three items (#1, #4 partial, #6) were pure engineering fixes and are implemented and
tested as of this commit. Three items (#2's IP whitelisting, #3, #5) require either a
broker/Exchange-side registration process, or a product decision with real user-facing
tradeoffs, and are documented below rather than silently implemented.

---

## Fixed this pass

### #1 — Unique per-order identifier

**Before:** Every order sent to Zerodha carried the literal hardcoded string
`"tag": "maxalgos"` — identical for every user, every strategy, every order.
Motilal Oswal sent `"tag": ""` (empty) with `"algoid": ""` (their actual Exchange
algo-ID field, unused). Nubra used `data.get("strategy", "maxalgos")` — better, but
still identical across every order from the same strategy, not unique per order.
Upstox sent the literal API-docs placeholder `"tag": "string"`.

**After:** New shared helper `utils/order_tag.py::generate_order_tag(strategy)`
produces a broker-safe (≤20 chars, sanitized) tag combining the originating strategy
name with a fresh UUID suffix, so no two orders — even from the same strategy in the
same second — ever share a tag. Wired into `broker/zerodha`, `broker/motilal`,
`broker/nubra`, `broker/upstox` mapping modules.

This is the engineering half of the requirement only. It does **not** create a real
Exchange-issued algo ID — Motilal's `algoid` field is deliberately left blank rather
than filled with a fake value (see Open Items — Exchange registration below).

### #4 (partial) — 2FA for API access

**Before:** `User.is_totp_required_for()` recognized three purposes (`login`, `mcp`,
`password_reset`), all opt-in per user. API key generation/regeneration
(`blueprints/apikey.py`) had **no** 2FA gate at all — a logged-in user with 2FA fully
disabled could freely mint or rotate their API key.

**After:** Added a fourth purpose, `totp_required_for_api_key`, following the exact
same opt-in pattern as the other three (defaults `False`, non-breaking). When a user
enables it, `POST /apikey` now requires and verifies a fresh `totp_code` before
issuing a new key, returning 401 otherwise. Backend `/auth/2fa/status` and
`/auth/2fa/configure` extended to read/write the new flag.

**Why this isn't "mandatory 2FA" as the circular actually requires:** making TOTP
mandatory for every user's API key, unconditionally, is a real product decision with a
breaking consequence — any current user who hasn't set up an authenticator app would
be locked out of generating/using their API key until they do. That tradeoff (and its
rollout plan — a grace period? forced setup on next login? admin override?) needs a
decision from you, not something to silently force via a default flip. See Open Items.

### #6 — 5-year audit trail retention

**Before:** `database/apilog_db.py`'s `OrderLog` table logs every order-related API
call and is never purged — but nothing said so explicitly, and there was no guard
against a future "clear old logs" feature accidentally violating the requirement.

**After:** Added `MIN_RETENTION_YEARS = 5` as an explicit, named constant;
`assert_no_premature_deletion(created_at)` raises if anything ever tries to delete a
record younger than 5 years (verified: raises for a fresh record, allows a 6-year-old
one); `get_audit_retention_status()` reports live oldest-record-age and row count for
an admin diagnostics view. Confirmed via direct query against the dev DB
(44 records, oldest 7 days old at time of writing — consistent with a recently-seeded
install, not evidence of a longer-running production history).

---

## Open items requiring a decision from you

### #2 (remainder) — Static IP whitelisting

Not implemented anywhere in the codebase as an *enforced* control. The only
IP-whitelist-related code found (`broker/dhan_sandbox/api/auth_api.py`'s
`set_static_ip`/`modify_static_ip`/`get_static_ip`) is unused dead code — never called.
`broker/deltaexchange/api/auth_api.py` only logs a message telling the *user* to check
their IP is whitelisted on the broker's own dashboard.

Per CLAUDE.md, this is already understood architecturally: **the SEBI static-IP
mandate is enforced broker-side** (the broker rejects orders from non-whitelisted
source IPs), and the platform's compliance posture depends on the *server* running Max
Algos having a static, broker-registered IP — which is an infrastructure/deployment
fact (your Contabo server's IP, registered with each broker), not something this
codebase can create. What IS missing: nothing in the app surfaces or verifies that
posture — there's no admin-visible confirmation of "this server's outbound IP is
X.X.X.X, and is it registered with each connected broker." That's a UX/observability
gap I can build (a diagnostics panel showing outbound IP + a checklist), but it doesn't
change the compliance state itself, which is already broker-enforced.

**Decision needed:** do you want an admin-facing "server IP / broker whitelist status"
diagnostics panel built? It's cosmetic/informational, not a new enforcement mechanism.

### #3 — OAuth-only broker authentication

Roughly a third of the 34 supported brokers use password/TOTP login rather than OAuth
token exchange (Angel, Kotak, Motilal, mstock, Samco, Firstock, Nubra, and others).
The circular requires OAuth-only, with all other mechanisms discontinued.

This is a genuine feature-removal decision: disabling/hiding these integrations would
affect any current user connected via one of them, and re-enabling them depends on
each broker separately shipping an OAuth flow on their end (not something this
codebase controls). No code change was made here pending your decision — see the
options presented earlier in this conversation (drop non-OAuth brokers now vs. leave
as-is pending broker-side OAuth availability).

**Decision needed:** which brokers, if any, should be disabled/deprecated, and on what
timeline? Recommend cross-checking with your broker relationships/compliance counsel
whether SEBI enforcement in practice targets the platform or the broker for this
specific sub-requirement, since the broker is itself a SEBI-regulated entity with its
own compliance obligations for its own auth mechanism.

### #5 — Order-rate threshold detection, categorization, and Exchange registration

`restx_api/place_order.py`'s `ORDER_RATE_LIMIT` (`utils/constants.py`) rate-limits by
source IP via `limiter.py` (in-memory, moving-window) and returns HTTP 429 above
threshold. This is **request throttling**, not the SEBI-mandated workflow: detecting
that a client has crossed the specified orders-per-second threshold, categorizing
their activity as "algo," and registering that with the Exchange through the broker.

Two blockers to building this properly:
1. The actual threshold value is meant to be "evolved by the Broker's Industry
   Standards Forum" per the circular (footnote 2) — not a number this codebase can
   invent on its own; it should match what your broker(s) actually use/expect.
2. "Registration with the Exchange" is the same category as #1 and #3's Exchange-side
   dependency — this platform can flag/categorize an order as algo-sourced internally,
   but cannot itself complete Exchange registration; that flows through the broker.

**Decision needed:** do you have (or can you obtain from your broker) the actual
order-per-second threshold value SEBI/the Broker ISF has set? With that, I can build
real categorization (tag orders exceeding it, surface them in an admin view, and wire
whatever registration API/webhook your broker exposes for algo-order reporting, if
one exists) rather than the current bare rate-limit.

---

## Files changed this pass

- `utils/order_tag.py` (new)
- `broker/zerodha/mapping/transform_data.py`
- `broker/motilal/mapping/transform_data.py`
- `broker/nubra/mapping/transform_data.py`
- `broker/upstox/mapping/transform_data.py`
- `database/apilog_db.py`
- `database/user_db.py`
- `blueprints/apikey.py`
- `blueprints/auth.py`

All changes are additive (new columns default to existing behavior, new tag generation
replaces a hardcoded/useless value with no behavior change to order execution itself).
Full test suite (17 tests) passes; migrations applied and verified against the dev DB.
