"""
Real coverage for services/strategy_compiler.py -- previously ZERO tests
existed for this module despite it being the sole translation layer between
a wizard/marketplace template's configuration and the conditions_tree
services/deployment_service.py's live evaluation loop actually executes.
Its own module docstring states the stakes plainly: without a compiled
tree, "deployments sat at status 'Waiting' forever, looking healthy, doing
nothing."

This suite proves, for every one of the 23 working compilers in
STRATEGY_TYPE_REGISTRY, that compiling a realistic config produces a tree
services/condition_engine.py can genuinely evaluate -- not just "doesn't
raise", but structurally valid per condition_engine.py's own leaf contract
(every leaf carries `indicator` + `condition`, exactly what
evaluate_conditions_tree's fail-closed check at condition_engine.py:171-179
requires to attempt a real comparison instead of silently treating a
malformed leaf as "not met").

Also covers: the 2 registry entries that must always raise CompilerError
(basket_strategy, options_strategy -- a wizard deploy of either must 400,
never silently persist an empty/no-op deployment), the CATALOG_ID_TO_SCHEMA_KEY
override table (the exact mapping a real marketplace template_id resolves
through), and the malformed-leaf defensive assertion itself.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from services.strategy_compiler import (  # noqa: E402
    CATALOG_ID_TO_SCHEMA_KEY,
    STRATEGY_TYPE_REGISTRY,
    CompilerError,
    _assert_no_malformed_leaves,
    _resolve_schema_key,
    compile_strategy_config,
)


def _walk_leaves(node: dict):
    """Yield every leaf (non-group) node in a compiled tree, recursively."""
    if not node:
        return
    if "operator" in node:
        for child in node.get("children", []):
            yield from _walk_leaves(child)
        return
    yield node


def _assert_valid_tree(tree: dict):
    """The structural contract every compiled tree must satisfy for
    condition_engine.py to evaluate it as a real (not silently-failing)
    condition -- mirrors _assert_no_malformed_leaves but asserts instead of
    raising, for clearer pytest failure output."""
    assert tree, "compiler produced an empty/falsy tree -- would evaluate as always-true (a no-op gate), never triggering the risk/order path meaningfully"
    leaves = list(_walk_leaves(tree))
    assert leaves, "tree has no leaves at all -- either a bare group with no children or a malformed structure"
    for leaf in leaves:
        assert leaf.get("indicator"), f"leaf missing 'indicator': {leaf}"
        assert leaf.get("condition"), f"leaf missing 'condition': {leaf}"
        assert leaf["condition"] in (">", "<", ">=", "<=", "==", "!="), (
            f"leaf has unrecognized condition operator (condition_engine.py's _compare only "
            f"handles >,<,>=,<=,==,!=): {leaf}"
        )
        # A leaf must carry EITHER a static `value` OR a `value_indicator` to
        # compare against -- condition_engine.py's line ~188 onward resolves
        # one or the other; neither present means the comparison target is
        # undefined.
        assert "value" in leaf or "value_indicator" in leaf, (
            f"leaf has no comparison target (value or value_indicator): {leaf}"
        )


# Every working compiler with a realistic, schema-shaped config -- values
# chosen to mirror frontend/src/lib/strategy-schemas.ts's documented
# defaults for each blueprint, not arbitrary numbers.
REALISTIC_CONFIGS: dict[str, dict] = {
    "orb": {"orbDuration": 15, "breakoutDirection": "both"},
    "ema_cross": {"fastEma": 9, "slowEma": 21, "exitOnReverse": True},
    "rsi_momentum": {"rsiLength": 14, "buyAbove": 55, "sellBelow": 45},
    "sma_cross": {"fastSma": 50, "slowSma": 200},
    "macd_momentum": {"fastPeriod": 12, "slowPeriod": 26},
    "rsi_reversal": {"rsiLength": 14, "oversoldLevel": 30, "overboughtLevel": 70},
    "swing_breakout": {"lookbackPeriod": 10, "breakoutDirection": "both"},
    "roc_momentum": {"rocPeriod": 10},
    "prev_day_breakout": {"breakoutDirection": "both"},
    "supertrend": {"atrPeriod": 10, "multiplier": 3.0},
    "triple_ema": {"fastPeriod": 5, "midPeriod": 13, "slowPeriod": 34},
    "adx_trend": {"adxPeriod": 14},
    "volume_breakout": {"volumeMultiplier": 2.0},
    "inside_candle_breakout": {},
    "nr7_breakout": {},
    "bollinger_reversal": {"bbPeriod": 20, "bbStdDev": 2.0},
    "vwap_reversion": {},
    "keltner_reversion": {"emaPeriod": 20, "atrPeriod": 10, "atrMultiplier": 2.0},
    "donchian_pullback": {"donchianPeriod": 20},
    "ema_pullback": {"emaPeriod": 20, "trendEmaPeriod": 50},
    "vwap_scalp": {},
    "gap_strategy": {"gapThresholdPercent": 1.0},
    "bollinger_squeeze": {"bbPeriod": 20, "bbStdDev": 2.0},
    "atr_trend": {"atrPeriod": 14, "emaPeriod": 20, "atrMultiplier": 1.5},
}


class TestEveryWorkingCompilerProducesAValidTree:
    """One test per registry key with a realistic config -- if a compiler
    genuinely has 23 working strategy types, this is 23 concrete proofs,
    not one assertion glossing over all of them."""

    @pytest.mark.parametrize("schema_key,config", sorted(REALISTIC_CONFIGS.items()))
    def test_compiles_to_valid_tree(self, schema_key, config):
        compiler = STRATEGY_TYPE_REGISTRY[schema_key]
        tree = compiler(config)
        _assert_valid_tree(tree)

    def test_realistic_configs_covers_every_working_compiler(self):
        """Guard against silent drift: if a new compile_* is added to
        STRATEGY_TYPE_REGISTRY without adding a case here, this fails loudly
        instead of the new compiler quietly having zero test coverage."""
        untested_still_working = set(STRATEGY_TYPE_REGISTRY) - set(REALISTIC_CONFIGS) - {
            "basket_strategy", "options_strategy",  # covered separately below, always raise
        }
        assert not untested_still_working, (
            f"New compiler(s) registered with no test coverage: {untested_still_working}"
        )


class TestCompilerErrorContractsAreEnforced:
    """basket_strategy and options_strategy are documented to ALWAYS raise
    CompilerError from the wizard path -- a real deploy attempt must 400,
    never silently create a Deployment with an empty tree."""

    def test_basket_strategy_always_raises(self):
        with pytest.raises(CompilerError):
            STRATEGY_TYPE_REGISTRY["basket_strategy"]({})

    def test_options_strategy_always_raises(self):
        with pytest.raises(CompilerError):
            STRATEGY_TYPE_REGISTRY["options_strategy"]({})

    def test_ema_cross_rejects_inverted_periods(self):
        """fastEma >= slowEma is a real, user-reachable config error (not
        just a hypothetical) -- must raise, not silently compile a tree
        that can never fire (or fires nonsensically)."""
        with pytest.raises(CompilerError):
            STRATEGY_TYPE_REGISTRY["ema_cross"]({"fastEma": 21, "slowEma": 9})


class TestCompileStrategyConfigEntryPoint:
    """compile_strategy_config is what blueprints/deployments.py actually
    calls -- exercise it end-to-end (catalog id -> schema key -> compiler
    -> validated tree), not just the inner compile_* functions directly."""

    @pytest.mark.parametrize("catalog_id,expected_schema_key", sorted(CATALOG_ID_TO_SCHEMA_KEY.items()))
    def test_every_catalog_id_resolves_to_a_registered_compiler(self, catalog_id, expected_schema_key):
        """Every entry in the override table must point at a real,
        registered compiler -- a typo'd schema key here would silently
        404/error for every user who deploys that specific marketplace
        template, since _resolve_schema_key would resolve correctly but
        STRATEGY_TYPE_REGISTRY.get() would return None."""
        assert expected_schema_key in STRATEGY_TYPE_REGISTRY, (
            f"CATALOG_ID_TO_SCHEMA_KEY['{catalog_id}'] = '{expected_schema_key}' "
            f"is not a registered compiler"
        )

    def test_end_to_end_compile_for_a_real_catalog_id(self):
        """ema-9-21 is a real marketplace catalog id (marketplace-catalog.ts)
        -- prove the full template_id -> tree path a live deploy takes."""
        tree = compile_strategy_config("ema-9-21", {"fastEma": 9, "slowEma": 21})
        _assert_valid_tree(tree)

    def test_basket_catalog_ids_raise_through_the_full_entry_point(self):
        """The 4 basket marketplace templates (eq-weight, top-vol,
        top-gainers, sector-basket) must 400 if routed through the wizard's
        compile_strategy_config -- confirms the fix in
        StrategyConfigurator.tsx (disabling Paper Trading for these) is
        guarding a REAL backend failure, not a hypothetical one."""
        for catalog_id in ("eq-weight", "top-vol", "top-gainers", "sector-basket"):
            with pytest.raises(CompilerError):
                compile_strategy_config(catalog_id, {})

    def test_unrecognized_template_id_falls_back_to_orb_not_an_error(self):
        """_resolve_schema_key's fallback chain (strategy_compiler.py:104-128)
        has no path that returns an unregistered key -- every branch resolves
        to orb/ema_cross/supertrend/rsi_momentum/options_strategy, all
        registered. So an unrecognized template_id compiles successfully
        (falls back to 'orb') rather than raising -- confirmed here rather
        than assumed, since compile_strategy_config's "No compiler
        registered" branch (line 677-678) is defensive code for a
        registry-vs-resolver mismatch that can't currently happen, not a
        reachable error path for a bad template_id string."""
        tree = compile_strategy_config("totally-unknown-template-xyz-does-not-exist", {})
        _assert_valid_tree(tree)

    def test_empty_template_id_defaults_to_orb_and_still_compiles(self):
        """_resolve_schema_key falls back to 'orb' for a None/empty
        template_id (strategy_compiler.py:110-111) -- confirm that fallback
        itself still produces a valid, evaluable tree rather than silently
        defaulting into a broken state."""
        tree = compile_strategy_config(None, {})
        _assert_valid_tree(tree)

    def test_none_config_defaults_to_empty_dict_and_still_compiles(self):
        tree = compile_strategy_config("orb-15", None)
        _assert_valid_tree(tree)


class TestMalformedLeafAssertionCatchesRealBugs:
    """_assert_no_malformed_leaves is the last line of defense before a
    compiled tree is persisted -- prove it actually catches what it claims
    to catch, not just that it exists."""

    def test_passes_on_well_formed_tree(self):
        _assert_no_malformed_leaves(
            {"operator": "OR", "children": [
                {"indicator": "SPOT", "condition": ">", "value": 100},
            ]}
        )  # must not raise

    def test_raises_on_leaf_missing_indicator(self):
        with pytest.raises(CompilerError, match="malformed leaf"):
            _assert_no_malformed_leaves({"condition": ">", "value": 100})

    def test_raises_on_leaf_missing_condition(self):
        with pytest.raises(CompilerError, match="malformed leaf"):
            _assert_no_malformed_leaves({"indicator": "SPOT", "value": 100})

    def test_raises_on_malformed_leaf_nested_in_group(self):
        with pytest.raises(CompilerError, match="malformed leaf"):
            _assert_no_malformed_leaves(
                {"operator": "AND", "children": [
                    {"indicator": "SPOT", "condition": ">", "value": 100},
                    {"condition": "<"},  # missing indicator -- must be caught even nested
                ]}
            )

    def test_empty_node_is_a_noop_not_an_error(self):
        _assert_no_malformed_leaves({})  # must not raise
        _assert_no_malformed_leaves(None)  # must not raise
