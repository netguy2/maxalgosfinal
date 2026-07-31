# Cross-Broker Live-Data Failover — Design Plan

**Date:** 2026-07-16
**Status:** PROPOSED — awaiting approval before any code is written
**Author:** Claude (opus-4.8)

> Goal (user's words): *"all tick-by-tick uncontrolled from broker, all brokers give
> full WS data continuously — even if a broker's data cuts or fails, fall back to
> another available broker that has the best speed of data. Order placement is
> separate; make it as fast as possible. Data and order placement are the keys
> since we depend purely on the broker (no external data)."*

---

## 1. What exists today (verified against the code)

- **One data feed per user.** The WS proxy keys everything by `user_id`:
  `broker_adapters[user_id]`, `user_broker_mapping[user_id]`. A user gets exactly
  **one** broker adapter, chosen from the broker tied to their API key
  (`get_broker_name(api_key)` in `authenticate_client`, server.py:827).
- **Adapter lifecycle:** `create_broker_adapter(broker_name)` → `adapter.initialize()`
  → `adapter.connect()` → adapter publishes normalized ticks to **ZeroMQ (port 5555)**
  → proxy's `zmq_listener` fans them out to subscribed browser clients.
- **Health signal already present.** `last_tick_time[user_id]` records the last tick;
  `get_adapter_health()` (server.py:520) already reports `connected`,
  `seconds_since_last_tick`, `has_subscriptions`. There is a **deliberate decision NOT
  to auto-evict** on silence (server.py:84-91) because a quiet market legitimately
  produces no ticks — so staleness alone is not proof of failure.
- **Credentials are process-wide.** Broker modules read creds via a monkey-patched
  `os.getenv`, scoped per-request by `broker_credential_context(user, broker)`
  contextvars. `multi_broker_order_service.py` fans orders out **sequentially** for
  exactly this reason — two brokers can't both be "active" in one request thread.
- **Users can already store credentials for multiple brokers** (`UserBrokerCredential`,
  one row per `(username, broker)`), and can connect/authenticate several. So the
  *credential* prerequisite for multi-feed already exists; only the *runtime* is single.

**Conclusion:** the platform is single-feed at runtime. Failover is a genuine new
capability, not a config flag. But the health-tracking seam (`last_tick_time`,
`get_adapter_health`) and the multi-credential storage are already in place, which
lowers the risk considerably.

---

## 2. Design principles (non-negotiables, from the user)

1. **Latency is paramount.** Failover must never *add* steady-state latency to the
   normal (healthy) path. Ticks from the primary feed flow exactly as they do today.
2. **The tick stream is sacred.** No throttling, no buffering, no added hops on the
   live WS/ZeroMQ tick path.
3. **Order placement is independent.** Failover is a *data-only* concern. Order routing
   is unchanged. (Orders always go to the broker the user explicitly selected — we do
   NOT silently reroute orders to a fallback broker; that would be a correctness/
   compliance hazard. Fallback affects DATA only.)
4. **Purely broker-dependent.** No external data vendor is introduced. Fallback sources
   are only *other brokers the same user has connected*.

---

## 3. Proposed architecture

### 3.1 Concept: primary + hot-standby data feeds per user

Introduce a **`DataFeedGroup`** per user that owns *up to N* broker adapters (N=2 or 3,
configurable) drawn from the user's connected brokers:

- **Primary** — the broker on the user's API key (unchanged default). All ticks the
  browser sees come from the primary while it is healthy.
- **Standby(s)** — 1-2 other connected brokers, connected and subscribed to the **same
  symbols** in the background, publishing to ZeroMQ on a **distinct topic namespace**
  (e.g. tick topics tagged with the source broker) so the proxy can tell feeds apart.

Only the **active** feed's ticks are forwarded to clients. Standby ticks are consumed
by a lightweight **health/latency scorer** (not forwarded), so we always know each
feed's real freshness and per-tick latency *before* we ever need to switch.

### 3.2 The failover decision (health scorer)

A per-user scorer evaluates each feed on a short interval (e.g. every 2-3s), using
signals we already have plus one new one:

- `connected` state (already tracked).
- **Latency estimate:** for symbols that tick on multiple feeds, compare arrival
  timestamps → which broker is delivering the same tick *first*. This directly answers
  "best speed of data."
- **Staleness while subscribed:** `seconds_since_last_tick` **relative to peers.** The
  key insight that resolves the "quiet market ≠ failure" problem: a feed is only
  "failed" if it's silent **while a peer feed on the same symbols is actively ticking.**
  Comparative silence is real failure; global silence is just a quiet market.

Switch-over rule (primary → best standby):
- Trigger when the active feed is `disconnected`, OR comparatively stale beyond a
  threshold (silent while a healthy peer keeps ticking the same symbols).
- Pick the standby with the best (connected + lowest-latency + freshest) score.
- Switch is a **pointer flip** in the proxy: change which feed's topic is forwarded to
  the user's clients. No reconnect, no re-subscribe on the client side, no message to
  the browser beyond an optional "data source: <broker>" status event.
- **Hysteresis / anti-flap:** require the new feed to be better for K consecutive checks,
  and rate-limit switches (e.g. no more than 1 switch / 15s) so a jittery broker can't
  cause thrashing.
- **Fail-back:** when the original primary recovers and is best again (after the
  hysteresis window), switch back — or optionally "sticky" stay on the current healthy
  feed until it too degrades (configurable; sticky is calmer, less flap).

### 3.3 Where the code lives (module boundaries)

- **`websocket_proxy/data_feed_group.py`** (NEW): owns the set of adapters for a user,
  the scorer, and the active-feed pointer. Pure runtime object, no Flask coupling.
- **`websocket_proxy/server.py`** (EDIT, surgical): where a single adapter is created in
  `authenticate_client`, optionally create a `DataFeedGroup` instead (behind a flag).
  The `zmq_listener` forwarding gains a single check: "is this tick from the active feed
  for its user?" — an O(1) dict lookup, no added latency on the hot path.
- **Broker adapters (`broker/*/streaming/`): UNCHANGED.** They already connect,
  subscribe, and publish to ZeroMQ. The group just runs several of them. This is the
  biggest risk-reducer — we do not touch the 25+ streaming adapters.
- **ZeroMQ topic tagging:** standby adapters must publish under a source-distinguishable
  topic so the proxy can attribute a tick to a feed. Verify whether the current tick
  envelope already carries the broker name; if not, this is the one adapter-side change
  needed, and it must be additive (extra field), never altering the existing tick shape
  the browser consumes.

### 3.4 Resource / FD budget (per CLAUDE.md FD hygiene)

Every standby feed is a **real broker WebSocket + connection pool + ZeroMQ socket** =
more file descriptors on a single-worker eventlet process. This is the main cost.

- Cap standby count (default N=2 total feeds, i.e. 1 standby; N=3 opt-in).
- Standbys subscribe to the **same symbol set** as the primary — no extra symbol fan-out.
- Group teardown MUST disconnect every adapter and close every pool/ZMQ socket on client
  disconnect, broker change, and error paths (reuse the existing
  `cleanup_pools_for_user` + `adapter.disconnect()` machinery already in server.py:844-874).
- A focused FD audit of the group's connect/disconnect/switch/error paths is part of the
  build's definition-of-done.

### 3.5 Feature flagging & safety

- Entire feature behind `DATA_FEED_FAILOVER_ENABLED` (**default OFF**). When off, code
  path is byte-for-byte today's single-adapter path. Zero risk to current production.
- Per-user opt-in (only users who explicitly enable multi-feed get standby feeds).
- Only brokers the user has **actually connected** (valid session) are eligible as
  standbys — we never auto-login a broker just to use it as a fallback.

---

## 4. What this does NOT do (explicit scope guards)

- Does **not** reroute order placement. Orders go to the user's chosen broker only.
- Does **not** introduce any external/non-broker data source.
- Does **not** touch the live tick path's latency in the healthy case.
- Does **not** modify the 25+ broker streaming adapters' connect/subscribe logic
  (only, if strictly necessary, an additive source-tag on the published tick envelope).
- Does **not** change anything when the flag is off.

---

## 5. Build phases (each independently verifiable, flag stays OFF until the end)

1. **Tick source attribution.** Confirm/instrument the ZeroMQ tick envelope so every
   tick is attributable to its source broker (additive field only). Verify browser
   payload unchanged.
2. **`DataFeedGroup` object + scorer** (no wiring yet). Unit-test the scorer against
   synthetic tick timelines: quiet market (no switch), primary disconnect (switch),
   primary comparatively stale (switch), flapping (hysteresis holds).
3. **Proxy wiring behind the flag.** `authenticate_client` builds a group; `zmq_listener`
   forwards only the active feed. O(1) active-feed check on the hot path.
4. **Switch-over + fail-back + anti-flap**, with an optional client status event
   ("data source: X").
5. **FD audit** of connect/disconnect/switch/error paths. Teardown proven leak-free.
6. **Admin/diagnostics surface:** extend `get_adapter_health()` to show the group
   (primary/standby, active, per-feed latency & freshness).
7. Enable flag in a controlled test, validate real failover with two live brokers,
   measure that healthy-path latency is unchanged.

---

## 6. Open questions for you (before I build)

1. **How many simultaneous feeds?** Default 2 (1 primary + 1 standby) is the safe, low-FD
   choice. Allow 3 as opt-in? More feeds = more failover resilience but more FDs/CPU.
2. **Fail-back behavior:** *sticky* (stay on current healthy feed until it degrades —
   calmer, fewer switches) vs *prefer-primary* (always return to the API-key broker when
   it recovers)? I recommend **sticky** to minimize flapping.
3. **Switch latency vs. stability:** how aggressive should the staleness trigger be?
   e.g. switch after the active feed is comparatively silent for 3s while a peer ticks?
   Lower = faster failover but more sensitive to blips; higher = more stable.
4. **Scope of standby brokers:** all of a user's connected brokers eligible, or an
   explicit user-chosen ordered preference list (primary, 1st fallback, 2nd fallback)?

---

## 7. Risk summary

| Risk | Mitigation |
| --- | --- |
| Added latency on healthy path | Active-feed check is one O(1) dict lookup; standby ticks never forwarded. Flag OFF = today's exact path. |
| FD exhaustion (single-worker eventlet) | Cap feed count; reuse existing pool/adapter teardown; mandatory FD audit. |
| Feed flapping | Hysteresis (K consecutive wins) + switch rate limit + sticky fail-back. |
| Touching 25+ streaming adapters | We don't — group orchestrates unmodified adapters; only additive tick source-tag if needed. |
| Quiet market misread as failure | Comparative staleness (silent *while a peer ticks the same symbols*), never absolute silence. |
| Breaking current prod | Feature flag default OFF + per-user opt-in; zero code-path change when disabled. |
