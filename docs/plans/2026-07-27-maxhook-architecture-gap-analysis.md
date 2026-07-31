# MaxHook Architecture — Gap Analysis & Sequencing

**Date**: 2026-07-27
**Status**: Draft for review
**Purpose**: Establish what already exists before building the "Trading Automation Designer" vision, and sequence the work so the current product becomes client-safe first.

---

## 0. Why this document exists

A module/pipeline architecture for MaxHook was proposed (modules, execution context,
dependency graph, event-driven core, WDL, trading personalities). Before designing it,
the codebase was audited. Two of the proposed foundations **already exist**, and one
prerequisite is a 2430-line PRD that has been in Draft since February with **zero files
implemented**.

This document exists so that work is not duplicated and so the sequencing decision is
made deliberately rather than by default.

---

## 1. What already exists (do not rebuild)

### 1.1 The Event Bus — BUILT AND SHIPPED

`utils/event_bus.py` is a working in-process pub/sub system. See
[Design 53](../design/53-event-bus/README.md) and [PRD](../prd/event-bus.md).

| Capability | Status |
|---|---|
| Topic-based routing | Built |
| Async dispatch (`ThreadPoolExecutor`, 10 workers) | Built |
| Per-subscriber error isolation (`_safe_call`) | Built |
| Thread-safe subscribe/unsubscribe | Built |
| Typed event dataclasses | Built (7 event modules) |
| Subscribers: Log, SocketIO, Telegram, WhatsApp | Built |
| 14 event topics across 10 order services | Built |

**Critically, it is already built as the observer model** — subscribers are non-blocking
and never gate execution. The event-driven core that was proposed is, in its correct
form, already here.

Its own PRD lists as future scope:
- *"Strategy-level position tracking (Phase 2 — new subscriber)"*
- *"Strategy-level risk management (Phase 2 — new subscriber)"*
- *"Event persistence/replay (SQLite event log table)"*

Those three are exactly what the MaxHook vision needs. **The path is additive: new
subscribers, not a new bus.**

### 1.2 Partial central risk gate — BUILT, NARROW SCOPE

`services/master_risk_monitor_service.py` (276 lines) implements account-wide combined
P&L auto-exit: every 5s it sums normalized P&L across all open positions on all
connected live brokers and closes everything if a configured SL/target threshold is
crossed.

Its docstring explicitly states it is **not** attempting to replace the Feb PRD's
per-leg/combined risk engine. Deliberate V1 limits:
- Live positions only (no sandbox)
- Account-wide, not per-strategy — *because there is no strategy↔position linkage yet*
- Reuses the kill-switch close-everything mechanism

That "no strategy↔position linkage" is the precise gap the Feb PRD's `StrategyPosition`
table would fill. The central gate exists in skeleton; it cannot become per-strategy
until position tracking lands.

### 1.3 Kill switch — BUILT

`utils/kill_switch.py` (56 lines) + `services/kill_switch_service.py` (416 lines).
Enforced inside `place_order_service` via `enforce_kill_switch`.

### 1.4 Signal resolution engine — BUILT, UNDER-EXPOSED

`services/signal_engine.py` already implements much of what the vision describes as new:

| Vision item | Existing implementation |
|---|---|
| Symbol Intelligence (resolve NIFTY → ATM CE → weekly) | `_resolve_live_instrument` (signal_engine.py:41-111) |
| Strike by ATM/ITMn/OTMn offset | Built |
| Strike by premium / delta / OI | Built |
| Dynamic expiry resolution | `services/expiry_service.py` |
| Multi-leg / rotation | `LegGroup`/`Leg` (strategy_db.py:432-568), `stateful` model |
| Per-action overrides (qty/product/order type) | `ExecutionProfile.resolve_execution` (strategy_db.py:402-429) |
| Condition tree | `_process_deployment_signal_event` (signal_engine.py:966-1296) |
| Per-user scoped notifications | `_emit_scoped` (signal_engine.py:114-134) |
| Correct per-broker credentials | `broker_credential_context` |

**The engine is far ahead of the UI.** The React MaxHook pages expose a fraction of this.
A large perceived-capability jump is available from UI work alone, with no engine changes.

---

## 2. What does NOT exist

### 2.1 The Feb 2026 Risk PRD — 0% implemented

[docs/plans/2026-02-06-strategy-risk-management-prd.md](2026-02-06-strategy-risk-management-prd.md)
— 2430 lines, Status: Draft. Verified absent:

