# Order-Path Safety Gates — findings and open items

Status as of the Branch A patch (kill-switch coverage across all live order
paths). Records what was fixed, what is still open, and the method that found
the gaps — the method matters because two of the five gaps were invisible to
the greps that found the first three.

## What was wrong

Five services call a broker's order-placement API directly:

| Service | Broker call |
| --- | --- |
| `services/place_order_service.py` | `place_order_api` |
| `services/basket_order_service.py` | `place_order_api` |
| `services/split_order_service.py` | `place_order_api` |
| `services/place_smart_order_service.py` | `place_smartorder_api` |
| `services/place_gtt_order_service.py` | `place_gtt_order` |

Only the first routed through `place_order_with_auth`. The other four each
reimplement `import_broker_module` (GTT uses `import_broker_gtt_module`) and
call the broker themselves, which is how they drifted out of every check
living in `place_order_service`.

Consequence: flipping the master kill switch stopped Chartink and Python
Strategy Host orders, and (after the earlier MaxHook patch) webhook orders —
but **not** basket, split, smart, or GTT orders reaching live brokers from the
REST API, the Flow no-code builder, or Action Center approvals.

## What was fixed

`services/order_gate.py` provides one `check_order_allowed(context)`, called
at all five sites immediately before the broker call and **after** each
service's analyze/sandbox branch. Sandbox orders are deliberately exempt: the
kill switch exists to stop real capital moving, and blocking paper orders buys
no safety while breaking testing workflows.

Blocked orders return 403 / `KILL_SWITCH_ACTIVE` **and** publish
`OrderFailedEvent` / `GTTFailedEvent`. The publish is not cosmetic —
`order.failed` drives the red error toast and notification-drawer entry in the
React UI (`subscribers/socketio_subscriber.py::on_order_failed`) plus the log,
telegram, and whatsapp subscribers. Basket and split initially returned the
error without publishing, which would have made a kill-switched basket vanish
from the user's view while the other three reported correctly.

Regression coverage: `test/test_order_gate.py`, including two static guards
that fail CI if a new order path is added without a gate, or if a gated path
blocks without publishing a failure event.

## Open items

### 1. Resting GTT orders survive the kill switch — HIGH

A user can flip the kill switch, see it report ACTIVE, have all new orders
blocked, and **still have a previously-placed GTT trigger days later** at the
broker, unwatched. The gate blocks GTT *placement*; it cannot touch orders
already resting broker-side.

Stopping those requires **cancellation** of resting GTTs on activation, not
gating. `Settings.kill_switch_cancel_orders_enabled` already exists as the
scope flag for cancel-on-activate behavior — check whether it covers GTTs or
only regular open orders.

This is the same class of gap as the one that started this whole
investigation: a control that appears to do more than it does. It is not a
"GTT edge case."

### 2. Fail-open alerts reach users but never an admin — MEDIUM

Both gates fail OPEN when the kill-switch flag cannot be read: a settings-table
fault must not silently halt every strategy platform-wide. The resulting state
is dangerous — the switch reads ACTIVE in the UI while not enforcing — so each
fail-open raises a Telegram alarm.

Today that alarm goes to **users with notifications enabled and nobody else**:

- `services/order_gate.py` alerts every user with notifications on (the kill
  switch is global, so a fault affects everyone).
- `services/signal_engine.py::_alert_safety_check_failed` alerts only the
  owning strategy's user.

So the person with the authority and access to investigate a persistent
settings-table fault — the platform administrator — **has no way to learn it is
happening** unless they happen to also be a notification-enabled user. If no
user has Telegram linked, a persistent fail-open is entirely silent outside the
log file.

Fix: a dedicated admin alert channel, used by both gates, with consistent
recipients.

### 3. Four services duplicate `import_broker_module` / `emit_analyzer_error`

The root cause of the drift above. Consolidating onto the shared helpers in
`place_order_service` would make it structurally harder for a new order path to
bypass the gate. This is a refactor, not a safety patch, and needs its own
review.

## Method note — how to verify "did we get them all"

Three successive greps each looked correct and each under-reported:

1. Importers of `place_order` — missed services calling the broker directly.
2. Calls to `place_order_api` — missed `place_smartorder_api` and
   `place_gtt_order`.
3. Uses of `import_broker_module` — missed `import_broker_gtt_module`.

Only enumerating the **full broker-call surface** closed the set:

```bash
grep -rhno "broker_module\.[a-z_]*api\|broker_module\.place[a-z_]*\|broker_funcs\[[^]]*\]" \
  --include="*.py" services/ | sed 's/^[0-9]*://' | sort -u
```

Grep by intent (what reaches a broker), not by name or import pattern. Naming
conventions in this codebase are inconsistent enough that any name-based search
will under-report, and an under-reported safety audit reads exactly like a
complete one.
