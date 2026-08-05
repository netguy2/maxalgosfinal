import os
from typing import List

from sqlalchemy import Column, Float, Index, Integer, Sequence, String, and_, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)


def _get_active_model_and_session():
    try:
        from database.token_db_enhanced import get_cache
        cache = get_cache()
        active_broker = cache.active_broker
    except Exception:
        active_broker = None

    if active_broker == "sharekhan":
        try:
            from broker.sharekhan.database.master_contract_db import SymToken as SK_SymToken, db_session as SK_db_session
            return SK_SymToken, SK_db_session
        except Exception:
            pass

    return SymToken, db_session


def _escape_like(term: str) -> str:
    """Escape LIKE wildcard characters to prevent unintended broad matching."""
    return term.replace("%", r"\%").replace("_", r"\_")

SYMBOL_DATABASE_URL = os.getenv("SYMBOL_DATABASE_URL") or os.getenv("DATABASE_URL")
engine = create_db_engine(SYMBOL_DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)
    contract_value = Column(Float)

    # Composite indices for improved search performance
    __table_args__ = (
        Index("idx_symbol_exchange", "symbol", "exchange"),
        Index("idx_symbol_name", "symbol", "name"),
        Index("idx_brsymbol_exchange", "brsymbol", "exchange"),
    )


