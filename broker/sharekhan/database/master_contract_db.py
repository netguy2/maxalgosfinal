"""Sharekhan symbol master ingestion.

IMPORTANT: Sharekhan's SDK exposes `master(exchange)` (GET
/skapi/services/master/{exchange}) but its response schema is not
documented anywhere in the public SDK/README - only that it returns
"Script Master data" per-exchange. The field names assumed below
(scripCode/tradingSymbol/companyName/expiry/strikePrice/lotSize/
instrumentType/tickSize) are a best-available guess based on the same
field-naming convention Sharekhan uses in its order-placement payloads
(which ARE documented). This MUST be verified against a real master()
response and adjusted if any field name differs.

`token` stores the raw Sharekhan scripCode as a single value (unlike some
other brokers, e.g. Zerodha, which pack a composite "a::::b" token) since
every Sharekhan endpoint that needs an instrument identifier
(historicaldata, and implicitly placeOrder's scripCode field) takes just
one scrip code.
"""

import os
import re

import pandas as pd
from sqlalchemy import Column, Float, Index, Integer, Sequence, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from broker.sharekhan.mapping.transform_data import EXCHANGE_MAP, reverse_map_exchange
from database.auth_db import get_auth_token
from database.engine_factory import create_db_engine
from utils.socket_scope import scoped_socketio as socketio  # per-user scoped; see utils/socket_scope.py
from utils.logging import get_logger

logger = get_logger(__name__)

# Use a dedicated SQLite database file for Sharekhan symbols to avoid
# overwriting symbols in the main database shared with the active data broker.
# Use the persisted db directory in Docker if available to prevent loss of symbols on container restarts
if os.path.exists("/app/db"):
    DATABASE_URL = "sqlite:////app/db/sharekhan_symtoken.db"
else:
    DATABASE_URL = "sqlite:///" + os.path.join(os.path.dirname(__file__), "sharekhan_symtoken.db")


engine = create_db_engine(DATABASE_URL)
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
    broker = Column(String, index=True, nullable=True)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)


def init_db():
    logger.info("Initializing Sharekhan Master Contract DB")
    Base.metadata.create_all(bind=engine)


def delete_symtoken_table():
    logger.info("Deleting Sharekhan Symtoken Table")
    SymToken.query.filter(SymToken.broker == "sharekhan").delete(synchronize_session=False)
    db_session.commit()


def copy_from_dataframe(df):
    logger.info("Performing Sharekhan bulk insert")
    data_dict = df.to_dict(orient="records")
    for row in data_dict:
        row["broker"] = "sharekhan"

    # Deduplicate on (token, brexchange) composite key to avoid skipping valid
    # F&O contracts that happen to have the same scrip code across segments
    # (e.g. NC and NF may reuse numeric codes for different instruments).
    existing_keys = {
        (result.token, result.brexchange)
        for result in db_session.query(SymToken.token, SymToken.brexchange).all()
    }
    filtered_data_dict = [
        row for row in data_dict
        if (str(row.get("token", "")), row.get("brexchange", "")) not in existing_keys
    ]

    try:
        if filtered_data_dict:
            db_session.bulk_insert_mappings(SymToken, filtered_data_dict)
            db_session.commit()
            logger.info(f"Sharekhan bulk insert completed with {len(filtered_data_dict)} new records.")
        else:
            logger.info("No new Sharekhan records to insert.")
    except Exception as e:
        logger.error(f"Error during Sharekhan bulk insert: {e}")
        db_session.rollback()


def _format_strike(strike) -> str:
    try:
        val = float(strike)
    except (TypeError, ValueError):
        return ""
    return str(int(val)) if val == int(val) else str(val)


