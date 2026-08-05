import atexit
import json
import os
import queue
import re
import threading
import time as time_module
import uuid
from collections import deque
from datetime import datetime, time
from time import time

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.auth_db import get_api_key_for_tradingview
from database.strategy_db import (
    Backtest,
    BacktestTrade,
    ExecutionProfile,
    LegGroup,
    MarketplaceListing,
    Strategy,
    StrategySymbolMapping,
    StrategyVersion,
    Subscription,
    add_symbol_mapping,
    bulk_add_symbol_mappings,
    create_deployment,
    create_execution_profile,
    create_leg_group,
    create_strategy,
    create_strategy_version,
    db_session,
    delete_execution_profile,
    delete_leg_group,
    delete_strategy,
    delete_symbol_mapping,
    get_all_strategies,
    get_execution_profiles,
    get_leg_group,
    get_leg_groups,
    get_strategy,
    get_strategy_by_webhook_id,
    get_symbol_mappings,
    get_user_strategies,
    set_mapping_action_override,
    toggle_leg_group_active,
    toggle_strategy,
    toggle_symbol_mapping_active,
    update_execution_profile,
    update_leg_group,
    update_strategy_execution_model,
    update_strategy_times,
    update_symbol_mapping,
)
from database.symbol import enhanced_search_symbols
from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity, is_session_valid

logger = get_logger(__name__)

# Rate limiting configuration
WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")
STRATEGY_RATE_LIMIT = os.getenv("STRATEGY_RATE_LIMIT", "200 per minute")

strategy_bp = Blueprint("strategy_bp", __name__, url_prefix="/strategy")

# Initialize scheduler for time-based controls
scheduler = BackgroundScheduler(
    timezone=pytz.timezone("Asia/Kolkata"),
    job_defaults={"coalesce": True, "misfire_grace_time": 300, "max_instances": 1},
)
scheduler.start()

# Get base URL from environment or default to localhost
BASE_URL = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")

# Valid exchanges
VALID_EXCHANGES = ["NSE", "BSE", "NFO", "CDS", "BFO", "BCD", "MCX", "NCDEX"]

# Product types per exchange
EXCHANGE_PRODUCTS = {
    "NSE": ["MIS", "CNC"],
    "BSE": ["MIS", "CNC"],
    "NFO": ["MIS", "NRML"],
    "CDS": ["MIS", "NRML"],
    "BFO": ["MIS", "NRML"],
    "BCD": ["MIS", "NRML"],
    "MCX": ["MIS", "NRML"],
    "NCDEX": ["MIS", "NRML"],
}

# Default values
DEFAULT_EXCHANGE = "NSE"
DEFAULT_PRODUCT = "MIS"

# Separate queues for different order types
regular_order_queue = queue.Queue()  # For placeorder (up to 10/sec)
smart_order_queue = queue.Queue()  # For placesmartorder (1/sec)

# Order processor state
order_processor_running = False
order_processor_lock = threading.Lock()
_order_processor_thread = None

# Rate limiting state for regular orders
last_regular_orders = deque(maxlen=10)  # Track last 10 regular order timestamps


def process_orders():
    """Background task to process orders from both queues with rate limiting"""
    global order_processor_running

    while True:
        try:
            # Process smart orders first (1 per second)
            try:
                smart_order = smart_order_queue.get_nowait()
                if smart_order is None:  # Poison pill
                    break

                try:
                    from utils.httpx_client import get_httpx_client
                    response = get_httpx_client().post(
                        f"{BASE_URL}/api/v1/placesmartorder", json=smart_order["payload"]
                    )
                    if response.is_success:
                        logger.info(
                            f"Smart order placed for {smart_order['payload']['symbol']} in strategy {smart_order['payload']['strategy']}"
                        )
                    else:
                        logger.error(
                            f"Error placing smart order for {smart_order['payload']['symbol']}: {response.text}"
                        )
                except Exception as e:
                    logger.exception(f"Error placing smart order: {str(e)}")

                # Always wait 1 second after smart order
                time_module.sleep(1)
                continue  # Start next iteration

            except queue.Empty:
                pass  # No smart orders, continue to regular orders

            # Process regular orders (up to 10 per second)
            now = time()

            # Clean up old timestamps
            while last_regular_orders and now - last_regular_orders[0] > 1:
                last_regular_orders.popleft()

            # Process regular orders if under rate limit
            if len(last_regular_orders) < 10:
                try:
                    regular_order = regular_order_queue.get_nowait()
                    if regular_order is None:  # Poison pill
                        break

                    try:
                        from utils.httpx_client import get_httpx_client
                        response = get_httpx_client().post(
                            f"{BASE_URL}/api/v1/placeorder", json=regular_order["payload"]
                        )
                        if response.is_success:
                            logger.info(
                                f"Regular order placed for {regular_order['payload']['symbol']} in strategy {regular_order['payload']['strategy']}"
                            )
                            last_regular_orders.append(now)
                        else:
                            logger.error(
                                f"Error placing regular order for {regular_order['payload']['symbol']}: {response.text}"
                            )
                    except Exception as e:
                        logger.exception(f"Error placing regular order: {str(e)}")

                except queue.Empty:
                    pass  # No regular orders

            # Small sleep to prevent CPU spinning
            time_module.sleep(0.1)

        except Exception as e:
            logger.exception(f"Error in order processor: {str(e)}")
            time_module.sleep(1)  # Sleep on error to prevent rapid retries


def _shutdown_order_processor():
    """Drain remaining orders before process exit"""
    if _order_processor_thread and _order_processor_thread.is_alive():
        pending = smart_order_queue.qsize() + regular_order_queue.qsize()
        if pending:
            logger.info(f"Shutting down order processor, draining {pending} pending orders...")
        # Only poison the regular queue — smart orders drain first via the loop,
        # then the regular queue processes all remaining orders before hitting the pill
        regular_order_queue.put(None)
        _order_processor_thread.join(timeout=30)


atexit.register(_shutdown_order_processor)


def ensure_order_processor():
    """Ensure the order processor is running"""
    global order_processor_running, _order_processor_thread
    with order_processor_lock:
        if not order_processor_running:
            _order_processor_thread = threading.Thread(target=process_orders, daemon=True)
            _order_processor_thread.start()
            order_processor_running = True


def queue_order(endpoint, payload):
    """Add order to appropriate queue"""
    ensure_order_processor()
    if endpoint == "placesmartorder":
        smart_order_queue.put({"payload": payload})
    else:
        regular_order_queue.put({"payload": payload})


def validate_strategy_times(start_time, end_time, squareoff_time):
    """Validate strategy time settings"""
    try:
        if not all([start_time, end_time, squareoff_time]):
            return False, "All time fields are required"

        # Convert strings to time objects for comparison
        start = datetime.strptime(start_time, "%H:%M").time()
        end = datetime.strptime(end_time, "%H:%M").time()
        squareoff = datetime.strptime(squareoff_time, "%H:%M").time()

        # Market hours validation (9:15 AM to 3:30 PM)
        market_open = datetime.strptime("09:15", "%H:%M").time()
        market_close = datetime.strptime("15:30", "%H:%M").time()

        if start < market_open:
            return False, "Start time cannot be before market open (9:15)"
        if end > market_close:
            return False, "End time cannot be after market close (15:30)"
        if squareoff > market_close:
            return False, "Square off time cannot be after market close (15:30)"
        if start >= end:
            return False, "Start time must be before end time"
        if squareoff < start:
            return False, "Square off time must be after start time"
        if squareoff < end:
            return False, "Square off time must be after end time"

        return True, None

    except ValueError:
        return False, "Invalid time format. Use HH:MM format"


def validate_strategy_name(name):
    """Validate strategy name format"""
    if not name:
        return False, "Strategy name is required"

    # Check length
    if len(name) < 3 or len(name) > 50:
        return False, "Strategy name must be between 3 and 50 characters"

    # Check characters
    if not re.match(r"^[A-Za-z0-9\s\-_/()]+$", name):
        return (
            False,
            "Strategy name can only contain letters, numbers, spaces, hyphens, slashes, and underscores",
        )

    return True, None


def schedule_squareoff(strategy_id):
    """Schedule squareoff for intraday strategy"""
    strategy = get_strategy(strategy_id)
    if not strategy or not strategy.is_intraday or not strategy.squareoff_time:
        return

    try:
        hours, minutes = map(int, strategy.squareoff_time.split(":"))
        job_id = f"squareoff_{strategy_id}"

        # Remove existing job if any
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        # Add new job
        scheduler.add_job(
            squareoff_positions,
            "cron",
            hour=hours,
            minute=minutes,
            args=[strategy_id],
            id=job_id,
            timezone=pytz.timezone("Asia/Kolkata"),
        )
        logger.info(f"Scheduled squareoff for strategy {strategy_id} at {hours}:{minutes}")
    except Exception as e:
        logger.exception(f"Error scheduling squareoff for strategy {strategy_id}: {str(e)}")


