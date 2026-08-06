"""Tests for services/ai_insight_service.py's deterministic trade-level math.

These specifically cover the fix for stop_loss/target/position_size_pct
previously being whatever number the LLM wrote into its JSON response, with
no server-side check that it actually matched the ATR/support-resistance
data it was given. compute_deterministic_trade_levels() is now the sole
source of those numbers -- the model no longer contributes anything numeric,
only a rationale sentence and the qualitative fields tested elsewhere.
"""

from services.ai_insight_service import (
    _validate_trade_levels,
    compute_deterministic_trade_levels,
)


class TestComputeDeterministicTradeLevels:
    def test_neutral_sentiment_returns_none(self):
        assert (
            compute_deterministic_trade_levels(
                sentiment="neutral",
                confidence=80,
                live_price=100.0,
                atr=2.0,
                support_resistance=None,
                model_rationale=None,
            )
            is None
        )

    def test_no_live_price_returns_none(self):
        assert (
            compute_deterministic_trade_levels(
                sentiment="bullish",
                confidence=80,
                live_price=None,
                atr=2.0,
                support_resistance=None,
                model_rationale=None,
            )
            is None
        )

    def test_no_atr_and_no_support_resistance_returns_none(self):
        assert (
            compute_deterministic_trade_levels(
                sentiment="bullish",
                confidence=80,
                live_price=100.0,
                atr=None,
                support_resistance=None,
                model_rationale=None,
            )
            is None
        )

    def test_bullish_atr_only_uses_atr_projection(self):
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert result is not None
        # No support/resistance data -> stop is exactly 1x ATR below price,
        # target is exactly 2x ATR above -- real arithmetic, not a guess.
        assert result["stop_loss"] == 98.0
        assert result["target"] == 104.0

    def test_bearish_atr_only_uses_atr_projection(self):
        result = compute_deterministic_trade_levels(
            sentiment="bearish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert result is not None
        assert result["stop_loss"] == 102.0
        assert result["target"] == 96.0

    def test_bullish_target_prefers_nearest_real_resistance_over_atr(self):
        sr = {"resistance": [{"price": 103.0, "touches": 4}, {"price": 110.0, "touches": 2}]}
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,  # would project to 104.0 -- the real level (103.0) must win
            support_resistance=sr,
            model_rationale=None,
        )
        assert result is not None
        assert result["target"] == 103.0

    def test_bullish_stop_takes_the_more_conservative_of_atr_and_support(self):
        # ATR stop = 100 - 2 = 98. A real support level sits at 99, which is
        # TIGHTER (more conservative, per the system prompt's own stated
        # rule) -- the tighter one must win, not simply "the real level".
        sr = {"support": [{"price": 99.0, "touches": 3}]}
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=sr,
            model_rationale=None,
        )
        assert result is not None
        assert result["stop_loss"] == 99.0

        # And the reverse: a distant support level (90) must NOT override a
        # tighter ATR stop (98) -- max() picks the closer-to-price value for
        # a bullish stop below price.
        sr_far = {"support": [{"price": 90.0, "touches": 3}]}
        result_far = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=sr_far,
            model_rationale=None,
        )
        assert result_far is not None
        assert result_far["stop_loss"] == 98.0

    def test_position_size_scales_down_with_lower_confidence(self):
        high_conf = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=90,
            live_price=100.0,
            atr=1.0,
            support_resistance=None,
            model_rationale=None,
        )
        low_conf = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=20,
            live_price=100.0,
            atr=1.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert high_conf is not None and low_conf is not None
        assert low_conf["position_size_pct"] < high_conf["position_size_pct"]

    def test_position_size_scales_down_with_higher_volatility(self):
        low_vol = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=0.5,
            support_resistance=None,
            model_rationale=None,
        )
        high_vol = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=20.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert low_vol is not None and high_vol is not None
        assert high_vol["position_size_pct"] < low_vol["position_size_pct"]

    def test_position_size_never_exceeds_25_percent(self):
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=100,
            live_price=100.0,
            atr=0.01,
            support_resistance=None,
            model_rationale=None,
        )
        assert result is not None
        assert result["position_size_pct"] <= 25.0

    def test_position_size_never_below_1_percent(self):
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=1,
            live_price=100.0,
            atr=50.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert result is not None
        assert result["position_size_pct"] >= 1.0

    def test_model_rationale_is_used_when_provided(self):
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=None,
            model_rationale="Strong momentum with RSI confirmation.",
        )
        assert result is not None
        assert result["rationale"] == "Strong momentum with RSI confirmation."

    def test_fallback_rationale_when_model_gave_none(self):
        result = compute_deterministic_trade_levels(
            sentiment="bullish",
            confidence=80,
            live_price=100.0,
            atr=2.0,
            support_resistance=None,
            model_rationale=None,
        )
        assert result is not None
        assert "ATR" in result["rationale"] or "support-resistance" in result["rationale"]


class TestValidateTradeLevelsShapeOnly:
    """_validate_trade_levels now only checks shape and salvages
    `rationale` -- the numeric fields it previously trusted from the model
    are intentionally discarded by the caller in favor of
    compute_deterministic_trade_levels()."""

    def test_valid_shape_returns_only_rationale(self):
        result = _validate_trade_levels(
            {"stop_loss": 95.0, "target": 110.0, "position_size_pct": 10.0, "rationale": "test"}
        )
        assert result == {"rationale": "test"}

    def test_missing_field_returns_none(self):
        assert _validate_trade_levels({"stop_loss": 95.0, "target": 110.0}) is None

    def test_non_numeric_field_returns_none(self):
        assert (
            _validate_trade_levels(
                {
                    "stop_loss": "not-a-number",
                    "target": 110.0,
                    "position_size_pct": 10.0,
                    "rationale": "x",
                }
            )
            is None
        )

    def test_not_a_dict_returns_none(self):
        assert _validate_trade_levels(None) is None
        assert _validate_trade_levels("garbage") is None
