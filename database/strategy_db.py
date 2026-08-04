import json
import logging
import os
import threading

from cachetools import TTLCache
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine

logger = logging.getLogger(__name__)

# Strategy caches - 5 minute TTL for webhook lookups (high frequency)
# Webhook lookups happen on every webhook trigger, caching significantly reduces DB load
_strategy_webhook_cache = TTLCache(maxsize=5000, ttl=300)  # 5 minutes TTL
_user_strategies_cache = TTLCache(maxsize=1000, ttl=600)  # 10 minutes TTL

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# What a mapping DOES when its trigger signal arrives. Deliberately mirrors
# the vocabulary mainstream webhook platforms use (TradersPost's
# buy/sell/exit/reverse/add, Altrady's open/increase/reduce/close) so alert
# bodies written for those services translate directly.
#
# ENTER is the default for any row where signal_action is NULL, because
# every mapping that predates this column placed an entry order.
SIGNAL_ACTIONS = ("ENTER", "EXIT", "REVERSE", "ADD", "REDUCE", "IGNORE")

# Order types a mapping may place. NULL/absent means MARKET.
ORDER_TYPES = ("MARKET", "LIMIT", "SL", "SL-M")

# Unit for SL/target/trailing values -- never absolute prices, see
# StrategySymbolMapping.get_risk_config for why.
RISK_VALUE_TYPES = ("percent", "points")


class Strategy(Base):
    """Model for trading strategies"""

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    webhook_id = Column(String(36), unique=True, nullable=False)  # UUID
    user_id = Column(String(255), nullable=False)
    platform = Column(
        String(50), nullable=False, default="tradingview"
    )  # Platform type (tradingview, chartink, etc)
    signal_source = Column(
        String(50), nullable=False, default="TradingView"
    )
    is_active = Column(Boolean, default=True)
    is_intraday = Column(Boolean, default=True)
    trading_mode = Column(String(10), nullable=False, default="LONG")  # LONG, SHORT, or BOTH
    lifecycle_state = Column(String(30), nullable=False, default="Draft")  # Draft, Ready, Paper, Live, Archived
    start_time = Column(String(5))  # HH:MM format
    end_time = Column(String(5))  # HH:MM format
    squareoff_time = Column(String(5))  # HH:MM format
    brokers = Column(String(255), nullable=True)  # comma-separated list of selected brokers
    # 'legacy': signal_engine.py's original 2-action (BUY/SELL) webhook path,
    # untouched. 'unified': the 4-action (BUY/SELL/SHORT/EXIT) execution
    # engine using StrategySymbolMapping.resolve_execution() /
    # ExecutionProfile -- each mapping row reacts to a fixed action with a
    # static order_side. 'stateful': LegGroup/Leg rotation -- tracks WHICH
    # leg is currently open (LegGroup.current_leg_id) so the same signal can
    # mean "close whichever leg is open, open the other one" (reversal/flip
    # strategies), which a static order_side cannot express. Defaults to
    # 'legacy' so every existing strategy keeps running on the exact code
    # path it always has.
    execution_model = Column(String(20), nullable=False, default="legacy")
    # Wizard blueprint id this strategy was created from (e.g. "orb-15",
    # "ema-cross"), matching frontend/src/lib/strategy-schemas.ts's
    # STRATEGY_SCHEMAS keys / getSchemaForTemplate's substring-match input.
    # Nullable: strategies created outside the wizard (webhooks, direct API,
    # pre-migration rows) have no blueprint. Used server-side by
    # services/strategy_compiler.py to select which compiler translates this
    # strategy's StrategyVersion.config into a real conditions_tree -- never
    # trust a client-supplied conditions_tree directly, see
    # blueprints/deployments.py's create_new_deployment.
    template_id = Column(String(50), nullable=True)
    # Opt-in market-hours gate, enforced in services/signal_engine.py before
    # dispatch. Defaults False because the platform-wide check in
    # place_order_service.py is intentionally commented out to allow
    # out-of-hours testing -- turning that back on globally would break it for
    # everyone, so strategies opt in one at a time instead.
    #
    # KNOWN ISSUE -- tri-state, not boolean. SQLite's "ADD COLUMN ... DEFAULT 0"
    # applies the default to new INSERTs only, so every row that predates the
    # migration holds NULL rather than 0. Reads are safe (None is falsy, and
    # signal_engine.py uses getattr(..., False)), but any query filtering on
    # "enforce_market_hours = 0" will silently MISS every pre-migration
    # strategy. Use "IS NOT 1" / "IS NOT TRUE", or backfill the NULLs first.
    enforce_market_hours = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    symbol_mappings = relationship(
        "StrategySymbolMapping", back_populates="strategy", cascade="all, delete-orphan"
    )
    versions = relationship(
        "StrategyVersion", back_populates="strategy", cascade="all, delete-orphan"
    )
    # Every one of these tables has a strategy_id FK with no ON DELETE
    # CASCADE at the DB level -- SQLite doesn't enforce FKs by default, so
    # deleting a Strategy with any row in these tables worked silently
    # there, but Postgres always enforces FK constraints and rejects the
    # DELETE with an IntegrityError, which delete_strategy()'s blanket
    # except swallowed into a generic "Failed to delete connection" (no
    # cascade relationship existed here at all, so SQLAlchemy didn't even
    # attempt to clean these up first). Deleting a user's own strategy is a
    # full teardown of everything that belongs to it -- deployments,
    # backtests, leg groups, and its own marketplace listing/subscriptions
    # are all this strategy's data, not shared state another strategy
    # depends on -- so cascade all of them the same way symbol_mappings/
    # versions already do above.
    deployments = relationship(
        "Deployment", cascade="all, delete-orphan",
        foreign_keys="Deployment.strategy_id",
    )
    leg_groups = relationship(
        "LegGroup", cascade="all, delete-orphan",
        foreign_keys="LegGroup.strategy_id",
    )
    backtests = relationship(
        "Backtest", cascade="all, delete-orphan",
        foreign_keys="Backtest.strategy_id",
    )
    marketplace_listings = relationship(
        "MarketplaceListing", cascade="all, delete-orphan",
        foreign_keys="MarketplaceListing.strategy_id",
    )
    subscriptions = relationship(
        "Subscription", cascade="all, delete-orphan",
        foreign_keys="Subscription.strategy_id",
    )


class StrategyVersion(Base):
    """Model for Strategy Versions (Strategy Templates).

    Moved here from the former database/deployment_db.py so it shares one
    SQLAlchemy Base/engine with Strategy -- the two were always the same
    physical maxalgos.db, just split across declarative_base() objects,
    which meant SQLAlchemy could not resolve FKs between them and caused
    real startup/session-mismatch bugs. See database/deployment_db.py for
    the backward-compatible re-export shim kept for existing imports.
    """

    __tablename__ = "strategy_versions"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    config = Column(Text, nullable=False)  # JSON config dump of strategy structure/legs
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    strategy = relationship("Strategy", back_populates="versions")

    def get_config(self):
        try:
            return json.loads(self.config) if self.config else {}
        except Exception:
            return {}


class Deployment(Base):
    """Model for Strategy Deployment Instances.

    Moved here from the former database/deployment_db.py for the same
    reason as StrategyVersion above -- version_id/strategy_id are now real
    foreign keys instead of unenforced bare ints.
    """

    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("strategy_versions.id"), nullable=False)
    status = Column(String(50), nullable=False, default="Draft")  # Draft, Deploying, Waiting, Entering, Managing, Completed, Paused, Stopped, Error, Cancelled
    broker = Column(String(50), nullable=False)
    capital = Column(Float, nullable=False)
    max_positions = Column(Integer, default=1)
    order_type = Column(String(20), default="Market")
    product = Column(String(20), default="MIS")
    trigger_type = Column(String(50), default="Immediately")
    conditions_tree = Column(Text, nullable=True)  # JSON composite boolean tree
    risk_params = Column(Text, nullable=True)  # JSON dict
    pnl = Column(Float, default=0.0)
    trades_count = Column(Integer, default=0)
    health_score = Column(Integer, default=100)
    metrics = Column(Text, nullable=True)  # JSON dict (CPU, memory, latency, last_tick)
    events_timeline = Column(Text, nullable=True)  # JSON list of trigger timeline events
    user_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Set ONLY when an order actually places (see set_deployment_last_trade
    # below) -- deliberately separate from `updated_at`, which SQLAlchemy's
    # onupdate bumps on EVERY commit to this row, including the heartbeat
    # written every ~30s while a deployment just sits evaluating conditions
    # that haven't matched yet. The risk engine's cooldown check used to read
    # `updated_at`, which meant a deployment being actively (and harmlessly)
    # evaluated looked identical to one that had just traded -- cooldown
    # could never elapse because the "last activity" timestamp kept
    # resetting itself every heartbeat, regardless of whether a trade had
    # ever happened.
    last_trade_at = Column(DateTime(timezone=True), nullable=True)
    # JSON array of broker keys, e.g. ["zebu", "bnr"] -- lets one deployment
    # place independent orders on every selected connected broker instead of
    # just one. `broker` (above) is kept in sync as brokers[0] purely for
    # backward compatibility with any older reader that only knows the
    # single-broker column (e.g. a stale cached query, an external
    # integration) -- every current code path (the evaluation loop, the
    # broker-edit endpoint, the wizard) reads/writes `brokers` and treats
    # `broker` as derived, never the other way around.
    brokers = Column(Text, nullable=True)

    # Relationships
    strategy_version = relationship("StrategyVersion")

    def get_brokers(self) -> list[str]:
        """Every broker this deployment places orders on. Falls back to the
        single `broker` column for deployments created before `brokers`
        existed, so nothing created pre-migration silently stops trading."""
        if self.brokers:
            try:
                parsed = json.loads(self.brokers)
                if isinstance(parsed, list) and parsed:
                    return [str(b) for b in parsed]
            except Exception:
                pass
        return [self.broker] if self.broker else []

    def to_dict(self):
        try:
            conditions = json.loads(self.conditions_tree) if self.conditions_tree else {}
        except Exception:
            conditions = {}

        try:
            risk = json.loads(self.risk_params) if self.risk_params else {}
        except Exception:
            risk = {}

        try:
            metrics_data = json.loads(self.metrics) if self.metrics else {}
        except Exception:
            metrics_data = {}

        try:
            timeline = json.loads(self.events_timeline) if self.events_timeline else []
        except Exception:
            timeline = []

        return {
            "id": self.id,
            "name": self.name,
            "strategy_id": self.strategy_id,
            "version_id": self.version_id,
            "status": self.status,
            "broker": self.broker,
            "brokers": self.get_brokers(),
            "capital": self.capital,
            "max_positions": self.max_positions,
            "order_type": self.order_type,
            "product": self.product,
            "trigger_type": self.trigger_type,
            "conditions_tree": conditions,
            "risk_params": risk,
            "pnl": self.pnl,
            "trades_count": self.trades_count,
            "health_score": self.health_score,
            "metrics": metrics_data,
            "events_timeline": timeline,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
        }


class MarketplaceListing(Base):
    """Model for strategies published to the public marketplace"""

    __tablename__ = "marketplace_listings"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    price = Column(Integer, nullable=False, default=0)  # Monthly price (₹)
    rating = Column(Float, nullable=False, default=5.0)
    reviews_count = Column(Integer, nullable=False, default=0)
    is_published = Column(Boolean, default=False)
    featured = Column(Boolean, default=False)
    creator = Column(String(255), default="MaxAlgos")
    description = Column(String, nullable=True)
    win_rate = Column(Float)
    drawdown = Column(Float)
    returns = Column(Float)


class Subscription(Base):
    """Model for user strategy marketplace subscriptions"""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    plan = Column(String(50), default="Free")
    expiry = Column(DateTime)
    status = Column(String(30), default="Active")  # Active, Expired, Cancelled
    renewal_enabled = Column(Boolean, default=True)


class Backtest(Base):
    """Model for historic backtesting runs"""

    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    version_id = Column(Integer)
    symbol = Column(String(50))
    timeframe = Column(String(10))
    status = Column(String(20), default="Pending")  # Pending, Running, Success, Failed
    start_date = Column(String(20))
    end_date = Column(String(20))
    capital = Column(Float)
    slippage = Column(Float)
    broker_charges = Column(Float)
    # Nullable JSON summary (max_drawdown, sharpe_ratio, total_return_pct,
    # avg_trade_pnl, largest_win/loss, ...) written once by
    # services/backtest_engine.py::run_backtest on completion. One
    # forward-compatible column instead of more scalar columns per metric --
    # matches the existing Deployment.conditions_tree/risk_params JSON-text
    # convention. win_rate/returns above stay as their own columns since
    # api_get_backtests already recomputes those identically from
    # BacktestTrade rows; report only carries metrics that aren't a simple
    # per-trade aggregate.
    report = Column(Text, nullable=True)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Cascades this backtest's own trade rows -- without this, deleting a
    # Backtest (e.g. via Strategy's cascade above) hits the exact same
    # unenforced-on-SQLite/enforced-on-Postgres FK problem one level down:
    # backtest_trades.backtest_id has no ON DELETE CASCADE and no ORM
    # relationship existed here to clean them up first.
    trades = relationship("BacktestTrade", cascade="all, delete-orphan")

    def get_report(self) -> dict:
        try:
            return json.loads(self.report) if self.report else {}
        except Exception:
            return {}


class BacktestTrade(Base):
    """Model for individual trade records inside a backtest"""

    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True)
    backtest_id = Column(Integer, ForeignKey("backtests.id"), nullable=False)
    symbol = Column(String(50))
    action = Column(String(10))  # BUY, SELL
    quantity = Column(Integer)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    entry_time = Column(String(30))
    exit_time = Column(String(30))


