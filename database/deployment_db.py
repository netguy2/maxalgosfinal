"""Backward-compatible re-export shim.

StrategyVersion and Deployment used to live here under their own
SQLAlchemy Base/engine, separate from database/strategy_db.py's Strategy
model -- even though both point at the same physical maxalgos.db. That
split meant SQLAlchemy couldn't resolve foreign keys between
Deployment/StrategyVersion and Strategy, which caused three real bugs
(parallel init race, a dropped FK as a band-aid, and a session/mapper
mismatch). The models and their helpers now live in database/strategy_db.py
under one Base. This module just re-exports them so existing imports
(app.py, blueprints/deployments.py, services/deployment_service.py,
services/signal_engine.py) keep working unchanged.
"""

from database.strategy_db import (  # noqa: F401
    Deployment,
    StrategyVersion,
    append_deployment_heartbeat,
    create_deployment,
    create_strategy_version,
    db_session,
    delete_deployment,
    engine,
    get_deployment,
    get_user_deployments,
    set_deployment_last_trade,
    try_claim_deployment_for_entry,
    update_deployment_status,
)


def init_db():
    """No-op: table creation now happens via strategy_db.init_db().

    Kept so app.py's ensure_deployment_tables_exists() call (imported as
    `from database.deployment_db import init_db as ...`) remains valid --
    the Strategy DB init sequence in app.py already creates every table in
    this shared Base, so calling this a second time is harmless.
    """
    pass