def _build_symbol(row: dict) -> str:
    """Build the Max Algos symbol string from a raw Sharekhan master row.

    Format follows CLAUDE.md's Symbol Format section:
      Equity:  BASE
      Futures: BASE[DDMMMYY]FUT
      Options: BASE[DDMMMYY][STRIKE][CE/PE]
    """
    instrument_type = (row.get("instrumenttype") or "").upper()
    name = row.get("name") or ""
    expiry = row.get("expiry") or ""
    brsymbol = row.get("brsymbol") or ""

    if instrument_type in ("FS", "FI", "FUTCUR", "FUT", "FUTIDX", "FUTSTK"):
        return f"{name}{expiry}FUT"

    if instrument_type in ("OS", "OI", "OPTCUR", "CE", "PE", "OPTIDX", "OPTSTK"):
        # Determine option type: prefer explicit field, then infer from brsymbol
        option_type = (row.get("optiontype") or "").upper()
        if option_type not in ("CE", "PE"):
            # Try extracting CE/PE from the raw broker symbol (e.g. NIFTY14JUL2623700CE)
            br_upper = brsymbol.upper()
            if br_upper.endswith("CE"):
                option_type = "CE"
            elif br_upper.endswith("PE"):
                option_type = "PE"
            elif "CE" in br_upper:
                option_type = "CE"
            elif "PE" in br_upper:
                option_type = "PE"
            else:
                # Cannot determine option type; fall back to the raw brsymbol
                return brsymbol or name
        return f"{name}{expiry}{_format_strike(row.get('strike'))}{option_type}"

    return name or brsymbol or ""


# Sharekhan flags index instruments (NIFTY, BANKNIFTY, SENSEX, INDIAVIX, ...)
# via a `groupName` field on the NC/BC master() response -- there is no
# separate "indices" exchange or instType to key off. Confirmed directly
# against the live API: every index row's groupName is one of these five
# values; every regular equity row's groupName is the literal string "NA"
# (not null/empty -- a real trap, see _looks_like_na below). Sector/
# thematic/strategy indices (NIFTYIT, INDIAVIX, etc.) live under NC same as
# NIFTY itself; BSE only has two groups (SENSEX, BSE100, ... and sector
# indices), no thematic/strategy split.
_NSE_INDEX_GROUPS = {
    "broad market indices",
    "sectoral indices",
    "thematic indices",
    "strategy indices",
}
_BSE_INDEX_GROUPS = {
    "broad market indices",
    "sector & industry",
}


def _looks_like_na(value) -> bool:
    """Sharekhan uses the literal string "NA" (not null) for missing
    companyName on scrip rows that have no proper company (indices,
    admin/placeholder rows). Treating "NA" as a real name previously
    caused every index's Max Algos symbol to become the string "NA"
    instead of the real underlying (e.g. NIFTY), since the truthy,
    non-empty check `if raw_name and raw_name.strip()` doesn't reject it.
    """
    return not value or str(value).strip().upper() in ("NA", "N/A", "-")