def enhanced_search_symbols(
    query: str | None, exchange: str | None = None, limit: int | None = None
) -> list[SymToken]:
    """
    Enhanced search function that searches across multiple fields
    and supports partial matching with multiple terms.

    If both query and exchange are empty, returns no results to avoid full-table scans.
    If query is empty/None but exchange is provided, returns all rows for that exchange
    (subject to limit) — useful for "show me everything in NSE" workflows.

    Args:
        query: Search query string (may be None/empty for exchange-only search)
        exchange: Exchange to filter by
        limit: Optional cap on number of results (None = no cap)

    Returns:
        List[SymToken]: List of matching SymToken objects
    """
    SymToken, db_session = _get_active_model_and_session()
    try:
        # Split the query into terms and clean them
        terms = [term.strip().upper() for term in (query or "").split() if term.strip()]

        # Refuse to scan the full table without any filter — caller must scope by exchange
        # if there is no query.
        if not terms and not exchange:
            return []

        # Base query
        base_query = SymToken.query

        # If exchange is specified, filter by it
        if exchange:
            base_query = base_query.filter(SymToken.exchange == exchange)

        # Create conditions for each term
        all_conditions = []
        for term in terms:
            safe_term = _escape_like(term)
            # Number detection for more accurate strike price and token searches
            try:
                num_term = float(term)
                term_conditions = or_(
                    SymToken.symbol.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.brsymbol.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.name.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.token.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.strike == num_term,
                )
            except ValueError:
                term_conditions = or_(
                    SymToken.symbol.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.brsymbol.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.name.ilike(f"{safe_term}%", escape="\\"),
                    SymToken.token.ilike(f"{safe_term}%", escape="\\"),
                )
            all_conditions.append(term_conditions)

        # Combine all conditions with AND
        if all_conditions:
            final_query = base_query.filter(and_(*all_conditions))
        else:
            final_query = base_query

        # Execute query — fetch candidate pool for relevance sorting
        fetch_limit = (limit * 5) if (limit and limit > 0) else 500
        results = final_query.limit(fetch_limit).all()

        # Fallback for FUT/CE/PE-shaped queries that came back empty: users
        # typing a derivative symbol from memory very often omit the 2-digit
        # expiry year (e.g. "NIFTY28JULFUT" for the real "NIFTY28JUL26FUT",
        # or "NIFTY24500CE" for "NIFTY28JUL2624500CE"), which a prefix match
        # can never find since the year sits in the MIDDLE of the real
        # symbol, not adjacent to where the user's shorter query ends.
        if not results and len(terms) == 1:
            collapsed = terms[0]
            for suffix in ("FUT", "CE", "PE"):
                if collapsed.endswith(suffix) and collapsed.isalnum():
                    base = collapsed[: -len(suffix)]
                    if not base:
                        break
                    safe_base = _escape_like(base)
                    safe_suffix = _escape_like(suffix)
                    fallback_query = base_query.filter(
                        or_(
                            SymToken.symbol.ilike(f"{safe_base}%{safe_suffix}", escape="\\"),
                            SymToken.brsymbol.ilike(f"{safe_base}%{safe_suffix}", escape="\\"),
                        )
                    )
                    results = fallback_query.limit(fetch_limit).all()
                    break

        # Relevance sorting key to ensure exact matches and symbol prefix matches
        # rank above name/description matches (e.g. 'NIFTY' ranks above mutual funds/ETFs
        # like 'MIRAEAMC' whose name happens to contain 'Nifty').
        raw_query = (query or "").strip().upper()

        def _relevance_score(item: SymToken) -> tuple:
            sym = (item.symbol or "").upper()
            brsym = (item.brsymbol or "").upper()
            name = (item.name or "").upper()
            ex = (item.exchange or "").upper()

            # Ignore placeholder NA symbols
            if sym == "NA" or not sym:
                return (99, 99, sym)

            # Exact match on symbol or brsymbol -> Rank 0
            if sym == raw_query or brsym == raw_query:
                return (0, len(sym), ex != "NSE_INDEX", sym)

            # Symbol or brsymbol starts with query -> Rank 1
            if sym.startswith(raw_query) or brsym.startswith(raw_query):
                return (1, len(sym), ex != "NSE_INDEX", sym)

            # Main index or equity contains query -> Rank 2
            if (raw_query in sym or raw_query in brsym) and ex in ("NSE", "BSE", "NSE_INDEX", "NFO"):
                return (2, len(sym), sym)

            # Any symbol contains query -> Rank 3
            if raw_query in sym or raw_query in brsym:
                return (3, len(sym), sym)

            # Name starts with query -> Rank 4
            if name.startswith(raw_query):
                return (4, len(name), sym)

            # Fallback (name contains query) -> Rank 5
            return (5, len(name), sym)

        results.sort(key=_relevance_score)
        # Filter out any rank 99 placeholders if real results are available
        valid_results = [r for r in results if (r.symbol or "").upper() != "NA"]
        final_results = valid_results if valid_results else results
        if limit is not None and limit > 0:
            return final_results[:limit]
        return final_results

    except Exception as e:
        logger.error(f"Error in enhanced search: {e}")
        try:
            from database.token_db_enhanced import fno_search_symbols
            cached_rows = fno_search_symbols(query=query, exchange=exchange, limit=limit or 100)
            fallback_results = []
            for r in cached_rows:
                st = SymToken()
                st.symbol = r.get("symbol")
                st.brsymbol = r.get("brsymbol") or r.get("symbol")
                st.name = r.get("name") or r.get("symbol")
                st.exchange = r.get("exchange")
                st.token = str(r.get("token") or "")
                st.lotsize = r.get("lotsize") or 1
                st.tick_size = r.get("tick_size") or 0.05
                st.instrumenttype = r.get("instrumenttype") or "EQ"
                fallback_results.append(st)
            return fallback_results
        except Exception as e2:
            logger.error(f"Fallback search also failed: {e2}")
            return []


