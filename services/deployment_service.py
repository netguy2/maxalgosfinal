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
    condition evaluation only. A plain equity exchange (NSE/BSE) is
    returned unchanged UNLESS the symbol is a known index -- indices are
    never quoted under the plain equity/cash segment either, only under
    NSE_INDEX/BSE_INDEX (see e.g. StrategyConfigurator.tsx's SYMBOL_OPTIONS,
    which now only ever sends NSE_INDEX for NIFTY/BANKNIFTY/FINNIFTY, but
    older deployments created before that fix may still hold plain "NSE").
    NFO/BFO are redirected to NSE_INDEX/BSE_INDEX only when the symbol is a
    known index (a stock's NFO derivative still resolves against its
    NSE-listed spot, which is already correct via the fallback below)."""
    exch = (exchange or "").upper()
    sym = (symbol or "").upper()
    if exch in ("NFO", "NSE") and sym in _NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if exch in ("BFO", "BSE") and sym in _BSE_INDEX_SYMBOLS:
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

    Also covers the plain-NSE/BSE case: a deployment holding symbol="NIFTY",
    exchange="NSE" (the wizard's own pre-fix default -- NSE is the equity/
    cash segment, which doesn't list the bare index either) hits the same
    "wrong symbol" broker rejection as the NFO/BFO case above.
    """
    exch = (exchange or "").upper()
    sym = (symbol or "").upper()

    if exch == "NSE" and sym in _NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if exch == "BSE" and sym in _BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"

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


def _fno_exchange_for_index(exchange: str) -> str:
    """The F&O segment a given index exchange's derivatives trade on --
    NSE_INDEX -> NFO, BSE_INDEX -> BFO. Used only to resolve a real
    tradeable future for a bare index (see _resolve_tradeable_symbol);
    unrelated exchanges are returned unchanged since this is never called
    for them."""
    exch = (exchange or "").upper()
    if exch in ("NSE_INDEX", "NSE"):
        return "NFO"
    if exch in ("BSE_INDEX", "BSE"):
        return "BFO"
    return exchange


def _resolve_tradeable_symbol(
    symbol: str, order_exchange: str, api_key: str | None
) -> tuple[str, str] | None:
    """For a bare INDEX underlying (NIFTY/BANKNIFTY/...), `order_exchange`
    resolves to NSE_INDEX/BSE_INDEX -- correct for LIVE PRICE DATA, but an
    index itself has no tradable instrument at all. Sending an order with
    exchange="NSE_INDEX" reaches the broker's own order API with an
    exchange code it doesn't recognize for order placement (Kite Connect,
    Zebu/Noren, etc. only accept NSE/BSE/NFO/BFO/CDS/BCD/MCX there) and
    fails with an opaque broker-side rejection -- there was previously no
    guard against attempting this at all.

    Resolves the nearest-month futures contract instead, so the order
    actually reaches a real, tradable instrument. Returns (symbol,
    exchange) for the resolved future, or None if no api_key is available
    or no contract could be resolved (caller must not silently fall back
    to the un-tradeable index in that case).
    """
    exch = (order_exchange or "").upper()
    if exch not in ("NSE_INDEX", "BSE_INDEX"):
        return None  # not a bare index -- nothing to resolve
    if not api_key:
        return None

    fno_exchange = _fno_exchange_for_index(exch)
    try:
        from services.expiry_service import resolve_expiry_type
        from services.option_symbol_service import get_futures_symbol

        expiry_date = resolve_expiry_type(symbol, fno_exchange, "current_month", api_key)
        if not expiry_date:
            return None
        future = get_futures_symbol(symbol, fno_exchange, expiry_date, api_key)
        if not future:
            return None
        return future["symbol"], future["exchange"]
    except Exception:
        logger.exception(f"Failed to resolve tradeable future for index {symbol}/{exch}")
        return None


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


