import logging
import time

from services.indicator_engine import calculate_indicator
from services.indicator_registry import (
    indicator_api_key_context,  # noqa: F401 -- re-exported for callers (e.g. deployment_service.py)
)

logger = logging.getLogger(__name__)


def _resolve_indicator_value(indicator: str, symbol: str, exchange: str, params: dict) -> float:
    """Resolve one live indicator value. Shared by both the primary
    `indicator` and the optional `value_indicator` side of a comparison leaf
    (see evaluate_conditions_tree Case 2) so both go through identical
    resolution/error-handling logic."""
    try:
        if indicator.upper() in ("SPOT", "LTP"):
            from services.indicator_registry import _indicator_api_key_var, _indicator_broker_var
            from services.market_data_service import get_ltp_value
            return (
                get_ltp_value(
                    symbol,
                    exchange,
                    api_key=_indicator_api_key_var.get(),
                    broker=_indicator_broker_var.get(),
                )
                or 0.0
            )
        # Pass through whatever extra kwargs the leaf carries (period,
        # interval, duration, etc.) -- calculate_indicator's **kwargs
        # signature and every indicator plugin's calculate(**kwargs) only
        # read the specific keys they care about, so unrelated leaf keys
        # (operator, condition, value_indicator, ...) are safely ignored.
        return calculate_indicator(indicator, symbol, exchange, **params)
    except Exception as e:
        logger.error(f"Error fetching indicator {indicator} value: {e}")
        return 0.0


def _compare(curr_val, condition: str, target_val) -> bool:
    """Shared comparison-operator switch used by both the indicator leaf
    and the newer system-condition leaf types (signal_fresh, etc.) so the
    >/</>=/<=/==/!= handling lives in exactly one place."""
    try:
        curr_val = float(curr_val)
        target_val = float(target_val)
    except (TypeError, ValueError):
        # Fall back to string comparison if not float-convertible
        curr_val = str(curr_val)
        target_val = str(target_val)

    if condition == ">":
        return curr_val > target_val
    elif condition == "<":
        return curr_val < target_val
    elif condition == ">=":
        return curr_val >= target_val
    elif condition == "<=":
        return curr_val <= target_val
    elif condition == "==":
        return curr_val == target_val
    elif condition == "!=":
        return curr_val != target_val
    else:
        logger.warning(f"Unsupported comparison condition operator: {condition}")
        return False