def process_sharekhan_master(raw_rows: list, exchange: str) -> pd.DataFrame:
    """Convert Sharekhan's raw master() rows (one per-exchange call) into
    the Max Algos SymToken schema.
    """
    oa_exchange = reverse_map_exchange(exchange)
    index_groups = _NSE_INDEX_GROUPS if exchange == "NC" else _BSE_INDEX_GROUPS if exchange == "BC" else set()
    index_exchange = "NSE_INDEX" if exchange == "NC" else "BSE_INDEX" if exchange == "BC" else None
    records = []

    for row in raw_rows:
        if not isinstance(row, dict):
            continue

        scrip_code = (
            row.get("scripCode")
            or row.get("ScripCode")
            or row.get("scrip_code")
            or row.get("code")
            or row.get("token")
        )
        trading_symbol = (
            row.get("tradingSymbol")
            or row.get("TradingSymbol")
            or row.get("symbol")
            or row.get("scripName")
            or row.get("ScripName")
            or row.get("name")
        )
        if not scrip_code or not trading_symbol:
            continue

        trading_symbol_str = str(trading_symbol).strip()

        is_index_row = (
            index_exchange is not None
            and str(row.get("groupName") or "").strip().lower() in index_groups
        )
        row_exchange = index_exchange if is_index_row else oa_exchange

        # Prefer Sharekhan's dedicated underlying name field. For F&O symbols,
        # tradingSymbol has no spaces (e.g. "NIFTY14JUL2623700CE"), so a
        # whitespace split just returns the full string — useless as a base name.
        # Fall back to extracting the leading alphabetic characters from the
        # trading symbol (e.g. "NIFTY" from "NIFTY14JUL2623700CE"). Index rows
        # (and some placeholder rows) have companyName=="NA" literally, which
        # must be treated the same as missing -- see _looks_like_na.
        raw_name = (
            row.get("companyName")
            or row.get("CompanyName")
            or row.get("company_name")
            or row.get("underlying")
            or row.get("Underlying")
            or row.get("baseName")
            or ""
        )
        if not _looks_like_na(raw_name):
            base_symbol = str(raw_name).strip().split()[0].upper()
        else:
            # Extract leading alphabetic prefix (e.g. "NIFTY" from "NIFTY14JUL2623700CE")
            m = re.match(r"^([A-Za-z&]+)", trading_symbol_str)
            base_symbol = m.group(1).upper() if m else trading_symbol_str.split()[0].upper()

        expiry_raw = (
            row.get("expiry")
            or row.get("expiryDate")
            or row.get("ExpiryDate")
            or row.get("Expiry")
            or ""
        )
        expiry = ""
        if expiry_raw and str(expiry_raw) != "0":
            try:
                # Format: "16-Jul-26" or "29/07/2026"
                expiry = pd.to_datetime(expiry_raw, dayfirst=True).strftime("%d%b%y").upper()
            except (ValueError, TypeError):
                expiry = str(expiry_raw)

        instrument_type = (
            row.get("instType")
            or row.get("instrumentType")
            or row.get("InstrumentType")
            or row.get("instrument_type")
            or row.get("InstType")
            or "EQ"
        )
        strike = (
            row.get("strike")
            or row.get("strikePrice")
            or row.get("StrikePrice")
            or row.get("strike_price")
            or 0.0
        )
        option_type_raw = (
            row.get("optionType")
            or row.get("OptionType")
            or row.get("option_type")
            or ""
        )

        record = {
            "symbol": "",  # filled below via _build_symbol
            "brsymbol": trading_symbol_str,
            "name": base_symbol,
            "exchange": row_exchange,
            "brexchange": exchange,
            "token": str(scrip_code),
            "expiry": expiry,
            "strike": float(strike) if strike else 0.0,
            "lotsize": int(
                row.get("lotSize")
                or row.get("LotSize")
                or row.get("lot_size")
                or 1
            ),
            "instrumenttype": instrument_type,
            "tick_size": float(
                row.get("tickSize")
                or row.get("TickSize")
                or row.get("tick_size")
                or 0.05
            ),
        }
        record["optiontype"] = option_type_raw
        record["symbol"] = _build_symbol(record)
        del record["optiontype"]

        # Standardize instrumenttype for Max Algos platform consumption
        raw_inst = (instrument_type or "").upper()
        symbol_upper = record["symbol"].upper()
        if raw_inst in ("CE", "PE", "OI", "OS", "OPTCUR", "OPTIDX", "OPTSTK"):
            if option_type_raw.upper() == "PE" or symbol_upper.endswith("PE"):
                record["instrumenttype"] = "PE"
            else:
                record["instrumenttype"] = "CE"
        elif raw_inst in ("FUT", "FI", "FS", "FUTCUR", "FUTIDX", "FUTSTK"):
            record["instrumenttype"] = "FUT"
        else:
            record["instrumenttype"] = "EQ"

        records.append(record)

    return pd.DataFrame(
        records,
        columns=[
            "symbol",
            "brsymbol",
            "name",
            "exchange",
            "brexchange",
            "token",
            "expiry",
            "strike",
            "lotsize",
            "instrumenttype",
            "tick_size",
        ],
    )