class ExecutionProfile(Base):
    """Reusable execution defaults, shared across instruments/segments.

    Part of the unified execution engine (Phase 1): one Instrument row
    (StrategySymbolMapping) references a profile for its broker/exchange/
    product/order-type/quantity defaults instead of repeating them inline,
    so changing a profile updates every instrument that references it.
    Segment-agnostic by design -- the same profile shape covers Equity,
    F&O, Commodity, and Currency; only the linked instrument's exchange/
    segment (resolved via the existing symbol/token lookup layer, e.g.
    database.token_db_enhanced) differs per row.
    """

    __tablename__ = "execution_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    broker = Column(String(50), nullable=True)  # nullable: falls back to the strategy's configured broker(s)
    product = Column(String(20), nullable=False, default="MIS")  # MIS/NRML/CNC
    order_type = Column(String(20), nullable=False, default="MARKET")  # MARKET/LIMIT/SL/SL-M
    default_quantity = Column(Integer, nullable=False, default=1)  # units for EQ, lots for F&O/MCX/CDS
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "broker": self.broker,
            "product": self.product,
            "order_type": self.order_type,
            "default_quantity": self.default_quantity,
        }


class StrategySymbolMapping(Base):
    """Model for symbol mappings in strategies.

    NOTE on `symbol` vs `action` vs `instrument`: historically this table's
    `symbol` column held the trigger ACTION string ("BUY"/"SELL"), not a
    tradable instrument -- `instrument` was the real symbol. That naming
    collision caused a real bug (blueprints/strategy.py's
    squareoff_positions built order payloads with the action string in the
    order's `symbol` field). `action` is the new, correctly-named column
    for the trigger action; `symbol` is kept and auto-populated from
    `action` for backward compatibility with any code not yet migrated to
    read `action` directly (see _migrate_add_action_column below). New code
    should read/write `action`, not `symbol`.
    """

    __tablename__ = "strategy_symbol_mappings"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    symbol = Column(String(50), nullable=False)  # deprecated alias of `action` -- see class docstring
    action = Column(String(10), nullable=True)  # BUY / SELL / SHORT / EXIT
    exchange = Column(String(10), nullable=False)
    quantity = Column(Integer, nullable=False)
    product_type = Column(String(10), nullable=False)  # MIS/CNC
    instrument = Column(String(50), nullable=True)  # Option/FUT/EQ contract instrument symbol
    is_active = Column(Boolean, nullable=False, server_default="1")  # per-symbol pause/resume
    # "EQ" (default/legacy) | "FUT" | "OPT" -- selects which fields below apply
    # and whether signal_engine resolves a live contract at signal time
    # instead of using the frozen `instrument` string.
    instrument_type = Column(String(10), nullable=True)
    underlying = Column(String(50), nullable=True)  # base symbol, e.g. "NIFTY" (FUT/OPT only)
    expiry_type = Column(String(20), nullable=True)  # current_week/next_week/current_month/next_month
    option_type = Column(String(2), nullable=True)  # CE / PE (OPT only)
    strike_offset = Column(String(10), nullable=True)  # ATM / ITM1 / OTM2 / ... (OPT only)
    # "offset" (default/NULL) | "premium" | "delta" | "oi" -- how the strike
    # is chosen at signal time. NULL/"offset" means "use strike_offset the
    # old way" (index-walk from ATM), so every mapping created before this
    # column existed keeps behaving exactly as it did. "premium"/"delta"
    # pick the strike whose live premium/delta is closest to
    # strike_target_value; "oi" picks the highest-open-interest strike in
    # the fetched window and ignores strike_target_value. See
    # services/option_symbol_service.py's get_option_symbol_by_metric.
    strike_selection_mode = Column(String(10), nullable=True)
    strike_target_value = Column(Float, nullable=True)  # target premium (Rs) or delta (0-1); unused for "oi"
    # BUY / SELL -- the broker-side order this mapping places when its
    # `action` matches the incoming signal. Only meaningful for the
    # unified (4-action) execution_model; independent of `action` on
    # purpose so a mapping can react to one signal (e.g. its trigger
    # `action` is SELL) while placing the OPPOSITE order (order_side BUY)
    # -- e.g. a reversal/flip strategy where a SELL signal exits a Call
    # AND enters a Put on a second mapping row. NULL means "derive from
    # `action` the old way" (BUY action -> BUY order, everything else ->
    # SELL order), so every mapping created before this column existed
    # keeps behaving exactly as it did.
    order_side = Column(String(4), nullable=True)

    # --- Per-signal action semantics -------------------------------------
    # What this mapping DOES when its `action` signal arrives. Until this
    # column existed every mapping implicitly meant "place an order", so
    # NULL is treated as "ENTER" and no existing row changes behaviour.
    #
    #   ENTER   place an entry order (the historical behaviour)
    #   EXIT    flatten this instrument's open position
    #   REVERSE exit whatever is open, then enter the opposite side
    #   ADD     add to an existing position (pyramid)
    #   REDUCE  partially close an existing position
    #   IGNORE  explicitly do nothing (lets a user mute one signal without
    #           deleting the row)
    #
    # Mirrors the action vocabulary used by mainstream webhook platforms
    # (TradersPost: buy/sell/exit/reverse/add) so incoming alerts written
    # for those services map over cleanly.
    signal_action = Column(String(10), nullable=True)

    # Order type for this mapping's entry. NULL => MARKET (previous
    # behaviour). LIMIT/SL/SL-M additionally use limit_price/trigger_price.
    order_type = Column(String(10), nullable=True)
    limit_price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)

    # --- Per-signal risk management --------------------------------------
    # All NULL by default => no automatic risk orders, exactly as before.
    # `*_type` is "percent" or "points"; the value is interpreted against
    # the fill price. Trailing uses trail_value with the same unit rule.
    stop_loss_type = Column(String(10), nullable=True)
    stop_loss_value = Column(Float, nullable=True)
    target_type = Column(String(10), nullable=True)
    target_value = Column(Float, nullable=True)
    trailing_type = Column(String(10), nullable=True)
    trailing_value = Column(Float, nullable=True)

    # --- Sizing ----------------------------------------------------------
    # Size expressed in LOTS for F&O. When set, signal_engine multiplies by
    # the contract's lot size at signal time and ignores `quantity`. NULL
    # keeps the raw-`quantity` behaviour every existing row has.
    lots = Column(Integer, nullable=True)

    # --- Multi-leg grouping ----------------------------------------------
    # Mappings that share a (strategy_id, leg_basket) fire TOGETHER as one
    # basket when their signal arrives -- this is what lets a single alert
    # open a straddle/strangle/spread instead of one instrument. NULL (the
    # default) means "standalone", i.e. today's one-instrument-per-mapping
    # behaviour. `basket_leg_order` orders legs within a basket so exits
    # can be sequenced before entries.
    leg_basket = Column(String(50), nullable=True)
    basket_leg_order = Column(Integer, nullable=True)

    # Human label shown in the signal-action table, e.g. "Long Call".
    # Cosmetic only; never used for matching.
    label = Column(String(100), nullable=True)

    # Optional extra gates that must ALSO pass before this rule fires, as
    # JSON: {"time_after": "09:20", "time_before": "15:00",
    #        "indicator": {"name": "RSI", "op": "<", "value": 70}}
    #
    # Deliberately a small, fixed shape rather than the full condition tree
    # the Flow builder supports -- the platform already has a node canvas at
    # /flow for arbitrary IF/AND/OR logic, and reimplementing that here
    # would create a second engine to keep in sync. This covers the two
    # gates people actually ask for on a webhook rule (don't trade the
    # opening minutes; don't buy an overbought market) and links out to Flow
    # for anything richer. NULL = always fire, so existing rows are
    # unaffected.
    conditions = Column(Text, nullable=True)

    execution_profile_id = Column(Integer, ForeignKey("execution_profiles.id"), nullable=True)
    # Per-action override JSON, e.g. {"quantity": 5, "product": "NRML",
    # "order_type": "LIMIT", "broker": "angel"}. Any key omitted falls back
    # to the linked execution_profile's default (or this row's own
    # quantity/product_type if no profile is linked). NULL means "use
    # defaults for every field" -- the common case.
    buy_override = Column(Text, nullable=True)
    sell_override = Column(Text, nullable=True)
    short_override = Column(Text, nullable=True)
    exit_override = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    strategy = relationship("Strategy", back_populates="symbol_mappings")
    execution_profile = relationship("ExecutionProfile")

    _OVERRIDE_COLUMNS = {
        "BUY": "buy_override",
        "SELL": "sell_override",
        "SHORT": "short_override",
        "EXIT": "exit_override",
    }

    def get_override(self, action: str) -> dict:
        """Parse the JSON override for one of the four actions. Returns {}
        if there is none (i.e. "use defaults") or the value is malformed."""
        column_name = self._OVERRIDE_COLUMNS.get((action or "").upper())
        if not column_name:
            return {}
        raw = getattr(self, column_name, None)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def resolve_execution(self, action: str) -> dict:
        """Resolve the effective quantity/product/order_type/broker for a
        given action: execution_profile defaults, then this row's own
        quantity/product_type as a fallback when no profile is linked, then
        the per-action override on top (override wins on any key it sets).
        This is the single source of truth both the webhook and deployment
        execution paths should call once they're wired to the 4-action
        model (Phase 2/3) -- centralizing it here means "change one profile,
        every linked instrument updates" holds for both paths identically.
        """
        resolved = {
            "quantity": self.quantity,
            "product": self.product_type,
            "order_type": "MARKET",
            "broker": None,
        }
        if self.execution_profile:
            resolved["quantity"] = self.execution_profile.default_quantity
            resolved["product"] = self.execution_profile.product
            resolved["order_type"] = self.execution_profile.order_type
            resolved["broker"] = self.execution_profile.broker

        override = self.get_override(action)
        for key in ("quantity", "product", "order_type", "broker"):
            if key in override and override[key] not in (None, ""):
                resolved[key] = override[key]

        # This row's own order_type wins over the profile default when set
        # -- the Signal Actions table writes it per mapping. The per-action
        # override JSON above still wins over both (it is the most specific).
        if self.order_type and "order_type" not in override:
            resolved["order_type"] = self.order_type

        return resolved

    def get_signal_action(self) -> str:
        """What this mapping does when its signal fires.

        NULL => "ENTER": every mapping created before signal_action existed
        placed an entry order, so that is the only safe interpretation.
        """
        value = (self.signal_action or "").upper()
        return value if value in SIGNAL_ACTIONS else "ENTER"

    def get_conditions(self) -> dict:
        """Parsed extra gates, or {} when this rule always fires."""
        if not self.conditions:
            return {}
        try:
            parsed = json.loads(self.conditions)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            logger.warning(f"Mapping {self.id}: conditions JSON is malformed; ignoring")
            return {}

    def conditions_pass(self, now=None, indicator_value=None) -> tuple[bool, str | None]:
        """Evaluate this rule's extra gates.

        Returns (passed, reason_if_blocked). Fails CLOSED for time windows
        (a malformed window blocks rather than trades) but OPEN for the
        indicator gate when no value is available -- an unreachable
        indicator feed must not silently halt a strategy, which is the same
        posture services/signal_engine.py takes for its other safety checks.
        """
        cfg = self.get_conditions()
        if not cfg:
            return True, None

        from datetime import datetime

        current = now or datetime.now()

        after = cfg.get("time_after")
        before = cfg.get("time_before")
        if after or before:
            try:
                hhmm = current.strftime("%H:%M")
                if after and hhmm < after:
                    return False, f"before the {after} start time"
                if before and hhmm > before:
                    return False, f"after the {before} cut-off"
            except Exception:
                return False, "time window is misconfigured"

        indicator = cfg.get("indicator")
        if indicator and indicator_value is not None:
            try:
                op = indicator.get("op", ">")
                target = float(indicator.get("value"))
                value = float(indicator_value)
                ok = {
                    ">": value > target,
                    "<": value < target,
                    ">=": value >= target,
                    "<=": value <= target,
                    "==": value == target,
                    "!=": value != target,
                }.get(op)
                if ok is False:
                    return False, (
                        f"{indicator.get('name', 'indicator')} is {value}, "
                        f"which fails {op} {target}"
                    )
            except (TypeError, ValueError):
                logger.warning(f"Mapping {self.id}: indicator condition is malformed; ignoring")

        return True, None

    def get_risk_config(self) -> dict:
        """Per-signal SL/target/trailing, or {} when none are configured.

        Values are unit-tagged ("percent" | "points") rather than absolute
        prices because a webhook mapping is written once and reused across
        many fills at different prices -- an absolute stop would be wrong
        on every fill but the first.
        """
        config: dict = {}
        if self.stop_loss_value is not None:
            config["stop_loss"] = {
                "type": (self.stop_loss_type or "percent").lower(),
                "value": self.stop_loss_value,
            }
        if self.target_value is not None:
            config["target"] = {
                "type": (self.target_type or "percent").lower(),
                "value": self.target_value,
            }
        if self.trailing_value is not None:
            config["trailing"] = {
                "type": (self.trailing_type or "percent").lower(),
                "value": self.trailing_value,
            }
        return config

    def resolve_quantity(self, lot_size: int | None = None) -> int:
        """Effective order quantity.

        `lots` (when set) is authoritative and multiplied by the contract's
        lot size resolved at signal time; `quantity` is the raw fallback
        every pre-existing row uses. A missing/invalid lot_size degrades to
        the raw quantity rather than guessing a multiplier -- silently
        sending the wrong size is far worse than sending the old one.
        """
        if self.lots and lot_size and lot_size > 0:
            return int(self.lots) * int(lot_size)
        if self.lots and not lot_size:
            logger.warning(
                f"Mapping {self.id}: lots={self.lots} set but lot size could not be "
                "resolved; falling back to raw quantity"
            )
        return int(self.quantity or 0)