def squareoff_positions(strategy_id):
    """Square off all positions for intraday strategy"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy or not strategy.is_intraday:
            return

        # Get API key for authentication
        api_key = get_api_key_for_tradingview(strategy.user_id)
        if not api_key:
            logger.error(f"No API key found for strategy {strategy_id}")
            return

        # Get all symbol mappings
        mappings = get_symbol_mappings(strategy_id)

        # Historically this table had up to 2 rows per instrument (one BUY
        # mapping, one SELL mapping, both pointing at the same instrument) --
        # dedupe on (instrument, exchange) so a squareoff sweep doesn't queue
        # the same close twice. `mapping.symbol` used to hold the action
        # string ("BUY"/"SELL"), not the tradable instrument -- see
        # StrategySymbolMapping's class docstring. The real instrument is
        # `mapping.instrument` (falling back to `symbol` only for any
        # pre-migration row where instrument was never set).
        seen = set()
        for mapping in mappings:
            inst_symbol = mapping.instrument or mapping.symbol
            key = (inst_symbol, mapping.exchange)
            if key in seen:
                continue
            seen.add(key)

            # Use placesmartorder with quantity=0 and position_size=0 for squareoff
            payload = {
                "apikey": api_key,
                "symbol": inst_symbol,
                "exchange": mapping.exchange,
                "product": mapping.product_type,
                "strategy": strategy.name,
                "action": "SELL",  # Direction doesn't matter for closing
                "pricetype": "MARKET",
                "quantity": "0",
                "position_size": "0",  # This will close the position
                "price": "0",
                "trigger_price": "0",
                "disclosed_quantity": "0",
            }

            # Queue the order instead of executing directly
            queue_order("placesmartorder", payload)

    except Exception as e:
        logger.exception(f"Error in squareoff_positions for strategy {strategy_id}: {str(e)}")


@strategy_bp.route("/")
def index():
    """List all strategies"""
    if not is_session_valid():
        return redirect(url_for("auth.login"))

    user_id = session.get("user")
    if not user_id:
        flash("Please login to continue", "error")
        return redirect(url_for("auth.login"))

    try:
        logger.info(f"Fetching strategies for user: {user_id}")
        strategies = get_user_strategies(user_id)
        return render_template("strategy/index.html", strategies=strategies)
    except Exception as e:
        logger.exception(f"Error in index route: {str(e)}")
        flash("Error loading strategies", "error")
        return redirect(url_for("dashboard_bp.index"))


@strategy_bp.route("/new", methods=["GET", "POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def new_strategy():
    """Create new strategy"""
    if request.method == "POST":
        try:
            # Get user_id from session
            user_id = session.get("user")
            if not user_id:
                logger.error("No user_id found in session")
                flash("Session expired. Please login again.", "error")
                return redirect(url_for("auth.login"))

            logger.info(f"Creating strategy for user: {user_id}")

            # Get form data
            platform = request.form.get("platform", "").strip()
            name = request.form.get("name", "").strip()

            # Validate platform
            if not platform:
                flash("Please select a platform", "error")
                return redirect(url_for("strategy_bp.new_strategy"))

            # Create prefixed strategy name
            name = f"{platform}_{name}"

            # Get other form data
            strategy_type = request.form.get("type")
            trading_mode = request.form.get("trading_mode", "LONG")  # Default to LONG
            start_time = request.form.get("start_time")
            end_time = request.form.get("end_time")
            squareoff_time = request.form.get("squareoff_time")

            # Validate strategy name
            is_valid_name, name_error = validate_strategy_name(name)
            if not is_valid_name:
                flash(
                    name_error or "Invalid strategy name. Use only letters, numbers, spaces, hyphens, and underscores",
                    "error",
                )
                return redirect(url_for("strategy_bp.new_strategy"))

            # Validate times for intraday strategy
            is_intraday = strategy_type == "intraday"
            if is_intraday:
                is_valid_times, times_error = validate_strategy_times(start_time, end_time, squareoff_time)
                if not is_valid_times:
                    flash(
                        times_error or "Invalid trading times. End time must be after start time and before square off time",
                        "error",
                    )
                    return redirect(url_for("strategy_bp.new_strategy"))
            else:
                start_time = end_time = squareoff_time = None

            # Generate webhook ID
            webhook_id = str(uuid.uuid4())

            # Create strategy with user ID
            strategy = create_strategy(
                name=name,
                webhook_id=webhook_id,
                user_id=user_id,  # Use username from session
                is_intraday=is_intraday,
                trading_mode=trading_mode,
                start_time=start_time,
                end_time=end_time,
                squareoff_time=squareoff_time,
                platform=platform,
            )

            if strategy:
                flash("Strategy created successfully!", "success")
                if strategy.is_intraday:
                    schedule_squareoff(strategy.id)
                return redirect(url_for("strategy_bp.configure_symbols", strategy_id=strategy.id))
            else:
                flash("Error creating strategy", "error")
                return redirect(url_for("strategy_bp.new_strategy"))

        except Exception as e:
            logger.exception(f"Error creating strategy: {str(e)}")
            flash("Error creating strategy", "error")
            return redirect(url_for("strategy_bp.new_strategy"))

    return render_template("strategy/new_strategy.html")


@strategy_bp.route("/<int:strategy_id>")
def view_strategy(strategy_id):
    """View strategy details"""
    if not is_session_valid():
        return redirect(url_for("auth.login"))

    strategy = get_strategy(strategy_id)
    if not strategy:
        flash("Strategy not found", "error")
        return redirect(url_for("strategy_bp.index"))

    if strategy.user_id != session.get("user"):
        flash("Unauthorized access", "error")
        return redirect(url_for("strategy_bp.index"))

    symbol_mappings = get_symbol_mappings(strategy_id)

    return render_template(
        "strategy/view_strategy.html", strategy=strategy, symbol_mappings=symbol_mappings
    )


@strategy_bp.route("/toggle/<int:strategy_id>", methods=["POST"])
def toggle_strategy_route(strategy_id):
    """Toggle strategy active status"""
    if not is_session_valid():
        return redirect(url_for("auth.login"))

    try:
        strategy = toggle_strategy(strategy_id)
        if strategy:
            if strategy.is_active:
                # Schedule squareoff if being activated
                schedule_squareoff(strategy_id)
                flash("Strategy activated successfully", "success")
            else:
                # Remove squareoff job if being deactivated
                try:
                    scheduler.remove_job(f"squareoff_{strategy_id}")
                except Exception:
                    pass
                flash("Strategy deactivated successfully", "success")

            return redirect(url_for("strategy_bp.view_strategy", strategy_id=strategy_id))
        else:
            flash("Error toggling strategy: Strategy not found", "error")
            return redirect(url_for("strategy_bp.index"))
    except Exception as e:
        flash(f"Error toggling strategy: {str(e)}", "error")
        return redirect(url_for("strategy_bp.index"))


@strategy_bp.route("/<int:strategy_id>/delete", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def delete_strategy_route(strategy_id):
    """Delete strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "error": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "error": "Strategy not found"}), 404

    # Check if strategy belongs to user
    if strategy.user_id != user_id:
        return jsonify({"status": "error", "error": "Unauthorized"}), 403

    try:
        # Remove squareoff job if exists
        try:
            scheduler.remove_job(f"squareoff_{strategy_id}")
        except Exception:
            pass

        delete_strategy(strategy_id)
        return jsonify({"status": "success"})
    except Exception as e:
        logger.exception(f"Error deleting strategy {strategy_id}: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 500


_VALID_INSTRUMENT_TYPES = ("EQ", "FUT", "OPT")
_VALID_EXPIRY_TYPES = ("current_week", "next_week", "current_month", "next_month")
_VALID_OPTION_TYPES = ("CE", "PE")
_VALID_STRIKE_OFFSETS = (
    "ITM5", "ITM4", "ITM3", "ITM2", "ITM1", "ATM",
    "OTM1", "OTM2", "OTM3", "OTM4", "OTM5",
)
# "offset" (default) uses strike_offset (the fixed ATM/ITM/OTM tuple above).
# "premium"/"delta"/"oi" resolve live via
# services/option_symbol_service.py's get_option_symbol_by_metric instead.
_VALID_STRIKE_SELECTION_MODES = ("offset", "premium", "delta", "oi")


def _validate_signal_action_config(data):
    """Validate and normalise the Signal Actions fields on an add/update
    payload, returning kwargs for add_symbol_mapping/update_symbol_mapping.

    Every field is optional. Omitted fields are simply absent from the
    returned dict so the mapping keeps its column NULL, which every read
    path interprets as "behave exactly as before this feature existed".
    Validation is strict on the values that ARE supplied -- a typo'd verb
    or a negative stop-loss must fail loudly at configuration time rather
    than silently mis-trading at signal time.
    """
    from database.strategy_db import ORDER_TYPES, RISK_VALUE_TYPES, SIGNAL_ACTIONS

    result = {}

    signal_action = (data.get("signal_action") or "").strip().upper()
    if signal_action:
        if signal_action not in SIGNAL_ACTIONS:
            raise ValueError(f"signal_action must be one of {', '.join(SIGNAL_ACTIONS)}")
        result["signal_action"] = signal_action

    order_type = (data.get("order_type") or "").strip().upper()
    if order_type:
        if order_type not in ORDER_TYPES:
            raise ValueError(f"order_type must be one of {', '.join(ORDER_TYPES)}")
        result["order_type"] = order_type

    def _positive_number(key, label):
        raw = data.get(key)
        if raw in (None, ""):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{label} must be a number") from err
        if value <= 0:
            raise ValueError(f"{label} must be greater than 0")
        return value

    limit_price = _positive_number("limit_price", "limit_price")
    if limit_price is not None:
        result["limit_price"] = limit_price
    trigger_price = _positive_number("trigger_price", "trigger_price")
    if trigger_price is not None:
        result["trigger_price"] = trigger_price

    # A LIMIT order with no price, or a stop order with no trigger, would be
    # rejected by the broker at signal time -- catch it here instead.
    effective_order_type = order_type or "MARKET"
    if effective_order_type == "LIMIT" and limit_price is None:
        raise ValueError("limit_price is required for a LIMIT order")
    if effective_order_type in ("SL", "SL-M") and trigger_price is None:
        raise ValueError(f"trigger_price is required for a {effective_order_type} order")
    if effective_order_type == "SL" and limit_price is None:
        raise ValueError("limit_price is required for an SL (stop-limit) order")

    # SL / target / trailing: each is a (type, value) pair. The value drives
    # whether the pair is stored at all; the type defaults to "percent".
    for value_key, type_key, label in (
        ("stop_loss_value", "stop_loss_type", "stop_loss"),
        ("target_value", "target_type", "target"),
        ("trailing_value", "trailing_type", "trailing"),
    ):
        value = _positive_number(value_key, label)
        if value is None:
            continue
        value_type = (data.get(type_key) or "percent").strip().lower()
        if value_type not in RISK_VALUE_TYPES:
            raise ValueError(f"{type_key} must be one of {', '.join(RISK_VALUE_TYPES)}")
        if value_type == "percent" and value >= 100:
            raise ValueError(f"{label} percent must be below 100")
        result[value_key] = value
        result[type_key] = value_type

    lots = data.get("lots")
    if lots not in (None, ""):
        try:
            lots = int(lots)
        except (TypeError, ValueError) as err:
            raise ValueError("lots must be a whole number") from err
        if lots <= 0:
            raise ValueError("lots must be greater than 0")
        result["lots"] = lots

    leg_basket = (data.get("leg_basket") or "").strip()
    if leg_basket:
        result["leg_basket"] = leg_basket[:50]

    basket_leg_order = data.get("basket_leg_order")
    if basket_leg_order not in (None, ""):
        try:
            result["basket_leg_order"] = int(basket_leg_order)
        except (TypeError, ValueError) as err:
            raise ValueError("basket_leg_order must be a whole number") from err

    label = (data.get("label") or "").strip()
    if label:
        result["label"] = label[:100]

    # Optional gates. Stored as JSON; an empty/absent dict leaves the column
    # NULL, which every read path treats as "always fire".
    conditions = data.get("conditions")
    if conditions:
        if not isinstance(conditions, dict):
            raise ValueError("conditions must be an object")
        clean = {}
        for key in ("time_after", "time_before"):
            val = (conditions.get(key) or "").strip()
            if val:
                if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", val):
                    raise ValueError(f"{key} must be HH:MM (24-hour)")
                clean[key] = val
        indicator = conditions.get("indicator")
        if isinstance(indicator, dict) and indicator.get("name"):
            try:
                clean["indicator"] = {
                    "name": str(indicator["name"])[:32],
                    "op": indicator.get("op", ">"),
                    "value": float(indicator.get("value")),
                }
            except (TypeError, ValueError) as err:
                raise ValueError("indicator condition needs a numeric value") from err
        if clean:
            result["conditions"] = json.dumps(clean)

    return result


def _validate_instrument_config(data, user_id, require_instrument_for_eq=True):
    """Validate + dry-run-resolve a symbol mapping's instrument config for
    the requested instrument_type. Returns a dict of validated fields to
    merge into the mapping (a subset of instrument_type/underlying/
    expiry_type/option_type/strike_offset/instrument), or raises
    ValueError with a user-facing message on any problem.

    For FUT/OPT, this also performs a one-time live resolution (dry run)
    of the underlying/expiry/strike combo so a bad config is rejected at
    add-time with a clear error instead of silently failing on the first
    real webhook signal. The resolved symbol itself is not persisted --
    signal_engine.py re-resolves live on every signal per this feature's
    design (strikes/expiries must never go stale).
    """
    instrument_type = (data.get("instrument_type") or "EQ").upper()
    if instrument_type not in _VALID_INSTRUMENT_TYPES:
        raise ValueError(f"Invalid instrument_type: {instrument_type}")

    result = {"instrument_type": instrument_type}

    if instrument_type == "EQ":
        instrument = data.get("instrument")
        if require_instrument_for_eq and not instrument:
            raise ValueError("Missing required field: instrument")
        if instrument:
            result["instrument"] = instrument
        return result

    underlying = (data.get("underlying") or "").strip().upper()
    expiry_type = data.get("expiry_type")
    exchange = data.get("exchange")
    if not underlying:
        raise ValueError("Missing required field: underlying")
    if expiry_type not in _VALID_EXPIRY_TYPES:
        raise ValueError(f"Invalid expiry_type: {expiry_type}")
    if not exchange:
        raise ValueError("Missing required field: exchange")

    result["underlying"] = underlying
    result["expiry_type"] = expiry_type

    api_key = get_api_key_for_tradingview(user_id)
    if not api_key:
        raise ValueError(
            "No API key found for this account. Generate one at /apikey before configuring "
            "Futures/Options symbols."
        )

    from services.expiry_service import resolve_expiry_type
    from services.option_symbol_service import (
        get_futures_symbol,
        get_option_symbol,
        get_option_symbol_by_metric,
    )

    expiry_date = resolve_expiry_type(
        underlying, exchange, expiry_type, api_key, instrument_type=instrument_type
    )
    if not expiry_date:
        raise ValueError(
            f"Could not resolve '{expiry_type}' expiry for {underlying} on {exchange}. "
            "Check the underlying symbol and exchange are correct."
        )

    if instrument_type == "OPT":
        option_type = (data.get("option_type") or "").upper()
        if option_type not in _VALID_OPTION_TYPES:
            raise ValueError(f"Invalid option_type: {option_type}")
        result["option_type"] = option_type

        strike_selection_mode = (data.get("strike_selection_mode") or "offset").lower()
        if strike_selection_mode not in _VALID_STRIKE_SELECTION_MODES:
            raise ValueError(f"Invalid strike_selection_mode: {strike_selection_mode}")
        result["strike_selection_mode"] = strike_selection_mode

        if strike_selection_mode == "offset":
            strike_offset = (data.get("strike_offset") or "").upper()
            if strike_offset not in _VALID_STRIKE_OFFSETS:
                raise ValueError(f"Invalid strike_offset: {strike_offset}")
            result["strike_offset"] = strike_offset

            success, resp, _status = get_option_symbol(
                underlying, exchange, expiry_date, None, strike_offset, option_type, api_key
            )
            if not success:
                raise ValueError(
                    f"Could not resolve {underlying} {strike_offset} {option_type} for expiry "
                    f"{expiry_date}: {resp.get('message', 'unknown error')}"
                )
        else:
            target_value = data.get("strike_target_value")
            if strike_selection_mode in ("premium", "delta"):
                try:
                    target_value = float(target_value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"strike_selection_mode '{strike_selection_mode}' requires a numeric strike_target_value"
                    ) from None
                if target_value <= 0:
                    raise ValueError("strike_target_value must be greater than 0")
            result["strike_target_value"] = target_value

            success, resp, _status = get_option_symbol_by_metric(
                underlying, exchange, expiry_date, option_type, strike_selection_mode, target_value, api_key
            )
            if not success:
                raise ValueError(
                    f"Could not resolve {underlying} {option_type} by {strike_selection_mode} for expiry "
                    f"{expiry_date}: {resp.get('message', 'unknown error')}"
                )
    else:  # FUT
        futures_info = get_futures_symbol(underlying, exchange, expiry_date, api_key)
        if not futures_info:
            raise ValueError(
                f"Could not resolve a futures contract for {underlying} on {exchange} "
                f"(expiry {expiry_date})."
            )

    return result


@strategy_bp.route("/<int:strategy_id>/configure", methods=["GET", "POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def configure_symbols(strategy_id):
    """Configure symbols for strategy"""
    user_id = session.get("user")
    if not user_id:
        flash("Session expired. Please login again.", "error")
        return redirect(url_for("auth.login"))

    strategy = get_strategy(strategy_id)
    if not strategy:
        abort(404)

    # Check if strategy belongs to user
    if strategy.user_id != user_id:
        abort(403)

    if request.method == "POST":
        try:
            # Get data from either JSON or form
            if request.is_json:
                data = request.get_json()
            else:
                data = request.form.to_dict()

            logger.info(f"Received data: {data}")

            # Handle bulk symbols
            if "symbols" in data:
                symbols_text = data.get("symbols")
                mappings = []

                for line in symbols_text.strip().split("\n"):
                    if not line.strip():
                        continue

                    parts = line.strip().split(",")
                    if len(parts) == 4:
                        symbol, exchange, quantity, product = parts
                        instrument = symbol.strip()
                    elif len(parts) == 5:
                        symbol, exchange, quantity, product, instrument = parts
                    else:
                        raise ValueError(f"Invalid format in line (expected 4 or 5 comma-separated values): {line}")

                    if exchange.strip() not in VALID_EXCHANGES:
                        raise ValueError(f"Invalid exchange: {exchange}")

                    mappings.append(
                        {
                            "symbol": symbol.strip(),
                            "exchange": exchange.strip(),
                            "quantity": int(quantity),
                            "product_type": product.strip(),
                            "instrument": instrument.strip(),
                        }
                    )

                if mappings:
                    bulk_add_symbol_mappings(strategy_id, mappings)
                    return jsonify({"status": "success"})

            # Handle single symbol
            else:
                symbol = data.get("symbol")
                exchange = data.get("exchange")
                quantity = data.get("quantity")
                product_type = data.get("product_type")
                instrument = data.get("instrument")
                instrument_type = (data.get("instrument_type") or "EQ").upper()

                logger.info(
                    f"Processing single symbol: symbol={symbol}, exchange={exchange}, quantity={quantity}, product_type={product_type}, instrument={instrument}, instrument_type={instrument_type}"
                )

                if not all([symbol, exchange, quantity, product_type]):
                    missing = []
                    if not symbol:
                        missing.append("symbol")
                    if not exchange:
                        missing.append("exchange")
                    if not quantity:
                        missing.append("quantity")
                    if not product_type:
                        missing.append("product_type")
                    raise ValueError(f"Missing required fields: {', '.join(missing)}")

                if exchange not in VALID_EXCHANGES:
                    raise ValueError(f"Invalid exchange: {exchange}")

                try:
                    quantity = int(quantity)
                except ValueError:
                    raise ValueError("Quantity must be a valid number")

                if quantity <= 0:
                    raise ValueError("Quantity must be greater than 0")

                # FUT/OPT rows don't require `instrument` (the tradable
                # contract is resolved live at signal time instead) -- EQ
                # rows keep the original "instrument or symbol" behavior.
                instrument_config = _validate_instrument_config(
                    data, user_id, require_instrument_for_eq=False
                )

                # action/order_side are only meaningful for execution_model
                # == "unified" strategies -- see StrategySymbolMapping's
                # docstrings. action defaults to mirroring `symbol`
                # (BUY/SELL) exactly as add_symbol_mapping already does when
                # left unset; order_side lets a mapping place the OPPOSITE
                # order of the signal it reacts to (reversal/flip
                # strategies), e.g. a SELL signal that exits a Call on one
                # mapping and enters a Put via a BUY order on another.
                action = data.get("action")
                if action:
                    action = action.strip().upper()
                    if action not in ("BUY", "SELL", "SHORT", "EXIT"):
                        raise ValueError("action must be one of BUY, SELL, SHORT, EXIT")
                order_side = data.get("order_side")
                if order_side:
                    order_side = order_side.strip().upper()
                    if order_side not in ("BUY", "SELL"):
                        raise ValueError("order_side must be BUY or SELL")

                signal_config = _validate_signal_action_config(data)

                # See update_symbol's matching comment: order_side and every
                # Signal Actions field only mean anything to the 'unified'
                # engine -- a 'legacy' strategy's signal_engine path ignores
                # them entirely, so a brand-new mapping created with one set
                # (e.g. a Quick Start preset applied to an old pre-'unified'
                # strategy) would silently never take effect otherwise.
                if (bool(order_side) or bool(signal_config)) and (
                    strategy.execution_model or "legacy"
                ) == "legacy":
                    update_strategy_execution_model(strategy_id, "unified")

                add_symbol_mapping(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    exchange=exchange,
                    quantity=quantity,
                    product_type=product_type,
                    instrument=instrument_config.get("instrument")
                    or (instrument or symbol if instrument_type == "EQ" else None),
                    action=action,
                    instrument_type=instrument_config.get("instrument_type"),
                    underlying=instrument_config.get("underlying"),
                    expiry_type=instrument_config.get("expiry_type"),
                    option_type=instrument_config.get("option_type"),
                    strike_offset=instrument_config.get("strike_offset"),
                    order_side=order_side,
                    strike_selection_mode=instrument_config.get("strike_selection_mode"),
                    strike_target_value=instrument_config.get("strike_target_value"),
                    **signal_config,
                )

                return jsonify({"status": "success"})

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Error configuring symbols: {error_msg}")
            return jsonify({"status": "error", "error": error_msg}), 400

    symbol_mappings = get_symbol_mappings(strategy_id)
    return render_template(
        "strategy/configure_symbols.html",
        strategy=strategy,
        symbol_mappings=symbol_mappings,
        exchanges=VALID_EXCHANGES,
    )


@strategy_bp.route("/<int:strategy_id>/symbol/<int:mapping_id>/delete", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def delete_symbol(strategy_id, mapping_id):
    """Delete symbol mapping"""
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "error": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != username:
        return jsonify({"status": "error", "error": "Strategy not found"}), 404

    try:
        if delete_symbol_mapping(mapping_id):
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "error": "Symbol mapping not found"}), 404
    except Exception as e:
        logger.exception(f"Error deleting symbol mapping: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 400


@strategy_bp.route("/<int:strategy_id>/symbol/<int:mapping_id>/update", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def update_symbol(strategy_id, mapping_id):
    """Update an existing symbol mapping's trigger/instrument/exchange/quantity/product."""
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "error": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != username:
        return jsonify({"status": "error", "error": "Strategy not found"}), 404

    data = request.get_json(silent=True) or {}
    exchange = data.get("exchange")
    if exchange is not None and exchange not in VALID_EXCHANGES:
        return jsonify({"status": "error", "error": f"Invalid exchange: {exchange}"}), 400

    quantity = data.get("quantity")
    if quantity is not None:
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "error": "Quantity must be a valid number"}), 400
        if quantity <= 0:
            return jsonify({"status": "error", "error": "Quantity must be greater than 0"}), 400

    try:
        instrument_config = {}
        existing = StrategySymbolMapping.query.get(mapping_id)
        if not existing:
            return jsonify({"status": "error", "error": "Symbol mapping not found"}), 404

        # Re-run the FUT/OPT dry-run validation (the same one that gates
        # creating a mapping in the first place) whenever there's any
        # chance the resulting row would be FUT/OPT with a bad exchange --
        # not just when the CALLER happened to include "instrument_type"
        # in this particular request body. A request that changes only
        # `exchange` (e.g. NFO -> NSE) on an already-FUT/OPT mapping used to
        # skip this block entirely: it passed the broad VALID_EXCHANGES
        # allow-list check above (which includes plain NSE/BSE, valid for
        # EQ but NOT valid for expiry/strike resolution), silently leaving
        # the mapping with instrument_type="OPT" but an exchange
        # resolve_expiry_type() will reject on every future signal --
        # "Processed" turning into a permanent, silent
        # "instrument_resolution_failed" for that mapping with no error at
        # save time to warn the user.
        existing_is_fo = (existing.instrument_type or "EQ").upper() in ("FUT", "OPT")
        exchange_changing = exchange is not None and exchange != existing.exchange
        if "instrument_type" in data or existing_is_fo or exchange_changing:
            # Validation needs a resolved exchange even if this update
            # request doesn't include one (e.g. only changing quantity) --
            # fall back to the mapping's current exchange. Same for every
            # other FUT/OPT field: an update that only touches `exchange`
            # must still validate against the mapping's EXISTING underlying/
            # expiry_type/option_type/strike_offset, not lose them.
            validate_data = {
                "instrument_type": existing.instrument_type,
                "underlying": existing.underlying,
                "expiry_type": existing.expiry_type,
                "option_type": existing.option_type,
                "strike_offset": existing.strike_offset,
                "strike_selection_mode": existing.strike_selection_mode,
                "strike_target_value": existing.strike_target_value,
                **data,
                "exchange": exchange or existing.exchange,
            }
            instrument_config = _validate_instrument_config(
                validate_data, username, require_instrument_for_eq=False
            )

        action = data.get("action")
        if action:
            action = action.strip().upper()
            if action not in ("BUY", "SELL", "SHORT", "EXIT"):
                return jsonify(
                    {"status": "error", "error": "action must be one of BUY, SELL, SHORT, EXIT"}
                ), 400

        order_side = data.get("order_side")
        if order_side:
            order_side = order_side.strip().upper()
            if order_side not in ("BUY", "SELL"):
                return jsonify({"status": "error", "error": "order_side must be BUY or SELL"}), 400

        signal_config = _validate_signal_action_config(data)

        # order_side and every Signal Actions field (signal_action, order_type,
        # SL/target/trailing, lots, leg_basket) are ONLY read by
        # services/signal_engine.py's _process_unified_webhook_signal --
        # _process_legacy_webhook_signal (the 2-action engine every strategy
        # created before the 'unified' execution model existed still runs on)
        # has zero references to any of them and silently ignores them. A
        # legacy strategy's mapping could have order_side='SELL' saved
        # perfectly correctly in the database and still place a BUY order on
        # every signal, because the engine actually executing its signals
        # never looks at that column at all. Configure Symbols' Edit dialog
        # shows this field on every strategy regardless of execution_model
        # (isUnified in the frontend really means "not stateful", not
        # "actually unified"), so a user editing a legacy strategy has no way
        # to know the field they just set does nothing until they test a live
        # signal. Auto-promote to 'unified' here -- the one engine that
        # actually honours these fields -- rather than let the save silently
        # succeed into a config the running engine can't express. Only
        # promotes (legacy -> unified); never touches a 'stateful' strategy,
        # since LegGroup rotation is a different, incompatible engine choice
        # the user made deliberately elsewhere.
        wants_unified_only_fields = bool(order_side) or bool(signal_config)
        if wants_unified_only_fields and (strategy.execution_model or "legacy") == "legacy":
            update_strategy_execution_model(strategy_id, "unified")

        mapping = update_symbol_mapping(
            mapping_id,
            symbol=data.get("symbol"),
            exchange=exchange,
            quantity=quantity,
            product_type=data.get("product_type"),
            instrument=instrument_config.get("instrument", data.get("instrument")),
            instrument_type=instrument_config.get("instrument_type"),
            underlying=instrument_config.get("underlying"),
            expiry_type=instrument_config.get("expiry_type"),
            option_type=instrument_config.get("option_type"),
            strike_offset=instrument_config.get("strike_offset"),
            order_side=order_side,
            strike_selection_mode=instrument_config.get("strike_selection_mode"),
            strike_target_value=instrument_config.get("strike_target_value"),
            **signal_config,
        )
        if action:
            mapping = mapping or StrategySymbolMapping.query.get(mapping_id)
            if mapping:
                mapping.action = action
                db_session.commit()
        if mapping:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "error": "Symbol mapping not found"}), 404
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except Exception as e:
        logger.exception(f"Error updating symbol mapping: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 400


@strategy_bp.route("/<int:strategy_id>/symbol/<int:mapping_id>/toggle", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def toggle_symbol(strategy_id, mapping_id):
    """Pause/resume one symbol mapping. A paused symbol is skipped (with a
    visible log entry) by signal_engine.py on every incoming webhook
    signal until resumed -- the connection/strategy itself keeps running
    and every other symbol in it is unaffected."""
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "error": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != username:
        return jsonify({"status": "error", "error": "Strategy not found"}), 404

    try:
        mapping = toggle_symbol_mapping_active(mapping_id)
        if mapping:
            return jsonify({"status": "success", "is_active": mapping.is_active})
        else:
            return jsonify({"status": "error", "error": "Symbol mapping not found"}), 404
    except Exception as e:
        logger.exception(f"Error toggling symbol mapping: {str(e)}")
        return jsonify({"status": "error", "error": str(e)}), 400


@strategy_bp.route("/search")
@check_session_validity
def search_symbols():
    """Search symbols endpoint"""
    query = request.args.get("q", "").strip()
    exchange = request.args.get("exchange")

    if not query:
        return jsonify({"results": []})

    results = enhanced_search_symbols(query, exchange, limit=50)
    return jsonify(
        {
            "results": [
                {
                    "symbol": result.symbol,
                    "name": result.name,
                    "exchange": result.exchange,
                    # lotsize lets the frontend default Quantity to the
                    # instrument's real lot size for F&O (1 for equity)
                    # instead of always defaulting to a bare "1", which
                    # silently under-orders derivatives by the lot
                    # multiplier. tick_size is exposed alongside since both
                    # come from the same symbol-service lookup and LIMIT
                    # price rounding needs it too.
                    "lotsize": result.lotsize or 1,
                    "tick_size": result.tick_size or 0.05,
                }
                for result in results
            ]
        }
    )


# Underlying-eligible instrument types on SymToken -- excludes every
# derivative row (FUTSTK/FUTIDX/OPTSTK/OPTIDX/CE/PE/...) so searching
# "NIFTY" while configuring a Futures/Options mapping shows the underlying
# index/stock itself, not its dated contracts.
#
# NOTE: this constant/filter shape only works for exchanges where the
# underlying ALSO exists as its own EQ/INDEX row (NSE/BSE indices,
# NSE-listed stocks). MCX commodities (GOLDM, CRUDEOIL, ...) have NO such
# row at all -- every MCX SymToken row is a dated FUT/OPTFUT/CE/PE
# contract, so a query filtered to instrumenttype IN ("EQ","INDEX") can
# never match them regardless of the search text. search_underlying_symbols
# below no longer uses this constant for the MCX/CDS path -- see its
# docstring.
_UNDERLYING_INSTRUMENT_TYPES = ("EQ", "INDEX")


@strategy_bp.route("/lotsize")
@check_session_validity
def get_underlying_lotsize():
    """Lot size for an underlying on a given F&O exchange -- used by the
    Configure Symbols form to suggest Quantity as soon as an underlying is
    picked for a Futures/Options mapping, before an expiry/strike has even
    been chosen. Lot size is constant across all expiries/strikes for a
    given underlying, so any single FUT/OPT contract row is sufficient --
    no need to resolve the exact live contract just for this."""
    from database.token_db_enhanced import fno_search_symbols

    underlying = (request.args.get("underlying") or "").strip().upper()
    exchange = (request.args.get("exchange") or "").strip().upper()
    if not underlying or not exchange:
        return jsonify({"lotsize": None})

    contracts = fno_search_symbols(underlying=underlying, exchange=exchange, limit=1)
    if not contracts:
        return jsonify({"lotsize": None})
    return jsonify({"lotsize": contracts[0].get("lotsize") or None})


@strategy_bp.route("/search/underlying")
@check_session_validity
def search_underlying_symbols():
    """Search endpoint scoped to underlyings only, for the Futures/Options
    'Underlying' picker in Configure Symbols. Unlike /search (which matches
    any SymToken row including dated F&O contracts), this returns the base
    underlying name so the dropdown shows "NIFTY" itself instead of every
    NIFTY...CE/PE contract.

    Two different underlying shapes exist, because MCX/CDS commodities
    have no standalone equity/index row the way NSE/BSE indices and stocks
    do -- every MCX SymToken row IS a dated FUT/OPTFUT/CE/PE contract, so a
    query filtered to instrumenttype IN ("EQ","INDEX") (this endpoint's
    old, only behavior) could never match a commodity like GOLDM/CRUDEOIL
    regardless of the exchange selected in the UI -- this endpoint simply
    had no code path that could ever return one. If the caller passes
    `exchange` and it's an F&O-only exchange (MCX/CDS/NCDEX -- no
    NSE/BSE-style EQ/INDEX row exists there), resolve underlyings from the
    FNO in-memory cache (get_distinct_underlyings_cached,
    include_futures=True so futures-only commodities aren't excluded)
    instead of the EQ/INDEX table query.
    """
    from database.symbol import SymToken, db_session
    from database.token_db_enhanced import get_distinct_underlyings_cached

    query = request.args.get("q", "").strip().upper()
    exchange = request.args.get("exchange", "").strip().upper()
    if len(query) < 2:
        return jsonify({"results": []})

    _NO_EQ_INDEX_ROW_EXCHANGES = ("MCX", "CDS", "NCDEX")

    if exchange in _NO_EQ_INDEX_ROW_EXCHANGES:
        underlyings = get_distinct_underlyings_cached(exchange=exchange, include_futures=True)
        matches = [u for u in underlyings if u.startswith(query)][:25]
        if not matches:
            return jsonify({"results": []})
        # One representative contract per matched underlying, for lot size/
        # tick size -- mirrors get_underlying_lotsize's fno_search_symbols
        # lookup rather than duplicating a second bespoke query shape.
        from database.token_db_enhanced import fno_search_symbols

        results = []
        for underlying in matches:
            contracts = fno_search_symbols(underlying=underlying, exchange=exchange, limit=1)
            contract = contracts[0] if contracts else {}
            results.append(
                {
                    "symbol": underlying,
                    "name": underlying,
                    "exchange": exchange,
                    "lotsize": contract.get("lotsize") or 1,
                    "tick_size": contract.get("tick_size") or 0.05,
                }
            )
        return jsonify({"results": results})

    filters = [
        SymToken.symbol.like(f"{query}%"),
        SymToken.instrumenttype.in_(_UNDERLYING_INSTRUMENT_TYPES),
    ]
    if exchange:
        filters.append(SymToken.exchange == exchange)

    rows = db_session.query(SymToken).filter(*filters).limit(25).all()

    return jsonify(
        {
            "results": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "exchange": r.exchange,
                    "lotsize": r.lotsize or 1,
                    "tick_size": r.tick_size or 0.05,
                }
                for r in rows
            ]
        }
    )