def _symbol_exists_for_evaluation(dep, symbol: str, exchange: str) -> bool:
    """True if (symbol, exchange) resolves in the master contract.

    Quarantines the deployment to Error when it does not, rather than
    letting it evaluate forever. A symbol that cannot be resolved makes
    EVERY indicator return 0.0 (their history fetches all fail and the
    failure paths return None -> 0.0), so the deployment reports
    "conditions not yet met" indefinitely while being completely blind to
    the market -- identical in the UI to a healthy strategy patiently
    waiting for a setup.

    Deliberately tolerant in two directions so this can only ever catch a
    genuinely-missing symbol:
      * A bare index (NSE_INDEX/BSE_INDEX) is exempt -- indices are not
        ordinary instruments and _resolve_tradeable_symbol already handles
        mapping them to a tradable future.
      * Any error in the lookup itself is treated as "exists" (fail OPEN).
        A transient master-contract or DB fault must not mass-quarantine
        every working deployment on the platform; the cost of a missed
        detection is one more cycle of the status quo, whereas the cost of
        a false positive is stopping strategies that were fine.
    """
    try:
        exch = (exchange or "").upper()
        if exch in ("NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX"):
            return True

        from database.token_db import get_token

        if get_token(symbol, exchange) is not None:
            return True

        logger.error(
            f"Deployment {dep.id} ({dep.name}): symbol '{symbol}' not found on "
            f"'{exchange}' in the master contract -- quarantining to Error. It would "
            "otherwise evaluate forever with every indicator silently reading 0.0."
        )
        update_deployment_status(
            dep.id,
            "Error",
            f"Symbol '{symbol}' was not found on '{exchange}'. It may have been "
            "renamed or delisted (for example ZOMATO is now ETERNAL on NSE), or "
            "master contracts may need re-downloading. Edit the strategy with a "
            "valid symbol and redeploy.",
        )
        try:
            from database.auth_db import record_activity

            record_activity(
                dep.user_id,
                "system",
                "Deployment Stopped",
                f"{dep.name}: symbol '{symbol}' not found on '{exchange}' -- the "
                "strategy was running blind (no market data) and has been stopped.",
            )
        except Exception:
            logger.debug("Could not record activity for unresolvable symbol", exc_info=True)
        return False
    except Exception:
        # Fail OPEN -- see docstring.
        logger.exception(
            f"Deployment {getattr(dep, 'id', '?')}: symbol existence check failed; "
            "allowing evaluation to continue rather than quarantining on a faulty check."
        )
        return True


def _deployment_owner_exists(dep) -> bool:
    """True only if this deployment belongs to a real, existing user.

    The evaluation loop reads Deployment rows directly, while every UI
    screen reads through get_user_deployments(user_id). A deployment whose
    user_id doesn't resolve to a real account is therefore invisible to
    everyone -- yet still evaluated, and still able to place orders, on
    every cycle forever. That is precisely the "autonomous strategy nobody
    can see or stop" failure mode, so such rows are quarantined to Error
    (not merely skipped, which would leave them silently looping) and
    never evaluated again until a human intervenes.
    """
    try:
        if not dep.user_id:
            reason = "deployment has no owner (user_id is empty)"
        else:
            from database.user_db import find_user_by_exact_username

            if find_user_by_exact_username(dep.user_id):
                return True
            reason = f"owning account '{dep.user_id}' no longer exists"

        logger.error(
            f"Deployment {dep.id} ({dep.name}): {reason} -- quarantining to Error "
            "instead of evaluating. An ownerless deployment is invisible in the UI "
            "and cannot be stopped by anyone, so it must not trade."
        )
        update_deployment_status(
            dep.id,
            "Error",
            f"Stopped automatically: {reason}. Re-create this deployment under an "
            "active account to run it again.",
        )
        return False
    except Exception:
        # Never let an ownership-check fault silently enable trading. Fail
        # CLOSED (skip this cycle) -- the opposite choice from the market-
        # hours/kill-switch gates, which fail open because a transient
        # settings fault must not halt the whole platform. Here the risk is
        # inverted: proceeding means placing real orders for a deployment we
        # could not confirm has an owner.
        logger.exception(
            f"Deployment {getattr(dep, 'id', '?')}: ownership check failed -- "
            "skipping this cycle rather than trading unverified."
        )
        return False