class TrailingStop(Base):
    """One live trailing stop being managed by the platform.

    Exists because a trailing stop is NOT a fire-and-forget broker order:
    the stop level has to be *moved* as price advances, which needs a
    process watching the position. Most Indian brokers either don't expose a
    trailing field at all or implement it inconsistently, so storing the
    intent on the mapping and hoping the broker honours it (what the first
    version of this feature did) meant the field silently did nothing.

    Lifecycle, driven by services/trailing_stop_service.py:
      active   -> created when an entry with trailing configured fills
      active   -> stop_price ratchets up (long) / down (short); NEVER back
      exited   -> price crossed the stop, we sent the exit order
      cancelled-> position closed by something else (target, manual, EOD)

    `stop_price` only ever moves in the profitable direction -- that
    ratchet is the entire point of a trailing stop, and enforcing it here
    rather than at the caller means no code path can accidentally loosen a
    stop that has already tightened.
    """

    __tablename__ = "trailing_stops"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    strategy_id = Column(Integer, nullable=True, index=True)
    mapping_id = Column(Integer, nullable=True)

    symbol = Column(String(100), nullable=False)
    exchange = Column(String(20), nullable=False)
    product = Column(String(20), nullable=True)
    broker = Column(String(50), nullable=True)
    quantity = Column(Integer, nullable=False)
    # Side of the ENTRY (BUY = long). The exit order is the opposite side.
    entry_side = Column(String(4), nullable=False)
    entry_price = Column(Float, nullable=False)

    # "percent" | "points" -- same unit convention as the mapping's stored
    # risk config; see StrategySymbolMapping.get_risk_config for why an
    # absolute price would be wrong here.
    trail_type = Column(String(10), nullable=False, default="percent")
    trail_value = Column(Float, nullable=False)

    # Best price seen since entry (high-water for a long, low-water for a
    # short) and the stop derived from it.
    peak_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=False)

    status = Column(String(20), nullable=False, default="active", index=True)
    exit_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def is_long(self) -> bool:
        return (self.entry_side or "").upper() == "BUY"

    def compute_stop(self, from_price: float) -> float:
        """Stop level for a given peak price."""
        if self.trail_type == "percent":
            offset = from_price * (self.trail_value / 100.0)
        else:
            offset = self.trail_value
        return round(from_price - offset if self.is_long() else from_price + offset, 2)

    def update_peak(self, ltp: float) -> bool:
        """Ratchet the peak/stop toward profit. Returns True if it moved.

        Deliberately one-directional: a long's stop can only rise, a
        short's can only fall. A pullback moves neither.
        """
        if ltp is None or ltp <= 0:
            return False
        improved = ltp > self.peak_price if self.is_long() else ltp < self.peak_price
        if not improved:
            return False
        self.peak_price = ltp
        new_stop = self.compute_stop(ltp)
        # Guard the ratchet even if compute_stop is ever changed.
        if (self.is_long() and new_stop > self.stop_price) or (
            not self.is_long() and new_stop < self.stop_price
        ):
            self.stop_price = new_stop
        return True

    def is_hit(self, ltp: float) -> bool:
        """True when price has crossed the stop and we must exit."""
        if ltp is None or ltp <= 0:
            return False
        return ltp <= self.stop_price if self.is_long() else ltp >= self.stop_price

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "entry_side": self.entry_side,
            "entry_price": self.entry_price,
            "trail_type": self.trail_type,
            "trail_value": self.trail_value,
            "peak_price": self.peak_price,
            "stop_price": self.stop_price,
            "status": self.status,
            "exit_reason": self.exit_reason,
        }


class LegGroup(Base):
    """One rotating position on a webhook strategy: a named set of
    mutually-exclusive `Leg` rows (e.g. "Call" and "Put"), where exactly one
    (or none) is open at a time. This is `execution_model == "stateful"`'s
    core primitive -- a new pair of tables rather than an extension of
    StrategySymbolMapping, because StrategySymbolMapping rows are
    independent of each other (any subset can be "active" simultaneously)
    while a LegGroup's legs are mutually exclusive by construction (opening
    one implies closing whichever sibling was open).

    `current_leg_id` is the actual state: NULL means flat (no leg open).
    Every transition goes through rotate_leg_group() below, which is the
    only code path allowed to change it -- never set it directly.
    """

    __tablename__ = "leg_groups"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default="1")  # pause the whole group
    current_leg_id = Column(Integer, ForeignKey("legs.id"), nullable=True)  # NULL = flat
    events_timeline = Column(Text, nullable=True)  # JSON list, same shape as Deployment.events_timeline
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    legs = relationship(
        "Leg", back_populates="leg_group", foreign_keys="Leg.leg_group_id",
        cascade="all, delete-orphan",
    )
    current_leg = relationship("Leg", foreign_keys=[current_leg_id], post_update=True)

    def to_dict(self):
        try:
            timeline = json.loads(self.events_timeline) if self.events_timeline else []
        except Exception:
            timeline = []
        return {
            "id": self.id,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "is_active": self.is_active,
            "current_leg_id": self.current_leg_id,
            "events_timeline": timeline,
            "legs": [leg.to_dict() for leg in sorted(self.legs, key=lambda leg_row: leg_row.sort_order)],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Leg(Base):
    """One instrument within a LegGroup, e.g. the "Call" or "Put" side of a
    reversal. Mirrors StrategySymbolMapping's FUT/OPT/EQ instrument columns
    exactly (same names, same meaning, same live-resolution path via
    signal_engine.py's _resolve_live_instrument -- a Leg row satisfies that
    function's duck-typed attribute interface without modification).

    `entry_signal` is which raw webhook signal (BUY/SELL/SHORT/EXIT) opens
    this leg -- kept per-leg rather than hardcoding a 2-leg BUY-vs-SELL
    convention so a LegGroup can have more than 2 legs. BUY/SELL/SHORT are
    ordinary tradable legs (own instrument, own order_side); EXIT is a
    special "flatten" leg with no instrument of its own -- exchange/
    quantity/product_type/order_side are all NULL for it, and
    resolve_leg_rotation treats a matching EXIT signal as "close whatever
    leg is currently open, go flat" rather than "open a new leg." At most
    one EXIT leg per group (enforced in blueprints/strategy.py). `order_side`
    is the entry order a tradable leg places (almost always BUY for a long
    option leg, but kept explicit since a leg could in principle be a short
    entry) -- NULL only for EXIT legs.

    `condition` (nullable) is an optional platform condition-tree/leaf (same
    JSON shape services/condition_engine.py's evaluate_conditions_tree
    consumes, e.g. {"indicator": "RSI", "condition": ">", "value": 70|"}) --
    when set, this leg's entry_signal matching this incoming signal is not
    enough on its own; the condition must ALSO evaluate true at signal time
    for the leg to actually trigger. NULL means "always trigger on a
    matching signal," the behavior every leg had before this field existed.
    """

    __tablename__ = "legs"

    id = Column(Integer, primary_key=True)
    leg_group_id = Column(Integer, ForeignKey("leg_groups.id"), nullable=False, index=True)
    label = Column(String(50), nullable=False)  # "Call" / "Put" / free text
    entry_signal = Column(String(10), nullable=False)  # BUY / SELL / SHORT / EXIT
    order_side = Column(String(4), nullable=True)  # BUY / SELL -- this leg's entry order; NULL for EXIT
    instrument_type = Column(String(10), nullable=True)  # EQ / FUT / OPT -- NULL for EXIT
    exchange = Column(String(10), nullable=True)  # NULL for EXIT
    underlying = Column(String(50), nullable=True)  # FUT/OPT only
    expiry_type = Column(String(20), nullable=True)  # FUT/OPT only
    option_type = Column(String(2), nullable=True)  # CE/PE -- OPT only
    strike_offset = Column(String(10), nullable=True)  # OPT only
    # "offset" (default/NULL) | "premium" | "delta" | "oi" -- see the
    # matching column on StrategySymbolMapping for full semantics.
    strike_selection_mode = Column(String(10), nullable=True)
    strike_target_value = Column(Float, nullable=True)  # target premium (Rs) or delta (0-1); unused for "oi"
    instrument = Column(String(50), nullable=True)  # EQ only -- frozen contract symbol
    quantity = Column(Integer, nullable=True)  # NULL for EXIT
    product_type = Column(String(10), nullable=True)  # MIS/NRML/CNC -- NULL for EXIT
    condition = Column(Text, nullable=True)  # JSON condition tree/leaf -- see class docstring
    sort_order = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    leg_group = relationship("LegGroup", back_populates="legs", foreign_keys=[leg_group_id])

    def get_condition(self) -> dict | None:
        """Parse the JSON condition tree/leaf, or None if unset/malformed."""
        if not self.condition:
            return None
        try:
            parsed = json.loads(self.condition)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            return None

    def to_dict(self):
        return {
            "id": self.id,
            "leg_group_id": self.leg_group_id,
            "label": self.label,
            "entry_signal": self.entry_signal,
            "order_side": self.order_side,
            "instrument_type": self.instrument_type or ("EQ" if self.entry_signal != "EXIT" else None),
            "exchange": self.exchange,
            "underlying": self.underlying,
            "expiry_type": self.expiry_type,
            "option_type": self.option_type,
            "strike_offset": self.strike_offset,
            "strike_selection_mode": self.strike_selection_mode,
            "strike_target_value": self.strike_target_value,
            "instrument": self.instrument,
            "quantity": self.quantity,
            "product_type": self.product_type,
            "condition": self.get_condition(),
            "sort_order": self.sort_order,
        }


def init_db():
    """Initialize the database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy DB", logger)
    _migrate_add_signal_source_column()
    _migrate_add_brokers_column()
    _migrate_add_instrument_column()
    _migrate_add_lifecycle_state_column()
    _migrate_add_action_column()
    _migrate_add_execution_profile_columns()
    _migrate_add_execution_model_column()
    _migrate_add_template_id_column()
    _migrate_add_maxhook_instrument_columns()
    _migrate_add_order_side_column()
    _migrate_add_signal_action_columns()
    _migrate_add_leg_condition_column()
    _migrate_relax_leg_not_null_columns()
    _migrate_add_strike_selection_columns()
    _migrate_add_enforce_market_hours_column()
    _migrate_add_last_trade_at_column()
    _migrate_add_deployment_brokers_column()
    _migrate_add_backtest_report_columns()


def _migrate_add_backtest_report_columns():
    """Add report (JSON summary) and error_message to backtests -- see the
    Backtest model's docstring on `report` above. Existing rows (all
    status="Pending" stubs from before services/backtest_engine.py existed)
    get NULL for both, which get_report() and every reader already handle."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "backtests" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("backtests")]
        with engine.connect() as conn:
            if "report" not in columns:
                conn.execute(text("ALTER TABLE backtests ADD COLUMN report TEXT"))
                logger.info("Migration: Added 'report' column to backtests table")
            if "error_message" not in columns:
                conn.execute(text("ALTER TABLE backtests ADD COLUMN error_message VARCHAR(500)"))
                logger.info("Migration: Added 'error_message' column to backtests table")
            conn.commit()
    except Exception as e:
        logger.exception(f"Migration check for backtest report/error_message columns: {e}")


