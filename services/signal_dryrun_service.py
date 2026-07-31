"""Dry-run a webhook signal: resolve exactly what WOULD be ordered.

Answers the question every trader has before going live -- "if TradingView
sends BUY right now, what actually happens?" -- without sending anything to
a broker. Until this existed the only way to find out was to arm the
strategy during market hours and watch, which is an expensive way to
discover a stale expiry or a strike outside the chain.

Deliberately reuses the SAME resolution helpers the live path uses
(services/signal_engine.py::_resolve_live_instrument, the mapping's own
resolve_execution/get_risk_config). A preview that computed things its own
way would be worse than no preview: it would agree with reality right up
until the moment it mattered.

Nothing here places, modifies or cancels an order.
"""

from __future__ import annotations

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _describe_risk(mapping) -> dict[str, Any]:
    risk = mapping.get_risk_config()
    out: dict[str, Any] = {}
    for key in ("stop_loss", "target", "trailing"):
        cfg = risk.get(key)
        if cfg:
            unit = "%" if cfg["type"] == "percent" else " pts"
            out[key] = {"value": cfg["value"], "type": cfg["type"], "display": f"{cfg['value']}{unit}"}
    return out


def dry_run_signal(strategy, signal: str, api_key: str | None) -> dict[str, Any]:
    """Resolve every mapping that `signal` would fire on `strategy`.

    Returns a report with one entry per matched rule:
        {
          "signal": "BUY",
          "matched": 2,
          "legs": [ {resolved order fields...}, ... ],
          "warnings": [...],
        }

    Each leg reports either the fully-resolved order (real tradable symbol,
    side, quantity, price type) or an `error` explaining why it could not be
    resolved -- which is precisely the information the live path would have
    logged and discarded.
    """
    from database.strategy_db import get_symbol_mappings
    from services.signal_engine import _mapping_sort_key, _resolve_live_instrument

    signal_action = (signal or "").strip().upper()
    report: dict[str, Any] = {
        "signal": signal_action,
        "strategy": strategy.name,
        "matched": 0,
        "legs": [],
        "warnings": [],
    }

    mappings = get_symbol_mappings(strategy.id) or []
    if not mappings:
        report["warnings"].append("This strategy has no rules configured yet.")
        return report

    # Match the same way the live engine does: legacy strategies collapse
    # SHORT/EXIT into SELL, unified strategies match the action exactly.
    execution_model = getattr(strategy, "execution_model", "legacy") or "legacy"
    if execution_model == "unified":
        matched = [m for m in mappings if (m.action or "").upper() == signal_action]
    else:
        normalized = "BUY" if signal_action in ("BUY", "COVER") else "SELL"
        matched = [
            m
            for m in mappings
            if (m.action or m.symbol or "").upper() in (normalized, "BOTH")
        ]

    active = [m for m in matched if m.is_active is not False]
    if matched and not active:
        report["warnings"].append(
            f"{len(matched)} rule(s) match '{signal_action}' but every one is paused."
        )

    ignored = [m for m in active if m.get_signal_action() == "IGNORE"]
    if ignored:
        report["warnings"].append(
            f"{len(ignored)} matching rule(s) are set to Ignore and will do nothing."
        )

    runnable = [m for m in active if m.get_signal_action() != "IGNORE"]
    runnable.sort(key=_mapping_sort_key)
    report["matched"] = len(runnable)

    if not runnable:
        if not matched:
            report["warnings"].append(
                f"No rule reacts to a '{signal_action}' signal. Add one, or check the "
                "signal name your alert sends."
            )
        return report

    needs_key = any(m.instrument_type in ("FUT", "OPT") for m in runnable)
    if needs_key and not api_key:
        report["warnings"].append(
            "No API key found for this account, so live F&O contracts cannot be resolved. "
            "Generate one on the API Key page."
        )

    for mapping in runnable:
        verb = mapping.get_signal_action()
        leg: dict[str, Any] = {
            "id": mapping.id,
            "label": mapping.label,
            "reacts_to": mapping.action or mapping.symbol,
            "does": verb,
            "instrument_type": mapping.instrument_type or "EQ",
            "basket": mapping.leg_basket,
        }

        # Resolve the live contract exactly as the order path would.
        resolved_symbol = None
        resolved_exchange = mapping.exchange
        if mapping.instrument_type in ("FUT", "OPT"):
            if not api_key:
                leg["error"] = "Needs an API key to resolve the live contract."
                report["legs"].append(leg)
                continue
            try:
                resolved = _resolve_live_instrument(mapping, api_key)
            except Exception as e:
                leg["error"] = f"Contract resolution failed: {e}"
                report["legs"].append(leg)
                continue
            if not resolved:
                leg["error"] = (
                    "Could not resolve a live contract. The expiry may have passed or the "
                    "strike may be outside the current chain."
                )
                report["legs"].append(leg)
                continue
            resolved_symbol, resolved_exchange = resolved
        else:
            resolved_symbol = mapping.instrument or mapping.symbol
            if not resolved_symbol:
                leg["error"] = "No instrument configured on this rule."
                report["legs"].append(leg)
                continue

        execution = mapping.resolve_execution(signal_action)

        # Same side derivation as the live path, including the EXIT/REDUCE
        # inversion -- a preview that showed BUY where the engine sends SELL
        # would be actively misleading.
        if mapping.order_side in ("BUY", "SELL"):
            side = mapping.order_side
        else:
            side = "SELL" if signal_action in ("SELL", "SHORT", "EXIT") else "BUY"
        if verb in ("EXIT", "REDUCE") and mapping.order_side not in ("BUY", "SELL"):
            side = "BUY" if side == "SELL" else "SELL"

        quantity = execution["quantity"]
        if mapping.lots:
            from services.signal_engine import _lookup_lot_size

            lot_size = _lookup_lot_size(resolved_symbol, resolved_exchange)
            if lot_size:
                quantity = mapping.resolve_quantity(lot_size)
                leg["lot_size"] = lot_size
            else:
                leg.setdefault("notes", []).append(
                    "Lot size could not be resolved; falling back to the raw quantity."
                )

        leg.update(
            {
                "symbol": resolved_symbol,
                "exchange": resolved_exchange,
                "side": side,
                "quantity": quantity,
                "order_type": mapping.order_type or execution["order_type"] or "MARKET",
                "product": execution["product"],
                "limit_price": mapping.limit_price,
                "trigger_price": mapping.trigger_price,
                "risk": _describe_risk(mapping),
            }
        )
        report["legs"].append(leg)

    # A basket is all-or-nothing at execution time, so warn here too rather
    # than letting the preview imply partial entry is acceptable.
    failed_baskets = {
        leg["basket"] for leg in report["legs"] if leg.get("basket") and leg.get("error")
    }
    for basket in sorted(failed_baskets):
        report["warnings"].append(
            f"Basket '{basket}' has a leg that cannot be resolved — the whole basket would be "
            "skipped, since a partially-filled basket is a one-sided position."
        )

    return report
