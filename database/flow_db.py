# database/flow_db.py

import logging
import os
import secrets

from cachetools import TTLCache
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine

logger = logging.getLogger(__name__)

# Flow workflow caches - 5 minute TTL for webhook lookups (high frequency)
_workflow_webhook_cache = TTLCache(maxsize=5000, ttl=300)  # 5 minutes TTL
_workflow_cache = TTLCache(maxsize=1000, ttl=600)  # 10 minutes TTL

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


def generate_webhook_token():
    """Generate a unique webhook token"""
    return secrets.token_urlsafe(32)


def generate_webhook_secret():
    """Generate a unique webhook secret for message validation"""
    return secrets.token_hex(32)


def get_workflow_api_key(workflow):
    """Decrypt and return a workflow's stored Max Algos API key.

    The api_key column transitioned from plaintext to Fernet-encrypted
    (auth_db Fernet, PBKDF2 over API_KEY_PEPPER). Pre-migration plaintext
    rows are returned as-is via safe_decrypt_token's fallback.
    """
    if not workflow or not workflow.api_key:
        return None
    from database.auth_db import safe_decrypt_token
    return safe_decrypt_token(workflow.api_key)


def _encrypt_api_key(api_key):
    """Encrypt an API key for storage in flow_workflows.api_key."""
    if not api_key:
        return None
    from database.auth_db import encrypt_token
    return encrypt_token(api_key)


class FlowWorkflow(Base):
    """Model for flow workflows"""

    __tablename__ = "flow_workflows"

    id = Column(Integer, primary_key=True, index=True)
    # Owner of this workflow. Nullable for backward compatibility with rows
    # created before this column existed (treated as "legacy/unowned" -- see
    # the ownership checks in blueprints/flow.py, which allow access to
    # user_id=None rows the same way python_strategy.py's
    # verify_strategy_ownership does). New workflows always get a real owner.
    user_id = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    nodes = Column(JSON, default=list)
    edges = Column(JSON, default=list)
    is_active = Column(Boolean, default=False)
    schedule_job_id = Column(String(255), nullable=True)
    webhook_token = Column(String(64), unique=True, nullable=True, default=generate_webhook_token)
    webhook_secret = Column(String(64), nullable=True, default=generate_webhook_secret)
    webhook_enabled = Column(Boolean, default=False)
    webhook_auth_type = Column(String(20), default="payload")  # "payload" or "url"
    api_key = Column(
        String(255), nullable=True
    )  # Stored when workflow is activated, used for webhook execution
    # NULL (default, all pre-existing workflows) = order/position calls use
    # whichever broker is the user's current primary Auth session, exactly
    # today's behavior. Set to a specific connected broker name to pin this
    # workflow's order placement to that one connected broker regardless of
    # which is primary -- see flow_maxalgos_client.py's FlowMaxAlgosClient
    # broker param and services/place_order_service.py's Case 1 broker=
    # override (the same mechanism services/deployment_service.py already
    # uses for multi-broker deployments).
    broker = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    executions = relationship(
        "FlowWorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )


class FlowWorkflowExecution(Base):
    """Model for flow workflow executions"""

    __tablename__ = "flow_workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("flow_workflows.id"), nullable=False)
    status = Column(String(50), default="pending")  # pending, running, completed, completed_with_errors, failed
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    logs = Column(JSON, default=list)
    error = Column(Text, nullable=True)

    # Relationships
    workflow = relationship("FlowWorkflow", back_populates="executions")


def init_db():
    """Initialize the database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Flow DB", logger)

    # Migrate: Add api_key column if it doesn't exist (for existing databases)
    _migrate_add_api_key_column()
    # Migrate: Add user_id column (workflow ownership) if it doesn't exist
    _migrate_add_user_id_column()
    # Migrate: Add broker column (per-workflow broker pinning) if it doesn't exist
    _migrate_add_broker_column()


def _migrate_add_user_id_column():
    """Add user_id column to flow_workflows table if it doesn't exist.

    Existing rows get NULL user_id (treated as legacy/unowned by the
    ownership checks in blueprints/flow.py), so this migration never breaks
    or hides pre-existing workflows -- it only enables per-user isolation
    for workflows created from here on.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "flow_workflows" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("flow_workflows")]
        if "user_id" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE flow_workflows ADD COLUMN user_id VARCHAR(255)"))
                conn.commit()
                logger.info("Migration: Added 'user_id' column to flow_workflows table")
    except Exception as e:
        logger.debug(f"Migration check for user_id column: {e}")


def _migrate_add_api_key_column():
    """Add api_key column to flow_workflows table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "flow_workflows" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("flow_workflows")]
        if "api_key" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE flow_workflows ADD COLUMN api_key VARCHAR(255)"))
                conn.commit()
                logger.info("Migration: Added 'api_key' column to flow_workflows table")
    except Exception as e:
        # Log but don't fail - column might already exist or other DB issue
        logger.debug(f"Migration check for api_key column: {e}")


def _migrate_add_broker_column():
    """Add broker column to flow_workflows table if it doesn't exist.

    NULL for every pre-existing row -- these keep resolving orders through
    whatever the user's primary Auth session is, exactly as before this
    migration ran.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "flow_workflows" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("flow_workflows")]
        if "broker" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE flow_workflows ADD COLUMN broker VARCHAR(50)"))
                conn.commit()
                logger.info("Migration: Added 'broker' column to flow_workflows table")
    except Exception as e:
        logger.debug(f"Migration check for broker column: {e}")