def master_contract_download():
    """Download and ingest Sharekhan's symbol master, one exchange at a time
    (Sharekhan's master() endpoint is per-exchange, unlike brokers that ship
    a single combined instruments dump)."""
    from broker.sharekhan.api.order_api import get_api_response

    logger.info("Downloading Sharekhan Master Contract")

    try:
        from database.auth_db import decrypt_token, Auth, AuthBrokerSession
        
        # Resolve Sharekhan's session token specifically (never use the active data broker's token like Zebu)
        auth_token = None
        session_username = None  # Username tied to the resolved auth session

        # 1. Try to get active session from Auth table (if Sharekhan is the data broker)
        session_obj = Auth.query.filter_by(broker="sharekhan", is_revoked=False).first()
        if session_obj and session_obj.auth:
            try:
                auth_token = decrypt_token(session_obj.auth)
                # Auth.name is the username stored at login time
                session_username = getattr(session_obj, "name", None) or getattr(session_obj, "user_id", None)
            except Exception as e:
                logger.error(f"Error decrypting fallback auth token from Auth table: {e}")
                
        # 2. Try to get active session from AuthBrokerSession table (if Sharekhan is an additional broker)
        if not auth_token:
            session_obj = AuthBrokerSession.query.filter_by(broker="sharekhan", is_revoked=False).first()
            if session_obj and session_obj.auth:
                try:
                    auth_token = decrypt_token(session_obj.auth)
                    # AuthBrokerSession.username is the direct username column
                    session_username = getattr(session_obj, "username", None)
                except Exception as e:
                    logger.error(f"Error decrypting fallback auth token from AuthBrokerSession table: {e}")

        if not auth_token:
            raise Exception("No active Sharekhan session found for master contract download")

        # Ensure session_username is a plain string (not empty)
        if not session_username:
            session_username = None
        logger.info(f"Sharekhan master download using username={session_username!r} for credential lookup")

        all_dfs = []
        failed_exchanges = {}
        for exchange in EXCHANGE_MAP.values():
            try:
                response = get_api_response(f"/skapi/services/master/{exchange}", auth_token, username=session_username)
                
                # Check for various error fields returned by Sharekhan
                is_error = (
                    not isinstance(response, dict)
                    or response.get("error_type")
                    or response.get("errorType")
                    or response.get("status") not in (200, "200", "success", None)
                )
                
                if is_error:
                    logger.warning(f"Sharekhan master() failed for exchange {exchange}: {response}")
                    failed_exchanges[exchange] = response
                    continue
                rows = response.get("data", [])
                if isinstance(rows, dict):
                    rows = [rows]
                df = process_sharekhan_master(rows, exchange)
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                logger.warning(f"Error downloading Sharekhan master for exchange {exchange}: {e}")
                failed_exchanges[exchange] = str(e)
                continue

        if not all_dfs:
            err_msg = f"No master contract data retrieved. Exchange errors: {failed_exchanges}"
            raise Exception(err_msg)

        combined_df = pd.concat(all_dfs, ignore_index=True)
        delete_symtoken_table()
        copy_from_dataframe(combined_df)

        return socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )
    except Exception as e:
        logger.exception(f"Error downloading Sharekhan master contract: {e}")
        socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
        raise


def search_symbols(symbol, exchange):
    return SymToken.query.filter(SymToken.symbol.like(f"%{symbol}%"), SymToken.exchange == exchange).all()


def get_sharekhan_symbol_info(symbol: str, exchange: str) -> SymToken | None:
    """Query the local Sharekhan database for symbol information (token, expiry, strike)."""
    try:
        return SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
    except Exception as e:
        logger.error(f"Error querying Sharekhan symbol info: {e}")
        return None


# Initialize the database tables on module import, now that SymToken is defined
init_db()