def _migrate_add_signal_source_column():
    """Add signal_source column to strategies table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "strategies" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "signal_source" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategies ADD COLUMN signal_source VARCHAR(50) DEFAULT 'TradingView'"
                    )
                )
                conn.commit()
                logger.info("Migration: Added 'signal_source' column to strategies table")
    except Exception as e:
        logger.exception(f"Migration check for signal_source column: {e}")


def _migrate_add_brokers_column():
    """Add brokers column to strategies table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "strategies" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "brokers" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategies ADD COLUMN brokers VARCHAR(255)"
                    )
                )
                conn.commit()
                logger.info("Migration: Added 'brokers' column to strategies table")
    except Exception as e:
        logger.exception(f"Migration check for brokers column: {e}")


def _migrate_add_instrument_column():
    """Add instrument column to strategy_symbol_mappings table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("strategy_symbol_mappings")]
        if "instrument" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategy_symbol_mappings ADD COLUMN instrument VARCHAR(50)"
                    )
                )
                conn.commit()
                logger.info("Migration: Added 'instrument' column to strategy_symbol_mappings table")
    except Exception as e:
        logger.exception(f"Migration check for instrument column: {e}")


def _migrate_add_lifecycle_state_column():
    """Add lifecycle_state column to strategies table if it doesn't exist"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        # Check if table exists
        if "strategies" not in inspector.get_table_names():
            return

        # Check if column exists
        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "lifecycle_state" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategies ADD COLUMN lifecycle_state VARCHAR(30) DEFAULT 'Draft'"
                    )
                )
                conn.commit()
                logger.info("Migration: Added 'lifecycle_state' column to strategies table")
    except Exception as e:
        logger.exception(f"Migration check for lifecycle_state column: {e}")


def _migrate_add_action_column():
    """Add action column to strategy_symbol_mappings and backfill it from
    the legacy `symbol` column, which historically held the trigger action
    string ("BUY"/"SELL") rather than a tradable instrument. See
    StrategySymbolMapping's class docstring for the full explanation.

    Backfill is safe/lossless: every existing row's `symbol` value is
    already exactly "BUY" or "SELL" (that was the only thing the old
    frontend selector could ever send), so copying it into the new
    `action` column reproduces today's behavior exactly. New rows should
    be written with `action` going forward; `symbol` is kept in sync by
    callers during the transition period (see add_symbol_mapping).
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategy_symbol_mappings")]
        if "action" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE strategy_symbol_mappings ADD COLUMN action VARCHAR(10)")
                )
                conn.commit()
                logger.info("Migration: Added 'action' column to strategy_symbol_mappings table")

        # Backfill any rows where action is still NULL (freshly-added column,
        # or rows inserted before this migration ran) from the legacy symbol
        # column. Idempotent - only touches rows that still need it.
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "UPDATE strategy_symbol_mappings SET action = symbol "
                    "WHERE action IS NULL AND symbol IN ('BUY', 'SELL')"
                )
            )
            conn.commit()
            if result.rowcount:
                logger.info(
                    f"Migration: Backfilled 'action' from legacy 'symbol' column for "
                    f"{result.rowcount} strategy_symbol_mappings row(s)"
                )
    except Exception as e:
        logger.exception(f"Migration check for action column: {e}")


def _migrate_add_execution_profile_columns():
    """Add execution_profile_id and the four per-action override columns to
    strategy_symbol_mappings. The execution_profiles table itself is a new
    table, so Base.metadata.create_all() (called earlier in init_db) already
    creates it -- this migration only needs to add columns to the existing
    strategy_symbol_mappings table. All new columns are nullable (or absent
    -> {} via get_override), so existing rows keep working exactly as
    before: resolve_execution() falls back to quantity/product_type with no
    profile and no override, identical to today's behavior.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategy_symbol_mappings")]
        new_columns = {
            "execution_profile_id": "INTEGER",
            "buy_override": "TEXT",
            "sell_override": "TEXT",
            "short_override": "TEXT",
            "exit_override": "TEXT",
        }
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                with engine.connect() as conn:
                    conn.execute(
                        text(
                            f"ALTER TABLE strategy_symbol_mappings ADD COLUMN {col_name} {col_type}"
                        )
                    )
                    conn.commit()
                    logger.info(
                        f"Migration: Added '{col_name}' column to strategy_symbol_mappings table"
                    )
    except Exception as e:
        logger.exception(f"Migration check for execution profile columns: {e}")


def _migrate_add_execution_model_column():
    """Add execution_model to strategies, defaulting existing rows to
    'legacy' so no strategy silently switches execution paths on upgrade."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategies" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "execution_model" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategies ADD COLUMN execution_model VARCHAR(20) DEFAULT 'legacy'"
                    )
                )
                conn.commit()
                logger.info("Migration: Added 'execution_model' column to strategies table")
    except Exception as e:
        logger.exception(f"Migration check for execution_model column: {e}")


def _migrate_add_enforce_market_hours_column():
    """Add enforce_market_hours to strategies, defaulting existing rows to 0
    (off) so no strategy starts rejecting out-of-hours signals on upgrade."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategies" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "enforce_market_hours" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE strategies ADD COLUMN enforce_market_hours BOOLEAN DEFAULT 0"
                    )
                )
                conn.commit()
                logger.info(
                    "Migration: Added 'enforce_market_hours' column to strategies table"
                )
    except Exception as e:
        logger.exception(f"Migration check for enforce_market_hours column: {e}")


def _migrate_add_last_trade_at_column():
    """Add last_trade_at to deployments -- see the column's docstring on
    the model above for why this must be separate from `updated_at`
    (cooldown risk checks need "last time we actually traded", not "last
    time any commit touched this row")."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "deployments" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("deployments")]
        if "last_trade_at" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE deployments ADD COLUMN last_trade_at DATETIME"))
                conn.commit()
                logger.info("Migration: Added 'last_trade_at' column to deployments table")
    except Exception as e:
        logger.exception(f"Migration check for last_trade_at column: {e}")


def _migrate_add_deployment_brokers_column():
    """Add brokers (JSON array) to deployments -- see the column's
    docstring on the model above. Existing rows get NULL, which
    get_brokers() correctly falls back to [self.broker] for."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "deployments" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("deployments")]
        if "brokers" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE deployments ADD COLUMN brokers TEXT"))
                conn.commit()
                logger.info("Migration: Added 'brokers' column to deployments table")
    except Exception as e:
        logger.exception(f"Migration check for brokers column: {e}")


def _migrate_add_template_id_column():
    """Add template_id to strategies, defaulting existing rows to NULL --
    pre-migration strategies have no wizard blueprint association and must
    not be assumed to be any particular type."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategies" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategies")]
        if "template_id" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE strategies ADD COLUMN template_id VARCHAR(50)")
                )
                conn.commit()
                logger.info("Migration: Added 'template_id' column to strategies table")
    except Exception as e:
        logger.exception(f"Migration check for template_id column: {e}")


def _migrate_add_maxhook_instrument_columns():
    """Add per-symbol pause (is_active) and instrument-type-aware columns
    (instrument_type/underlying/expiry_type/option_type/strike_offset) to
    strategy_symbol_mappings. All nullable/defaulted, existing rows keep
    working exactly as before: is_active defaults to true (nothing that
    worked yesterday silently stops firing), instrument_type NULL is
    treated identically to "EQ" everywhere it's read.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategy_symbol_mappings")]
        new_columns = {
            "is_active": "BOOLEAN DEFAULT 1",
            "instrument_type": "VARCHAR(10)",
            "underlying": "VARCHAR(50)",
            "expiry_type": "VARCHAR(20)",
            "option_type": "VARCHAR(2)",
            "strike_offset": "VARCHAR(10)",
        }
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                with engine.connect() as conn:
                    conn.execute(
                        text(
                            f"ALTER TABLE strategy_symbol_mappings ADD COLUMN {col_name} {col_type}"
                        )
                    )
                    conn.commit()
                    logger.info(
                        f"Migration: Added '{col_name}' column to strategy_symbol_mappings table"
                    )

        # Backfill any pre-existing rows where is_active landed NULL (SQLite
        # only applies a column DEFAULT to rows inserted after the ALTER,
        # not retroactively -- existing rows get NULL, not 1).
        # TRUE (not the bare integer 1) -- Postgres's BOOLEAN column rejects
        # an integer literal on UPDATE/assignment with DatatypeMismatch, even
        # though it accepts `BOOLEAN DEFAULT 1` in DDL above (literal is
        # coerced at DDL-parse time there, not on a DML SET). TRUE/FALSE are
        # valid boolean literals on both SQLite and Postgres.
        with engine.connect() as conn:
            result = conn.execute(
                text("UPDATE strategy_symbol_mappings SET is_active = TRUE WHERE is_active IS NULL")
            )
            conn.commit()
            if result.rowcount:
                logger.info(
                    f"Migration: Backfilled 'is_active' = 1 for {result.rowcount} "
                    "strategy_symbol_mappings row(s)"
                )
    except Exception as e:
        logger.exception(f"Migration check for MaxHook instrument columns: {e}")