def evaluate_conditions_tree(
    node: dict, symbol: str, exchange: str, *, context: dict | None = None
) -> bool:
    """
    Recursively evaluates a nested boolean tree node against the live feed of
    a symbol.

    `context` (keyword-only, defaults to None) carries data that non-
    indicator leaf types need but indicator leaves don't: currently
    `{"username": str, "signal_timestamp": int}`, populated by
    services/signal_engine.py's _leg_condition_met for leg-group condition
    gating. Every other existing caller (services/deployment_service.py)
    omits it and is completely unaffected -- indicator leaves never read
    `context`, and it's only required by the new system-condition leaf
    types (broker_connected, signal_fresh) added below, which fail closed
    with a clear log if the caller didn't provide what they need rather
    than silently passing a live-trading gate.
    """
    if not node:
        return True

    # Case 1: Logical Group Node (AND/OR)
    if "operator" in node:
        operator = node["operator"].upper()
        children = node.get("children", [])

        if not children:
            return True

        if operator == "AND":
            return all(
                evaluate_conditions_tree(child, symbol, exchange, context=context)
                for child in children
            )
        elif operator == "OR":
            return any(
                evaluate_conditions_tree(child, symbol, exchange, context=context)
                for child in children
            )
        else:
            logger.warning(f"Unsupported logical operator: {operator}")
            return False

    # Case 2: Leaf node -- dispatch on `type`. Absent/"indicator" is the
    # original (and still default) shape, kept fully backward-compatible
    # with every leaf ever saved before `type` existed.
    leaf_type = (node.get("type") or "indicator").lower()

    if leaf_type == "market_open":
        from database.market_calendar_db import is_market_open

        return is_market_open(node.get("exchange") or exchange)

    if leaf_type == "broker_connected":
        username = (context or {}).get("username")
        if not username:
            logger.error(
                "Condition leaf type 'broker_connected' has no username in context -- "
                "cannot evaluate. Treating as not met."
            )
            return False

        from database.auth_db import get_broker_session, list_broker_sessions

        broker = node.get("broker")
        if broker:
            return get_broker_session(username, broker) is not None
        return any(not s.get("is_revoked") for s in list_broker_sessions(username))

    if leaf_type == "signal_fresh":
        signal_timestamp = (context or {}).get("signal_timestamp")
        if signal_timestamp is None:
            logger.error(
                "Condition leaf type 'signal_fresh' has no signal_timestamp in context -- "
                "cannot evaluate. Treating as not met."
            )
            return False

        age_seconds = time.time() - signal_timestamp
        return _compare(age_seconds, node.get("condition", "<"), node.get("value_seconds"))

    if leaf_type != "indicator":
        logger.warning(f"Unsupported condition leaf type: {leaf_type}")
        return False

    # Indicator comparison leaf (the original/default shape).
    indicator = node.get("indicator")
    condition = node.get("condition")

    if not indicator or not condition:
        # Fail closed: a malformed leaf (missing the two keys required to
        # even attempt a comparison) must never silently pass a live-trading
        # condition. services/strategy_compiler.py's contract is to never
        # emit such a leaf in the first place (enforced by its own
        # _assert_no_malformed_leaves before persisting); this is a defense-
        # in-depth backstop for any other caller of evaluate_conditions_tree.
        logger.error(f"Malformed condition leaf (missing indicator/condition): {node}")
        return False

    # 1. Resolve the live value of the primary indicator.
    curr_val = _resolve_indicator_value(indicator, symbol, exchange, node)

    # 2. Resolve the comparison target -- either a second live indicator
    # (value_indicator), letting a leaf express "SPOT > ORB_HIGH" or
    # "EMA(fast) > EMA(slow)" rather than only a static number, or the
    # existing static "value".
    value_indicator = node.get("value_indicator")
    if value_indicator:
        # Merge value_indicator_params over the leaf's own kwargs so both
        # sides of a comparison can pass the SAME param name (e.g. "period")
        # with DIFFERENT values without colliding in one leaf dict.
        merged_params = {**node, **node.get("value_indicator_params", {})}
        target_val = _resolve_indicator_value(value_indicator, symbol, exchange, merged_params)
    else:
        target_val = node.get("value")

    return _compare(curr_val, condition, target_val)


def describe_first_leaf(node: dict, symbol: str, exchange: str) -> str | None:
    """Human-readable summary of the first comparison leaf found in a
    conditions tree, e.g. "EMA_9 (21450.30) > EMA_21 (21460.10)".

    Used only for deployment-status visibility (the "waiting" heartbeat) --
    NOT part of evaluate_conditions_tree's actual pass/fail logic, so it
    can't affect trading decisions. Walks AND/OR groups depth-first and
    describes the first leaf it finds; a tree with multiple leaves still
    only surfaces one representative comparison, which is enough to show
    a user real numbers are being checked without re-deriving the whole
    tree's boolean outcome a second time.
    """
    if not node:
        return None

    if "operator" in node:
        for child in node.get("children", []):
            desc = describe_first_leaf(child, symbol, exchange)
            if desc:
                return desc
        return None

    leaf_type = (node.get("type") or "indicator").lower()

    if leaf_type == "market_open":
        return f"Market Open ({node.get('exchange') or exchange})"
    if leaf_type == "broker_connected":
        return f"Broker Connected ({node.get('broker') or 'any'})"
    if leaf_type == "signal_fresh":
        return f"Signal Fresh ({node.get('condition', '<')}{node.get('value_seconds')}s)"

    indicator = node.get("indicator")
    condition = node.get("condition")
    if not indicator or not condition:
        return None

    try:
        curr_val = _resolve_indicator_value(indicator, symbol, exchange, node)
        value_indicator = node.get("value_indicator")
        if value_indicator:
            merged_params = {**node, **node.get("value_indicator_params", {})}
            target_val = _resolve_indicator_value(value_indicator, symbol, exchange, merged_params)
            target_label = f"{value_indicator} ({target_val})"
        else:
            target_val = node.get("value")
            target_label = str(target_val)

        return f"{indicator} ({curr_val}) {condition} {target_label}"
    except Exception:
        return None