def fno_search_symbols_db(
    query: str = None,
    exchange: str = None,
    expiry: str = None,
    instrumenttype: str = None,  # "FUT", "CE", or "PE"
    strike_min: float = None,
    strike_max: float = None,
    underlying: str = None,
    limit: int = 10000,
) -> list[dict]:
    """
    FNO-specific search function using direct database queries.
    This is the fallback when cache is not available.

    Can search with just filters (no query required) - useful for:
    - "Show all NIFTY futures" (underlying=NIFTY, instrumenttype=FUT)
    - "Show all weekly expiry options" (expiry=26-DEC-24)

    Args:
        query (str, optional): Search query string (optional if filters are provided)
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)
        expiry (str, optional): Expiry date filter (e.g., "26-DEC-24")
        instrumenttype (str, optional): "FUT" for futures, "CE" for calls, "PE" for puts
        strike_min (float, optional): Minimum strike price
        strike_max (float, optional): Maximum strike price
        underlying (str, optional): Underlying symbol name (e.g., "NIFTY")
        limit (int, optional): Maximum results to return (default 500)

    Returns:
        List[dict]: List of matching symbol dictionaries
    """
    SymToken, db_session = _get_active_model_and_session()
    try:
        # Base query
        base_query = SymToken.query

        # Filter by exchange
        if exchange:
            base_query = base_query.filter(SymToken.exchange == exchange)

        # Filter by underlying name
        if underlying:
            base_query = base_query.filter(SymToken.name.ilike(underlying.strip().upper()))

        # Filter by expiry date
        if expiry:
            base_query = base_query.filter(SymToken.expiry == expiry.strip())

        # Filter by instrument type (FUT, CE, PE) - based on symbol suffix
        if instrumenttype:
            inst_type = instrumenttype.strip().upper()
            if inst_type == "FUT":
                # Symbol ends with FUT (e.g., NIFTY26DEC24FUT)
                base_query = base_query.filter(SymToken.symbol.ilike("%FUT"))
            elif inst_type == "CE":
                # Symbol ends with CE (e.g., NIFTY26DEC2424000CE)
                base_query = base_query.filter(SymToken.symbol.ilike("%CE"))
            elif inst_type == "PE":
                # Symbol ends with PE (e.g., NIFTY26DEC2424000PE)
                base_query = base_query.filter(SymToken.symbol.ilike("%PE"))

        # Filter by strike price range (for options)
        if strike_min is not None:
            base_query = base_query.filter(SymToken.strike >= strike_min)
        if strike_max is not None:
            base_query = base_query.filter(SymToken.strike <= strike_max)

        # Create conditions for each search term (if query provided)
        primary_term = None
        if query:
            terms = [term.strip().upper() for term in query.split() if term.strip()]
            primary_term = terms[0] if terms else None
            all_conditions = []
            for term in terms:
                safe_term = _escape_like(term)
                try:
                    num_term = float(term)
                    term_conditions = or_(
                        SymToken.symbol.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.brsymbol.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.name.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.token.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.strike == num_term,
                    )
                except ValueError:
                    term_conditions = or_(
                        SymToken.symbol.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.brsymbol.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.name.ilike(f"%{safe_term}%", escape="\\"),
                        SymToken.token.ilike(f"%{safe_term}%", escape="\\"),
                    )
                all_conditions.append(term_conditions)

            # Combine all conditions with AND
            if all_conditions:
                base_query = base_query.filter(and_(*all_conditions))

        # Apply database-level ordering and limit for performance
        # Order by symbol for consistent results
        base_query = base_query.order_by(SymToken.symbol)

        # Apply limit at database level - critical for performance with large datasets
        if limit:
            base_query = base_query.limit(limit)

        # Execute query with limit already applied
        results = base_query.all()

        # Import freeze qty function (uses in-memory cache, fast)
        from database.qty_freeze_db import get_freeze_qty_for_option

        # Convert to dictionaries - now only processing limited results
        results_dicts = [
            {
                "symbol": r.symbol,
                "brsymbol": r.brsymbol,
                "name": r.name,
                "exchange": r.exchange,
                "brexchange": r.brexchange,
                "token": r.token,
                "expiry": r.expiry,
                "strike": r.strike,
                "lotsize": r.lotsize,
                "instrumenttype": r.instrumenttype,
                "tick_size": r.tick_size,
                "freeze_qty": get_freeze_qty_for_option(r.symbol, r.exchange),
            }
            for r in results
        ]

        # Only apply Python-level sorting if there's a search query
        # For filter-only queries (FNO chain discovery), DB ordering is sufficient
        if primary_term:

            def sort_key(r):
                """Sort results by relevance: exact match, prefix match, then alphabetical."""
                name = r["name"] or ""
                symbol = r["symbol"] or ""
                # Priority 1: Exact match on name/underlying
                name_exact = 0 if name.upper() == primary_term else 1
                # Priority 2: Name starts with search term
                name_starts = 0 if name.upper().startswith(primary_term) else 1
                # Priority 3: Symbol starts with search term
                symbol_starts = 0 if symbol.upper().startswith(primary_term) else 1
                # Priority 4: Alphabetical by symbol
                return (name_exact, name_starts, symbol_starts, symbol)

            results_dicts.sort(key=sort_key)

        return results_dicts

    except Exception as e:
        logger.exception(f"Error in FNO search: {str(e)}")
        return []