# --- Workflow CRUD Operations ---


def create_workflow(name, description=None, nodes=None, edges=None, user_id=None, broker=None):
    """Create a new workflow owned by user_id."""
    try:
        workflow = FlowWorkflow(
            name=name,
            description=description,
            nodes=nodes or [],
            edges=edges or [],
            user_id=user_id,
            broker=broker,
        )
        db_session.add(workflow)
        db_session.commit()

        # Clear workflow cache
        _workflow_cache.clear()

        logger.info(f"Created workflow: {name} (id={workflow.id})")
        return workflow
    except Exception as e:
        logger.exception(f"Error creating workflow: {str(e)}")
        db_session.rollback()
        return None


def get_workflow(workflow_id):
    """Get workflow by ID"""
    try:
        return FlowWorkflow.query.get(workflow_id)
    except Exception as e:
        logger.exception(f"Error getting workflow {workflow_id}: {str(e)}")
        return None


def get_workflow_by_webhook_token(webhook_token):
    """Get workflow by webhook token (cached for 5 minutes)"""
    # Check cache first
    if webhook_token in _workflow_webhook_cache:
        return _workflow_webhook_cache[webhook_token]

    try:
        workflow = FlowWorkflow.query.filter_by(webhook_token=webhook_token).first()
        # Cache the result (including None for not found)
        if workflow:
            _workflow_webhook_cache[webhook_token] = workflow
        return workflow
    except Exception as e:
        logger.exception(f"Error getting workflow by webhook token: {str(e)}")
        return None


def get_all_workflows(user_id=None):
    """Get all workflows visible to user_id.

    When user_id is given, returns that user's own workflows plus any
    legacy rows with no owner (user_id IS NULL) -- matching the
    "allow access to unowned legacy rows" convention used elsewhere. When
    user_id is None (internal/admin callers), returns everything.
    """
    try:
        query = FlowWorkflow.query
        if user_id is not None:
            query = query.filter(
                (FlowWorkflow.user_id == user_id) | (FlowWorkflow.user_id.is_(None))
            )
        return query.order_by(FlowWorkflow.updated_at.desc()).all()
    except Exception as e:
        logger.exception(f"Error getting all workflows: {str(e)}")
        return []


def user_owns_workflow(workflow_id, user_id):
    """Return True if user_id may access this workflow (owns it, or it's a
    legacy row with no owner). Used by blueprints/flow.py to gate every
    per-workflow route so one user can't read/edit/execute/delete another
    user's workflows."""
    workflow = get_workflow(workflow_id)
    if not workflow:
        return False
    owner = getattr(workflow, "user_id", None)
    return owner is None or owner == user_id


def get_active_workflows():
    """Get all active workflows"""
    try:
        return FlowWorkflow.query.filter_by(is_active=True).all()
    except Exception as e:
        logger.exception(f"Error getting active workflows: {str(e)}")
        return []