```
MISSING: services/strategy_risk_engine.py
MISSING: services/strategy_position_tracker.py
MISSING: services/strategy_order_poller.py
MISSING: services/strategy_pnl_service.py
MISSING: services/strategy_options_resolver.py
MISSING: services/strategy_exit_executor.py
MISSING: database/strategy_position_db.py
MISSING: upgrade/migrate_strategy_risk.py
MISSING: frontend/src/pages/StrategyDashboard.tsx
MISSING: subscribers/strategy_store.py
```

This PRD contains prerequisites for nearly everything in the MaxHook vision:
strategy-level position tracking, SL/target/trailing/breakeven, multi-leg risk modes,
restart recovery with broker reconciliation, position state machine for race conditions,
and **webhook deduplication (5s window)**.

### 2.2 Webhook security & integrity gaps

| Gap | Location | Impact |
|---|---|---|
| No HMAC/signature verification | `blueprints/strategy.py:1862`, `blueprints/chartink.py:786` | UUID in URL is the **only** credential. Leaked URL = anyone places live orders. |
| No idempotency / replay protection | All webhook paths | TradingView/ChartInk retries on timeout duplicate orders. Confirmed absent — no dedup code exists. |
| No delivery/audit log | — | No queryable record of payloads received or decisions made. Support = log-file forensics. |
| No rate limit on Flow webhook | `blueprints/flow.py:669-693` | Only unthrottled webhook entry point. |
| No kill-switch fast-check on strategy webhook | `blueprints/strategy.py:1862` | chartink.py has one; strategy.py relies on downstream enforcement. |
| Rate limiter is `memory://` | `limiter.py:7` | Per-process only; resets on restart. |
| Flow API-key fallback to global env var | `blueprints/flow.py:635-643` | Unconfigured workflow can trade on a shared platform key. |

Note: `docs/audit/api-security.md` covers webhook security **only** for the
`/api/v1/placeorder` path. The UUID-URL webhook systems are undocumented there — these
are genuine gaps, not accepted-and-documented risk.

### 2.3 Missing module-architecture primitives

Not present in any form: module contract/registry, rich outcomes
(Modify/Retry/Pause/Skip), declared module metadata, dependency graph, execution-context
snapshots, WDL, capability model, signal-source abstraction.

### 2.4 Stale documentation

[docs/design/39-strategy-module/README.md](../design/39-strategy-module/README.md)
describes a 2-action BUY/SELL system with a simple `Strategy` table and HTTP-loopback
queueing. Reality: three execution models, `ExecutionProfile`, `LegGroup`/`Leg`, live
strike resolution. **Anyone onboarding from this doc will be misled.** Needs rewrite.

---

## 3. The sequencing decision

> **ASSUMPTION — reversible, flagged for owner confirmation.**
> This document assumes: **finish the Feb risk PRD first; layer the module architecture
> on top.** The alternative is to supersede the Feb PRD with the module architecture.

Rationale for the assumption:

1. The Feb PRD contains the client-safety prerequisites (dedup, position tracking,
   strategy-isolated exits). Those are needed regardless of which architecture wins.
2. `master_risk_monitor_service.py` is explicitly blocked on the PRD's
   `StrategyPosition` table for per-strategy risk. The PRD unblocks work already started.
3. A 2430-line PRD stalling for five months is the central risk. Replacing it with a
   larger architecture makes stalling more likely, not less.
4. The module architecture is largely a **refactor** of `signal_engine.py` with a
   known-correct reference implementation to diff against — it is safer to do second,
   on top of a tracked-position foundation.

**If the owner prefers to supersede rather than finish, sections 4 and 5 reorder but the
contents do not change.**

---

## 4. Recommended sequence

### Phase A — Client safety (blocks external clients)

Small, independent, shippable. None require the module architecture.

| # | Item | Why now |
|---|---|---|
| A1 | HMAC signature verification on strategy + chartink webhooks | Flow already does this correctly (`hmac.compare_digest`) — copy the pattern. Highest security ROI. |
| A2 | Webhook deduplication (payload hash + TTL window) | Feb PRD §21 specifies 5s default. Prevents duplicate live orders on retry. |
| A3 | `WebhookDeliveryLog` table + pipeline observer | Build as an **event bus subscriber**, not inline. Every future module then gets audit free. |
| A4 | Rate limit on `/flow/webhook` | One-line fix; closes the last unthrottled entry point. |
| A5 | Kill-switch fast-check on strategy webhook | Parity with chartink.py. |
| A6 | UI warning: "this URL is the credential" | `ViewMaxHookConnection.tsx` next to the copy button. |

**A1–A3 are the minimum bar for handing MaxHook to clients you cannot personally support.**

### Phase B — Feb PRD core (unblocks everything else)