def get_distinct_expiries(exchange: str = None, underlying: str = None) -> list[str]:
    """
    Get distinct expiry dates for FNO symbols.

    Args:
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)
        underlying (str, optional): Underlying symbol name (e.g., "NIFTY")

    Returns:
        List[str]: List of distinct expiry dates sorted chronologically
    """
    SymToken, db_session = _get_active_model_and_session()
    try:
        from datetime import datetime

        from sqlalchemy import distinct

        query = db_session.query(distinct(SymToken.expiry))

        if exchange:
            query = query.filter(SymToken.exchange == exchange)

        if underlying:
            query = query.filter(SymToken.name.ilike(underlying.strip().upper()))

        # Only get non-null expiries
        query = query.filter(SymToken.expiry.isnot(None))
        query = query.filter(SymToken.expiry != "")

        results = query.all()
        expiries = [r[0] for r in results if r[0]]

        # Sort expiries chronologically
        def parse_expiry(exp_str):
            """Parse an expiry date string into a datetime for chronological sorting."""
            try:
                return datetime.strptime(exp_str, "%d-%b-%y")
            except ValueError:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%Y")
                except ValueError:
                    return datetime.max

        expiries.sort(key=parse_expiry)
        return expiries

    except Exception as e:
        logger.exception(f"Error fetching distinct expiries: {str(e)}")
        return []


_underlyings_cache = {}
_last_sym_count = None
_last_active_broker = None


def get_distinct_underlyings(exchange: str = None) -> list[str]:
    """
    Get distinct underlying names for FNO symbols.

    Args:
        exchange (str, optional): Exchange to filter by (NFO, BFO, MCX, CDS)

    Returns:
        List[str]: List of distinct underlying names sorted alphabetically
    """
    global _last_sym_count, _underlyings_cache, _last_active_broker
    SymToken, db_session = _get_active_model_and_session()

    try:
        from database.token_db_enhanced import get_cache
        active_broker = get_cache().active_broker
    except Exception:
        active_broker = None

    try:
        current_count = SymToken.query.count()
        if current_count != _last_sym_count or active_broker != _last_active_broker:
            _underlyings_cache.clear()
            _last_sym_count = current_count
            _last_active_broker = active_broker

        cache_key = exchange or "all"
        if cache_key in _underlyings_cache:
            return _underlyings_cache[cache_key]

        from sqlalchemy import distinct
        import re

        # Regex pattern to extract underlying from Max Algos symbol format
        UNDERLYING_PATTERN = re.compile(
            r"^([A-Z0-9_]+?)"
            r"(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})",
            re.IGNORECASE,
        )

        if exchange in ("NFO", "BFO", "MCX", "CDS", "NCO"):
            # For FNO exchanges, we extract the underlying from the symbol column
            # because the name column might be null or contain misclassified values.
            query = db_session.query(SymToken.symbol).filter(SymToken.symbol.isnot(None))
            if exchange:
                query = query.filter(SymToken.exchange == exchange)
            
            results = query.all()
            underlyings_set = set()
            for r in results:
                symbol = r[0]
                match = UNDERLYING_PATTERN.match(symbol)
                if match:
                    underlyings_set.add(match.group(1).upper())
                else:
                    # Fallback to name or first part of symbol
                    parts = symbol.split("-")
                    if parts:
                        underlyings_set.add(parts[0].upper())
            
            # Filter out any test/invalid underlyings
            underlyings = sorted([u for u in underlyings_set if u and "TEST" not in u])
        else:
            # For non-FNO exchanges (equity etc.), use the distinct name column
            query = db_session.query(distinct(SymToken.name))
            if exchange:
                query = query.filter(SymToken.exchange == exchange)
            query = query.filter(SymToken.name.isnot(None))
            query = query.filter(SymToken.name != "")
            
            results = query.all()
            underlyings = sorted([r[0] for r in results if r[0]])

            _underlyings_cache[cache_key] = underlyings
            return underlyings

    except Exception as e:
        logger.exception(f"Error fetching distinct underlyings: {str(e)}")
        return []


