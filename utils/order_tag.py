"""Per-order broker tag generation.

SEBI's algo trading circular (SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013)
requires every algo order to carry a unique identifier for audit-trail
purposes. The exchange-issued algo ID itself only exists once this
platform (as "Algo Provider") completes empanelment/registration with the
Exchange through the broker -- that registration step is a business/legal
process, not something this code can generate.

What this module DOES provide, as the engineering half of that
requirement: every order gets a genuinely unique, traceable-back-to-its-
strategy tag instead of the previous hardcoded static string (e.g. Kite
orders were ALL tagged "maxalgos" regardless of which strategy or user
placed them, making the tag useless for any kind of audit trail). Once an
Exchange-issued algo ID exists, it should be prefixed/embedded here
instead of (or alongside) the strategy name -- see generate_order_tag()'s
docstring for the swap-in point.
"""

import re
import uuid

# Most brokers cap order tags at a small fixed length (Zerodha/Kite: 20
# chars, alphanumeric plus a few symbols). Using the tightest common
# denominator keeps one generator safe for every broker's mapping module
# rather than needing a per-broker length variant.
MAX_TAG_LENGTH = 20

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def generate_order_tag(strategy: str | None) -> str:
    """Build a short, broker-safe, per-order-unique tag.

    Format: <sanitized strategy prefix><8 hex chars from a fresh uuid4>,
    truncated to MAX_TAG_LENGTH. The strategy prefix keeps the tag
    human-traceable to which strategy placed the order (useful for
    support/debugging and partially satisfies the "identify the
    originating algo" intent); the uuid suffix guarantees no two orders
    -- even from the same strategy, same second -- ever collide, unlike
    the previous hardcoded "maxalgos" tag shared by literally every order.

    TODO once Exchange algo-ID registration is complete for a given
    broker/strategy pair: prefix the tag with the registered algo ID
    instead of (or in addition to) the strategy name, e.g.
    f"{exchange_algo_id}-{uuid_suffix}". That mapping (strategy -> algo
    ID) doesn't exist yet in this codebase; it depends on the actual
    registration completed with each Exchange/broker.
    """
    suffix = uuid.uuid4().hex[:8]
    if not strategy:
        return f"maxalgos-{suffix}"[:MAX_TAG_LENGTH]

    prefix = _SAFE_CHARS_RE.sub("", strategy.strip())[: MAX_TAG_LENGTH - len(suffix) - 1]
    if not prefix:
        return f"maxalgos-{suffix}"[:MAX_TAG_LENGTH]
    return f"{prefix}-{suffix}"[:MAX_TAG_LENGTH]
