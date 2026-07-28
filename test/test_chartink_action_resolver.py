"""Regression tests for ChartInk scan-name action resolution.

The original implementation resolved the action with unanchored substring tests
(`if "BUY" in scan_name`), which could pick the WRONG SIDE of a live trade:

  - "BUYBACK ANNOUNCEMENT" contains "BUY"   -> placed a BUY entry
  - "COVERED CALL WRITING" contains "COVER" -> placed a COVER exit
  - "SELL TO COVER" contains SELL and COVER -> silently resolved to SELL

These tests pin the fixed behavior: word-boundary matching, and explicit
rejection of ambiguous names rather than guessing.
"""

import pytest

from services.chartink_action_resolver import ActionResolutionError, resolve_action

# (action, use_smart_order, is_entry_order) -- must match the original
# blueprints/chartink.py branch semantics exactly.
BUY = ("BUY", False, True)
SELL = ("SELL", True, False)
SHORT = ("SELL", False, True)
COVER = ("BUY", True, False)


@pytest.mark.parametrize(
    "scan_name,expected",
    [
        ("BUY Nifty Breakout", BUY),
        ("My SELL scan", SELL),
        ("SHORT setup", SHORT),
        ("COVER positions", COVER),
        ("buy nifty", BUY),  # case-insensitive
        ("Intraday BUY Signal", BUY),
        # Punctuation counts as a word boundary.
        ("NIFTY-BUY-SIGNAL", BUY),
        ("scan:SELL", SELL),
        ("[SHORT] setup", SHORT),
    ],
)
def test_correctly_named_scans_resolve_unchanged(scan_name, expected):
    """Behavior for well-formed scan names is preserved exactly."""
    assert resolve_action(scan_name) == expected


@pytest.mark.parametrize(
    "scan_name",
    [
        "BUYBACK ANNOUNCEMENT",  # previously resolved BUY
        "COVERED CALL WRITING",  # previously resolved COVER
        "SHORTLIST MOMENTUM",  # previously resolved SHORT
        "BUYERS ACTIVE",  # previously resolved BUY
    ],
)
def test_substring_collisions_no_longer_match(scan_name):
    """A keyword embedded in a larger word must not trigger a trade."""
    with pytest.raises(ActionResolutionError) as exc:
        resolve_action(scan_name)
    assert exc.value.code == "no_action_keyword"


@pytest.mark.parametrize(
    "scan_name",
    [
        "BUY / SELL REVERSAL",
        "SELL TO COVER",
        "SHORT and COVER scan",
    ],
)
def test_conflicting_keywords_are_rejected_not_guessed(scan_name):
    """Ambiguous names must fail loudly rather than pick the first match."""
    with pytest.raises(ActionResolutionError) as exc:
        resolve_action(scan_name)
    assert exc.value.code == "ambiguous_action"
    # The error names the conflicting keywords so the user can fix the scan.
    assert len(exc.value.found) > 1


@pytest.mark.parametrize("scan_name", ["Momentum Breakout", "", None, "OVERSOLD BOUNCE"])
def test_missing_keyword_is_rejected(scan_name):
    with pytest.raises(ActionResolutionError) as exc:
        resolve_action(scan_name)
    assert exc.value.code == "no_action_keyword"


class TestExplicitAction:
    """A structured `action` field bypasses name parsing entirely."""

    def test_explicit_action_overrides_ambiguous_name(self):
        assert resolve_action("AMBIGUOUS BUY SELL NAME", explicit_action="BUY") == BUY

    def test_explicit_action_overrides_unusable_name(self):
        assert resolve_action("total nonsense", explicit_action="SHORT") == SHORT

    def test_explicit_action_is_case_insensitive(self):
        assert resolve_action("BUYBACK", explicit_action="cover") == COVER

    def test_unrecognized_explicit_action_is_rejected(self):
        with pytest.raises(ActionResolutionError) as exc:
            resolve_action("whatever", explicit_action="SIDEWAYS")
        assert exc.value.code == "invalid_explicit_action"
