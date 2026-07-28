import json
import logging

from flask import Blueprint, jsonify, request, session

from database.deployment_db import (
    Deployment,
    create_deployment,
    create_strategy_version,
    db_session,
    delete_deployment,
    get_deployment,
    get_user_deployments,
    update_deployment_status,
)
from services.deployment_service import clone_deployment, validate_dry_run

logger = logging.getLogger(__name__)
deployments_bp = Blueprint("deployments", __name__)


def _get_authenticated_user():
    """Helper to resolve logged-in username or API key user.

    Returns None when neither a session nor a valid API key is present --
    callers must treat that as unauthenticated (401), never substitute a
    default user. A prior version of this fell back to "admin", which meant
    any misconfigured/unauthenticated request silently acted as the admin
    account instead of failing.
    """
    username = None
    if "user" in session and session["user"]:
        if isinstance(session["user"], dict):
            username = session["user"].get("username")
        else:
            username = session["user"]

    if not username:
        api_key = request.headers.get("X-API-KEY") or request.args.get("apikey")
        if api_key:
            from database.auth_db import verify_api_key
            username = verify_api_key(api_key)

    return username


@deployments_bp.route("/api/v1/deployments", methods=["GET"])
def list_deployments():
    """List all strategy deployments for the authenticated user"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployments = get_user_deployments(user_id)
    return jsonify([d.to_dict() for d in deployments])


@deployments_bp.route("/api/v1/deployments", methods=["POST"])
def create_new_deployment():
    """Deploy a strategy template as an execution instance"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    data = request.json or {}

    required_fields = ["name", "strategy_id", "broker", "capital"]
    for field in required_fields:
        if field not in data:
            return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400

    strategy_config = data.get("strategy_config", {})
    strategy_id = int(data["strategy_id"])

    # The strategy must actually exist and belong to the caller -- without
    # this, a fabricated/guessed strategy_id could create a StrategyVersion
    # and Deployment against a nonexistent row, or (on a collision) against
    # another user's real strategy.
    from database.strategy_db import get_strategy
    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    # Store or locate the correct StrategyVersion
    if strategy_config:
        ver = create_strategy_version(strategy_id, strategy_config)
    else:
        from database.deployment_db import StrategyVersion
        ver = db_session.query(StrategyVersion).filter_by(strategy_id=strategy_id).order_by(StrategyVersion.version.desc()).first()
        if not ver:
            ver = create_strategy_version(strategy_id, {})

    if not ver:
        return jsonify({"status": "error", "message": "Failed to create strategy version"}), 500

    # Compile strategy_config into a real conditions_tree server-side --
    # NEVER trust a client-supplied conditions_tree directly (it gates real
    # broker order placement in services/deployment_service.py's
    # _evaluation_loop). template_id is read from the Strategy row (set at
    # creation time via blueprints/strategy.py, database/strategy_db.py's
    # template_id column) rather than trusting the request body's
    # template_id, since the DB value is the one actually persisted and
    # associated with this strategy. Falls back to the request body only for
    # strategies created before the template_id column existed.
    from services.strategy_compiler import CompilerError, compile_strategy_config

    template_id = strategy.template_id or data.get("template_id")
    try:
        conditions_tree = compile_strategy_config(template_id, strategy_config)
    except CompilerError as e:
        logger.warning(f"Strategy compilation failed for strategy_id={strategy_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

    # 2. Setup the deployment parameters
    deployment_data = {
        "name": str(data["name"]),
        "strategy_id": strategy_id,
        "version_id": ver.id,
        "status": "Waiting" if data.get("deploy_now") else "Draft",
        "broker": str(data["broker"]),
        "capital": float(data["capital"]),
        "max_positions": int(data.get("max_positions", 1)),
        "order_type": str(data.get("order_type", "Market")),
        "product": str(data.get("product", "MIS")),
        "trigger_type": str(data.get("trigger_type", "Immediately")),
        "conditions_tree": conditions_tree,
        "risk_params": data.get("risk_params", {}),
        "user_id": user_id,
        "events_timeline": [{
            "time": "Now",
            "event": "Strategy deployed successfully"
        }]
    }

    deployment = create_deployment(deployment_data)
    if not deployment:
        return jsonify({"status": "error", "message": "Failed to create deployment"}), 500

    return jsonify(deployment.to_dict()), 201


@deployments_bp.route("/api/v1/deployments/dry-run", methods=["POST"])
def dry_run_deployment():
    """Compile a wizard strategy_config into a conditions_tree and evaluate
    it against LIVE current market data, without creating a Deployment or
    placing any order.

    Reuses the exact same compile_strategy_config() and
    evaluate_conditions_tree() functions services/deployment_service.py's
    _evaluation_loop calls in production -- so a dry-run result reflects
    genuinely what would happen live, not a separate/divergent test-only
    code path. Intended for the frontend to show a REAL compiled result
    (instead of, or alongside, the cosmetic client-side explanation string)
    before the user commits to deploying.
    """
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    data = request.json or {}

    strategy_config = data.get("strategy_config", {})
    template_id = data.get("template_id")
    symbol = strategy_config.get("symbol") or "NIFTY"
    exchange = strategy_config.get("exchange") or "NSE_INDEX"

    from services.strategy_compiler import CompilerError, compile_strategy_config

    try:
        conditions_tree = compile_strategy_config(template_id, strategy_config)
    except CompilerError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    from services.condition_engine import evaluate_conditions_tree

    try:
        would_trigger = evaluate_conditions_tree(conditions_tree, symbol, exchange)
    except Exception as e:
        logger.exception(f"Dry-run evaluation failed for template_id={template_id}: {e}")
        return jsonify({"status": "error", "message": f"Evaluation failed: {e}"}), 500

    return jsonify({
        "status": "success",
        "conditions_tree": conditions_tree,
        "symbol": symbol,
        "exchange": exchange,
        "would_trigger": would_trigger,
    })


@deployments_bp.route("/api/v1/deployments/<int:id>/pause", methods=["POST"])
def pause_deployment(id):
    """Pause a running/waiting deployment"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    success = update_deployment_status(id, "Paused", "Deployment paused by user")
    if not success:
        return jsonify({"status": "error", "message": "Failed to pause deployment"}), 500

    return jsonify({"status": "success", "message": "Deployment paused"})


@deployments_bp.route("/api/v1/deployments/<int:id>/resume", methods=["POST"])
def resume_deployment(id):
    """Resume a paused deployment"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    # Determine next status based on trigger type
    next_status = "Waiting"
    if deployment.trigger_type == "Immediately":
        next_status = "Waiting" # Will trigger on next check or immediately

    success = update_deployment_status(id, next_status, "Deployment resumed by user")
    if not success:
        return jsonify({"status": "error", "message": "Failed to resume deployment"}), 500

    return jsonify({"status": "success", "message": "Deployment resumed"})


@deployments_bp.route("/api/v1/deployments/<int:id>/broker", methods=["PATCH"])
def update_deployment_broker(id):
    """Change which broker a deployment routes orders/quotes through.

    Exists because deployments could previously be created with a broker
    that was never actually connected for that user (StrategyConfigurator.tsx
    used to default to a hardcoded 'zebu' regardless of what the user really
    had set up) -- with no way to fix an existing deployment, the only
    option was deleting and recreating it. This lets a user correct just the
    broker field in place.

    Validates the new broker is genuinely connected (mirrors
    place_order_service.py's Case-1-specific-broker check) rather than
    trusting the client-supplied name outright -- otherwise this endpoint
    would just move the same "silently wrong broker" bug to a different
    value.
    """
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    data = request.json or {}
    broker = str(data.get("broker") or "").strip()
    if not broker:
        return jsonify({"status": "error", "message": "broker is required"}), 400

    is_paper = broker.lower() in ("paper", "paper trading", "paper trading (simulated)")
    if not is_paper:
        from database.auth_db import get_broker_session

        session_info = get_broker_session(user_id, broker)
        if not session_info:
            return jsonify({
                "status": "error",
                "message": f"Broker '{broker}' is not connected for this account. "
                           "Connect it in Broker Management first.",
            }), 400

    deployment.broker = broker
    db_session.commit()

    # Give it a clean run against the corrected broker rather than leaving
    # a stale "Error" from the old misconfigured one sitting on screen.
    update_deployment_status(
        id, "Waiting", f"Broker changed to {broker} by user -- resuming evaluation."
    )

    return jsonify({"status": "success", "message": "Deployment broker updated", "broker": broker})


@deployments_bp.route("/api/v1/deployments/<int:id>/stop", methods=["POST"])
def stop_deployment(id):
    """Permanently stop a deployment"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    success = update_deployment_status(id, "Stopped", "Deployment stopped by user")
    if not success:
        return jsonify({"status": "error", "message": "Failed to stop deployment"}), 500

    return jsonify({"status": "success", "message": "Deployment stopped"})


@deployments_bp.route("/api/v1/deployments/<int:id>", methods=["DELETE"])
def delete_deployment_endpoint(id):
    """Permanently delete a deployment row.

    Refuses to delete a deployment that's actively managing a real position
    (status "Managing"/"Entering") -- that would orphan the position from
    any tracking without actually closing it at the broker. The user must
    Stop it first (which the frontend's Stop button already does), then
    Delete becomes available. Draft/Waiting/Paused/Stopped/Completed/Error
    deployments can always be deleted -- none of them have live broker-side
    state depending on the row's continued existence.
    """
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    if deployment.status in ("Managing", "Entering"):
        return jsonify({
            "status": "error",
            "message": f"Cannot delete a deployment that's actively {deployment.status.lower()} "
                       "a position -- stop it first.",
        }), 400

    success = delete_deployment(id)
    if not success:
        return jsonify({"status": "error", "message": "Failed to delete deployment"}), 500

    return jsonify({"status": "success", "message": "Deployment deleted"})


@deployments_bp.route("/api/v1/deployments/<int:id>/clone", methods=["POST"])
def clone_deployment_endpoint(id):
    """Clone an existing deployment to another broker or capital allocation"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    data = request.json or {}
    new_broker = data.get("broker")
    new_capital = data.get("capital")

    cloned = clone_deployment(id, new_broker, new_capital)
    if not cloned:
        return jsonify({"status": "error", "message": "Failed to clone deployment"}), 500

    return jsonify(cloned.to_dict()), 201


@deployments_bp.route("/api/v1/deployments/<int:id>/dryrun", methods=["GET"])
def run_dryrun(id):
    """Run a pre-flight dry-run check for the deployment"""
    user_id = _get_authenticated_user()
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401
    deployment = get_deployment(id)
    if not deployment or deployment.user_id != user_id:
        return jsonify({"status": "error", "message": "Deployment not found"}), 404

    result = validate_dry_run(id)
    return jsonify(result)
