"""Server-side validator for client-authored conditions_tree JSON, used by
the no-code custom strategy builder (Tradetron-style condition tree).

This is NOT a compiler -- there is nothing to translate. The client tree
IS the executable shape services.condition_engine.evaluate_conditions_tree
already interprets for wizard-created deployments. The only new work here
is validating that a user-authored tree is well-formed and safe to
evaluate every cycle, since (unlike compile_strategy_config's fixed 26
blueprints) a hand-authored tree can reference an unknown/typo'd indicator
name or be arbitrarily deep/wide.

blueprints/deployments.py::create_new_deployment deliberately never
accepts a client-supplied conditions_tree for wizard deployments (always
recompiles server-side via compile_strategy_config) -- this validator is a
second, parallel, EXPLICITLY client-authored path into
Deployment.conditions_tree for Strategy rows with
template_id == "custom_builder", not a change to that trust boundary.
"""

from services.indicator_registry import IndicatorRegistry
from services.strategy_compiler import CompilerError, _assert_no_malformed_leaves

# Bounds per-cycle evaluation cost in services/deployment_service.py's
# _evaluation_loop -- each leaf is one live indicator calculation (a
# broker API call or cached lookup), so an unbounded tree is a real
# perf/DoS risk against the single evaluation thread that services every
# waiting deployment.
MAX_TREE_DEPTH = 6
MAX_TREE_NODES = 60

_COMPARISON_OPERATORS = {">", "<", ">=", "<=", "==", "!="}
_SYSTEM_CONDITION_TYPES = {"market_open", "broker_connected", "signal_fresh"}
# SPOT/LTP are handled directly by condition_engine.py, not registered in
# IndicatorRegistry -- valid indicator references for a leaf's `indicator`/
# `value_indicator` are the union of these two sets.
_PSEUDO_INDICATORS = {"SPOT", "LTP"}


class TreeValidationError(ValueError):
    """Raised when a client-authored conditions_tree fails validation.
    Callers (blueprints/strategy.py) must treat this as a 400 and refuse
    to save/deploy the tree -- mirrors services.strategy_compiler.CompilerError's
    role for the wizard path."""


def _valid_indicator_names() -> set[str]:
    return {name.upper() for name in IndicatorRegistry.list_indicators()} | _PSEUDO_INDICATORS


def _validate_node(node: dict, depth: int, node_counter: list[int]) -> None:
    if depth > MAX_TREE_DEPTH:
        raise TreeValidationError(
            f"Condition tree exceeds the maximum nesting depth of {MAX_TREE_DEPTH}."
        )

    if not isinstance(node, dict):
        raise TreeValidationError(f"Condition tree node must be an object, got: {type(node).__name__}")

    node_counter[0] += 1
    if node_counter[0] > MAX_TREE_NODES:
        raise TreeValidationError(
            f"Condition tree exceeds the maximum of {MAX_TREE_NODES} total nodes."
        )

    # Group node: {"operator": "AND"/"OR", "children": [...]}
    if "operator" in node:
        operator = str(node.get("operator", "")).upper()
        if operator not in ("AND", "OR"):
            raise TreeValidationError(f"Unsupported logical operator: {node.get('operator')!r}")
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise TreeValidationError("A group node must have a non-empty 'children' list.")
        for child in children:
            _validate_node(child, depth + 1, node_counter)
        return

    leaf_type = str(node.get("type") or "indicator").lower()

    if leaf_type in _SYSTEM_CONDITION_TYPES:
        if leaf_type == "signal_fresh":
            if node.get("condition") not in _COMPARISON_OPERATORS:
                raise TreeValidationError(
                    f"signal_fresh leaf has an unsupported comparison operator: {node.get('condition')!r}"
                )
            if not isinstance(node.get("value_seconds"), int | float):
                raise TreeValidationError("signal_fresh leaf requires a numeric 'value_seconds'.")
        return

    if leaf_type != "indicator":
        raise TreeValidationError(
            f"Unsupported condition leaf type: {leaf_type!r}. "
            f"Supported types: indicator, {', '.join(sorted(_SYSTEM_CONDITION_TYPES))}."
        )

    # Reuse the exact malformed-leaf contract compile_strategy_config
    # enforces server-side -- a leaf missing indicator/condition fails
    # closed (evaluates to False) rather than auto-passing, which would be
    # a landmine for a live-trading system. Re-raised as
    # TreeValidationError so every rejection this validator produces is
    # one consistent exception type for callers to catch.
    try:
        _assert_no_malformed_leaves(node)
    except CompilerError as e:
        raise TreeValidationError(str(e)) from e

    valid_names = _valid_indicator_names()
    indicator = str(node.get("indicator", "")).upper()
    if indicator not in valid_names:
        raise TreeValidationError(
            f"Unknown indicator: {node.get('indicator')!r}. "
            f"Valid indicators: {', '.join(sorted(valid_names))}."
        )

    if node.get("condition") not in _COMPARISON_OPERATORS:
        raise TreeValidationError(f"Unsupported comparison operator: {node.get('condition')!r}")

    value_indicator = node.get("value_indicator")
    if value_indicator is not None:
        value_indicator_upper = str(value_indicator).upper()
        if value_indicator_upper not in valid_names:
            raise TreeValidationError(
                f"Unknown value_indicator: {value_indicator!r}. "
                f"Valid indicators: {', '.join(sorted(valid_names))}."
            )
    elif "value" not in node:
        raise TreeValidationError(
            "A comparison leaf must have either a static 'value' or a 'value_indicator'."
        )


def validate_conditions_tree(tree: dict) -> None:
    """Raises TreeValidationError on any structural/whitelist violation.
    Returns None (not a copy/transform) on success -- the validated tree is
    used byte-for-byte as-authored, since (unlike compile_strategy_config)
    there is nothing to translate."""
    if not tree:
        raise TreeValidationError("Condition tree must not be empty.")
    _validate_node(tree, depth=1, node_counter=[0])
