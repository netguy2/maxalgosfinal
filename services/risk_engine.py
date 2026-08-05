import logging
import json
from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

logger = logging.getLogger(__name__)


def validate_risk(deployment, next_trade_value: float = 0.0) -> tuple[bool, str]:
    """
    Validates a deployment instance against its risk management rules.
    Returns:
        Tuple of (is_safe: bool, reason: str)
    """
    try:
        risk_params = json.loads(deployment.risk_params) if deployment.risk_params else {}
    except Exception:
        risk_params = {}

    pnl = deployment.pnl or 0.0
    trades_count = deployment.trades_count or 0

    # 1. Daily Loss Limit
    daily_loss_limit = risk_params.get("daily_loss_limit")
    if daily_loss_limit:
        try:
            limit = float(daily_loss_limit)
            if pnl < -limit:
                return False, f"Daily Loss Limit of {limit} breached (Current P&L: {pnl})"
        except (ValueError, TypeError):
            pass

    # 2. Maximum Trades per Day
    max_trades = risk_params.get("max_trades")
    if max_trades:
        try:
            limit = int(max_trades)
            if trades_count >= limit:
                return False, f"Maximum daily trades limit of {limit} reached"
        except (ValueError, TypeError):
            pass

    # 3. Cooldown Enforcement
    #
    # Deliberately reads last_trade_at, NOT updated_at. updated_at is bumped
    # by SQLAlchemy's onupdate on every commit to this row, including the
    # heartbeat written every ~30s while conditions haven't matched yet
    # (see database/strategy_db.py's append_deployment_heartbeat) -- reading
    # that here meant the cooldown timer reset itself continuously just
    # from the deployment being evaluated, so it could never actually
    # elapse. last_trade_at is only set at the moment an order is placed
    # (set_deployment_last_trade), so a deployment that hasn't traded yet
    # has no cooldown to enforce.
    cooldown_min = risk_params.get("cooldown")
    if cooldown_min and deployment.last_trade_at:
        try:
            cooldown_period = timedelta(minutes=int(cooldown_min))
            # last_trade_at is DateTime(timezone=True): on Postgres this reads
            # back as timezone-AWARE, but on SQLite it reads back naive
            # regardless of the column declaration. Normalize before
            # comparing so this works on either backend -- comparing a naive
            # datetime.utcnow() directly against an aware value raised
            # TypeError, which the broad `except (ValueError, TypeError)`
            # below silently swallowed, making this cooldown check a no-op
            # (always falling through to "risk validation passed") on
            # Postgres with zero logging. See services/risk_engine.py commit
            # history / CLAUDE.md for the Postgres migration context.
            last_trade_at = deployment.last_trade_at
            if last_trade_at.tzinfo is None:
                last_trade_at = last_trade_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - last_trade_at < cooldown_period:
                return False, "Cooldown period is active"
        except (ValueError, TypeError) as e:
            logger.warning(f"Cooldown check skipped due to invalid cooldown/last_trade_at value: {e}")

    # 4. Capital Allocation Limit
    if next_trade_value > deployment.capital:
        return False, f"Insufficient allocated capital (Order value: {next_trade_value}, Capital: {deployment.capital})"

    return True, "Risk validation passed"