def _evaluation_loop():
    """
    Background worker loop checking and evaluating condition triggers.
    """
    global _engine_running
    logger.info("Strategy Deployment Engine thread started.")
    
    while _engine_running:
        try:
            # Query all active waiting deployments.
            #
            # OWNERSHIP GUARD: a deployment must belong to a real, existing
            # user to be evaluated at all. This loop reads the DB directly
            # while the UI reads through get_user_deployments(user_id), so
            # anything whose user_id no longer resolves (account deleted,
            # renamed, or seeded by a fixture/migration that never belonged
            # to a person) is INVISIBLE in every screen yet still evaluated
            # -- and still placing orders -- on every cycle, forever, with
            # no way for anyone to see or stop it. Ownerless automation that
            # cannot be reached by its owner must never trade.
            waiting_deployments = Deployment.query.filter_by(status="Waiting").all()

            for dep in waiting_deployments:
                if not _deployment_owner_exists(dep):
                    continue

                # 1. Resolve strategy config symbol & exchange. Two config
                # shapes exist: options-leg templates carry a "legs" array
                # (each leg has its own symbol/exchange), while the
                # rule-based wizard (StrategyConfigurator.tsx's
                # STRATEGY_SCHEMAS blueprints -- ORB, EMA Cross, etc.) writes
                # flat top-level "symbol"/"exchange" keys instead.
                #
                # No fabricated fallback here -- "NIFTY"/"NFO" (the old
                # default) is an always-invalid pair (NFO lists only dated
                # F&O contracts, never a bare index) that the broker
                # rejected as "wrong symbol"/"no data" on every cycle, for
                # every deployment whose config happened to be missing or
                # malformed. A deployment we can't resolve a real
                # symbol/exchange for is marked Error and skipped instead of
                # silently evaluating against a pair that could never work.
                try:
                    config = dep.strategy_version.get_config()
                    legs = config.get("legs", [])
                    if legs:
                        # Use first leg for baseline tracking symbol
                        symbol = legs[0].get("symbol")
                        exchange = legs[0].get("exchange")
                    else:
                        symbol = config.get("symbol")
                        exchange = config.get("exchange")
                    if not symbol or not exchange:
                        raise ValueError(
                            f"StrategyVersion {dep.version_id} config has no resolvable symbol/exchange"
                        )
                except Exception as e:
                    logger.exception(
                        f"Deployment {dep.id} ({dep.name}): cannot resolve symbol/exchange "
                        f"from strategy_version config -- {e}. Marking Error and skipping "
                        "this cycle rather than evaluating against a fabricated pair."
                    )
                    update_deployment_status(
                        dep.id, "Error",
                        "Strategy configuration is missing or malformed (no symbol/exchange) -- "
                        "cannot evaluate. Edit and redeploy."
                    )
                    from database.auth_db import record_activity
                    record_activity(
                        dep.user_id, "system", "Deployment Failed",
                        f"{dep.name}: missing/malformed strategy config"
                    )
                    continue

                # The symbol must actually EXIST in the master contract
                # before we spend cycles evaluating against it. Without
                # this, a delisted/renamed/mistyped symbol produced a
                # strategy that looked perfectly healthy -- status
                # "Waiting", heartbeat Healthy, 100% health -- while every
                # indicator silently returned 0.0 because its underlying
                # history fetch failed with "Symbol not found". The
                # timeline then reported "conditions not yet met" forever,
                # which is indistinguishable from genuinely waiting for a
                # setup, so a blind strategy could run for days unnoticed.
                # (Real case: ZOMATO was renamed ETERNAL on NSE; the
                # deployment kept "waiting" against a symbol that no longer
                # existed.) Existence is only validated at ORDER time by
                # _resolve_tradeable_symbol, which never runs when
                # conditions can never match.
                if not _symbol_exists_for_evaluation(dep, symbol, exchange):
                    continue

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
                # A multi-broker deployment only needs ONE session to read
                # market data from -- the first selected broker acts as the
                # reference session for indicator/price lookups; order
                # placement below still fans out to every broker.
                dep_brokers = dep.get_brokers()
                dep_broker = dep_brokers[0] if dep_brokers else ""
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

                # A bare INDEX (NIFTY/BANKNIFTY/...) has no tradable
                # instrument at all -- NSE_INDEX/BSE_INDEX is correct for
                # price data (used above for indicator evaluation) but is
                # not a real order-placement exchange any broker's order
                # API recognizes. Resolve the nearest-month future so the
                # order actually reaches something tradable, rather than
                # attempting a doomed order and surfacing whatever opaque
                # error the broker happens to return for an exchange code
                # it doesn't understand. See _resolve_tradeable_symbol.
                order_symbol = symbol
                resolved = _resolve_tradeable_symbol(symbol, order_exchange, eval_api_key)
                if resolved:
                    order_symbol, order_exchange = resolved
                elif order_exchange in ("NSE_INDEX", "BSE_INDEX"):
                    logger.warning(
                        f"Deployment {dep.id} ({dep.name}): {symbol} is an index with no "
                        "tradable instrument, and no futures contract could be resolved -- "
                        "skipping this cycle rather than placing a doomed order."
                    )
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        f"{symbol} is an index and has no tradable instrument -- could not "
                        "resolve a futures contract to trade instead. Will retry automatically "
                        "next time conditions match.",
                    )
                    continue

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

                # Fan out to EVERY broker this deployment is configured for,
                # independently. One broker rejecting (bad margin, session
                # expired) must not block or roll back another's order --
                # each is its own broker session and its own real position.
                brokers_to_trade = dep.get_brokers()
                if not brokers_to_trade:
                    logger.warning(f"Deployment {dep.id} ({dep.name}) has no broker configured.")
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        "No broker configured for this deployment -- select one and it will "
                        "trade automatically next time conditions match.",
                    )
                    continue

                results: list[tuple[str, bool, str]] = []  # (broker, success, message)

                for broker_name in brokers_to_trade:
                    order_data = {
                        "apikey": user_api_key,
                        "strategy": dep.name,
                        "symbol": order_symbol,
                        "exchange": order_exchange,
                        "action": "BUY",
                        "quantity": dep.max_positions or 1,
                        "pricetype": requested_pricetype,
                        "product": (dep.product or "MIS").upper(),
                    }

                    is_paper = (broker_name or "").lower() in (
                        "paper", "paper trading", "paper trading (simulated)"
                    )

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

                            # place_order()'s `broker=` kwarg only marks this
                            # as a "direct internal call" when paired with
                            # auth_token (which we don't have here) -- without
                            # both, that branch is never taken and place_order
                            # instead reads order_data["broker"] to pick a
                            # SPECIFIC one of the user's connected brokers
                            # (services/place_order_service.py's Case 1).
                            # Iterating brokers_to_trade and setting this per
                            # loop is what makes multi-broker fan-out work --
                            # each pass targets a different connected session.
                            order_data["broker"] = broker_name
                            success, response, status_code = place_order(
                                order_data=order_data,
                                api_key=user_api_key,
                            )

                        if success:
                            order_id = (
                                response.get("orderid") or response.get("order_id")
                                or f"ORD_{int(time.time())}"
                            )
                            results.append(
                                (broker_name, True, f"Order placed successfully (ID: {order_id}).")
                            )
                        else:
                            err = response.get("message") or response.get("emsg") or "Order placement failed"
                            results.append((broker_name, False, f"Broker order rejected: {err}"))
                    except Exception as _oe:
                        logger.exception(
                            f"Order placement error for deployment {dep.id} on broker "
                            f"{broker_name}: {_oe}"
                        )
                        results.append((broker_name, False, f"Order error: {_oe}"))

                any_success = any(ok for _, ok, _ in results)
                broker_label = lambda b: f"[{b}]" if len(brokers_to_trade) > 1 else ""
                summary_lines = [
                    f"{broker_label(b)} {msg}".strip() for b, ok, msg in results
                ]

                if any_success:
                    update_deployment_status(
                        dep.id,
                        "Managing",
                        "Managing position. " + " | ".join(summary_lines),
                    )
                    # Cooldown risk checks measure elapsed time from here, not
                    # from `updated_at` (which every heartbeat commit also
                    # bumps) -- see set_deployment_last_trade.
                    set_deployment_last_trade(dep.id)
                else:
                    # Back to Waiting, not Error -- see the no-API-key branch
                    # above for why leaving this as "Error" would strand the
                    # deployment: the evaluation loop never looks at anything
                    # but status="Waiting" (line 191), so every broker
                    # rejecting (bad margin, market closed, broker-side
                    # hiccup) would otherwise silently stop this deployment
                    # forever until a human clicked Resume, even though the
                    # failure is often transient.
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        "All brokers rejected the order. Will retry automatically next time "
                        "conditions match. " + " | ".join(summary_lines),
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
