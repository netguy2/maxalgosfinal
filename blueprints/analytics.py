"""Performance analytics API.

Computes real portfolio analytics from the Sandbox (paper-trading / analyzer)
tables and the latency database. There is no separate live-trade store, so the
P&L figures here are sourced from Sandbox activity and are labelled as such on
the frontend. No values are fabricated: when there is not enough data to compute
a metric honestly (e.g. Sharpe/drawdown with < 2 days of history), the field is
returned as null and the UI renders "—".
"""

from datetime import date

from cachetools import TTLCache
from flask import Blueprint, jsonify, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

analytics_bp = Blueprint("analytics_bp", __name__, url_prefix="/analytics_api")

# Short per-user cache — analytics is polled by the dashboard; recomputing the
# aggregates on every poll is wasteful. Mirrors the TTLCache pattern used by
# database/latency_db.py.
_summary_cache: TTLCache = TTLCache(maxsize=256, ttl=10)


def _to_float(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _compute_summary(user_id: str) -> dict:
    """Aggregate real analytics for a user from the sandbox + latency stores."""
    from sqlalchemy import case, func

    from database.sandbox_db import (
        SandboxDailyPnL,
        SandboxFunds,
        SandboxPositions,
        SandboxTrades,
    )
    from database.sandbox_db import (
        db_session as sandbox_session,
    )

    # --- Trade counts & win rate (from closed/realized positions) ------------
    # A "win" is a position whose accumulated realized P&L is positive. This is
    # an honest proxy for round-trip outcomes given the sandbox schema.
    pos_stats = sandbox_session.query(
        func.count(SandboxPositions.id).label("total"),
        func.sum(
            case((SandboxPositions.accumulated_realized_pnl > 0, 1), else_=0)
        ).label("wins"),
        func.sum(
            case((SandboxPositions.accumulated_realized_pnl != 0, 1), else_=0)
        ).label("closed"),
        func.sum(SandboxPositions.accumulated_realized_pnl).label("realized"),
        func.sum(SandboxPositions.pnl).label("unrealized"),
    ).filter(SandboxPositions.user_id == user_id).first()

    closed_count = int(pos_stats.closed or 0) if pos_stats else 0
    wins = int(pos_stats.wins or 0) if pos_stats else 0
    realized_pnl = _to_float(pos_stats.realized) if pos_stats else 0.0
    unrealized_pnl = _to_float(pos_stats.unrealized) if pos_stats else 0.0
    win_rate = round((wins / closed_count * 100), 1) if closed_count else None

    # Total executed trades (fills)
    trades_total = (
        sandbox_session.query(func.count(SandboxTrades.id))
        .filter(SandboxTrades.user_id == user_id)
        .scalar()
        or 0
    )
    trades_today = (
        sandbox_session.query(func.count(SandboxTrades.id))
        .filter(
            SandboxTrades.user_id == user_id,
            func.date(SandboxTrades.trade_timestamp) == date.today(),
        )
        .scalar()
        or 0
    )

    # --- Funds snapshot (today realized) -------------------------------------
    funds = (
        sandbox_session.query(SandboxFunds)
        .filter(SandboxFunds.user_id == user_id)
        .first()
    )
    today_realized = _to_float(funds.today_realized_pnl) if funds else 0.0
    used_margin = _to_float(funds.used_margin) if funds else 0.0
    if funds:
        # Prefer the authoritative funds figures when present
        realized_pnl = _to_float(funds.realized_pnl)

    # --- Equity curve → drawdown + Sharpe (from daily EOD snapshots) ---------
    daily_rows = (
        sandbox_session.query(SandboxDailyPnL)
        .filter(SandboxDailyPnL.user_id == user_id)
        .order_by(SandboxDailyPnL.date.asc())
        .all()
    )
    equity = [_to_float(r.portfolio_value) for r in daily_rows]

    max_drawdown = None
    sharpe = None
    if len(equity) >= 2:
        # Peak-to-trough drawdown on the equity curve (percent, positive number)
        peak = equity[0]
        worst = 0.0
        for value in equity:
            if value > peak:
                peak = value
            if peak > 0:
                dd = (peak - value) / peak * 100
                if dd > worst:
                    worst = dd
        max_drawdown = round(worst, 1)

        # Daily returns → annualized Sharpe (rf = 0)
        returns = []
        for i in range(1, len(equity)):
            prev = equity[i - 1]
            if prev:
                returns.append((equity[i] - prev) / prev)
        if len(returns) >= 2:
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
            std = variance ** 0.5
            if std > 0:
                sharpe = round((mean / std) * (252 ** 0.5), 2)

    total_pnl = round(realized_pnl + unrealized_pnl, 2)

    # --- Active deployments --------------------------------------------------
    from database.strategy_db import get_user_deployments

    running_states = {"Deploying", "Waiting", "Entering", "Managing"}
    try:
        deployments = get_user_deployments(user_id)
        active_deployments = sum(1 for d in deployments if d.status in running_states)
    except Exception:
        active_deployments = 0

    # --- Latency (real) ------------------------------------------------------
    order_latency = None
    ws_latency = None
    try:
        from database.latency_db import OrderLatency

        stats = OrderLatency.get_latency_stats()
        if stats and stats.get("total_orders"):
            order_latency = round(_to_float(stats.get("avg_total")), 1)
    except Exception:
        pass

    return {
        "source": "sandbox",  # analytics are computed from sandbox/analyzer activity
        "total_pnl": total_pnl,
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "today_realized_pnl": round(today_realized, 2),
        "win_rate": win_rate,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "trades_total": int(trades_total),
        "trades_today": int(trades_today),
        "closed_trades": closed_count,
        "used_margin": round(used_margin, 2),
        "active_deployments": active_deployments,
        "order_latency_ms": order_latency,
        "ws_latency_ms": ws_latency,
        "has_data": bool(trades_total or closed_count or equity),
    }


@analytics_bp.route("/summary", methods=["GET"])
@check_session_validity
def get_analytics_summary():
    """Return real performance analytics for the current user."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    cached = _summary_cache.get(user_id)
    if cached is not None:
        return jsonify({"status": "success", "data": cached})

    try:
        summary = _compute_summary(user_id)
        _summary_cache[user_id] = summary
        return jsonify({"status": "success", "data": summary})
    except Exception as e:
        logger.exception(f"Error computing analytics summary: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        # Release the scoped session used by this request thread (FD hygiene)
        try:
            from database.sandbox_db import db_session as sandbox_session

            sandbox_session.remove()
        except Exception:
            pass