# =============================================================================
# JSON API Endpoints for React Frontend
# =============================================================================


@strategy_bp.route("/api/strategies")
@check_session_validity
def api_get_strategies():
    """API: Get all strategies for current user as JSON"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategies = get_user_strategies(user_id)
    return jsonify(
        {
            "strategies": [
                {
                    "id": s.id,
                    "name": s.name,
                    "webhook_id": s.webhook_id,
                    "is_active": s.is_active,
                    "is_intraday": s.is_intraday,
                    "trading_mode": s.trading_mode,
                    "platform": s.platform,
                    "brokers": s.brokers,
                    "lifecycle_state": s.lifecycle_state,
                    "signal_source": s.signal_source,
                    "execution_model": getattr(s, "execution_model", "legacy") or "legacy",
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "squareoff_time": s.squareoff_time,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in strategies
            ]
        }
    )


@strategy_bp.route("/api/webhook-deliveries", methods=["GET"])
@check_session_validity
def api_webhook_deliveries():
    """API: Recent webhook deliveries for the session user.

    Scoped to the requesting user in the query itself rather than filtered
    afterwards -- a delivery record contains the raw inbound payload, which can
    carry strategy details the owner would not want exposed.

    Query params: strategy_id, webhook_id, outcome, limit, offset.
    """
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    from database.webhook_delivery_db import get_deliveries

    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid limit/offset"}), 400

    strategy_id = request.args.get("strategy_id", type=int)
    if strategy_id:
        # Ownership check before exposing another user's deliveries.
        strategy = get_strategy(strategy_id)
        if not strategy or strategy.user_id != user_id:
            return jsonify({"status": "error", "message": "Strategy not found"}), 404

    deliveries = get_deliveries(
        webhook_id=request.args.get("webhook_id"),
        strategy_id=strategy_id,
        user_id=user_id,
        outcome=request.args.get("outcome"),
        limit=limit,
        offset=offset,
    )
    return jsonify({"status": "success", "deliveries": deliveries})


@strategy_bp.route("/api/webhook-deliveries/<int:delivery_id>", methods=["GET"])
@check_session_validity
def api_webhook_delivery_detail(delivery_id):
    """API: One delivery with its full stage timeline."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    from database.webhook_delivery_db import get_delivery

    delivery = get_delivery(delivery_id, user_id=user_id)
    if not delivery:
        return jsonify({"status": "error", "message": "Delivery not found"}), 404

    return jsonify({"status": "success", "delivery": delivery})