def _seed_default_symtokens():
    """Seed symtoken database with standard market symbols if table is empty"""
    SymToken, db_session = _get_active_model_and_session()
    try:
        if SymToken.query.first() is not None:
            return
        
        from database.token_db_enhanced import FALLBACK_INDICES
        items_to_add = []
        token_counter = 100000

        # Seed indices
        for (sym, exch), (tok, brex, name, brsym, inst, lot, tick) in FALLBACK_INDICES.items():
            st = SymToken(
                symbol=sym,
                brsymbol=brsym,
                name=name,
                exchange=exch,
                brexchange=brex,
                token=tok,
                instrumenttype=inst,
                lotsize=lot,
                tick_size=tick
            )
            items_to_add.append(st)

        # Seed equities and commodities list
        DEFAULT_SEEDS = [
            ("ADANIENT", "ADANI ENTERPRISES", "NSE"),
            ("ADANIPORTS", "ADANI PORTS", "NSE"),
            ("ADANIGREEN", "ADANI GREEN ENERGY", "NSE"),
            ("ADANIPOWER", "ADANI POWER", "NSE"),
            ("ATGL", "ADANI TOTAL GAS", "NSE"),
            ("AWL", "ADANI WILMAR", "NSE"),
            ("APOLLOHOSP", "APOLLO HOSPITALS", "NSE"),
            ("ASIANPAINT", "ASIAN PAINTS", "NSE"),
            ("AXISBANK", "AXIS BANK", "NSE"),
            ("BAJAJ-AUTO", "BAJAJ AUTO", "NSE"),
            ("BAJFINANCE", "BAJAJ FINANCE", "NSE"),
            ("BAJAJFINSV", "BAJAJ FINSERV", "NSE"),
            ("BEL", "BHARAT ELECTRONICS", "NSE"),
            ("BPCL", "BHARAT PETROLEUM", "NSE"),
            ("BHARTIARTL", "BHARTI AIRTEL", "NSE"),
            ("BRITANNIA", "BRITANNIA INDUSTRIES", "NSE"),
            ("CANBK", "CANARA BANK", "NSE"),
            ("CIPLA", "CIPLA", "NSE"),
            ("COALINDIA", "COAL INDIA", "NSE"),
            ("DIVISLAB", "DIVIS LABORATORIES", "NSE"),
            ("DLF", "DLF", "NSE"),
            ("DRREDDY", "DR REDDYS LABORATORIES", "NSE"),
            ("EICHERMOT", "EICHER MOTORS", "NSE"),
            ("GAIL", "GAIL INDIA", "NSE"),
            ("GRASIM", "GRASIM INDUSTRIES", "NSE"),
            ("HAL", "HINDUSTAN AERONAUTICS", "NSE"),
            ("HCLTECH", "HCL TECHNOLOGIES", "NSE"),
            ("HDFCBANK", "HDFC BANK", "NSE"),
            ("HDFCLIFE", "HDFC LIFE INSURANCE", "NSE"),
            ("HEROMOTOCO", "HERO MOTOCORP", "NSE"),
            ("HINDALCO", "HINDALCO INDUSTRIES", "NSE"),
            ("HINDUNILVR", "HINDUSTAN UNILEVER", "NSE"),
            ("ICICIBANK", "ICICI BANK", "NSE"),
            ("INDUSINDBK", "INDUSIND BANK", "NSE"),
            ("INFY", "INFOSYS", "NSE"),
            ("IOC", "INDIAN OIL CORP", "NSE"),
            ("IRCTC", "IRCTC", "NSE"),
            ("ITC", "ITC", "NSE"),
            ("JIOFIN", "JIO FINANCIAL SERVICES", "NSE"),
            ("JSWSTEEL", "JSW STEEL", "NSE"),
            ("KOTAKBANK", "KOTAK MAHINDRA BANK", "NSE"),
            ("LT", "LARSEN & TOUBRO", "NSE"),
            ("LTIM", "LTIMINDTREE", "NSE"),
            ("M&M", "MAHINDRA & MAHINDRA", "NSE"),
            ("MARUTI", "MARUTI SUZUKI", "NSE"),
            ("NESTLEIND", "NESTLE INDIA", "NSE"),
            ("NTPC", "NTPC", "NSE"),
            ("ONGC", "OIL & NATURAL GAS CORP", "NSE"),
            ("PERSISTENT", "PERSISTENT SYSTEMS", "NSE"),
            ("PFC", "POWER FINANCE CORP", "NSE"),
            ("POWERGRID", "POWER GRID CORP", "NSE"),
            ("RECLTD", "REC LIMITED", "NSE"),
            ("RELIANCE", "RELIANCE INDUSTRIES", "NSE"),
            ("SBILIFE", "SBI LIFE INSURANCE", "NSE"),
            ("SBIN", "STATE BANK OF INDIA", "NSE"),
            ("SHRIRAMFIN", "SHRIRAM FINANCE", "NSE"),
            ("SIEMENS", "SIEMENS", "NSE"),
            ("SUNPHARMA", "SUN PHARMACEUTICALS", "NSE"),
            ("TATACONSUM", "TATA CONSUMER PRODUCTS", "NSE"),
            ("TATAMOTORS", "TATA MOTORS", "NSE"),
            ("TATAPOWER", "TATA POWER", "NSE"),
            ("TATASTEEL", "TATA STEEL", "NSE"),
            ("TCS", "TATA CONSULTANCY SERVICES", "NSE"),
            ("TECHM", "TECH MAHINDRA", "NSE"),
            ("TITAN", "TITAN COMPANY", "NSE"),
            ("TRENT", "TRENT", "NSE"),
            ("TVSMOTOR", "TVS MOTOR COMPANY", "NSE"),
            ("ULTRACEMCO", "ULTRATECH CEMENT", "NSE"),
            ("UNITDSPR", "UNITED SPIRITS", "NSE"),
            ("UPL", "UPL LIMITED", "NSE"),
            ("VBL", "VARUN BEVERAGES", "NSE"),
            ("VEDL", "VEDANTA", "NSE"),
            ("WIPRO", "WIPRO", "NSE"),
            ("ZOMATO", "ZOMATO", "NSE"),
            ("GOLD", "GOLD", "MCX"),
            ("GOLDM", "GOLD MINI", "MCX"),
            ("SILVER", "SILVER", "MCX"),
            ("SILVERM", "SILVER MINI", "MCX"),
            ("CRUDEOIL", "CRUDEOIL", "MCX"),
            ("NATURALGAS", "NATURALGAS", "MCX"),
            ("COPPER", "COPPER", "MCX"),
            ("ZINC", "ZINC", "MCX"),
            ("ALUMINIUM", "ALUMINIUM", "MCX"),
            ("LEAD", "LEAD", "MCX"),
            ("NICKEL", "NICKEL", "MCX"),
        ]

        for sym, name, exch in DEFAULT_SEEDS:
            token_counter += 1
            st = SymToken(
                symbol=sym,
                brsymbol=sym,
                name=name,
                exchange=exch,
                brexchange=exch,
                token=str(token_counter),
                instrumenttype="EQ" if exch == "NSE" else "FUT",
                lotsize=1,
                tick_size=0.05
            )
            items_to_add.append(st)

        db_session.bulk_save_objects(items_to_add)
        db_session.commit()
        logger.info(f"Seeded {len(items_to_add)} default symbols into SymToken database.")
    except Exception as e:
        logger.error(f"Failed to seed default symtokens: {e}")
        db_session.rollback()


def init_db():
    """Initialize the master contract database tables.

    Creates the ``symtoken`` table if it does not already exist,
    using the shared ``db_init_helper`` for consistent startup logging.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Master Contract DB", logger)
    _seed_default_symtokens()