def _migrate_add_order_side_column():
    """Add order_side to strategy_symbol_mappings -- decouples which order
    a mapping places (BUY/SELL) from which signal action it reacts to,
    needed for reversal/flip strategies (e.g. a webhook SELL signal that
    exits a Call on one mapping AND enters a Put via BUY on a second
    mapping). NULL for every existing row -- signal_engine.py falls back
    to its original action-derived side when order_side is unset, so no
    existing strategy's behavior changes."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategy_symbol_mappings")]
        if "order_side" not in columns:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE strategy_symbol_mappings ADD COLUMN order_side VARCHAR(4)")
                )
                conn.commit()
                logger.info("Migration: Added 'order_side' column to strategy_symbol_mappings table")
    except Exception as e:
        logger.exception(f"Migration check for order_side column: {e}")


def _migrate_add_signal_action_columns():
    """Add the per-signal action/order/risk/sizing/basket columns to
    strategy_symbol_mappings.

    Every column is nullable with no default, and every read path treats
    NULL as "behave exactly as before this feature existed":
      signal_action NULL -> ENTER, order_type NULL -> MARKET, all risk
      fields NULL -> no SL/target/trailing orders, lots NULL -> use the
      raw `quantity`, leg_basket NULL -> standalone mapping.
    So an existing install keeps running unchanged until the user opts in
    from the new Signal Actions table.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "strategy_symbol_mappings" not in inspector.get_table_names():
            return

        existing = {col["name"] for col in inspector.get_columns("strategy_symbol_mappings")}
        new_columns = {
            "signal_action": "VARCHAR(10)",
            "order_type": "VARCHAR(10)",
            "limit_price": "FLOAT",
            "trigger_price": "FLOAT",
            "stop_loss_type": "VARCHAR(10)",
            "stop_loss_value": "FLOAT",
            "target_type": "VARCHAR(10)",
            "target_value": "FLOAT",
            "trailing_type": "VARCHAR(10)",
            "trailing_value": "FLOAT",
            "lots": "INTEGER",
            "leg_basket": "VARCHAR(50)",
            "basket_leg_order": "INTEGER",
            "label": "VARCHAR(100)",
            "conditions": "TEXT",
        }
        missing = {n: d for n, d in new_columns.items() if n not in existing}
        if not missing:
            return

        with engine.connect() as conn:
            for name, ddl in missing.items():
                conn.execute(
                    text(f"ALTER TABLE strategy_symbol_mappings ADD COLUMN {name} {ddl}")
                )
            conn.commit()
        logger.info(
            f"Migration: Added {len(missing)} signal-action column(s) to strategy_symbol_mappings"
        )
    except Exception as e:
        logger.exception(f"Migration check for signal-action columns: {e}")