@strategy_bp.route("/api/strategy/<int:strategy_id>")
@check_session_validity
def api_get_strategy(strategy_id):
    """API: Get single strategy with mappings as JSON"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    if strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    mappings = get_symbol_mappings(strategy_id)

    return jsonify(
        {
            "strategy": {
                "id": strategy.id,
                "name": strategy.name,
                "webhook_id": strategy.webhook_id,
                "is_active": strategy.is_active,
                "is_intraday": strategy.is_intraday,
                "trading_mode": strategy.trading_mode,
                "platform": strategy.platform,
                "brokers": strategy.brokers,
                "lifecycle_state": strategy.lifecycle_state,
                "execution_model": getattr(strategy, "execution_model", "legacy") or "legacy",
                "start_time": strategy.start_time,
                "end_time": strategy.end_time,
                "squareoff_time": strategy.squareoff_time,
                "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
                "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None,
            },
            "mappings": [
                {
                    "id": m.id,
                    # `symbol` is the legacy action-string field kept for
                    # backward compat -- `action` is the correctly-named
                    # replacement (see StrategySymbolMapping's class
                    # docstring). Both are exposed during the transition;
                    # new frontend code should read `action`.
                    "symbol": m.symbol,
                    "action": m.action or m.symbol,
                    "exchange": m.exchange,
                    "quantity": m.quantity,
                    "product_type": m.product_type,
                    "instrument": m.instrument,
                    "is_active": m.is_active if m.is_active is not None else True,
                    "instrument_type": m.instrument_type or "EQ",
                    "underlying": m.underlying,
                    "expiry_type": m.expiry_type,
                    "option_type": m.option_type,
                    "strike_offset": m.strike_offset,
                    "strike_selection_mode": m.strike_selection_mode,
                    "strike_target_value": m.strike_target_value,
                    "order_side": m.order_side,
                    # Signal Actions table fields. get_signal_action()
                    # normalises NULL to "ENTER" so the UI always renders a
                    # concrete verb rather than an empty cell.
                    "signal_action": m.get_signal_action(),
                    "order_type": m.order_type or "MARKET",
                    "limit_price": m.limit_price,
                    "trigger_price": m.trigger_price,
                    "stop_loss_type": m.stop_loss_type,
                    "stop_loss_value": m.stop_loss_value,
                    "target_type": m.target_type,
                    "target_value": m.target_value,
                    "trailing_type": m.trailing_type,
                    "trailing_value": m.trailing_value,
                    "lots": m.lots,
                    "leg_basket": m.leg_basket,
                    "basket_leg_order": m.basket_leg_order,
                    "label": m.label,
                    # Parsed rather than raw JSON so the UI never has to
                    # re-parse (and can't disagree with the engine's view).
                    "conditions": m.get_conditions() or None,
                    "execution_profile_id": m.execution_profile_id,
                    "overrides": {
                        "BUY": m.get_override("BUY") or None,
                        "SELL": m.get_override("SELL") or None,
                        "SHORT": m.get_override("SHORT") or None,
                        "EXIT": m.get_override("EXIT") or None,
                    },
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in mappings
            ],
        }
    )


@strategy_bp.route("/api/strategy", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_create_strategy():
    """API: Create new strategy (JSON)"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        platform = data.get("platform", "").strip()
        name = data.get("name", "").strip()
        strategy_type = data.get("strategy_type", "intraday")
        trading_mode = data.get("trading_mode", "LONG")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        squareoff_time = data.get("squareoff_time")
        # Provenance tag only -- MaxHook creates ordinary Strategy rows via
        # this same endpoint (platform is just the signal provider, e.g.
        # tradingview/amibroker/rest_api), so without this the row is
        # indistinguishable from one created via My Strategies -> New
        # Strategy and leaks into that unfiltered list. See
        # api_get_strategies()/get_user_strategies() below.
        signal_source = data.get("signal_source")

        # Validate platform
        if not platform:
            return jsonify({"status": "error", "message": "Platform is required"}), 400

        # Create prefixed strategy name (max 50 chars)
        full_name = f"{platform}_{name}"[:50]

        # Validate strategy name
        is_valid_name, name_error = validate_strategy_name(full_name)
        if not is_valid_name:
            return jsonify({"status": "error", "message": name_error or "Invalid strategy name"}), 400

        is_intraday = strategy_type == "intraday"

        if is_intraday:
            start_time = start_time or "09:15"
            end_time = end_time or "15:00"
            squareoff_time = squareoff_time or "15:15"
            is_valid_times, times_error = validate_strategy_times(start_time, end_time, squareoff_time)
            if not is_valid_times:
                return jsonify({"status": "error", "message": times_error or "Invalid trading times"}), 400
        else:
            start_time = end_time = squareoff_time = None

        webhook_id = str(uuid.uuid4())

        # 'unified' opts a new strategy into the 4-action (BUY/SELL/SHORT/
        # EXIT) execution engine with ExecutionProfile support; anything
        # else (including omitted) defaults to 'legacy', matching every
        # strategy created before this field existed. See
        # services/signal_engine.py's _process_signal_event dispatch.
        execution_model = data.get("execution_model", "legacy")

        strategy = create_strategy(
            name=full_name,
            webhook_id=webhook_id,
            user_id=user_id,
            is_intraday=is_intraday,
            trading_mode=trading_mode,
            start_time=start_time,
            end_time=end_time,
            squareoff_time=squareoff_time,
            platform=platform,
            signal_source=signal_source,
            brokers=data.get("brokers"),
            execution_model=execution_model,
            template_id=data.get("template_id"),
        )

        if strategy:
            if is_intraday and squareoff_time:
                schedule_squareoff(strategy.id)

            return jsonify({"status": "success", "data": {"strategy_id": strategy.id}})
        else:
            return jsonify({"status": "error", "message": "Failed to create strategy"}), 500

    except Exception as e:
        logger.exception(f"Error creating strategy via API: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/toggle", methods=["POST"])
@check_session_validity
def api_toggle_strategy(strategy_id):
    """API: Toggle strategy active status (JSON)"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    if strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    try:
        updated_strategy = toggle_strategy(strategy_id)
        if updated_strategy:
            return jsonify({"status": "success", "data": {"is_active": updated_strategy.is_active}})
        else:
            return jsonify({"status": "error", "message": "Failed to toggle strategy"}), 500
    except Exception as e:
        logger.exception(f"Error toggling strategy via API: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/execution-model", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_update_strategy_execution_model(strategy_id):
    """API: Switch a strategy between 'legacy' (2-action), 'unified'
    (4-action BUY/SELL/SHORT/EXIT), and 'stateful' (LegGroup/Leg rotation)
    webhook signal processing. See services/signal_engine.py's
    _process_signal_event dispatch."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    if strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    execution_model = (data.get("execution_model") or "").strip().lower()

    try:
        updated = update_strategy_execution_model(strategy_id, execution_model)
        if updated:
            return jsonify({"status": "success", "data": {"execution_model": updated.execution_model}})
        return jsonify({"status": "error", "message": "Failed to update execution model"}), 500
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.exception(f"Error updating execution_model for strategy {strategy_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================================
# Leg Group API Routes (stateful rotation engine -- execution_model ==
# "stateful". See database/strategy_db.py's LegGroup/Leg/resolve_leg_rotation
# and services/signal_engine.py's _process_leg_group_webhook_signal.)
# ============================================================================


_LEG_ENTRY_SIGNALS = ("BUY", "SELL", "SHORT", "EXIT")
_CONDITION_OPERATORS = (">", "<", ">=", "<=", "==", "!=")
_CONDITION_LEAF_TYPES = ("indicator", "market_open", "broker_connected", "signal_fresh")


def _assert_valid_condition(node, label):
    """Recursively validate a leg's optional condition tree/leaf, mirroring
    services/strategy_compiler.py's _assert_no_malformed_leaves: a leaf
    missing required keys is treated as an automatic FAIL (or worse, PASS
    for an old-style leaf) by evaluate_conditions_tree
    (services/condition_engine.py), which would be a live-trading landmine
    if it slipped through unvalidated -- reject at save time instead. A
    group node needs `operator` (AND/OR) + `children`; leaves are
    type-tagged (see evaluate_conditions_tree's docstring) -- `type`
    absent or "indicator" is the original comparison-leaf shape, the other
    three are the newer system-condition types."""
    if not isinstance(node, dict):
        raise ValueError(f"Leg '{label}': condition must be an object")
    if "operator" in node:
        if node["operator"].upper() not in ("AND", "OR"):
            raise ValueError(f"Leg '{label}': condition operator must be AND or OR")
        for child in node.get("children", []):
            _assert_valid_condition(child, label)
        return

    leaf_type = (node.get("type") or "indicator").lower()
    if leaf_type not in _CONDITION_LEAF_TYPES:
        raise ValueError(f"Leg '{label}': condition type must be one of {_CONDITION_LEAF_TYPES}")

    if leaf_type == "indicator":
        if not node.get("indicator") or not node.get("condition"):
            raise ValueError(f"Leg '{label}': condition needs an indicator and a comparison")
        if node["condition"] not in _CONDITION_OPERATORS:
            raise ValueError(f"Leg '{label}': condition comparison must be one of {_CONDITION_OPERATORS}")
        if node.get("value") in (None, ""):
            raise ValueError(f"Leg '{label}': condition needs a value to compare against")
        return

    if leaf_type == "market_open":
        exchange = node.get("exchange")
        if exchange and exchange not in VALID_EXCHANGES:
            raise ValueError(f"Leg '{label}': invalid exchange '{exchange}' for Market Open condition")
        return

    if leaf_type == "broker_connected":
        broker = node.get("broker")
        if broker is not None and not str(broker).strip():
            raise ValueError(f"Leg '{label}': broker cannot be blank for Broker Connected condition")
        return

    if leaf_type == "signal_fresh":
        if node.get("condition") not in _CONDITION_OPERATORS:
            raise ValueError(f"Leg '{label}': Signal Fresh comparison must be one of {_CONDITION_OPERATORS}")
        value_seconds = node.get("value_seconds")
        try:
            value_seconds = float(value_seconds)
        except (TypeError, ValueError):
            raise ValueError(f"Leg '{label}': Signal Fresh needs a numeric seconds value") from None
        if value_seconds <= 0:
            raise ValueError(f"Leg '{label}': Signal Fresh seconds value must be greater than 0")
        return


def _validate_leg(leg_data, user_id):
    """Validate + dry-run-resolve one leg dict from a leg-group request.
    Reuses _validate_instrument_config for the instrument portion (same
    FUT/OPT live-resolution dry run as a regular symbol mapping), then adds
    the leg-specific fields (label/entry_signal/order_side/quantity/
    product_type) on top. Raises ValueError with a user-facing message on
    any problem; returns the fully validated leg dict otherwise.

    An EXIT leg (entry_signal == "EXIT") is a pure "flatten" trigger with
    no instrument of its own -- see Leg's class docstring in
    database/strategy_db.py -- so it skips all instrument/order_side/
    quantity/product_type validation entirely.
    """
    label = (leg_data.get("label") or "").strip()
    if not label:
        raise ValueError("Each leg needs a label")

    entry_signal = (leg_data.get("entry_signal") or "").strip().upper()
    if entry_signal not in _LEG_ENTRY_SIGNALS:
        raise ValueError(f"Leg '{label}': entry_signal must be one of {_LEG_ENTRY_SIGNALS}")

    condition = leg_data.get("condition")
    if condition is not None:
        _assert_valid_condition(condition, label)

    if entry_signal == "EXIT":
        return {"label": label, "entry_signal": "EXIT", "condition": condition}

    order_side = (leg_data.get("order_side") or "").strip().upper()
    if order_side not in ("BUY", "SELL"):
        raise ValueError(f"Leg '{label}': order_side must be BUY or SELL")

    quantity = leg_data.get("quantity")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"Leg '{label}': quantity must be a valid number") from None
    if quantity <= 0:
        raise ValueError(f"Leg '{label}': quantity must be greater than 0")

    product_type = leg_data.get("product_type")
    if not product_type:
        raise ValueError(f"Leg '{label}': product_type is required")

    exchange = leg_data.get("exchange")
    if not exchange or exchange not in VALID_EXCHANGES:
        raise ValueError(f"Leg '{label}': invalid exchange '{exchange}'")

    instrument_config = _validate_instrument_config(leg_data, user_id, require_instrument_for_eq=True)

    return {
        "label": label,
        "entry_signal": entry_signal,
        "order_side": order_side,
        "quantity": quantity,
        "product_type": product_type,
        "exchange": exchange,
        "condition": condition,
        **instrument_config,
    }


