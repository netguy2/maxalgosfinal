# Broker Auto Session Refresh — Implementation Plan

**Status:** Approved in principle, not yet built
**Date:** 2026-07-16
**Decision owner:** platform owner (approved storing broker TOTP seeds despite the risks below)

## Goal

Let a user connect a password+TOTP broker once and not have to manually
re-login every trading day. The platform stores the user's broker 2FA seed
+ PIN encrypted, and a scheduled morning job re-authenticates unattended.

## Scope — which brokers (and why only these)

Unattended daily re-auth is **only architecturally possible** for brokers
whose `authenticate_broker()` takes username + PIN/password + TOTP as
parameters (no browser redirect). Confirmed from the code:

**IN SCOPE (password + TOTP, no OAuth redirect):**
`angel`, `fivepaisa`, `motilal`, `shoonya`, `zebu`

**OUT OF SCOPE — structurally impossible (OAuth/redirect brokers need a
`request_token`/`auth_code` only a live browser login produces; no refresh
token is stored/reusable):** zerodha, upstox, dhan, fyers, flattrade,
firstock, definedge, aliceblue, bnr, arrow, iiflcapital, all XTS brokers,
indmoney, pocketful. deltaexchange sidesteps expiry entirely (crypto,
`DISABLE_SESSION_EXPIRY`).

## Risks the owner has accepted (on record)

1. Storing broker TOTP seeds is **against most brokers' terms of service**.
2. A DB breach exposes **unattended real-money trading access** to every
   opted-in user's brokerage account, bypassing 2FA entirely.
3. Arguably conflicts with the SEBI 2FA-for-API-access mandate audited in
   `docs/audit/sebi-algo-trading-compliance-2026-07.md`.

Mitigations built in: strong per-broker explicit opt-in with an
acknowledged warning modal (off by default); Fernet+PBKDF2 encryption at
rest (same scheme as SMTP/Razorpay secrets); fail-safe fallback (never
leaves a user thinking they're connected when they're not).

## Design

### 1. Data model — extend `UserBrokerCredential` (`database/user_db.py:218`)

New columns (idempotent ALTER TABLE migration, same pattern as the
kill-switch/email-identity migrations):
- `totp_seed_encrypted` `Text` nullable — the base32 TOTP seed, Fernet-encrypted.
- `auto_login_pin_encrypted` `Text` nullable — PIN/password needed for re-auth, encrypted.
- `auto_refresh_enabled` `Boolean` default `False` — per-broker opt-in flag.
- `auto_refresh_last_status` `String(20)` nullable — 'success' | 'failed' | null.
- `auto_refresh_last_at` `DateTime` nullable.

Reuse existing Fernet helpers (or add a dedicated
`AUTO_REFRESH_KEY_SALT` per-purpose salt for key separation, matching the
SMTP/Razorpay convention).

### 2. Orchestrator — new `services/broker_auto_refresh_service.py`

- `refresh_one(username, broker) -> dict`: decrypt seed+PIN, generate TOTP
  via `pyotp.TOTP(seed).now()`, call the broker's `authenticate_broker()`
  with the same param shape `blueprints/brlogin.py` uses for that broker,
  then `upsert_auth()` the fresh token. Update `auto_refresh_last_status`.
- `refresh_all_enabled()`: iterate every row with `auto_refresh_enabled=True`
  and a still-relevant broker, call `refresh_one`, collect results.
- On failure: set status='failed', do NOT leave a stale valid-looking
  token, and trigger a notification (Telegram + in-app) telling the user
  to log in manually today. Never silently retry into a false-connected
  state.

### 3. Scheduler — APScheduler cron (mirror `flow_scheduler_service.py`)

- One daily job at ~08:30 IST (after the 3 AM token death, before market
  open at 09:15). Cron via the shared APScheduler instance.
- Registered at app init alongside the other schedulers.

### 4. REST endpoints — extend broker credentials blueprint

- `POST /api/broker/auto-refresh/enable` — accepts broker, totp_seed, pin;
  requires the acknowledgement flag; encrypts + stores; sets enabled=True.
- `POST /api/broker/auto-refresh/disable` — clears seed/pin, sets enabled=False.
- `GET /api/broker/auto-refresh/status` — per-broker enabled + last status/time.

### 5. Frontend — opt-in in the broker credentials flow

- In `BrokerSelect.tsx` (only when the selected broker is one of the 5
  in-scope), a "Keep me logged in (auto-refresh)" section.
- Enabling opens a **warning modal** the user must read + check
  ("I understand my broker 2FA seed will be stored so the platform can
  log in for me, and that a breach could expose my trading account")
  before the seed/PIN fields unlock.
- Show last auto-refresh status ("Auto-refreshed today 8:31 AM" / "Failed
  — log in manually") in Broker Management.

### 6. Audit

- Log every auto-refresh attempt (success/failure, broker, timestamp) to
  the existing order/activity log infrastructure, so there's a record of
  every unattended authentication.

## Verification plan

- Unit-test `refresh_one` with a mocked `authenticate_broker` (success +
  failure paths) and a known TOTP seed → deterministic code generation.
- Migration applied + verified against dev DB.
- Manual: enable for a real zebu/shoonya account, confirm next-morning job
  refreshes the token without interaction; force a bad seed, confirm the
  fail-safe fallback + notification fire.
- Confirm the 20 out-of-scope brokers show no auto-refresh option.

## Why this is deferred to its own session

This is the single most security-sensitive change in the platform (stored
credentials that grant unattended real-money trading access). It warrants
focused, unrushed implementation and careful review rather than being
appended to a long multi-feature session.