def _migrate_add_leg_condition_column():
    """Add condition to legs -- an optional platform condition-tree/leaf
    that must ALSO evaluate true (in addition to entry_signal matching the
    incoming webhook signal) for that leg to actually trigger. NULL for
    every existing leg -- signal_engine.py treats NULL as "always trigger
    on a matching signal," so no existing leg group's behavior changes."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        if "legs" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("legs")]
        if "condition" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE legs ADD COLUMN condition TEXT"))
                conn.commit()
                logger.info("Migration: Added 'condition' column to legs table")
    except Exception as e:
        logger.exception(f"Migration check for legs.condition column: {e}")


def _migrate_relax_leg_not_null_columns():
    """Widen order_side/exchange/quantity/product_type on legs from NOT
    NULL to nullable, needed for EXIT legs (a pure "flatten" trigger with
    no instrument of its own -- see Leg's class docstring). SQLite has no
    ALTER COLUMN, so this rebuilds the table via the established rename-
    recreate-copy-drop pattern (see database/user_db.py's
    user_broker_credentials migration for the same technique) -- but only
    when the existing table still has the old constraint, so this is a
    no-op after the first run (checked via PRAGMA table_info's notnull
    flag on order_side, which every row created before this migration
    existed had to satisfy)."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "legs" not in inspector.get_table_names():
            return

        columns = {col["name"]: col for col in inspector.get_columns("legs")}
        if "order_side" not in columns or columns["order_side"]["nullable"]:
            return  # already relaxed (or column doesn't exist yet -- create_all will make it nullable)

        if engine.dialect.name != "sqlite":
            # The rename-recreate-copy-drop rebuild below is a SQLite-only
            # workaround for lack of native ALTER TABLE ... ALTER COLUMN (see
            # database/user_db.py's _ensure_broker_name_column for the same
            # pattern/guard). It also hardcodes `id INTEGER NOT NULL PRIMARY
            # KEY`, which SQLite treats as an alias for the auto-incrementing
            # rowid but Postgres would create as a plain, non-generating
            # column -- any INSERT without an explicit id would then fail. A
            # non-SQLite install that somehow still has the old NOT NULL
            # schema should go through a proper Postgres migration
            # (ALTER TABLE legs ALTER COLUMN <col> DROP NOT NULL) instead.
            logger.warning(
                "legs table predates the EXIT-leg NOT NULL relaxation on a "
                "non-SQLite database; skipping the SQLite-specific rebuild. "
                "Run 'ALTER TABLE legs ALTER COLUMN order_side DROP NOT NULL' "
                "(and the same for exchange/quantity/product_type) directly "
                "against Postgres instead."
            )
            return

        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE legs RENAME TO legs_old"))
            conn.commit()
            conn.execute(text("""
                CREATE TABLE legs (
                    id INTEGER NOT NULL PRIMARY KEY,
                    leg_group_id INTEGER NOT NULL,
                    label VARCHAR(50) NOT NULL,
                    entry_signal VARCHAR(10) NOT NULL,
                    order_side VARCHAR(4),
                    instrument_type VARCHAR(10),
                    exchange VARCHAR(10),
                    underlying VARCHAR(50),
                    expiry_type VARCHAR(20),
                    option_type VARCHAR(2),
                    strike_offset VARCHAR(10),
                    instrument VARCHAR(50),
                    quantity INTEGER,
                    product_type VARCHAR(10),
                    condition TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(leg_group_id) REFERENCES leg_groups (id)
                )
            """))
            conn.execute(text("""
                INSERT INTO legs
                    (id, leg_group_id, label, entry_signal, order_side, instrument_type,
                     exchange, underlying, expiry_type, option_type, strike_offset,
                     instrument, quantity, product_type, condition, sort_order,
                     created_at, updated_at)
                SELECT
                    id, leg_group_id, label, entry_signal, order_side, instrument_type,
                    exchange, underlying, expiry_type, option_type, strike_offset,
                    instrument, quantity, product_type, condition, sort_order,
                    created_at, updated_at
                FROM legs_old
            """))
            conn.execute(text("DROP TABLE legs_old"))
            conn.commit()
            logger.info("Migration: Relaxed NOT NULL constraints on legs table for EXIT legs")
    except Exception as e:
        logger.exception(f"Migration check for legs NOT NULL relaxation: {e}")


def _migrate_add_strike_selection_columns():
    """Add strike_selection_mode/strike_target_value to both
    strategy_symbol_mappings and legs -- lets a user pick an option strike
    by target premium/delta or highest OI, in addition to the existing
    ATM/ITM/OTM strike_offset. NULL/"offset" for every existing row means
    "use strike_offset the old way," so no existing mapping/leg's behavior
    changes -- see services/option_symbol_service.py's
    get_option_symbol_by_metric for the new resolution path."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)

        for table in ("strategy_symbol_mappings", "legs"):
            if table not in inspector.get_table_names():
                continue
            columns = [col["name"] for col in inspector.get_columns(table)]
            with engine.connect() as conn:
                if "strike_selection_mode" not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN strike_selection_mode VARCHAR(10)"))
                    conn.commit()
                    logger.info(f"Migration: Added 'strike_selection_mode' column to {table} table")
                if "strike_target_value" not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN strike_target_value FLOAT"))
                    conn.commit()
                    logger.info(f"Migration: Added 'strike_target_value' column to {table} table")
    except Exception as e:
        logger.exception(f"Migration check for strike_selection columns: {e}")


def create_strategy(
    name,
    webhook_id,
    user_id,
    is_intraday=True,
    trading_mode="LONG",
    start_time=None,
    end_time=None,
    squareoff_time=None,
    platform="tradingview",
    signal_source=None,
    brokers=None,
    lifecycle_state="Draft",
    execution_model="unified",
    template_id=None,
):
    """Create a new strategy.

    New strategies default to the 'unified' (4-action) engine. It is a
    strict superset of 'legacy': BUY/SELL behave identically, while
    SHORT/EXIT additionally work as distinct actions instead of both
    collapsing into SELL. This is what lets the Signal Actions table offer
    per-signal behaviour without asking the user to pick an engine.
    Existing rows are untouched -- they keep whatever model they were
    created with, and services/signal_engine.py::_resolve_execution_model
    still honours it.
    """
    if not signal_source:
        signal_source = "TradingView"

    # Handle brokers lists
    brokers_str = None
    if brokers:
        if isinstance(brokers, list):
            brokers_str = ",".join(brokers)
        else:
            brokers_str = str(brokers)

    try:
        strategy = Strategy(
            name=name,
            webhook_id=webhook_id,
            user_id=user_id,
            is_intraday=is_intraday,
            trading_mode=trading_mode,
            start_time=start_time,
            end_time=end_time,
            squareoff_time=squareoff_time,
            platform=platform,
            signal_source=signal_source,
            brokers=brokers_str,
            lifecycle_state=lifecycle_state,
            execution_model=execution_model if execution_model in ("legacy", "unified") else "legacy",
            template_id=str(template_id) if template_id else None,
        )
        db_session.add(strategy)
        db_session.commit()

        # Automatically create Version 1 of this strategy configuration snapshot
        version = StrategyVersion(
            strategy_id=strategy.id,
            version=1,
            config="{}"
        )
        db_session.add(version)
        db_session.commit()

        # Invalidate user strategies cache
        user_cache_key = f"user_{user_id}"
        if user_cache_key in _user_strategies_cache:
            del _user_strategies_cache[user_cache_key]

        return strategy
    except Exception as e:
        logger.exception(f"Error creating strategy: {str(e)}")
        db_session.rollback()
        return None


def get_strategy(strategy_id):
    """Get strategy by ID"""
    try:
        return Strategy.query.get(strategy_id)
    except Exception as e:
        logger.exception(f"Error getting strategy {strategy_id}: {str(e)}")
        return None


def get_strategy_by_webhook_id(webhook_id):
    """Get strategy by webhook ID (cached for 5 minutes)"""
    # Check cache first
    if webhook_id in _strategy_webhook_cache:
        return _strategy_webhook_cache[webhook_id]

    try:
        strategy = Strategy.query.filter_by(webhook_id=webhook_id).first()
        # Cache the result (including None for not found)
        if strategy:
            _strategy_webhook_cache[webhook_id] = strategy
        return strategy
    except Exception as e:
        logger.exception(f"Error getting strategy by webhook ID {webhook_id}: {str(e)}")
        return None


def get_all_strategies():
    """Get all strategies"""
    try:
        return Strategy.query.all()
    except Exception as e:
        logger.exception(f"Error getting all strategies: {str(e)}")
        return []


def get_user_strategies(user_id):
    """Get all strategies for a user (cached for 10 minutes)"""
    cache_key = f"user_{user_id}"

    # Check cache first
    if cache_key in _user_strategies_cache:
        return _user_strategies_cache[cache_key]

    try:
        logger.info(f"Fetching strategies for user: {user_id}")
        strategies = Strategy.query.filter_by(user_id=user_id).all()
        logger.info(f"Found {len(strategies)} strategies")
        # Cache the result
        _user_strategies_cache[cache_key] = strategies
        return strategies
    except Exception as e:
        logger.exception(f"Error getting user strategies for {user_id}: {str(e)}")
        return []


def delete_strategy(strategy_id):
    """Delete strategy and its symbol mappings"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy:
            return False

        # Invalidate caches before deletion
        webhook_id = strategy.webhook_id
        user_id = strategy.user_id

        db_session.delete(strategy)
        db_session.commit()

        # Clear from caches
        if webhook_id in _strategy_webhook_cache:
            del _strategy_webhook_cache[webhook_id]
        user_cache_key = f"user_{user_id}"
        if user_cache_key in _user_strategies_cache:
            del _user_strategies_cache[user_cache_key]

        return True
    except Exception as e:
        logger.exception(f"Error deleting strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        # Re-raise (not swallow-to-False) so the caller's real error --
        # almost always a Postgres FK constraint violation from a child
        # table with no cascade relationship -- reaches the user instead of
        # the generic "Failed to delete strategy"/"Failed to delete
        # connection" that gave no signal of what actually blocked it.
        raise


def toggle_strategy(strategy_id):
    """Toggle strategy active status"""
    try:
        strategy = get_strategy(strategy_id)
        if not strategy:
            return None

        strategy.is_active = not strategy.is_active
        db_session.commit()

        # Invalidate caches so the flip is visible immediately -- without
        # this, get_strategy_by_webhook_id can keep serving a stale
        # is_active=True Strategy object to the async signal-processing
        # worker pool for up to the cache's 5-minute TTL, meaning a user's
        # "pause" (e.g. an emergency stop on a misbehaving strategy) isn't
        # guaranteed to block the very next incoming webhook signal.
        # Mirrors delete_strategy's cache invalidation exactly.
        webhook_id = strategy.webhook_id
        user_id = strategy.user_id
        if webhook_id in _strategy_webhook_cache:
            del _strategy_webhook_cache[webhook_id]
        user_cache_key = f"user_{user_id}"
        if user_cache_key in _user_strategies_cache:
            del _user_strategies_cache[user_cache_key]

        return strategy
    except Exception as e:
        logger.exception(f"Error toggling strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return None


def update_strategy_execution_model(strategy_id, execution_model):
    """Switch an existing strategy between 'legacy' (2-action), 'unified'
    (4-action BUY/SELL/SHORT/EXIT), and 'stateful' (LegGroup/Leg rotation)
    webhook signal processing -- see services/signal_engine.py's
    _process_signal_event dispatch. Safe to flip at any time: mapping rows
    and leg groups keep whatever config they already have, they just start
    (or stop) being matched by their respective engine.
    """
    try:
        if execution_model not in ("legacy", "unified", "stateful"):
            raise ValueError("execution_model must be 'legacy', 'unified', or 'stateful'")
        strategy = Strategy.query.get(strategy_id)
        if not strategy:
            return None
        strategy.execution_model = execution_model
        db_session.commit()

        # get_strategy_by_webhook_id caches the Strategy object for 5
        # minutes -- without invalidating here, a signal arriving shortly
        # after this flip could still be routed through the OLD engine
        # (e.g. 'legacy', which ignores order_side/signal_action entirely)
        # for up to 5 minutes, exactly the same class of staleness bug
        # _process_signal_event's db_session.expire_all() fixes for the
        # in-session identity map -- this is a SEPARATE cache (a plain
        # dict-like TTLCache, not part of the SQLAlchemy session) that
        # needs its own explicit invalidation. Mirrors delete_strategy/
        # toggle_strategy's existing cache invalidation.
        webhook_id = strategy.webhook_id
        if webhook_id in _strategy_webhook_cache:
            del _strategy_webhook_cache[webhook_id]

        return strategy
    except ValueError:
        raise
    except Exception as e:
        logger.exception(f"Error updating execution_model for strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return None


def update_strategy_times(strategy_id, start_time=None, end_time=None, squareoff_time=None):
    """Update strategy trading times"""
    try:
        strategy = Strategy.query.get(strategy_id)
        if strategy:
            if start_time is not None:
                strategy.start_time = start_time
            if end_time is not None:
                strategy.end_time = end_time
            if squareoff_time is not None:
                strategy.squareoff_time = squareoff_time
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.exception(f"Error updating strategy times {strategy_id}: {str(e)}")
        db_session.rollback()
        return False


def add_symbol_mapping(
    strategy_id,
    symbol,
    exchange,
    quantity,
    product_type,
    instrument=None,
    action=None,
    instrument_type=None,
    underlying=None,
    expiry_type=None,
    option_type=None,
    strike_offset=None,
    is_active=True,
    order_side=None,
    strike_selection_mode=None,
    strike_target_value=None,
    signal_action=None,
    order_type=None,
    limit_price=None,
    trigger_price=None,
    stop_loss_type=None,
    stop_loss_value=None,
    target_type=None,
    target_value=None,
    trailing_type=None,
    trailing_value=None,
    lots=None,
    leg_basket=None,
    basket_leg_order=None,
    label=None,
    conditions=None,
):
    """Add symbol mapping to strategy.

    `symbol` is kept for backward compatibility with existing callers (see
    StrategySymbolMapping's class docstring) -- if `action` isn't passed
    explicitly and `symbol` is a valid trigger action ("BUY"/"SELL"), it's
    mirrored into the new `action` column automatically.

    `instrument_type`/`underlying`/`expiry_type`/`option_type`/
    `strike_offset` are only meaningful for FUT/OPT rows -- left as None
    for the default EQ case, which behaves identically to before this
    feature existed.

    `order_side` (BUY/SELL) is only meaningful for `execution_model ==
    "unified"` strategies -- see StrategySymbolMapping.order_side's
    docstring. Left as None for legacy strategies, which derive the order
    side from the signal itself exactly as before.

    `strike_selection_mode`/`strike_target_value` are only meaningful for
    OPT rows -- see StrategySymbolMapping.strike_selection_mode's
    docstring. Left as None (offset mode) for every mapping that doesn't
    explicitly opt into Premium/Delta/OI-based strike selection.

    `signal_action` (ENTER/EXIT/REVERSE/ADD/REDUCE/IGNORE), `order_type`
    with `limit_price`/`trigger_price`, the SL/target/trailing pairs,
    `lots`, and `leg_basket`/`basket_leg_order` all back the Signal Actions
    table. Every one is None by default and every read path treats None as
    "behave exactly as before", so callers that don't pass them produce a
    mapping identical to what this function has always created.
    """
    try:
        if action is None and symbol in ("BUY", "SELL"):
            action = symbol
        mapping = StrategySymbolMapping(
            strategy_id=strategy_id,
            symbol=symbol,
            action=action,
            exchange=exchange,
            quantity=quantity,
            product_type=product_type,
            instrument=instrument,
            instrument_type=instrument_type,
            underlying=underlying,
            expiry_type=expiry_type,
            option_type=option_type,
            strike_offset=strike_offset,
            is_active=is_active,
            order_side=order_side,
            strike_selection_mode=strike_selection_mode,
            strike_target_value=strike_target_value,
            signal_action=(signal_action or "").upper() or None,
            order_type=(order_type or "").upper() or None,
            limit_price=limit_price,
            trigger_price=trigger_price,
            stop_loss_type=stop_loss_type,
            stop_loss_value=stop_loss_value,
            target_type=target_type,
            target_value=target_value,
            trailing_type=trailing_type,
            trailing_value=trailing_value,
            lots=lots,
            leg_basket=leg_basket,
            basket_leg_order=basket_leg_order,
            label=label,
            conditions=conditions,
        )
        db_session.add(mapping)
        db_session.commit()
        return mapping
    except Exception as e:
        logger.exception(f"Error adding symbol mapping: {str(e)}")
        db_session.rollback()
        # Re-raise (not swallow-to-None) so the caller's real DB/constraint
        # error reaches the user instead of the generic "Failed to add
        # symbol mapping" blueprints/strategy.py used to substitute here --
        # that string gave no signal of what actually failed (bad FK,
        # NOT NULL violation, etc), making every real cause indistinguishable
        # from every other one in the UI.
        raise


def bulk_add_symbol_mappings(strategy_id, mappings):
    """Add multiple symbol mappings at once.

    See add_symbol_mapping's docstring -- each row's `action` is mirrored
    from `symbol` when not explicitly provided.
    """
    try:
        for mapping_data in mappings:
            if "action" not in mapping_data and mapping_data.get("symbol") in ("BUY", "SELL"):
                mapping_data = {**mapping_data, "action": mapping_data["symbol"]}
            mapping = StrategySymbolMapping(strategy_id=strategy_id, **mapping_data)
            db_session.add(mapping)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error bulk adding symbol mappings: {str(e)}")
        db_session.rollback()
        return False


def get_symbol_mappings(strategy_id):
    """Get all symbol mappings for a strategy"""
    try:
        return StrategySymbolMapping.query.filter_by(strategy_id=strategy_id).all()
    except Exception as e:
        logger.exception(f"Error getting symbol mappings: {str(e)}")
        return []


def update_symbol_mapping(
    mapping_id,
    symbol=None,
    exchange=None,
    quantity=None,
    product_type=None,
    instrument=None,
    instrument_type=None,
    underlying=None,
    expiry_type=None,
    option_type=None,
    strike_offset=None,
    order_side=None,
    strike_selection_mode=None,
    strike_target_value=None,
    signal_action=None,
    order_type=None,
    limit_price=None,
    trigger_price=None,
    stop_loss_type=None,
    stop_loss_value=None,
    target_type=None,
    target_value=None,
    trailing_type=None,
    trailing_value=None,
    lots=None,
    leg_basket=None,
    basket_leg_order=None,
    label=None,
    conditions=None,
):
    """Update an existing symbol mapping in place. Any arg left as None
    keeps its current value (same partial-update convention as
    set_smtp_settings/set_email_identities). `symbol` is the trigger
    action (BUY/SELL) -- see add_symbol_mapping's docstring -- so updating
    it also re-mirrors the `action` column exactly like creation does.

    `instrument_type` switching (e.g. EQ -> OPT) also clears whichever
    fields no longer apply to the new type, so a mapping can't end up with
    a stale `instrument` string alongside a live OPT config or vice versa.

    `order_side` (BUY/SELL) is only meaningful for unified-execution-model
    strategies -- see StrategySymbolMapping.order_side's docstring.

    `strike_selection_mode`/`strike_target_value` are only meaningful for
    OPT rows -- see StrategySymbolMapping.strike_selection_mode's
    docstring.
    """
    try:
        mapping = StrategySymbolMapping.query.get(mapping_id)
        if not mapping:
            return None
        if symbol is not None:
            mapping.symbol = symbol
            if symbol in ("BUY", "SELL"):
                mapping.action = symbol
        if exchange is not None:
            mapping.exchange = exchange
        if quantity is not None:
            mapping.quantity = quantity
        if product_type is not None:
            mapping.product_type = product_type
        if instrument is not None:
            mapping.instrument = instrument
        if instrument_type is not None:
            mapping.instrument_type = instrument_type
            if instrument_type == "EQ":
                mapping.underlying = None
                mapping.expiry_type = None
                mapping.option_type = None
                mapping.strike_offset = None
                mapping.strike_selection_mode = None
                mapping.strike_target_value = None
            elif instrument_type == "FUT":
                mapping.option_type = None
                mapping.strike_offset = None
                mapping.strike_selection_mode = None
                mapping.strike_target_value = None
        if underlying is not None:
            mapping.underlying = underlying
        if expiry_type is not None:
            mapping.expiry_type = expiry_type
        if option_type is not None:
            mapping.option_type = option_type
        if strike_offset is not None:
            mapping.strike_offset = strike_offset
        if order_side is not None:
            mapping.order_side = order_side
        if strike_selection_mode is not None:
            mapping.strike_selection_mode = strike_selection_mode
        if strike_target_value is not None:
            mapping.strike_target_value = strike_target_value

        # Signal Actions fields -- same partial-update convention: None
        # means "leave as-is". The caller (blueprints/strategy.py's
        # _validate_signal_action_config) only includes keys the request
        # actually supplied, so omitted fields never get clobbered.
        for attr, value in (
            ("signal_action", (signal_action or "").upper() or None),
            ("order_type", (order_type or "").upper() or None),
            ("limit_price", limit_price),
            ("trigger_price", trigger_price),
            ("stop_loss_type", stop_loss_type),
            ("stop_loss_value", stop_loss_value),
            ("target_type", target_type),
            ("target_value", target_value),
            ("trailing_type", trailing_type),
            ("trailing_value", trailing_value),
            ("lots", lots),
            ("leg_basket", leg_basket),
            ("basket_leg_order", basket_leg_order),
            ("label", label),
            ("conditions", conditions),
        ):
            if value is not None:
                setattr(mapping, attr, value)

        db_session.commit()
        return mapping
    except Exception as e:
        logger.exception(f"Error updating symbol mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return None


def create_trailing_stop(
    username: str,
    symbol: str,
    exchange: str,
    quantity: int,
    entry_side: str,
    entry_price: float,
    trail_type: str,
    trail_value: float,
    product: str | None = None,
    broker: str | None = None,
    strategy_id: int | None = None,
    mapping_id: int | None = None,
):
    """Register a trailing stop for a freshly-filled entry.

    The initial peak is the entry price, so the stop starts one full trail
    distance away and can only tighten from there.
    """
    try:
        ts = TrailingStop(
            username=username,
            strategy_id=strategy_id,
            mapping_id=mapping_id,
            symbol=symbol,
            exchange=exchange,
            product=product,
            broker=broker,
            quantity=quantity,
            entry_side=(entry_side or "BUY").upper(),
            entry_price=entry_price,
            trail_type=(trail_type or "percent").lower(),
            trail_value=trail_value,
            peak_price=entry_price,
            stop_price=0.0,  # replaced below once the helpers are bound
            status="active",
        )
        ts.stop_price = ts.compute_stop(entry_price)
        db_session.add(ts)
        db_session.commit()
        logger.info(
            f"Trailing stop armed: {symbol} {entry_side} qty={quantity} "
            f"entry={entry_price} stop={ts.stop_price} ({trail_value}{trail_type})"
        )
        return ts
    except Exception as e:
        logger.exception(f"Error creating trailing stop for {symbol}: {e}")
        db_session.rollback()
        return None


def get_active_trailing_stops(username: str | None = None):
    """Every trailing stop still being managed, optionally for one user."""
    try:
        query = TrailingStop.query.filter_by(status="active")
        if username:
            query = query.filter_by(username=username)
        return query.all()
    except Exception as e:
        logger.exception(f"Error loading active trailing stops: {e}")
        return []


def close_trailing_stop(trailing_id: int, status: str, reason: str | None = None):
    """Mark a trailing stop finished ('exited' or 'cancelled')."""
    try:
        ts = TrailingStop.query.get(trailing_id)
        if not ts:
            return None
        ts.status = status
        ts.exit_reason = reason
        db_session.commit()
        return ts
    except Exception as e:
        logger.exception(f"Error closing trailing stop {trailing_id}: {e}")
        db_session.rollback()
        return None


def commit_trailing_stop_move():
    """Persist in-place peak/stop ratchets made by the monitor."""
    try:
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error committing trailing stop move: {e}")
        db_session.rollback()
        return False


def toggle_symbol_mapping_active(mapping_id):
    """Flip is_active (pause/resume) for one symbol mapping. Returns the
    mapping on success (with the new state already applied), None if not
    found. Does not touch any other field."""
    try:
        mapping = StrategySymbolMapping.query.get(mapping_id)
        if not mapping:
            return None
        mapping.is_active = not mapping.is_active
        db_session.commit()
        return mapping
    except Exception as e:
        logger.exception(f"Error toggling symbol mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return None


def delete_symbol_mapping(mapping_id):
    """Delete a symbol mapping"""
    try:
        mapping = StrategySymbolMapping.query.get(mapping_id)
        if mapping:
            db_session.delete(mapping)
            db_session.commit()
            return True
        return False
    except Exception as e:
        logger.exception(f"Error deleting symbol mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return False


def set_mapping_action_override(mapping_id, action, override: dict | None):
    """Set (or clear, if override is None/{}) the per-action override JSON
    for one of a mapping's four actions (BUY/SELL/SHORT/EXIT). `override`
    keys are any of quantity/product/order_type/broker -- omitted keys fall
    back to the linked execution profile (or the mapping's own defaults)."""
    try:
        mapping = StrategySymbolMapping.query.get(mapping_id)
        if not mapping:
            return False
        column_name = StrategySymbolMapping._OVERRIDE_COLUMNS.get((action or "").upper())
        if not column_name:
            logger.warning(f"set_mapping_action_override: invalid action '{action}'")
            return False
        setattr(mapping, column_name, json.dumps(override) if override else None)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error setting action override for mapping {mapping_id}: {str(e)}")
        db_session.rollback()
        return False


def create_execution_profile(user_id, name, broker=None, product="MIS", order_type="MARKET", default_quantity=1):
    """Create a reusable execution profile."""
    try:
        profile = ExecutionProfile(
            user_id=user_id,
            name=name,
            broker=broker,
            product=product,
            order_type=order_type,
            default_quantity=default_quantity,
        )
        db_session.add(profile)
        db_session.commit()
        return profile
    except Exception as e:
        logger.exception(f"Error creating execution profile: {str(e)}")
        db_session.rollback()
        return None


def get_execution_profiles(user_id):
    """Get all execution profiles for a user."""
    try:
        return ExecutionProfile.query.filter_by(user_id=user_id).order_by(ExecutionProfile.name).all()
    except Exception as e:
        logger.exception(f"Error getting execution profiles for {user_id}: {str(e)}")
        return []


def update_execution_profile(profile_id, **fields):
    """Update an execution profile's fields (broker/product/order_type/
    default_quantity/name). Every instrument referencing this profile picks
    up the change automatically via ExecutionProfile.resolve_execution()."""
    try:
        profile = ExecutionProfile.query.get(profile_id)
        if not profile:
            return None
        for key in ("name", "broker", "product", "order_type", "default_quantity"):
            if key in fields:
                setattr(profile, key, fields[key])
        db_session.commit()
        return profile
    except Exception as e:
        logger.exception(f"Error updating execution profile {profile_id}: {str(e)}")
        db_session.rollback()
        return None


def delete_execution_profile(profile_id):
    """Delete an execution profile. Mappings referencing it fall back to
    their own quantity/product_type (execution_profile_id is nullable)."""
    try:
        profile = ExecutionProfile.query.get(profile_id)
        if not profile:
            return False
        StrategySymbolMapping.query.filter_by(execution_profile_id=profile_id).update(
            {"execution_profile_id": None}
        )
        db_session.delete(profile)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error deleting execution profile {profile_id}: {str(e)}")
        db_session.rollback()
        return False


def clear_strategy_cache():
    """
    Clear all strategy caches.
    Called on logout/session expiry to ensure fresh data on next login.
    """
    _strategy_webhook_cache.clear()
    _user_strategies_cache.clear()
    logger.info("Strategy cache cleared")


# =============================================================================
# Deployment helpers (moved from database/deployment_db.py -- see the
# StrategyVersion/Deployment class docstrings above for why)
# =============================================================================


def create_strategy_version(strategy_id: int, config: dict) -> StrategyVersion:
    """Create a new version for a strategy template"""
    try:
        # Determine next version number
        last_version = db_session.query(func.max(StrategyVersion.version)).filter_by(strategy_id=strategy_id).scalar()
        next_ver = (last_version or 0) + 1

        ver = StrategyVersion(
            strategy_id=strategy_id,
            version=next_ver,
            config=json.dumps(config)
        )
        db_session.add(ver)
        db_session.commit()
        return ver
    except Exception as e:
        logger.exception(f"Error creating strategy version: {e}")
        db_session.rollback()
        return None


def create_deployment(deployment_data: dict) -> Deployment:
    """Create a new Deployment instance"""
    try:
        # Convert JSON fields
        if "conditions_tree" in deployment_data and not isinstance(deployment_data["conditions_tree"], str):
            deployment_data["conditions_tree"] = json.dumps(deployment_data["conditions_tree"])
        if "risk_params" in deployment_data and not isinstance(deployment_data["risk_params"], str):
            deployment_data["risk_params"] = json.dumps(deployment_data["risk_params"])
        if "metrics" in deployment_data and not isinstance(deployment_data["metrics"], str):
            deployment_data["metrics"] = json.dumps(deployment_data["metrics"])
        if "events_timeline" in deployment_data and not isinstance(deployment_data["events_timeline"], str):
            deployment_data["events_timeline"] = json.dumps(deployment_data["events_timeline"])
        if "brokers" in deployment_data and not isinstance(deployment_data["brokers"], str):
            brokers_list = deployment_data["brokers"]
            deployment_data["brokers"] = json.dumps(brokers_list)
            # Keep the legacy single `broker` column in sync (brokers[0])
            # so any older reader that only knows that column still works.
            if brokers_list and not deployment_data.get("broker"):
                deployment_data["broker"] = brokers_list[0]

        deployment = Deployment(**deployment_data)
        db_session.add(deployment)
        db_session.commit()
        return deployment
    except Exception as e:
        logger.exception(f"Error creating deployment: {e}")
        db_session.rollback()
        return None


def get_deployment(deployment_id: int) -> Deployment:
    """Fetch a deployment by its ID"""
    try:
        return Deployment.query.get(deployment_id)
    except Exception as e:
        logger.error(f"Error getting deployment {deployment_id}: {e}")
        return None


def get_user_deployments(user_id: str) -> list[Deployment]:
    """Fetch all deployment instances for a specific user"""
    try:
        return Deployment.query.filter_by(user_id=user_id).all()
    except Exception as e:
        logger.error(f"Error getting deployments for user {user_id}: {e}")
        return []


# Per-deployment in-process lock guarding the claim below. NOT a
# .with_for_update() row lock: this project runs single-worker Gunicorn/
# eventlet (see CLAUDE.md), and SQLite's dialect silently ignores
# SELECT...FOR UPDATE entirely (it has no row-level locking concept) --
# combined with NullPool (every query gets its own fresh connection, no
# shared transaction to actually block on) that made .with_for_update()
# here a complete no-op, which a real concurrent-thread test caught: 9 of
# 10 simultaneous callers still won the "claim" instead of exactly 1. A
# real mutex is required for SQLite; this mirrors the existing convention
# in services/place_order_service.py's `_recent_order_fingerprints_lock`
# (an in-process dict+lock, safe under the same single-worker model).
# Locks are created lazily per deployment_id and never removed -- a small,
# bounded number of long-lived Lock objects (one per ever-seen deployment
# id) is a negligible, acceptable memory cost for the lifetime of the
# process, same tradeoff already accepted for the fingerprint dedup dict.
_deployment_claim_locks: dict[int, threading.Lock] = {}
_deployment_claim_locks_guard = threading.Lock()


def _get_deployment_claim_lock(deployment_id: int) -> threading.Lock:
    with _deployment_claim_locks_guard:
        lock = _deployment_claim_locks.get(deployment_id)
        if lock is None:
            lock = threading.Lock()
            _deployment_claim_locks[deployment_id] = lock
        return lock


def try_claim_deployment_for_entry(deployment_id: int, signal_action: str, log_event: str) -> bool:
    """Atomically check-and-transition a deployment from 'Waiting' to
    'Entering' for an entry signal. Returns True if THIS call won the claim
    (caller should proceed to place orders), False if the deployment was
    not in 'Waiting' (already being handled, or in some other state).

    This exists because services/signal_engine.py's webhook dispatch runs
    on an 8-worker thread pool (see _dispatch's ThreadPoolExecutor), so two
    near-simultaneous deliveries for the SAME deployment (a genuine
    TradingView retry, or a strategy condition that legitimately re-fires)
    could previously both read dep.status == "Waiting" via a plain
    Deployment.query.filter(...) before either thread's later call to
    update_deployment_status() committed "Entering" -- a classic
    check-then-act race with no lock between the read and the write,
    letting both threads place a full set of orders for what should be one
    signal. A per-deployment threading.Lock (see above) makes the read
    (status == "Waiting") and the write (status = "Entering", committed)
    atomic with respect to every other thread in this same process --
    exactly the guarantee needed under the single-worker deployment model.
    """
    lock = _get_deployment_claim_lock(deployment_id)
    with lock:
        try:
            deployment = db_session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment or deployment.status != "Waiting":
                return False

            deployment.status = "Entering"
            try:
                timeline = json.loads(deployment.events_timeline) if deployment.events_timeline else []
            except Exception:
                timeline = []
            from datetime import datetime

            timeline.append({"time": datetime.now().strftime("%H:%M"), "event": log_event})
            deployment.events_timeline = json.dumps(timeline)

            db_session.commit()
            return True
        except Exception as e:
            logger.exception(
                f"Error claiming deployment {deployment_id} for entry signal '{signal_action}': {e}"
            )
            db_session.rollback()
            return False


def update_deployment_status(deployment_id: int, status: str, log_event: str = None) -> bool:
    """Transition a deployment's state and append a log event if provided"""
    try:
        deployment = Deployment.query.get(deployment_id)
        if not deployment:
            return False

        deployment.status = status

        if log_event:
            try:
                timeline = json.loads(deployment.events_timeline) if deployment.events_timeline else []
            except Exception:
                timeline = []

            # Append new event
            from datetime import datetime
            timeline.append({
                "time": datetime.now().strftime("%H:%M"),
                "event": log_event
            })
            deployment.events_timeline = json.dumps(timeline)

        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error transitioning status of deployment {deployment_id}: {e}")
        db_session.rollback()
        return False


def set_deployment_last_trade(deployment_id: int) -> bool:
    """Record that a deployment just placed an order. This is the ONLY
    thing the cooldown risk check should measure elapsed time against --
    call this at the moment an order is actually sent, never on a
    heartbeat/status-only update (see the model's last_trade_at docstring)."""
    try:
        from datetime import datetime

        deployment = Deployment.query.get(deployment_id)
        if not deployment:
            return False
        deployment.last_trade_at = datetime.utcnow()
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error recording last trade time for deployment {deployment_id}: {e}")
        db_session.rollback()
        return False


def append_deployment_heartbeat(deployment_id: int, event: str) -> bool:
    """Append a timeline entry WITHOUT changing status -- unlike
    update_deployment_status, this is for the "still evaluating, condition
    not yet met" case. Before this existed, a deployment sitting in
    "Waiting" produced zero visible trace between its creation event and
    whatever eventually triggers it (or never triggers it), making it
    indistinguishable from a silently-dead evaluation loop. Called on a
    throttled cadence from services/deployment_service.py, not every
    5-second poll cycle, to avoid flooding the timeline with near-
    identical entries."""
    try:
        from datetime import datetime

        deployment = Deployment.query.get(deployment_id)
        if not deployment:
            return False

        try:
            timeline = json.loads(deployment.events_timeline) if deployment.events_timeline else []
        except Exception:
            timeline = []

        timeline.append({"time": datetime.now().strftime("%H:%M"), "event": event})
        # Cap timeline length -- a long-waiting deployment's heartbeat
        # would otherwise grow this column unboundedly over days/weeks.
        deployment.events_timeline = json.dumps(timeline[-100:])
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error appending heartbeat for deployment {deployment_id}: {e}")
        db_session.rollback()
        return False


def delete_deployment(deployment_id: int) -> bool:
    """Permanently delete a deployment row. Callers (blueprints/deployments.py)
    must refuse to delete a deployment that's actively managing a real
    position (status "Managing"/"Entering") -- deleting it would orphan that
    position from any UI/tracking without actually closing it at the broker.
    Safe for Draft/Waiting/Paused/Stopped/Completed/Error deployments, which
    have no live broker-side state depending on the row's continued
    existence."""
    try:
        deployment = Deployment.query.get(deployment_id)
        if not deployment:
            return False
        db_session.delete(deployment)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error deleting deployment {deployment_id}: {e}")
        db_session.rollback()
        return False


# =============================================================================
# LegGroup / Leg -- stateful multi-leg webhook rotation (execution_model ==
# "stateful"). See services/signal_engine.py's _process_leg_group_webhook_signal
# for how these are consumed at signal time.
# =============================================================================


def get_leg_groups(strategy_id):
    """All leg groups for a strategy, each with its legs eager-loadable via
    the .legs relationship (used by to_dict())."""
    try:
        return LegGroup.query.filter_by(strategy_id=strategy_id).all()
    except Exception as e:
        logger.exception(f"Error getting leg groups for strategy {strategy_id}: {str(e)}")
        return []


def get_leg_group(leg_group_id):
    try:
        return LegGroup.query.get(leg_group_id)
    except Exception as e:
        logger.exception(f"Error getting leg group {leg_group_id}: {str(e)}")
        return None


def _build_leg(group_id, leg_data, sort_order):
    """Shared Leg-row construction for create_leg_group/update_leg_group.
    EXIT legs carry no instrument config (order_side/exchange/quantity/
    product_type all None) -- see Leg's class docstring -- so those fields
    are read with .get() rather than required-key indexing, unlike every
    other (tradable) entry_signal."""
    entry_signal = leg_data["entry_signal"].upper()
    order_side = leg_data.get("order_side")
    condition = leg_data.get("condition")
    return Leg(
        leg_group_id=group_id,
        label=leg_data["label"],
        entry_signal=entry_signal,
        order_side=order_side.upper() if order_side else None,
        instrument_type=leg_data.get("instrument_type") or ("EQ" if entry_signal != "EXIT" else None),
        exchange=leg_data.get("exchange"),
        underlying=leg_data.get("underlying"),
        expiry_type=leg_data.get("expiry_type"),
        option_type=leg_data.get("option_type"),
        strike_offset=leg_data.get("strike_offset"),
        strike_selection_mode=leg_data.get("strike_selection_mode"),
        strike_target_value=leg_data.get("strike_target_value"),
        instrument=leg_data.get("instrument"),
        quantity=leg_data.get("quantity"),
        product_type=leg_data.get("product_type"),
        condition=json.dumps(condition) if condition else None,
        sort_order=leg_data.get("sort_order", sort_order),
    )


def create_leg_group(strategy_id, name, legs):
    """Create a LegGroup and its Leg rows in one transaction. `legs` is a
    list of dicts with keys matching Leg's columns (label, entry_signal,
    order_side, instrument_type, exchange, underlying, expiry_type,
    option_type, strike_offset, instrument, quantity, product_type,
    condition). sort_order defaults to the list index when not provided.
    Starts flat (current_leg_id NULL) -- a new group never assumes a leg is
    already open."""
    try:
        group = LegGroup(strategy_id=strategy_id, name=name)
        db_session.add(group)
        db_session.flush()  # assign group.id before creating legs

        for i, leg_data in enumerate(legs):
            db_session.add(_build_leg(group.id, leg_data, i))

        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error creating leg group for strategy {strategy_id}: {str(e)}")
        db_session.rollback()
        return None


def update_leg_group(leg_group_id, name=None, legs=None):
    """Update a group's name and/or replace its legs entirely (delete +
    recreate under the same group id) -- mirrors bulk_add_symbol_mappings'
    replace-not-merge semantics for bulk config. Replacing legs resets
    current_leg_id to NULL (flat): the old open leg no longer has a
    well-defined identity once the leg list changes, so treating the group
    as flat again is the only safe default -- the alternative (silently
    guessing which new leg corresponds to the old open one) risks placing a
    wrong-side order on the next signal."""
    try:
        group = LegGroup.query.get(leg_group_id)
        if not group:
            return None

        if name is not None:
            group.name = name

        if legs is not None:
            for leg in list(group.legs):
                db_session.delete(leg)
            group.current_leg_id = None
            db_session.flush()

            for i, leg_data in enumerate(legs):
                db_session.add(_build_leg(group.id, leg_data, i))

        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error updating leg group {leg_group_id}: {str(e)}")
        db_session.rollback()
        return None


def toggle_leg_group_active(leg_group_id):
    """Flip is_active (pause/resume) for one leg group. Pausing does NOT
    close whatever leg is currently open -- it only stops the group from
    reacting to further signals, matching toggle_symbol_mapping_active's
    "pause reacting, don't force-close" semantics."""
    try:
        group = LegGroup.query.get(leg_group_id)
        if not group:
            return None
        group.is_active = not group.is_active
        db_session.commit()
        return group
    except Exception as e:
        logger.exception(f"Error toggling leg group {leg_group_id}: {str(e)}")
        db_session.rollback()
        return None


def delete_leg_group(leg_group_id):
    try:
        group = LegGroup.query.get(leg_group_id)
        if not group:
            return False
        group.current_leg_id = None  # clear FK before cascade-deleting legs
        db_session.flush()
        db_session.delete(group)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error deleting leg group {leg_group_id}: {str(e)}")
        db_session.rollback()
        return False


def resolve_leg_rotation(leg_group_id, signal: str):
    """Read-only: given an incoming signal, resolve what should happen to
    this leg group WITHOUT placing any orders or changing state yet. Called
    by signal_engine.py before it talks to any broker, so order placement
    and state commit can be sequenced correctly (exit order, then entry
    order, then commit_leg_rotation -- never commit state before the orders
    it describes have actually been placed).

    Returns a dict:
      {"action": "no_target"} -- no leg in this group reacts to this signal
      {"action": "noop", "leg": <Leg>} -- signal's target leg is already open
      {"action": "open", "target_leg": <Leg>} -- flat -> open target (1 order)
      {"action": "flip", "current_leg": <Leg>, "target_leg": <Leg>} -- close
        current, open target (2 orders, exit first)
      {"action": "exit", "current_leg": <Leg>} -- an EXIT leg's signal
        arrived and a leg is open: close it, go flat (1 order, no target
        to open -- EXIT legs have no instrument, see Leg's class docstring)
    Returns None if the group doesn't exist.
    """
    try:
        group = LegGroup.query.get(leg_group_id)
        if not group:
            return None

        signal = (signal or "").upper()
        target_leg = next((leg for leg in group.legs if leg.entry_signal == signal), None)
        if not target_leg:
            return {"action": "no_target"}

        if target_leg.entry_signal == "EXIT":
            if group.current_leg_id is None:
                return {"action": "no_target"}  # already flat -- nothing to exit
            current_leg = Leg.query.get(group.current_leg_id)
            if not current_leg:
                return {"action": "no_target"}  # stale FK -- treat as already flat
            return {"action": "exit", "current_leg": current_leg}

        if group.current_leg_id is None:
            return {"action": "open", "target_leg": target_leg}

        if group.current_leg_id == target_leg.id:
            return {"action": "noop", "leg": target_leg}

        current_leg = Leg.query.get(group.current_leg_id)
        if not current_leg:
            # Stale FK (current leg was deleted out from under the group) --
            # treat as flat rather than crash; the next signal opens fresh.
            return {"action": "open", "target_leg": target_leg}

        return {"action": "flip", "current_leg": current_leg, "target_leg": target_leg}
    except Exception as e:
        logger.exception(f"Error resolving leg rotation for group {leg_group_id}: {e}")
        return None


def commit_leg_rotation(leg_group_id, new_current_leg_id, log_event: str = None):
    """Atomically set current_leg_id after the orders resolve_leg_rotation
    described have actually been placed. Mirrors update_deployment_status's
    "transition + log" shape -- events_timeline is capped at 100 entries the
    same way append_deployment_heartbeat caps Deployment's."""
    try:
        from datetime import datetime

        group = LegGroup.query.get(leg_group_id)
        if not group:
            return False

        group.current_leg_id = new_current_leg_id

        if log_event:
            try:
                timeline = json.loads(group.events_timeline) if group.events_timeline else []
            except Exception:
                timeline = []
            timeline.append({"time": datetime.now().strftime("%H:%M"), "event": log_event})
            group.events_timeline = json.dumps(timeline[-100:])

        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error committing leg rotation for group {leg_group_id}: {e}")
        db_session.rollback()
        return False