Follow the PRD's own Phases 1–2:
- `StrategyOrder` / `StrategyPosition` / `StrategyTrade` / `StrategyDailyPnL` tables
- `strategy_order_poller` (1 req/sec, priority queue)
- `strategy_position_tracker` — **implement as `subscribers/strategy_store.py`**, which
  the event bus PRD already anticipates
- Risk engine: SL / target / trailing / breakeven
- Restart recovery + broker reconciliation

Then extend `master_risk_monitor_service.py` from account-wide to per-strategy, now that
the linkage exists.

### Phase C — Expose the existing engine (high visible value, low risk)

Mostly UI over capabilities that already work: strike/expiry/premium/OI selection,
per-action overrides, position rules, cooldown, sessions. Plus rewrite the stale
Design 39 doc.

### Phase D — Module architecture

Refactor `signal_engine.py` into modules behind a feature flag, diffing against the
existing path. Extract Symbol / Strike / Expiry first — they are already cohesive in
`_resolve_live_instrument`.

Contract requirements (settle before writing code):
- **Rich outcomes**: `Continue | Modify | Retry | Pause | Skip | Reject | Complete`.
  Hardest thing to retrofit — must be in from day one.
- **Structured reject reasons** (module id + code + message), not free text — the
  delivery log renders these.
- **Declared metadata**: name, version, stage, deps, timeout, fallback, settings schema,
  permissions.
- **I/O declaration + per-module timeout with declared fallback.** Matters acutely: the
  order path runs under eventlet, single worker.
- **Fixed stage ordering** in v1. Gates must not be reorderable — Risk-after-Execution is
  a footgun.
- **Dependency resolution warns; never auto-enables.** Auto-enabling silently adds
  modules with their own latency and failure modes into a live order path.

### Phase E — Designer layer

WDL as the compile target for all UIs; trading personalities; Basic/Advanced views;
capability graph; signal-source unification (ChartInk, Flow, REST, webhook as peers).

**Custom Module Builder**: restricted DSL, not arbitrary Python. Anything running inline
in the order path on a box holding live broker sessions is a security boundary. The
Python Strategy Host's subprocess isolation is not a fit for inline execution.

---

## 5. Architectural notes

### 5.1 Pipeline vs. event bus — both, with a clear split

The proposed "modules react to events" model is right for observers and wrong for gates.
Risk cannot be a subscriber: subscribers are async and non-blocking, so a risk subscriber
either has to be special-cased (a pipeline wearing an event-bus costume) or the order
proceeds while risk is still deciding.

The existing bus already draws this line correctly. Extend it:

- **Ordered pipeline** for the order path — stages, dependency resolution, rich outcomes,
  timeouts, fallbacks.
- **Event emission at stage boundaries** — consumed by observers only: Log, Analytics,
  Journal, Telegram, Copy Trading, AI Advisor.

Everything on the five-year list (AI Advisor, Copy Trading, Analytics, Journal,
Notifications) is an observer and works under the existing bus unchanged.

### 5.2 Snapshots

Stage boundaries are natural snapshot points. Capturing before/after context per stage is
what makes "why did this trade happen six months ago" answerable, and is the single
biggest support-cost reducer in the vision. Build it into the pipeline core, not into
individual modules.

### 5.3 Context versioning

Every execution context should carry schema version, pipeline version, strategy version,
and module versions — otherwise historical reconstruction is guesswork.

### 5.4 WDL and module schemas are not in tension

Modules own their settings schemas; WDL is the versioned document that composes them plus
wiring. Modules define the vocabulary, WDL is the sentence. Persistence does not disappear
under a module architecture — it becomes namespaced and module-owned.

---

## 6. Open questions for the owner

1. **Finish or supersede the Feb PRD?** (Section 3 assumes finish.)
2. **Why did the Feb PRD stall?** If the cause was scope, the module architecture is
   strictly larger and will stall harder. Worth naming before committing.
3. **Custom Module Builder: DSL or sandboxed Python?** Shapes the module contract.
4. **Does `master_risk_monitor_service.py` become the central gate**, or does the Feb
   PRD's engine replace it? Currently they are designed as complements.
5. **Nine webhook types or one designer + personalities?** Recommendation: one designer;
   nine UIs is nine validation paths and users straddle categories constantly.

---

## 7. Bottom line on client-readiness

**Today**: shippable to a small, hand-held set of clients running simple equity /
single-leg option webhooks whom you can support directly.

**Not yet shippable self-serve**: missing signature verification and idempotency means a
duplicate-fire incident becomes a money conversation, and missing delivery logs means
support is log-file forensics.

**Phase A converts "shippable to friends" into "shippable to strangers."** It is roughly
a week of work and does not depend on any architectural decision in this document.