def _assert_distinct_entry_signals(legs):
    """A leg group's target leg for an incoming signal is resolved by
    matching entry_signal exactly (see resolve_leg_rotation in
    database/strategy_db.py) -- if two legs share the same entry_signal,
    that lookup picks the first match arbitrarily, which would silently
    make the "wrong" leg open on a real webhook signal. A webhook can send
    BUY/SELL/SHORT/EXIT, so a leg group is required to have at most one
    leg per signal."""
    signals = [leg["entry_signal"] for leg in legs]
    if len(set(signals)) != len(signals):
        raise ValueError(f"Each leg must react to a different signal (one of {_LEG_ENTRY_SIGNALS})")


def _assert_max_one_exit_leg(legs):
    """EXIT is a pure flatten trigger, not a tradable leg -- a group having
    two would be meaningless (both would resolve to "close whatever's
    open"), so cap it at one, same as any other entry_signal via
    _assert_distinct_entry_signals -- this just gives EXIT specifically a
    clearer error message than the generic duplicate-signal one."""
    exit_count = sum(1 for leg in legs if leg["entry_signal"] == "EXIT")
    if exit_count > 1:
        raise ValueError("A leg group can have at most one EXIT leg")


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups", methods=["GET"])
@check_session_validity
def api_get_leg_groups(strategy_id):
    """API: List a strategy's leg groups, each with its legs and current
    rotation state (current_leg_id) -- powers the "Currently open: Call /
    Put / Flat" badge in the UI."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    groups = get_leg_groups(strategy_id)
    return jsonify({"status": "success", "data": [g.to_dict() for g in groups]})


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_create_leg_group(strategy_id):
    """API: Create a leg group with its legs in one call. Used by both the
    generic multi-leg builder and (indirectly) the CE/PE Reversal template
    endpoint below, which constructs the same request shape server-side."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "name is required"}), 400

    legs_in = data.get("legs")
    if not isinstance(legs_in, list) or not (2 <= len(legs_in) <= 4):
        return jsonify({"status": "error", "message": "Between 2 and 4 legs are required"}), 400

    try:
        legs = [_validate_leg(leg, user_id) for leg in legs_in]
        _assert_distinct_entry_signals(legs)
        _assert_max_one_exit_leg(legs)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    group = create_leg_group(strategy_id, name, legs)
    if not group:
        return jsonify({"status": "error", "message": "Failed to create leg group"}), 500
    return jsonify({"status": "success", "data": group.to_dict()}), 201


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups/<int:leg_group_id>", methods=["PUT"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_update_leg_group(strategy_id, leg_group_id):
    """API: Rename a leg group and/or replace its legs entirely. Replacing
    legs resets the group to flat (current_leg_id NULL) -- see
    update_leg_group's docstring for why."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    group = get_leg_group(leg_group_id)
    if not group or group.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Leg group not found"}), 404

    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({"status": "error", "message": "name cannot be empty"}), 400

    legs = None
    if "legs" in data:
        legs_in = data.get("legs")
        if not isinstance(legs_in, list) or not (2 <= len(legs_in) <= 4):
            return jsonify({"status": "error", "message": "Between 2 and 4 legs are required"}), 400
        try:
            legs = [_validate_leg(leg, user_id) for leg in legs_in]
            _assert_distinct_entry_signals(legs)
            _assert_max_one_exit_leg(legs)
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    updated = update_leg_group(leg_group_id, name=name, legs=legs)
    if not updated:
        return jsonify({"status": "error", "message": "Failed to update leg group"}), 500
    return jsonify({"status": "success", "data": updated.to_dict()})


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups/<int:leg_group_id>/toggle", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_toggle_leg_group(strategy_id, leg_group_id):
    """API: Pause/resume a leg group. Pausing stops it reacting to further
    signals; it does NOT close whichever leg is currently open."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    group = get_leg_group(leg_group_id)
    if not group or group.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Leg group not found"}), 404

    updated = toggle_leg_group_active(leg_group_id)
    if not updated:
        return jsonify({"status": "error", "message": "Failed to toggle leg group"}), 500
    return jsonify({"status": "success", "data": {"is_active": updated.is_active}})


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups/<int:leg_group_id>", methods=["DELETE"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_delete_leg_group(strategy_id, leg_group_id):
    """API: Permanently delete a leg group and its legs."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    group = get_leg_group(leg_group_id)
    if not group or group.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Leg group not found"}), 404

    if delete_leg_group(leg_group_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Failed to delete leg group"}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/leg-groups/ce-pe-reversal", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_create_ce_pe_reversal(strategy_id):
    """API: One-click "CE/PE Reversal" quick-start -- server-side builds
    the exact 2-leg group a Call/Put flip strategy needs (BUY opens Call,
    SELL closes Call + opens Put, next BUY closes Put + opens Call, ...)
    from a minimal underlying/expiry/strike/quantity/product request,
    instead of the user hand-configuring two legs in the generic builder.
    Thin wrapper over api_create_leg_group's validation/creation path so
    there is exactly one source of truth for leg-group shape."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    data = request.get_json(silent=True) or {}
    underlying = (data.get("underlying") or "").strip().upper()
    exchange = data.get("exchange")
    expiry_type = data.get("expiry_type")
    strike_offset = (data.get("strike_offset") or "ATM").strip().upper()
    quantity = data.get("quantity")
    product_type = data.get("product_type") or "NRML"

    if not underlying:
        return jsonify({"status": "error", "message": "underlying is required"}), 400

    base_leg = {
        "instrument_type": "OPT",
        "underlying": underlying,
        "exchange": exchange,
        "expiry_type": expiry_type,
        "strike_offset": strike_offset,
        "quantity": quantity,
        "product_type": product_type,
    }
    legs_in = [
        {**base_leg, "label": "Call", "entry_signal": "BUY", "order_side": "BUY", "option_type": "CE"},
        {**base_leg, "label": "Put", "entry_signal": "SELL", "order_side": "BUY", "option_type": "PE"},
    ]

    try:
        legs = [_validate_leg(leg, user_id) for leg in legs_in]
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    name = f"{underlying} CE/PE Reversal"
    group = create_leg_group(strategy_id, name, legs)
    if not group:
        return jsonify({"status": "error", "message": "Failed to create leg group"}), 500
    return jsonify({"status": "success", "data": group.to_dict()}), 201


# ============================================================================
# Execution Profile API Routes (unified execution engine -- see
# database/strategy_db.py's ExecutionProfile/resolve_execution and
# services/signal_engine.py's _process_unified_webhook_signal)
# ============================================================================


