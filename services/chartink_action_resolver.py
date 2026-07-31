"""Resolve a ChartInk scan into a trading action, unambiguously.

ChartInk alerts do not carry a structured action field -- the scan name is the
only signal of intent, and users are instructed (see the MaxHook connection UI)
to put BUY / SELL / SHORT / COVER in it. The original implementation resolved
this with a chain of `if "BUY" in scan_name` substring tests, which has two
failure modes that can pick the WRONG SIDE of a real trade:

1. Substring collision. The test is unanchored, so any scan name containing an
   action keyword inside a larger word matches it. "BREAKOUT COVERED CALL"
   contains "COVER"; "OVERSOLD" contains no keyword but "SHORTLIST" contains
   "SHORT"; "BUYBACK ANNOUNCEMENT" contains "BUY". The user gets a live order
   in a direction they never asked for.

2. Silent first-match-wins on genuine ambiguity. The chain tested BUY, then
   SELL, then SHORT, then COVER, returning on the first hit. A scan named
   "SELL TO COVER" contains both SELL and COVER and resolved to SELL with no
   warning. Worse, because BUY was tested first, "BUY / SELL REVERSAL" always
   resolved BUY.

This module replaces that with word-boundary matching plus explicit ambiguity
detection: if a scan name yields more than one distinct action, it is REJECTED
rather than silently resolved. Refusing to trade on an ambiguous instruction is
always correct; guessing the side is not.

Precedence note: SHORT and COVER are checked as distinct keywords from
SELL/BUY, but they map onto the same two order actions:

    BUY   -> action BUY,  entry, regular order
    SELL  -> action SELL, exit,  smart order (position_size=0)
    SHORT -> action SELL, entry, regular order
    COVER -> action BUY,  exit,  smart order (position_size=0)

That mapping is preserved exactly from the original implementation -- this
module changes *how the keyword is found*, never what a correctly-named scan
does.
"""

import re

from utils.logging import get_logger

logger = get_logger(__name__)

# keyword -> (action, use_smart_order, is_entry_order)
# Mirrors the original blueprints/chartink.py branch semantics exactly.
_KEYWORD_MAP = {
    "BUY": ("BUY", False, True),
    "SELL": ("SELL", True, False),
    "SHORT": ("SELL", False, True),
    "COVER": ("BUY", True, False),
}

# Word-boundary patterns. \b means "BUYBACK" no longer matches BUY, and
# "COVERED" no longer matches COVER -- the substring collisions above.
_KEYWORD_PATTERNS = {
    kw: re.compile(rf"\b{kw}\b", re.IGNORECASE) for kw in _KEYWORD_MAP
}


class ActionResolutionError(ValueError):
    """Raised when a scan name yields no action, or more than one."""

    def __init__(self, message, code, found=None):
        super().__init__(message)
        self.code = code
        self.found = found or []


def resolve_action(scan_name, explicit_action=None):
    """Resolve a ChartInk scan into (action, use_smart_order, is_entry_order).

    Args:
        scan_name: The scan/alert name from the ChartInk payload.
        explicit_action: Optional structured action from the payload. When
            ChartInk (or a proxy/relay in front of it) can send a real field,
            it wins outright -- no name parsing, no ambiguity. This is the
            path to prefer; scan-name parsing is the fallback for the many
            users whose alerts cannot carry extra fields.

    Returns:
        (action, use_smart_order, is_entry_order)

    Raises:
        ActionResolutionError: no keyword found, or the name is ambiguous.
    """
    # 1. Structured field wins when present.
    if explicit_action:
        key = str(explicit_action).strip().upper()
        if key in _KEYWORD_MAP:
            return _KEYWORD_MAP[key]
        raise ActionResolutionError(
            f"Unrecognized action '{explicit_action}'. Expected one of: "
            f"{', '.join(sorted(_KEYWORD_MAP))}",
            code="invalid_explicit_action",
        )

    name = scan_name or ""

    # 2. Which keywords actually appear, as whole words.
    matched = [kw for kw, pat in _KEYWORD_PATTERNS.items() if pat.search(name)]

    if not matched:
        raise ActionResolutionError(
            "No valid action keyword (BUY/SELL/SHORT/COVER) found in scan name",
            code="no_action_keyword",
        )

    # 3. Ambiguity check on the resolved ORDER INTENT, not the raw keyword.
    #    Two keywords that mean the same thing are not a conflict; two that
    #    imply different orders are, and must not be guessed at.
    intents = {_KEYWORD_MAP[kw] for kw in matched}
    if len(intents) > 1:
        raise ActionResolutionError(
            f"Scan name is ambiguous -- it contains multiple conflicting action "
            f"keywords ({', '.join(sorted(matched))}). Rename the scan to contain "
            f"exactly one of BUY / SELL / SHORT / COVER, or send an explicit "
            f"'action' field in the webhook payload.",
            code="ambiguous_action",
            found=sorted(matched),
        )

    if len(matched) > 1:
        # Same intent via multiple keywords -- safe, but worth surfacing since
        # it usually means the scan is named more loosely than intended.
        logger.info(
            f"ChartInk scan name matched multiple equivalent keywords "
            f"({', '.join(sorted(matched))}); resolved unambiguously."
        )

    return _KEYWORD_MAP[matched[0]]