def update_workflow(workflow_id, **kwargs):
    """Update workflow fields"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        # Update allowed fields
        allowed_fields = [
            "name",
            "description",
            "nodes",
            "edges",
            "is_active",
            "schedule_job_id",
            "webhook_enabled",
            "webhook_auth_type",
            "api_key",
            "broker",
        ]
        for field in allowed_fields:
            if field in kwargs:
                # api_key is encrypted at rest with the auth_db Fernet.
                if field == "api_key":
                    setattr(workflow, field, _encrypt_api_key(kwargs[field]))
                else:
                    setattr(workflow, field, kwargs[field])

        db_session.commit()

        # Clear caches
        _workflow_cache.clear()
        if workflow.webhook_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[workflow.webhook_token]

        logger.info(f"Updated workflow {workflow_id}")
        return workflow
    except Exception as e:
        logger.exception(f"Error updating workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def delete_workflow(workflow_id):
    """Delete workflow and its executions"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return False

        # Store for cache invalidation
        webhook_token = workflow.webhook_token

        db_session.delete(workflow)
        db_session.commit()

        # Clear caches
        _workflow_cache.clear()
        if webhook_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[webhook_token]

        logger.info(f"Deleted workflow {workflow_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return False


def activate_workflow(workflow_id, api_key=None):
    """Activate a workflow and optionally store the API key for webhook execution"""
    kwargs = {"is_active": True}
    if api_key:
        kwargs["api_key"] = api_key
    return update_workflow(workflow_id, **kwargs)


def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    return update_workflow(workflow_id, is_active=False)


def regenerate_webhook_token(workflow_id):
    """Regenerate webhook token for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        old_token = workflow.webhook_token
        workflow.webhook_token = generate_webhook_token()
        db_session.commit()

        # Clear old token from cache
        if old_token in _workflow_webhook_cache:
            del _workflow_webhook_cache[old_token]

        logger.info(f"Regenerated webhook token for workflow {workflow_id}")
        return workflow.webhook_token
    except Exception as e:
        logger.exception(f"Error regenerating webhook token for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def regenerate_webhook_secret(workflow_id):
    """Regenerate webhook secret for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        workflow.webhook_secret = generate_webhook_secret()
        db_session.commit()

        logger.info(f"Regenerated webhook secret for workflow {workflow_id}")
        return workflow.webhook_secret
    except Exception as e:
        logger.exception(f"Error regenerating webhook secret for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def enable_webhook(workflow_id):
    """Enable webhook for a workflow"""
    return update_workflow(workflow_id, webhook_enabled=True)


def disable_webhook(workflow_id):
    """Disable webhook for a workflow"""
    return update_workflow(workflow_id, webhook_enabled=False)


def set_webhook_auth_type(workflow_id, auth_type):
    """Set webhook auth type for a workflow"""
    if auth_type not in ["payload", "url"]:
        logger.error(f"Invalid webhook auth type: {auth_type}")
        return None
    return update_workflow(workflow_id, webhook_auth_type=auth_type)


def ensure_webhook_credentials(workflow_id):
    """Ensure webhook token and secret exist for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return False

        needs_update = False
        if not workflow.webhook_token:
            workflow.webhook_token = generate_webhook_token()
            needs_update = True
        if not workflow.webhook_secret:
            workflow.webhook_secret = generate_webhook_secret()
            needs_update = True

        if needs_update:
            db_session.commit()
            # Clear cache to force refresh
            _workflow_cache.clear()
            logger.info(f"Generated webhook credentials for workflow {workflow_id}")

        return True
    except Exception as e:
        logger.exception(f"Error ensuring webhook credentials for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return False


def set_schedule_job_id(workflow_id, job_id):
    """Set schedule job ID for a workflow"""
    try:
        workflow = get_workflow(workflow_id)
        if not workflow:
            return None

        workflow.schedule_job_id = job_id
        db_session.commit()

        logger.info(f"Set schedule job ID {job_id} for workflow {workflow_id}")
        return workflow
    except Exception as e:
        logger.exception(f"Error setting schedule job ID for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


# --- Workflow Execution CRUD Operations ---


def create_execution(workflow_id, status="pending"):
    """Create a new workflow execution"""
    try:
        execution = FlowWorkflowExecution(workflow_id=workflow_id, status=status, logs=[])
        db_session.add(execution)
        db_session.commit()

        logger.info(f"Created execution for workflow {workflow_id} (id={execution.id})")
        return execution
    except Exception as e:
        logger.exception(f"Error creating execution for workflow {workflow_id}: {str(e)}")
        db_session.rollback()
        return None


def get_execution(execution_id):
    """Get execution by ID"""
    try:
        return FlowWorkflowExecution.query.get(execution_id)
    except Exception as e:
        logger.exception(f"Error getting execution {execution_id}: {str(e)}")
        return None


def get_workflow_executions(workflow_id, limit=50):
    """Get executions for a workflow"""
    try:
        return (
            FlowWorkflowExecution.query.filter_by(workflow_id=workflow_id)
            .order_by(FlowWorkflowExecution.started_at.desc())
            .limit(limit)
            .all()
        )
    except Exception as e:
        logger.exception(f"Error getting executions for workflow {workflow_id}: {str(e)}")
        return []


def update_execution_status(execution_id, status, error=None):
    """Update execution status"""
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        execution.status = status
        if error:
            execution.error = error

        if status == "running" and not execution.started_at:
            execution.started_at = func.now()
        elif status in ["completed", "failed"]:
            execution.completed_at = func.now()

        db_session.commit()

        logger.info(f"Updated execution {execution_id} status to {status}")
        return execution
    except Exception as e:
        logger.exception(f"Error updating execution {execution_id}: {str(e)}")
        db_session.rollback()
        return None


def add_execution_log(execution_id, log_entry):
    """Add a log entry to execution"""
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        # Get current logs and append
        logs = execution.logs or []
        logs.append(log_entry)
        execution.logs = logs

        db_session.commit()
        return execution
    except Exception as e:
        logger.exception(f"Error adding log to execution {execution_id}: {str(e)}")
        db_session.rollback()
        return None


def save_execution_logs(execution_id, logs):
    """Overwrite the full logs list on an execution in one write.

    Used at the end of a run (see services/flow_executor_service.py's
    execute_workflow) instead of calling add_execution_log() once per log
    entry -- a workflow can log many entries per run, and committing once
    per entry would mean one DB round-trip per node visited. The executor
    accumulates entries in an in-memory list during the run; this persists
    that list exactly once when the run finishes (success or failure).
    """
    try:
        execution = get_execution(execution_id)
        if not execution:
            return None

        execution.logs = logs
        db_session.commit()
        return execution
    except Exception as e:
        logger.exception(f"Error saving logs for execution {execution_id}: {str(e)}")
        db_session.rollback()
        return None


def clear_workflow_cache():
    """Clear all workflow caches"""
    _workflow_webhook_cache.clear()
    _workflow_cache.clear()
    logger.info("Flow workflow cache cleared")
