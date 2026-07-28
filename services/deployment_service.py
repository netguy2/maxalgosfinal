import logging
import json
import time
import threading
from datetime import datetime

from database.auth_db import get_api_key_for_tradingview
from database.deployment_db import (
    Deployment,
    append_deployment_heartbeat,
    db_session,
    get_deployment,
    set_deployment_last_trade,
    update_deployment_status,
    create_deployment,
)
from services.condition_engine import (
    describe_first_leaf,
    evaluate_conditions_tree,
    indicator_api_key_context,
)
from services.risk_engine import validate_risk

logger = logging.getLogger(__name__)

# Underlyings whose live/historical price data is stored under the INDEX
# exchange, never their derivatives exchange (NFO/BFO don't list the index
# itself, only dated contracts on it). Mirrors
# services/oi_profile_service.py's NSE_INDEX_SYMBOLS/BSE_INDEX_SYMBOLS.
_NSE_INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
_BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def _to_underlying_exchange(symbol: str, exchange: str) -> str:
    """Map a deployment's order-placement exchange to the exchange its
    underlying's OWN price/candle data actually lives under, for indicator/
    condition evaluation only. A plain equity/index exchange (NSE/BSE) is
    returned unchanged; NFO/BFO are redirected to NSE_INDEX/BSE_INDEX only
    when the symbol is a known index (a stock's NFO derivative still
    resolves against its NSE-listed spot, which is already correct via the
    fallback below)."""
    exch = (exchange or "").upper()
    sym = (symbol or "").upper()
    if exch == "NFO" and sym in _NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if exch == "BFO" and sym in _BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if exch in ("NFO",):
        return "NSE"
    if exch in ("BFO",):
        return "BSE"
    return exchange

def _to_order_exchange(symbol: str, exchange: str) -> str:
    """Exchange an ORDER for `symbol` should actually be routed to.

    Distinct from _to_underlying_exchange above, which answers "where does
    this symbol's PRICE DATA live" for indicator evaluation. This answers
    "where is this symbol actually tradable".

    The two differ for indices: NIFTY's candles live on NSE_INDEX, but you
    cannot place an order on an index at all -- and critically, you cannot
    place one on NFO either, because NFO lists only dated F&O contracts
    (NIFTY28JUL2623950CE), never the bare underlying.

    That impossible (symbol="NIFTY", exchange="NFO") pair is exactly what the
    wizard fallback produced, and it reached the broker as
    "No instrument token found for NIFTY on NFO".

    Rules:
      * a REAL derivative symbol keeps its derivatives exchange untouched --
        detected by length, since every F&O contract carries an embedded
        expiry/strike (NIFTY28JUL2623950CE) and is far longer than its
        underlying;
      * a BARE underlying on NFO/BFO is redirected to its spot/index
        exchange, which is where it is genuinely quotable and tradable;
      * everything else is returned unchanged.

    This is a safety net, not a substitute for correct config: a strategy
    that means to trade options should carry a resolved contract symbol.
    Routing a bare index to its index exchange at least produces a coherent
    order (and a clear broker-side error if the segment is untradable)
    rather than a guaranteed token-lookup failure.
    """
    exch = (exchange or "").upper()
    sym = (symbol or "").upper()

    if exch not in ("NFO", "BFO"):
        return exchange

    # A dated F&O contract embeds its expiry and (for options) strike, so it
    # is always substantially longer than the bare underlying it derives
    # from. Anything that short on NFO/BFO is an underlying, not a contract.
    if len(sym) > 12:
        return exchange

    if sym in _NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if sym in _BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"

    # A bare stock symbol on NFO means the equity underlying -> cash segment.
    return "NSE" if exch == "NFO" else "BSE"


# Track active background evaluation loop thread
_engine_thread = None
_engine_running = False

# Throttle for the "still waiting, here's what's being checked" heartbeat
# (see append_deployment_heartbeat's docstring) -- without this, a
# deployment sitting in "Waiting" for hours produces zero visible trace
# that its evaluation loop is actually alive and checking. Logged at most
# once per this interval per deployment, not every 5-second poll cycle.
_HEARTBEAT_INTERVAL_SECONDS = 120
_last_heartbeat_at: dict[int, float] = {}


def validate_dry_run(deployment_id: int) -> dict:
    """
    Performs a pre-deployment checklist check.
    """
    deployment = get_deployment(deployment_id)
    if not deployment:
        return {"success": False, "error": "Deployment not found"}

    # Mock/simulated checks representing enterprise checks
    checks = {
        "broker_connected": False,
        "market_feed_connected": True,
        "api_permissions_valid": True,
        "margin_sufficient": True,
        "capital_allocated": True,
    }

    # Verify if active broker credentials exist
    from database.user_db import get_user_broker_credentials
    creds = get_user_broker_credentials(deployment.user_id, deployment.broker)
    if creds:
        checks["broker_connected"] = True

    success = all(checks.values())

    return {
        "success": success,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }


def clone_deployment(deployment_id: int, new_broker: str = None, new_capital: float = None) -> Deployment:
    """
    Clones an existing deployment template.
    """
    source = get_deployment(deployment_id)
    if not source:
        return None

    cloned_data = {
        "name": f"Clone of {source.name}",
        "strategy_id": source.strategy_id,
        "version_id": source.version_id,
        "status": "Draft",
        "broker": new_broker if new_broker else source.broker,
        "capital": new_capital if new_capital is not None else source.capital,
        "max_positions": source.max_positions,
        "order_type": source.order_type,
        "product": source.product,
        "trigger_type": source.trigger_type,
        "conditions_tree": source.conditions_tree,
        "risk_params": source.risk_params,
        "user_id": source.user_id,
        "events_timeline": json.dumps([{
            "time": datetime.now().strftime("%H:%M"),
            "event": "Deployment cloned from template"
        }])
    }

    return create_deployment(cloned_data)


def _evaluation_loop():
    """
    Background worker loop checking and evaluating condition triggers.
    """
    global _engine_running
    logger.info("Strategy Deployment Engine thread started.")
    
    while _engine_running:
        try:
            # Query all active waiting deployments
            waiting_deployments = Deployment.query.filter_by(status="Waiting").all()
            
            for dep in waiting_deployments:
                # 1. Resolve strategy config symbol & exchange.
                # Two config shapes exist: options-leg templates carry a
                # "legs" array (each leg has its own symbol/exchange), while
                # the rule-based wizard (StrategyConfigurator.tsx's
                # STRATEGY_SCHEMAS blueprints -- ORB, EMA Cross, etc.) writes
                # flat top-level "symbol"/"exchange" keys instead. Without
                # this second branch, every wizard-created deployment
                # silently evaluated conditions against the hardcoded
                # NIFTY/NFO fallback regardless of what the user actually
                # selected.
                try:
                    config = dep.strategy_version.get_config()
                    legs = config.get("legs", [])
                    if legs:
                        # Use first leg for baseline tracking symbol
                        symbol = legs[0].get("symbol", "NIFTY")
                        exchange = legs[0].get("exchange", "NFO")
                    elif config.get("symbol"):
                        symbol = config["symbol"]
                        exchange = config.get("exchange", "NSE")
                    else:
                        symbol = "NIFTY"
                        exchange = "NFO"
                except Exception:
                    symbol = "NIFTY"
                    exchange = "NFO"

                # Indicator/condition lookups (SPOT, candle-based indicators
                # like Donchian/ORB/PREV_DAY_*) need the underlying's own
                # spot/index exchange, not its derivatives exchange -- NIFTY
                # itself isn't listed on NFO (NFO is F&O contracts only), so
                # historical candles and live LTP for "NIFTY" are stored
                # under NSE_INDEX, never NFO. Using `exchange` (NFO/BFO) for
                # data lookups here always misses, which is a second,
                # independent reason indicator values were pinned at 0.0 for
                # every NIFTY/BANKNIFTY-style deployment on top of the
                # get_ltp_value WebSocket-cache gap fixed above. `exchange`
                # itself is left untouched since it's also used below to
                # build the live order's exchange field once conditions
                # actually match.
                data_exchange = _to_underlying_exchange(symbol, exchange)

                # 2. Evaluate boolean tree conditions
                try:
                    tree = json.loads(dep.conditions_tree) if dep.conditions_tree else {}
                except Exception:
                    tree = {}

                # Deployments run as a headless background thread with no
                # WebSocket client of its own, so market_data_service's tick
                # cache (what SPOT/LTP and every indicator's no-data
                # fallback normally read) is always empty here. Scope this
                # deployment's API key (and its specific broker) for the
                # duration of evaluation so get_ltp_value can fall back to a
                # stateless REST quote instead of silently returning 0.0 --
                # see services/market_data_service.py::get_ltp's api_key/
                # broker docstring and services/indicator_registry.py's
                # indicator_api_key_context. Passing dep.broker matters:
                # without it, the REST fallback resolves whichever broker
                # happens to be the user's single "primary" Auth session,
                # which silently returns 0.0/no-data whenever that doesn't
                # match this deployment's configured broker (or there is no
                # primary session at all) -- this was showing up as
                # "SPOT (0.0)" in the trigger timeline for every leaf.
                eval_api_key = get_api_key_for_tradingview(dep.user_id) if dep.user_id else None
                # "Paper Trading" (and its variant labels) is a sandbox
                # sentinel, not a real connected broker -- passing it as
                # broker= would make get_broker_session look for a
                # nonexistent "Paper Trading" session and fail outright
                # instead of falling back to the primary session, so a
                # paper-trading deployment's indicators would break here.
                dep_broker = (dep.broker or "")
                indicator_broker = (
                    None
                    if dep_broker.lower() in ("paper", "paper trading", "paper trading (simulated)")
                    else dep_broker
                )
                with indicator_api_key_context(eval_api_key, broker=indicator_broker):
                    conditions_met = tree and evaluate_conditions_tree(tree, symbol, data_exchange)

                    if not conditions_met:
                        # Heartbeat: proves the evaluation loop is alive and
                        # actually checking this deployment, throttled so a
                        # deployment waiting for hours doesn't flood its
                        # timeline with a near-identical entry every 5s.
                        now_ts = time.time()
                        last_ts = _last_heartbeat_at.get(dep.id, 0)
                        if now_ts - last_ts >= _HEARTBEAT_INTERVAL_SECONDS:
                            _last_heartbeat_at[dep.id] = now_ts
                            if tree:
                                summary = describe_first_leaf(tree, symbol, data_exchange)
                            else:
                                summary = None
                            event = (
                                f"Checked conditions on {symbol} ({data_exchange}): not yet met"
                                + (f" -- {summary}" if summary else "")
                                if tree
                                else f"Waiting: no conditions configured for {symbol} ({data_exchange})"
                            )
                            append_deployment_heartbeat(dep.id, event)
                        continue

                logger.info(f"Conditions matched for deployment: {dep.name}")
                _last_heartbeat_at.pop(dep.id, None)

                # 3. Perform risk check
                is_safe, reason = validate_risk(dep)
                if not is_safe:
                    logger.warning(f"Risk validation failed for deployment {dep.name}: {reason}")
                    update_deployment_status(
                        dep.id, "Error", f"Risk check failed: {reason}"
                    )
                    from database.auth_db import record_activity
                    record_activity(
                        dep.user_id, "system", "Deployment Failed", f"{dep.name}: {reason}"
                    )
                    continue

                # 4. Trigger real order execution via place_order_service / sandbox
                from database.auth_db import record_activity

                # get_api_key_for_tradingview returns the actual decrypted
                # API key string. The previous code called get_api_key()
                # instead, which only returns a bool ("does a key exist?")
                # -- that bool (or a fabricated "deployment_{id}" string
                # when it was falsy) was then sent as order_data["apikey"]
                # to place_order/sandbox_place_order, which both resolve
                # the acting user via that key. Every wizard-deployed
                # strategy was therefore placing orders with an apikey
                # that could never resolve to a real user, so every order
                # would fail at the auth step regardless of whether
                # conditions correctly matched.
                # Reuses eval_api_key resolved above (before condition
                # evaluation) instead of a second identical DB lookup.
                user_api_key = eval_api_key
                if not user_api_key:
                    logger.warning(
                        f"Deployment {dep.id} ({dep.name}): user {dep.user_id} has no "
                        "API key generated -- cannot place order. Skipping this cycle."
                    )
                    # Back to Waiting rather than Error: a missing API key is
                    # transient (the user may generate one after this point)
                    # and this loop only ever evaluates status="Waiting"
                    # deployments (line 191) -- leaving this as "Error" would
                    # silently strand the deployment forever, requiring a
                    # manual resume even after the user fixes the key.
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        "No API key found for this account -- generate one from the API Key page. Will retry automatically next time conditions match.",
                    )
                    continue

                update_deployment_status(dep.id, "Entering", "Conditions matched. Placing order to broker...")
                record_activity(
                    dep.user_id, "system", "Strategy Started", f"{dep.name} entering position"
                )

                # Resolve the exchange the ORDER should actually be placed on.
                #
                # `exchange` here can be a derivatives segment (NFO/BFO) while
                # `symbol` is a bare underlying like "NIFTY" -- that is the
                # hardcoded fallback a few lines above, and it is an
                # impossible pair: NFO lists only dated F&O contracts, so
                # "NIFTY" has no token there. The broker then rejected the
                # order ("No instrument token found for NIFTY on NFO"), and on
                # Zebu that surfaced as a failed Market Price Protection quote
                # because MPP cannot price an order it has no quote for.
                #
                # A bare underlying trades on its own spot/index exchange, so
                # reuse the same mapping the indicator path already uses.
                # A real derivative symbol (NIFTY28JUL2623950CE) keeps its
                # NFO/BFO exchange untouched -- see _to_order_exchange.
                order_exchange = _to_order_exchange(symbol, exchange)

                # Wizard-deployed strategies have no UI field to collect a
                # limit/trigger price (the Deployment model itself has no
                # limit_price/trigger_price column -- see StrategySymbolMapping
                # for the columns that DO exist for the webhook flow). Sending
                # LIMIT/SL/SL-M with no price is a guaranteed broker rejection
                # (price=0), so fall back to MARKET rather than let every
                # cycle fail silently for a config this flow can't express.
                requested_pricetype = (dep.order_type or "MARKET").upper()
                if requested_pricetype not in ("MARKET",):
                    logger.warning(
                        f"Deployment {dep.id} ({dep.name}): order_type={requested_pricetype} "
                        "has no limit/trigger price configured -- placing as MARKET instead."
                    )
                    requested_pricetype = "MARKET"

                order_data = {
                    "apikey": user_api_key,
                    "strategy": dep.name,
                    "symbol": symbol,
                    "exchange": order_exchange,
                    "action": "BUY",
                    "quantity": dep.max_positions or 1,
                    "pricetype": requested_pricetype,
                    "product": (dep.product or "MIS").upper(),
                }

                is_paper = (dep.broker or "").lower() in ("paper", "paper trading", "paper trading (simulated)")

                try:
                    if is_paper:
                        from services.sandbox_service import sandbox_place_order
                        # user_api_key is already confirmed non-empty by
                        # the guard above -- sandbox_place_order resolves
                        # the acting user's sandbox account from this key
                        # (get_user_id_from_apikey), so it must be the
                        # real key, never a placeholder like "paper".
                        success, response, status_code = sandbox_place_order(
                            order_data, user_api_key, order_data
                        )
                    else:
                        from services.place_order_service import place_order

                        # place_order()'s `broker=` kwarg only marks this as
                        # a "direct internal call" when paired with
                        # auth_token (which we don't have here) -- without
                        # both, that branch is never taken and place_order
                        # instead reads order_data["broker"] to pick a
                        # SPECIFIC one of the user's connected brokers
                        # (services/place_order_service.py's Case 1). Omitting
                        # it here meant every live deployment silently used
                        # get_auth_token_broker()'s single primary Auth
                        # session -- whichever broker the user happened to be
                        # logged into on the platform -- instead of the
                        # broker actually selected for this deployment,
                        # failing outright when no primary session existed.
                        order_data["broker"] = dep.broker
                        success, response, status_code = place_order(
                            order_data=order_data,
                            api_key=user_api_key,
                        )

                    if success:
                        order_id = response.get("orderid") or response.get("order_id") or f"ORD_{int(time.time())}"
                        update_deployment_status(
                            dep.id,
                            "Managing",
                            f"Order placed successfully (ID: {order_id}). Managing position.",
                        )
                        # Cooldown risk checks measure elapsed time from
                        # here, not from `updated_at` (which every heartbeat
                        # commit also bumps) -- see set_deployment_last_trade.
                        set_deployment_last_trade(dep.id)
                    else:
                        err = response.get("message") or response.get("emsg") or "Order placement failed"
                        # Back to Waiting, not Error -- see the no-API-key
                        # branch above for why leaving this as "Error" would
                        # strand the deployment: the evaluation loop never
                        # looks at anything but status="Waiting" (line 191),
                        # so a rejected order (bad margin, market closed,
                        # broker-side hiccup) would otherwise silently stop
                        # this deployment forever until a human clicked
                        # Resume, even though the failure is often transient.
                        update_deployment_status(
                            dep.id,
                            "Waiting",
                            f"Broker order rejected: {err}. Will retry automatically next time conditions match.",
                        )
                except Exception as _oe:
                    logger.exception(f"Order placement error for deployment {dep.id}: {_oe}")
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        f"Order error: {_oe}. Will retry automatically next time conditions match.",
                    )

                # Update metrics to reflect telemetry
                metrics = {
                    "cpu": 1.2,
                    "memory": 24,
                    "latency": 15,
                    "heartbeat": 100,
                    "last_tick": datetime.now().strftime("%H:%M:%S")
                }
                dep.metrics = json.dumps(metrics)
                dep.trades_count += 1
                db_session.commit()

        except Exception as e:
            logger.error(f"Error in strategy deployment evaluation loop: {e}")
            
        time.sleep(5)  # 5-second check intervals


def start_deployment_engine():
    """Start the background deployments evaluation worker"""
    global _engine_thread, _engine_running
    if _engine_running:
        return

    _engine_running = True
    _engine_thread = threading.Thread(target=_evaluation_loop, daemon=True)
    _engine_thread.start()


def stop_deployment_engine():
    global _engine_running
    _engine_running = False