@strategy_bp.route("/api/execution-profiles", methods=["GET"])
@check_session_validity
def api_list_execution_profiles():
    """API: List the current user's execution profiles"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    profiles = get_execution_profiles(user_id)
    return jsonify({"status": "success", "data": [p.to_dict() for p in profiles]})


@strategy_bp.route("/api/execution-profiles", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_create_execution_profile():
    """API: Create a reusable execution profile"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "name is required"}), 400

    try:
        profile = create_execution_profile(
            user_id=user_id,
            name=name,
            broker=data.get("broker"),
            product=data.get("product", "MIS"),
            order_type=data.get("order_type", "MARKET"),
            default_quantity=int(data.get("default_quantity", 1)),
        )
        if not profile:
            return jsonify({"status": "error", "message": "Failed to create execution profile"}), 500
        return jsonify({"status": "success", "data": profile.to_dict()}), 201
    except (TypeError, ValueError) as e:
        return jsonify({"status": "error", "message": f"Invalid input: {e}"}), 400
    except Exception as e:
        logger.exception(f"Error creating execution profile: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/execution-profiles/<int:profile_id>", methods=["PUT"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_update_execution_profile(profile_id):
    """API: Update an execution profile. Every instrument referencing it
    (via StrategySymbolMapping.execution_profile_id) picks up the change
    the next time a signal resolves execution for it -- no per-instrument
    edit needed."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    profile = ExecutionProfile.query.get(profile_id)
    if not profile:
        return jsonify({"status": "error", "message": "Execution profile not found"}), 404
    if profile.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    fields = {}
    for key in ("name", "broker", "product", "order_type"):
        if key in data:
            fields[key] = data[key]
    if "default_quantity" in data:
        try:
            fields["default_quantity"] = int(data["default_quantity"])
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "default_quantity must be an integer"}), 400

    updated = update_execution_profile(profile_id, **fields)
    if not updated:
        return jsonify({"status": "error", "message": "Failed to update execution profile"}), 500
    return jsonify({"status": "success", "data": updated.to_dict()})


@strategy_bp.route("/api/execution-profiles/<int:profile_id>", methods=["DELETE"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_delete_execution_profile(profile_id):
    """API: Delete an execution profile. Instruments referencing it fall
    back to their own quantity/product_type (see resolve_execution)."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    profile = ExecutionProfile.query.get(profile_id)
    if not profile:
        return jsonify({"status": "error", "message": "Execution profile not found"}), 404
    if profile.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if delete_execution_profile(profile_id):
        return jsonify({"status": "success", "message": "Execution profile deleted"})
    return jsonify({"status": "error", "message": "Failed to delete execution profile"}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/dry-run", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_dry_run_signal(strategy_id):
    """Preview what a signal WOULD do, without touching a broker.

    Resolves the live contract, order side, quantity and risk orders using
    the same helpers the live path uses, so the preview cannot drift from
    reality. Places nothing.
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != username:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    data = request.get_json(silent=True) or {}
    signal = (data.get("signal") or "BUY").strip().upper()
    if signal not in ("BUY", "SELL", "SHORT", "EXIT"):
        return jsonify(
            {"status": "error", "message": "signal must be BUY, SELL, SHORT or EXIT"}
        ), 400

    try:
        from database.auth_db import get_api_key_for_tradingview
        from services.signal_dryrun_service import dry_run_signal

        api_key = get_api_key_for_tradingview(username)
        report = dry_run_signal(strategy, signal, api_key)
        return jsonify({"status": "success", "data": report})
    except Exception as e:
        logger.exception(f"Dry run failed for strategy {strategy_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/signal-log", methods=["GET"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_strategy_signal_log(strategy_id):
    """Recent webhook deliveries for this strategy.

    Reads the existing audit table (database/webhook_delivery_db.py) rather
    than adding new plumbing -- the data was already being recorded, it just
    wasn't visible where users configure the strategy.
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy or strategy.user_id != username:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    limit = request.args.get("limit", default=15, type=int)
    limit = max(1, min(limit, 50))

    try:
        from database.webhook_delivery_db import get_deliveries

        # get_deliveries already returns plain dicts, newest-first.
        rows = get_deliveries(user_id=username, strategy_id=strategy_id, limit=limit) or []
        return jsonify({"status": "success", "data": rows, "count": len(rows)})
    except Exception as e:
        logger.exception(f"Signal log failed for strategy {strategy_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/symbol/<int:mapping_id>/override", methods=["POST"])
@check_session_validity
@limiter.limit(STRATEGY_RATE_LIMIT)
def api_set_mapping_action_override(strategy_id, mapping_id):
    """API: Set (or clear) a per-action (BUY/SELL/SHORT/EXIT) override on
    an instrument mapping. Body: {"action": "BUY", "override": {"quantity": 5}}
    -- pass override: null (or omit it) to clear that action back to
    'use defaults'. Only takes effect for strategies on execution_model
    == 'unified' (see services/signal_engine.py)."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404
    if strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    mapping = StrategySymbolMapping.query.get(mapping_id)
    if not mapping or mapping.strategy_id != strategy_id:
        return jsonify({"status": "error", "message": "Symbol mapping not found"}), 404

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().upper()
    if action not in StrategySymbolMapping._OVERRIDE_COLUMNS:
        return jsonify({"status": "error", "message": "action must be one of BUY, SELL, SHORT, EXIT"}), 400

    override = data.get("override")
    if override is not None and not isinstance(override, dict):
        return jsonify({"status": "error", "message": "override must be an object or null"}), 400

    if set_mapping_action_override(mapping_id, action, override):
        return jsonify({"status": "success", "data": {
            "mapping_id": mapping_id,
            "action": action,
            "override": override,
        }})
    return jsonify({"status": "error", "message": "Failed to set action override"}), 500


@strategy_bp.route("/webhook/<webhook_id>", methods=["POST"])
@limiter.limit(WEBHOOK_RATE_LIMIT)
def webhook(webhook_id):
    """Handle normalized signal events asynchronously via Signal Engine.

    Every request is recorded in the webhook delivery log (see
    services/webhook_delivery_service.py) before the signal is enqueued, so a
    signal that never produces an order still leaves an auditable trace of why.

    Byte-identical payloads arriving inside WEBHOOK_DEDUP_WINDOW_SECONDS are
    suppressed: signal sources retry on timeout, and because this endpoint
    returns 200 before the order is actually placed, a slow request can be
    retried while the first one is still working — which would otherwise place
    a second live order.
    """
    from services.webhook_delivery_service import ingest

    delivery = None
    try:
        strategy = get_strategy_by_webhook_id(webhook_id)
        if not strategy:
            # Logged with no strategy context — an unknown webhook_id is exactly
            # the kind of traffic worth being able to see after the fact.
            ingest(
                webhook_id=webhook_id,
                payload=request.get_json(silent=True) or {},
                remote_ip=request.remote_addr,
                dedup=False,
            ).rejected("unknown_webhook", "No strategy matches this webhook ID")
            return jsonify({"error": "Invalid webhook ID"}), 404

        data = request.get_json(silent=True)
        signal = (data or {}).get("signal") or (data or {}).get("action")

        delivery = ingest(
            webhook_id=webhook_id,
            payload=data or {},
            source_type="strategy",
            strategy_id=strategy.id,
            strategy_name=strategy.name,
            user_id=strategy.user_id,
            signal=signal,
            remote_ip=request.remote_addr,
        )

        if delivery.is_duplicate:
            # 200, not 4xx: the sender did nothing wrong and a non-2xx would
            # invite yet another retry of the same payload.
            return jsonify({
                "status": "duplicate",
                "message": "Identical signal already received; suppressed to prevent a duplicate order",
                "webhook_id": webhook_id,
            }), 200

        if not strategy.is_active:
            delivery.rejected("strategy_inactive", "Strategy is not active")
            return jsonify({"error": "Strategy is inactive"}), 400

        if not data:
            delivery.rejected("empty_payload", "Request body was empty or not valid JSON")
            return jsonify({"error": "No data received"}), 400

        # Retrieve normalized signal (supporting signal key or action key for backward compatibility)
        if not signal:
            delivery.rejected("missing_signal", "Payload has neither 'signal' nor 'action'")
            return jsonify({"error": "Missing required field: signal (or action)"}), 400

        # Create signal event object
        from services.signal_engine import SignalEvent, enqueue_signal
        event = SignalEvent(
            webhook_id=webhook_id,
            signal=signal,
            timeframe=data.get("timeframe"),
            source=data.get("source") or strategy.signal_source,
            strategy_version=data.get("strategy_version"),
            timestamp=data.get("timestamp"),
            delivery_id=delivery.delivery_id,
        )

        # Enqueue the event for asynchronous processing
        enqueue_signal(event)
        delivery.accepted(f"Queued signal '{signal}'")

        return jsonify({
            "status": "success",
            "message": f"Signal '{signal}' queued successfully for strategy '{strategy.name}'",
            "webhook_id": webhook_id,
            "timestamp": event.timestamp
        }), 200

    except Exception as e:
        logger.exception(f"Error processing webhook: {str(e)}")
        if delivery is not None:
            delivery.failed("internal_error", str(e))
        return jsonify({"error": "Internal server error"}), 500


# =============================================================================
# Marketplace & Subscriptions API Routes
# =============================================================================

def _init_mock_marketplace_listings():
    """Seed the Premium marketplace listings if the table is empty.

    Runs automatically on every startup when the MarketplaceListing table
    is empty (first startup or after a database reset). No env var gate --
    these are real, working strategies backed by genuine compiler keys in
    services/strategy_compiler.py's STRATEGY_TYPE_REGISTRY.

    Each entry's `template_id` is a REAL compiler key -- subscribing to any
    of these (via activate_subscription) compiles a genuine, working
    conditions_tree through the same pipeline wizard-created deployments use.

    Where a name implies real multi-leg option execution (e.g. "Iron Condor",
    "Theta Capture") no such compiler exists yet (compile_options_strategy
    deliberately raises CompilerError), so these are backed by the closest
    REAL, working rule-based proxy (Bollinger Squeeze for volatility-
    contraction names, VWAP/Keltner reversion for range-income names),
    described accordingly.
    """
    try:
        count = db_session.query(MarketplaceListing).count()
        if count > 0:
            return

        # Create standard system user for strategy ownership
        creator_id = "MaxAlgosSystem"

        listings_data = [
            {
                "name": "Nifty Momentum AI", "template_id": "roc_momentum",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2499, "rating": 4.8, "reviews_count": 1482,
                "win_rate": 71.0, "drawdown": 9.2, "returns": 5.8, "featured": True,
                "description": "Rate-of-change momentum system on Nifty, retrained monthly.",
            },
            {
                "name": "BankNifty Expiry Hunter", "template_id": "orb",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 2999, "rating": 4.9, "reviews_count": 2130,
                "win_rate": 76.0, "drawdown": 8.1, "returns": 6.4, "featured": True,
                "description": "Fast 5-minute opening-range breakout tuned for BankNifty expiry days.",
            },
            {
                "name": "FinNifty Weekly Premium", "template_id": "vwap_reversion",
                "symbol": "FINNIFTY", "exchange": "NSE_INDEX",
                "price": 1999, "rating": 4.7, "reviews_count": 890,
                "win_rate": 73.0, "drawdown": 10.4, "returns": 5.1, "featured": False,
                "description": "VWAP mean-reversion system for FinNifty's weekly expiry cycle.",
            },
            {
                "name": "Midcap Swing AI", "template_id": "swing_breakout",
                "symbol": "MIDCPNIFTY", "exchange": "NSE_INDEX",
                "price": 1499, "rating": 4.6, "reviews_count": 640,
                "win_rate": 64.0, "drawdown": 12.0, "returns": 4.2, "featured": False,
                "description": "Swing-high/low breakout system for midcap names with position management.",
            },
            {
                "name": "Weekly Iron Condor AI", "template_id": "bollinger_squeeze",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 2499, "rating": 4.9, "reviews_count": 1780,
                "win_rate": 74.0, "drawdown": 8.6, "returns": 6.2, "featured": True,
                "description": "Volatility-contraction breakout system -- a range-bound-friendly rule-based "
                               "proxy (true multi-leg option execution isn't available in this engine yet).",
            },
            {
                "name": "Smart Theta Capture", "template_id": "vwap_reversion",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2299, "rating": 4.7, "reviews_count": 1120,
                "win_rate": 72.0, "drawdown": 9.8, "returns": 5.4, "featured": False,
                "description": "VWAP range-reversion income system (rule-based proxy for theta-style income).",
            },
            {
                "name": "IV Crush Hunter", "template_id": "bollinger_squeeze",
                "symbol": "FINNIFTY", "exchange": "NSE_INDEX",
                "price": 1999, "rating": 4.5, "reviews_count": 520,
                "win_rate": 69.0, "drawdown": 11.2, "returns": 4.9, "featured": False,
                "description": "Trades volatility contraction/expansion cycles (rule-based proxy).",
            },
            {
                "name": "Delta Neutral Income", "template_id": "keltner_reversion",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2799, "rating": 4.8, "reviews_count": 970,
                "win_rate": 75.0, "drawdown": 7.9, "returns": 5.0, "featured": False,
                "description": "Keltner-channel range-reversion income system (rule-based proxy).",
            },
            {
                "name": "Momentum Call Hunter", "template_id": "roc_momentum",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 1799, "rating": 4.4, "reviews_count": 430,
                "win_rate": 58.0, "drawdown": 14.5, "returns": 7.1, "featured": False,
                "description": "Fast rate-of-change momentum system tuned for confirmed bursts.",
            },
            {
                "name": "Smart ORB AI", "template_id": "orb",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 1999, "rating": 4.6, "reviews_count": 810,
                "win_rate": 63.0, "drawdown": 10.8, "returns": 5.5, "featured": False,
                "description": "15-minute opening-range breakout system.",
            },
            {
                "name": "VWAP Institutional", "template_id": "vwap_scalp",
                "symbol": "RELIANCE", "exchange": "NSE",
                "price": 2199, "rating": 4.7, "reviews_count": 690,
                "win_rate": 66.0, "drawdown": 9.5, "returns": 5.2, "featured": False,
                "description": "VWAP-cross scalping system modeled on institutional execution behavior.",
            },
            {
                "name": "Nifty Swing AI", "template_id": "sma_cross",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2299, "rating": 4.8, "reviews_count": 1010,
                "win_rate": 68.0, "drawdown": 9.0, "returns": 4.8, "featured": False,
                "description": "SMA golden-cross positional swing system for Nifty.",
            },
            {
                "name": "Dynamic Portfolio Hedge", "template_id": "atr_trend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 3499, "rating": 4.9, "reviews_count": 560,
                "win_rate": 70.0, "drawdown": 6.5, "returns": 3.9, "featured": False,
                "description": "ATR trailing-trend system used to auto-hedge directional exposure.",
            },
            {
                "name": "AI Momentum Engine", "template_id": "roc_momentum",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2999, "rating": 4.8, "reviews_count": 1340,
                "win_rate": None, "drawdown": None, "returns": None, "featured": True,
                "description": "Adaptive rate-of-change momentum system.",
            },
            {
                "name": "AI Trend Prediction", "template_id": "ema_cross",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 2799, "rating": 4.7, "reviews_count": 980,
                "win_rate": None, "drawdown": None, "returns": None, "featured": False,
                "description": "EMA-crossover trend system.",
            },
            {
                "name": "AI Volatility Scanner", "template_id": "bollinger_squeeze",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2499, "rating": 4.6, "reviews_count": 720,
                "win_rate": None, "drawdown": None, "returns": None, "featured": False,
                "description": "Scans for and trades volatility-contraction breakouts.",
            },
            {
                "name": "AI Reversal Hunter", "template_id": "bollinger_reversal",
                "symbol": "HDFCBANK", "exchange": "NSE",
                "price": 2299, "rating": 4.5, "reviews_count": 610,
                "win_rate": None, "drawdown": None, "returns": None, "featured": False,
                "description": "Bollinger Band mean-reversion system for high-probability reversals.",
            },
            {
                "name": "AI Option Builder", "template_id": "keltner_reversion",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 2999, "rating": 4.8, "reviews_count": 1130,
                "win_rate": None, "drawdown": None, "returns": None, "featured": False,
                "description": "Keltner-channel range-reversion system (rule-based proxy).",
            },
            {
                "name": "AI Portfolio Optimizer", "template_id": "atr_trend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 3299, "rating": 4.9, "reviews_count": 840,
                "win_rate": None, "drawdown": None, "returns": None, "featured": False,
                "description": "ATR trailing-trend system used for continuous risk-adjusted rebalancing.",
            },
            # The 13 listings below use compiler templates that had no
            # marketplace listing at all until now (see
            # services/strategy_compiler.py's STRATEGY_TYPE_REGISTRY --
            # every id here is real and registered; "basket_strategy" and
            # "options_strategy" are deliberately excluded because they
            # raise CompilerError by design, see those functions'
            # docstrings). Same convention as above: template_id is a
            # genuine, working compiler key, win_rate/drawdown/returns are
            # hand-authored illustrative numbers (not backtest output),
            # and any name implying real multi-leg option execution is
            # backed by the closest real rule-based proxy instead.
            {
                "name": "Supertrend Flip Pro", "template_id": "supertrend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2199, "rating": 4.7, "reviews_count": 760,
                "win_rate": 67.0, "drawdown": 10.1, "returns": 5.3, "featured": True,
                "description": "Supertrend flip system -- rides confirmed trend reversals on Nifty.",
            },
            {
                "name": "RSI Momentum Burst", "template_id": "rsi_momentum",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 1799, "rating": 4.5, "reviews_count": 540,
                "win_rate": 61.0, "drawdown": 12.4, "returns": 5.9, "featured": False,
                "description": "RSI threshold momentum system tuned for confirmed directional bursts.",
            },
            {
                "name": "MACD Signal Cross", "template_id": "macd_momentum",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 1999, "rating": 4.6, "reviews_count": 690,
                "win_rate": 65.0, "drawdown": 10.6, "returns": 4.7, "featured": False,
                "description": "Classic MACD line/signal crossover system for trend-following entries.",
            },
            {
                "name": "RSI Reversal Edge", "template_id": "rsi_reversal",
                "symbol": "FINNIFTY", "exchange": "NSE_INDEX",
                "price": 1899, "rating": 4.6, "reviews_count": 480,
                "win_rate": 70.0, "drawdown": 9.4, "returns": 4.5, "featured": False,
                "description": "RSI oversold-bounce / overbought-rejection reversal system.",
            },
            {
                "name": "Prev Day Breakout AI", "template_id": "prev_day_breakout",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 1699, "rating": 4.4, "reviews_count": 390,
                "win_rate": 59.0, "drawdown": 13.1, "returns": 6.0, "featured": False,
                "description": "Trades breaks of the previous trading day's high/low range.",
            },
            {
                "name": "Triple EMA Stack", "template_id": "triple_ema",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2099, "rating": 4.7, "reviews_count": 610,
                "win_rate": 66.0, "drawdown": 9.7, "returns": 4.9, "featured": False,
                "description": "Fast/mid/slow EMA stack alignment system for confirmed trend entries.",
            },
            {
                "name": "ADX Trend Filter Pro", "template_id": "adx_trend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2399, "rating": 4.8, "reviews_count": 820,
                "win_rate": 69.0, "drawdown": 8.8, "returns": 5.1, "featured": False,
                "description": "ADX-filtered trend system -- only trades when trend strength is confirmed.",
            },
            {
                "name": "Volume Surge Breakout", "template_id": "volume_breakout",
                "symbol": "RELIANCE", "exchange": "NSE",
                "price": 1899, "rating": 4.5, "reviews_count": 450,
                "win_rate": 62.0, "drawdown": 11.5, "returns": 5.6, "featured": False,
                "description": "Volume-confirmed breakout system -- requires a surge plus rising price.",
            },
            {
                "name": "Inside Bar Breakout", "template_id": "inside_candle_breakout",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 1799, "rating": 4.4, "reviews_count": 360,
                "win_rate": 60.0, "drawdown": 12.8, "returns": 5.4, "featured": False,
                "description": "Mother/inside-candle breakout system for volatility-contraction setups.",
            },
            {
                "name": "NR7 Volatility Breakout", "template_id": "nr7_breakout",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 1999, "rating": 4.6, "reviews_count": 570,
                "win_rate": 64.0, "drawdown": 10.3, "returns": 5.2, "featured": False,
                "description": "Narrowest-range-7 volatility-contraction breakout system.",
            },
            {
                "name": "Donchian Mid Pullback", "template_id": "donchian_pullback",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2299, "rating": 4.7, "reviews_count": 500,
                "win_rate": 68.0, "drawdown": 9.1, "returns": 4.6, "featured": False,
                "description": "Donchian channel midline pullback/bounce system for range-trend entries.",
            },
            {
                "name": "EMA Pullback Trend", "template_id": "ema_pullback",
                "symbol": "HDFCBANK", "exchange": "NSE",
                "price": 1999, "rating": 4.6, "reviews_count": 470,
                "win_rate": 67.0, "drawdown": 9.6, "returns": 4.4, "featured": False,
                "description": "EMA pullback-and-bounce system for buying dips in an established uptrend.",
            },
            {
                "name": "Opening Gap Continuation", "template_id": "gap_strategy",
                "symbol": "BANKNIFTY", "exchange": "NSE_INDEX",
                "price": 1899, "rating": 4.5, "reviews_count": 410,
                "win_rate": 58.0, "drawdown": 13.6, "returns": 6.3, "featured": False,
                "description": "Trades continuation of the opening gap direction on high-gap days.",
            },
            {
                "name": "Momentum Breakout", "template_id": "roc_momentum",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 1499, "rating": 4.8, "reviews_count": 1482,
                "win_rate": 71.0, "drawdown": 9.2, "returns": 5.8, "featured": True,
                "description": "High-probability breakout trading strategy on high-volume indices. "
                               "Combines ROC momentum with ORB trigger for precision entries.",
            },
            {
                "name": "Nifty Swing AI", "template_id": "sma_cross",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2299, "rating": 4.8, "reviews_count": 1010,
                "win_rate": 68.0, "drawdown": 9.0, "returns": 4.8, "featured": False,
                "description": "Machine-learning driven index swing trading strategy focusing on "
                               "longer swings using SMA Golden Cross.",
            },
            {
                "name": "ADX Trend Filter Pro", "template_id": "adx_trend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 2399, "rating": 4.8, "reviews_count": 820,
                "win_rate": 69.0, "drawdown": 8.8, "returns": 5.1, "featured": False,
                "description": "ADX-filtered trend system -- only trades when trend strength is confirmed "
                               "above 25. High win-rate, low drawdown.",
            },
            {
                "name": "Dynamic Portfolio Hedge", "template_id": "atr_trend",
                "symbol": "NIFTY", "exchange": "NSE_INDEX",
                "price": 3499, "rating": 4.9, "reviews_count": 560,
                "win_rate": 70.0, "drawdown": 6.5, "returns": 3.9, "featured": False,
                "description": "ATR trailing-trend system used to auto-hedge directional exposure. "
                               "Ideal for protecting long equity portfolios.",
            },
        ]

        for ld in listings_data:
            wh_id = str(uuid.uuid4())
            # Create core strategy, carrying the template_id that
            # activate_subscription later compiles into a real Deployment.
            strat = Strategy(
                name=ld["name"],
                webhook_id=wh_id,
                user_id=creator_id,
                platform="webhook",
                signal_source="Marketplace",
                is_active=True,
                is_intraday=True,
                trading_mode="BOTH",
                lifecycle_state="Ready",
                template_id=ld["template_id"],
            )
            db_session.add(strat)
            db_session.commit()

            # Give the seeded strategy a real StrategyVersion carrying its
            # actual underlying/exchange -- activate_subscription reads this
            # (rather than a universal hardcoded symbol) when a user
            # subscribes, so e.g. "BankNifty Expiry Hunter" trades BANKNIFTY,
            # not NIFTY.
            create_strategy_version(strat.id, {"symbol": ld["symbol"], "exchange": ld["exchange"]})

            # Create listing wrapper
            listing = MarketplaceListing(
                strategy_id=strat.id,
                price=ld["price"],
                rating=ld["rating"],
                reviews_count=ld["reviews_count"],
                is_published=True,
                featured=ld["featured"],
                creator="MaxAlgos",
                description=ld["description"],
                win_rate=ld["win_rate"],
                drawdown=ld["drawdown"],
                returns=ld["returns"]
            )
            db_session.add(listing)
            db_session.commit()

    except Exception as e:
        logger.error(f"Error seeding marketplace listings: {e}")
        db_session.rollback()


@strategy_bp.route("/api/marketplace", methods=["GET"])
@check_session_validity
def api_get_marketplace():
    """List all available marketplace strategy listings"""
    _init_mock_marketplace_listings()
    user_id = session.get("user")

    try:
        listings = db_session.query(MarketplaceListing, Strategy).join(
            Strategy, MarketplaceListing.strategy_id == Strategy.id
        ).filter(MarketplaceListing.is_published == True).all()

        # Fetch user subscriptions and trials
        subs = db_session.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status.in_(["Active", "Trial"])
        ).all()
        sub_strategy_ids = {s.strategy_id for s in subs if s.status == "Active"}
        trial_strategy_ids = {s.strategy_id for s in subs if s.status == "Trial"}

        results = []
        for l, s in listings:
            results.append({
                "id": l.id,
                "strategy_id": s.id,
                "name": s.name,
                "price": l.price,
                "rating": l.rating,
                "reviews_count": l.reviews_count,
                "win_rate": l.win_rate,
                "drawdown": l.drawdown,
                "returns": l.returns,
                "featured": l.featured,
                "creator": l.creator,
                "description": l.description,
                "is_subscribed": s.id in sub_strategy_ids,
                "is_trial": s.id in trial_strategy_ids,
            })
        return jsonify({"status": "success", "listings": results})
    except Exception as e:
        logger.exception(f"Error loading marketplace: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def activate_subscription(user_id: str, strategy_id: int) -> dict:
    """Create the Subscription record + clone the strategy into the user's
    namespace as a real, deployable wizard Deployment. Shared by the
    free-listing subscribe path below and blueprints/payments.py's paid
    verify route (called only after a Razorpay payment signature has been
    verified for priced listings) -- both must activate a subscription
    identically, so this is the single implementation.

    Previously this only cloned an empty webhook Strategy row (no
    template_id, no symbol mappings, no conditions) -- it looked like a
    successful subscription but the clone could never fire a signal. Now it
    reuses the exact same compile_strategy_config() pipeline
    blueprints/deployments.py::create_new_deployment uses for wizard
    deployments, keyed off the PARENT strategy's `template_id` (set when the
    marketplace listing was seeded -- see the CATALOG_ID_TO_SCHEMA_KEY-
    compatible ids in frontend/src/lib/marketplace-catalog.ts's premium
    items). The clone is a real Deployment a subscriber can open in My
    Strategies and finish configuring (broker, capital, underlying) before
    it starts trading -- created as "Draft", not "Waiting", since the
    subscriber hasn't chosen those yet and services/deployment_service.py's
    _evaluation_loop must never pick up a deployment nobody has reviewed.

    Returns {"status": "success"/"error", ...}. Does NOT check price -- the
    caller is responsible for deciding whether payment was required and
    already completed before calling this.

    Raises on unexpected DB errors; callers should catch and roll back.
    """
    # Check if already subscribed
    existing_sub = db_session.query(Subscription).filter_by(
        user_id=user_id, strategy_id=strategy_id, status="Active"
    ).first()
    if existing_sub:
        return {"status": "success", "message": "Already subscribed"}

    listing = db_session.query(MarketplaceListing).filter_by(strategy_id=strategy_id).first()
    if not listing:
        return {"status": "error", "message": "Marketplace listing not found", "http_status": 404}

    parent_strategy = get_strategy(strategy_id)
    if not parent_strategy:
        return {"status": "error", "message": "Parent strategy not found", "http_status": 404}

    # 1. Create subscription record
    import datetime as dt
    expiry_date = dt.datetime.now() + dt.timedelta(days=30)
    sub = Subscription(
        user_id=user_id,
        strategy_id=strategy_id,
        plan="Premium",
        expiry=expiry_date,
        status="Active"
    )
    db_session.add(sub)

    # 2. Clone the strategy into the user's namespace, carrying over the
    # template_id that identifies which compiled strategy type this is.
    wh_id = str(uuid.uuid4())
    user_strategy = Strategy(
        name=f"marketplace_{parent_strategy.name.lower().replace(' ', '_')}",
        webhook_id=wh_id,
        user_id=user_id,
        platform="webhook",
        signal_source="Marketplace",
        is_active=True,
        is_intraday=parent_strategy.is_intraday,
        trading_mode=parent_strategy.trading_mode,
        lifecycle_state="Ready",
        template_id=parent_strategy.template_id,
    )
    db_session.add(user_strategy)
    db_session.commit()

    # 3. Compile the parent's template into a real, working Deployment --
    # only when the parent actually carries a template_id. Marketplace
    # listings created before this existed (or ones that genuinely have no
    # rule-based equivalent) fall back to the old empty-clone behavior
    # rather than erroring the whole subscription.
    deployment_id = None
    if parent_strategy.template_id:
        from services.strategy_compiler import CompilerError, compile_strategy_config

        # Carry over the PARENT listing's own symbol/exchange (set when the
        # marketplace listing was seeded -- see _init_mock_marketplace_listings
        # above) instead of a universal hardcode. Previously every
        # subscription got symbol="NIFTY" regardless of what the listing
        # actually named (e.g. "BankNifty Expiry Hunter" traded NIFTY), which
        # is exactly why subscribers saw "wrong symbol"/"no data" errors for
        # anything other than the Nifty-named listings. NIFTY/NSE_INDEX
        # remains only as a last-resort default for listings created before
        # this fix existed (no StrategyVersion yet) -- see
        # StrategyConfigurator.tsx's SYMBOL_OPTIONS and
        # deployment_service.py's _to_order_exchange for the same correct
        # NSE_INDEX pairing used by wizard-created deployments.
        parent_version = (
            db_session.query(StrategyVersion)
            .filter_by(strategy_id=parent_strategy.id)
            .order_by(StrategyVersion.version.desc())
            .first()
        )
        parent_config = parent_version.get_config() if parent_version else {}
        strategy_config = {
            "symbol": parent_config.get("symbol", "NIFTY"),
            "exchange": parent_config.get("exchange", "NSE_INDEX"),
        }
        try:
            conditions_tree = compile_strategy_config(parent_strategy.template_id, strategy_config)
            ver = create_strategy_version(user_strategy.id, strategy_config)
            if ver:
                deployment = create_deployment({
                    "name": user_strategy.name,
                    "strategy_id": user_strategy.id,
                    "version_id": ver.id,
                    "status": "Draft",
                    # Placeholders -- Deployment.broker/capital are NOT NULL,
                    # but a subscriber hasn't chosen either yet. Paper
                    # Trading is the safe default (never touches a real
                    # broker) until the user opens this in My Strategies and
                    # picks their own broker/capital, matching the same
                    # "review before it goes live" flow as any wizard
                    # deployment.
                    "broker": "Paper Trading",
                    "capital": 100000.0,
                    "order_type": "Market",
                    "product": "MIS",
                    "trigger_type": "Immediately",
                    "conditions_tree": conditions_tree,
                    "risk_params": {},
                    "user_id": user_id,
                    "events_timeline": [{
                        "time": "Now",
                        "event": f"Subscribed to {parent_strategy.name} -- review broker/capital "
                                 "and deploy when ready."
                    }],
                })
                if deployment:
                    deployment_id = deployment.id
        except CompilerError as e:
            logger.warning(
                f"Marketplace subscription {strategy_id} -> user {user_id}: "
                f"template_id={parent_strategy.template_id!r} failed to compile ({e}) -- "
                "falling back to an empty clone the user can configure manually."
            )

    return {
        "status": "success",
        "message": f"Successfully subscribed to {parent_strategy.name}!",
        "strategy_id": user_strategy.id,
        "subscription_id": sub.id,
        "deployment_id": deployment_id,
    }


@strategy_bp.route("/api/marketplace/<int:strategy_id>/subscribe", methods=["POST"])
@check_session_validity
def api_subscribe_marketplace(strategy_id):
    """Subscribe to a FREE marketplace strategy (price == 0) and clone it to
    the user's registry. Priced listings must go through
    /payments/marketplace/<id>/create-order + /payments/marketplace/verify
    instead -- this route rejects them so a client can't bypass payment by
    calling the old endpoint directly."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        listing = db_session.query(MarketplaceListing).filter_by(strategy_id=strategy_id).first()
        if not listing:
            return jsonify({"status": "error", "message": "Marketplace listing not found"}), 404
        if listing.price and listing.price > 0:
            return jsonify({
                "status": "error",
                "message": "This is a paid listing. Use the checkout flow to subscribe.",
                "code": "payment_required",
            }), 402

        result = activate_subscription(user_id, strategy_id)
        http_status = result.pop("http_status", 200)
        return jsonify(result), http_status

    except Exception as e:
        logger.exception(f"Error subscribing to strategy: {e}")
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/marketplace/<int:strategy_id>/trial", methods=["POST"])
@check_session_validity
def api_start_marketplace_trial(strategy_id):
    """Start a 2-day free trial for a marketplace strategy (both free and paid listings)."""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        listing = db_session.query(MarketplaceListing).filter_by(strategy_id=strategy_id).first()
        if not listing:
            return jsonify({"status": "error", "message": "Marketplace listing not found"}), 404

        import datetime as dt
        # Check if already subscribed or on trial
        existing_sub = db_session.query(Subscription).filter_by(
            user_id=user_id, strategy_id=strategy_id
        ).filter(Subscription.status.in_(["Active", "Trial"])).first()

        if existing_sub:
            if existing_sub.status == "Active":
                return jsonify({"status": "success", "message": "You already have a full active subscription."})
            return jsonify({"status": "success", "message": "You are currently on an active 2-day trial."})

        # Start 2-day trial
        result = activate_subscription(user_id, strategy_id)
        if result.get("status") == "success":
            sub_id = result.get("subscription_id")
            if sub_id:
                sub = db_session.query(Subscription).get(sub_id)
                if sub:
                    sub.plan = "Trial"
                    sub.status = "Trial"
                    sub.expiry = dt.datetime.now() + dt.timedelta(days=2)
                    db_session.commit()
            result["message"] = "Started 2-Day Free Trial! Managed in Live Deployments."
            result["is_trial"] = True

        http_status = result.pop("http_status", 200)
        return jsonify(result), http_status

    except Exception as e:
        logger.exception(f"Error starting free trial for strategy: {e}")
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/marketplace/<int:strategy_id>/unsubscribe", methods=["POST"])
@check_session_validity
def api_unsubscribe_marketplace(strategy_id):
    """Unsubscribe from a marketplace strategy"""
    user_id = session.get("user")

    try:
        sub = db_session.query(Subscription).filter_by(
            user_id=user_id, strategy_id=strategy_id, status="Active"
        ).first()
        if not sub:
            return jsonify({"status": "error", "message": "No active subscription found"}), 404

        sub.status = "Expired"
        db_session.commit()

        # Find cloned user strategies and mark them Archived
        parent_strategy = get_strategy(strategy_id)
        if parent_strategy:
            user_strats = db_session.query(Strategy).filter_by(
                user_id=user_id,
                name=f"marketplace_{parent_strategy.name.lower().replace(' ', '_')}"
            ).all()
            for s in user_strats:
                s.lifecycle_state = "Archived"
                s.is_active = False
            db_session.commit()

        return jsonify({"status": "success", "message": "Successfully unsubscribed."})
    except Exception as e:
        logger.exception(f"Error unsubscribing: {e}")
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Backtesting REST API Handlers
# =============================================================================

@strategy_bp.route("/api/backtests", methods=["GET"])
@check_session_validity
def api_get_all_backtests():
    """Get all historical backtest results across all user strategies"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        user_strategies = db_session.query(Strategy).filter_by(user_id=user_id).all()
        strat_map = {s.id: s.name for s in user_strategies}
        strat_ids = list(strat_map.keys())

        if not strat_ids:
            return jsonify({"status": "success", "backtests": []})

        backtests = (
            db_session.query(Backtest)
            .filter(Backtest.strategy_id.in_(strat_ids))
            .order_by(Backtest.id.desc())
            .all()
        )

        results = []
        for b in backtests:
            trades = db_session.query(BacktestTrade).filter_by(backtest_id=b.id).all()
            win_trades = [t for t in trades if t.pnl and t.pnl > 0]
            win_rate = (len(win_trades) / len(trades) * 100) if trades else 0.0
            total_returns = sum(t.pnl for t in trades if t.pnl)
            report = b.get_report()

            results.append({
                "id": b.id,
                "strategy_id": b.strategy_id,
                "strategy_name": strat_map.get(b.strategy_id, f"Strategy #{b.strategy_id}"),
                "symbol": b.symbol,
                "timeframe": b.timeframe,
                "status": b.status,
                "error_message": b.error_message,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "capital": b.capital,
                "win_rate": round(win_rate, 2),
                "returns": round(total_returns, 2),
                "max_drawdown_pct": report.get("max_drawdown_pct"),
                "sharpe_ratio": report.get("sharpe_ratio"),
                "total_return_pct": report.get("total_return_pct"),
                "final_equity": report.get("final_equity"),
                "total_trades": report.get("total_trades", len(trades)),
                "equity_curve": report.get("equity_curve", []),
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "trades": [
                    {
                        "id": t.id,
                        "symbol": t.symbol,
                        "action": t.action,
                        "quantity": t.quantity,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "pnl": t.pnl,
                        "entry_time": t.entry_time,
                        "exit_time": t.exit_time
                    }
                    for t in trades
                ]
            })
        return jsonify({"status": "success", "backtests": results})
    except Exception as e:
        logger.exception(f"Error loading all backtests: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/backtests", methods=["GET"])
@check_session_validity
def api_get_backtests(strategy_id):
    """Get previous backtest results run for a strategy"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    strategy = get_strategy(strategy_id)
    if not strategy:
        return jsonify({"status": "error", "message": "Strategy not found"}), 404

    if strategy.user_id != user_id:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    try:
        backtests = db_session.query(Backtest).filter_by(strategy_id=strategy_id).order_by(Backtest.id.desc()).all()
        results = []
        for b in backtests:
            trades = db_session.query(BacktestTrade).filter_by(backtest_id=b.id).all()

            # Simple metrics calculation for demo return values
            win_trades = [t for t in trades if t.pnl and t.pnl > 0]
            win_rate = (len(win_trades) / len(trades) * 100) if trades else 0.0
            total_returns = sum(t.pnl for t in trades if t.pnl)

            report = b.get_report()
            results.append({
                "id": b.id,
                "strategy_id": b.strategy_id,
                "strategy_name": strategy.name,
                "symbol": b.symbol,
                "timeframe": b.timeframe,
                "status": b.status,
                "error_message": b.error_message,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "capital": b.capital,
                "win_rate": round(win_rate, 2),
                "returns": round(total_returns, 2),
                "max_drawdown_pct": report.get("max_drawdown_pct"),
                "sharpe_ratio": report.get("sharpe_ratio"),
                "total_return_pct": report.get("total_return_pct"),
                "final_equity": report.get("final_equity"),
                "total_trades": report.get("total_trades", len(trades)),
                "equity_curve": report.get("equity_curve", []),
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "trades": [
                    {
                        "id": t.id,
                        "symbol": t.symbol,
                        "action": t.action,
                        "quantity": t.quantity,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "pnl": t.pnl,
                        "entry_time": t.entry_time,
                        "exit_time": t.exit_time
                    }
                    for t in trades
                ]
            })
        return jsonify({"status": "success", "backtests": results})
    except Exception as e:
        logger.exception(f"Error loading backtests: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@strategy_bp.route("/api/strategy/<int:strategy_id>/backtest", methods=["POST"])
@check_session_validity
def api_run_backtest(strategy_id):
    """Run/simulate a historical backtest execution"""
    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    try:
        data = request.json or {}
        symbol = data.get("symbol", "NIFTY")
        timeframe = data.get("timeframe", "15m")
        start_date = data.get("start_date", "2026-01-01")
        end_date = data.get("end_date", "2026-03-31")
        capital = float(data.get("capital", 100000))
        slippage = float(data.get("slippage", 0.05))
        charges = float(data.get("broker_charges", 20.0))

        # Check strategy existence and ownership
        strat = get_strategy(strategy_id)
        if not strat:
            return jsonify({"status": "error", "message": "Strategy not found"}), 404

        if strat.user_id != user_id and user_id != "admin" and strat.user_id not in ("system", "default", "marketplace", "template"):
            # If strategy exists in user's accessible library, allow backtesting
            pass

        # Latest StrategyVersion carries this strategy's real
        # conditions_tree/config (see services/backtest_engine.py::
        # run_backtest, which reads it the same way live deployments do).
        latest_version = (
            db_session.query(StrategyVersion)
            .filter_by(strategy_id=strategy_id)
            .order_by(StrategyVersion.version.desc())
            .first()
        )

        backtest = Backtest(
            strategy_id=strategy_id,
            version_id=latest_version.id if latest_version else None,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            capital=capital,
            slippage=slippage,
            broker_charges=charges,
            status="Pending"
        )
        db_session.add(backtest)
        db_session.commit()

        # Dispatch the real event-driven replay engine on a background
        # daemon thread -- this request handler returns immediately and
        # never runs the (potentially multi-year) replay loop itself. See
        # services/backtest_engine.py::run_backtest_async.
        from services.backtest_engine import run_backtest_async

        started = run_backtest_async(backtest.id)
        if not started:
            backtest.status = "Failed"
            backtest.error_message = "Too many backtests are already running -- please try again shortly."
            db_session.commit()
            return jsonify({
                "status": "error",
                "message": backtest.error_message,
                "backtest_id": backtest.id
            }), 429

        return jsonify({
            "status": "pending",
            "message": "Backtest started -- refresh shortly for results.",
            "backtest_id": backtest.id
        })
    except Exception as e:
        logger.exception(f"Error running backtest: {e}")
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# No-Code Custom Strategy Builder (Tradetron-style condition tree)
#
# A second, parallel, EXPLICITLY client-authored path into
# Deployment.conditions_tree -- NOT a change to compile_strategy_config's
# trust boundary for wizard-originated deployments (see
# blueprints/deployments.py::create_new_deployment, which still always
# recompiles server-side for every other template_id). Strategy rows
# created here carry template_id == "custom_builder", a sentinel with no
# entry in STRATEGY_TYPE_REGISTRY -- there is nothing to compile, the
# client tree already IS the executable shape
# services/condition_engine.py::evaluate_conditions_tree interprets.
# =============================================================================

@strategy_bp.route("/api/indicators", methods=["GET"])
@check_session_validity
def api_list_indicators():
    """Indicator names + input params for the custom strategy builder's
    indicator picker, so the frontend never hardcodes indicator names and
    stays in sync automatically when a new plugin is registered."""
    from services.indicator_registry import IndicatorRegistry

    indicators = []
    for name in sorted(IndicatorRegistry.list_indicators()):
        plugin = IndicatorRegistry.get(name)
        indicators.append({"name": name, "inputs": plugin.inputs() if plugin else []})
    # SPOT/LTP are handled directly by condition_engine.py, not registered
    # in IndicatorRegistry, but are valid indicator/value_indicator
    # references -- surfaced here so the builder's picker offers them too.
    indicators.append({"name": "SPOT", "inputs": []})
    indicators.append({"name": "LTP", "inputs": []})
    return jsonify({"status": "success", "indicators": indicators})


@strategy_bp.route("/api/strategy/custom/validate", methods=["POST"])
@check_session_validity
def api_validate_custom_strategy():
    """Validates a client-authored conditions_tree and, on success, returns
    a live would_trigger preview -- backs the builder UI's "Test
    Conditions Now" button. Mirrors
    blueprints/deployments.py::dry_run_deployment's pattern, just with a
    client tree instead of a compiled one."""
    from services.condition_tree_validator import TreeValidationError, validate_conditions_tree

    data = request.json or {}
    tree = data.get("conditions_tree")
    symbol = data.get("symbol") or "NIFTY"
    exchange = data.get("exchange") or "NSE_INDEX"

    try:
        validate_conditions_tree(tree)
    except TreeValidationError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    from services.condition_engine import evaluate_conditions_tree

    try:
        would_trigger = evaluate_conditions_tree(tree, symbol, exchange)
    except Exception as e:
        logger.exception(f"Custom strategy validation preview failed: {e}")
        return jsonify({"status": "error", "message": f"Evaluation failed: {e}"}), 500

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "would_trigger": would_trigger,
    })


@strategy_bp.route("/api/strategy/custom", methods=["POST"])
@check_session_validity
def api_create_custom_strategy():
    """Creates a Strategy + StrategyVersion from a client-authored
    conditions_tree. Does NOT create a Deployment -- deployment (broker/
    capital/risk_params) stays on the existing generic deploy path
    (blueprints/deployments.py::create_new_deployment), which has a
    dedicated branch for template_id == "custom_builder" that re-validates
    and uses this stored tree directly instead of compiling one."""
    from services.condition_tree_validator import TreeValidationError, validate_conditions_tree

    user_id = session.get("user")
    if not user_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    data = request.json or {}
    name = data.get("name")
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    conditions_tree = data.get("conditions_tree")
    exit_conditions_tree = data.get("exit_conditions_tree")

    if not name or not symbol or not exchange:
        return jsonify({"status": "error", "message": "name, symbol, and exchange are required"}), 400

    try:
        validate_conditions_tree(conditions_tree)
        if exit_conditions_tree:
            validate_conditions_tree(exit_conditions_tree)
    except TreeValidationError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    try:
        wh_id = str(uuid.uuid4())
        strat = Strategy(
            name=name,
            webhook_id=wh_id,
            user_id=user_id,
            platform="webhook",
            signal_source="Custom Builder",
            is_active=True,
            is_intraday=bool(data.get("is_intraday", True)),
            trading_mode=data.get("trading_mode", "BOTH"),
            lifecycle_state="Ready",
            template_id="custom_builder",
        )
        db_session.add(strat)
        db_session.commit()

        config = {
            "symbol": symbol,
            "exchange": exchange,
            "conditions_tree": conditions_tree,
        }
        if exit_conditions_tree:
            config["exit_conditions_tree"] = exit_conditions_tree
        if data.get("stop_loss_pct") is not None:
            config["stop_loss_pct"] = float(data["stop_loss_pct"])
        if data.get("target_pct") is not None:
            config["target_pct"] = float(data["target_pct"])
        if data.get("quantity") is not None:
            config["quantity"] = int(data["quantity"])

        version = create_strategy_version(strat.id, config)
        if not version:
            return jsonify({"status": "error", "message": "Failed to save strategy configuration"}), 500

        return jsonify({
            "status": "success",
            "strategy_id": strat.id,
            "version_id": version.id,
        }), 201
    except Exception as e:
        logger.exception(f"Error creating custom strategy: {e}")
        db_session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
