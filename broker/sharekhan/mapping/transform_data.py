# Mapping Max Algos API request -> Sharekhan ShareConnect order params
# https://github.com/Sharekhan-API/shareconnectpython

# Max Algos exchange -> Sharekhan exchange code.
# Sharekhan uses its own short codes rather than NSE/BSE/NFO/BFO/MCX:
#   NC = NSE Cash, BC = BSE Cash, NF = NSE F&O (derivatives), BM = BSE F&O,
#   NX = Currency derivatives (NSE), MX = MCX Commodity.
EXCHANGE_MAP = {
    "NSE": "NC",
    "BSE": "BC",
    "NFO": "NF",
    "BFO": "BM",
    "CDS": "NX",
    "MCX": "MX",
}

REVERSE_EXCHANGE_MAP = {v: k for k, v in EXCHANGE_MAP.items()}

# Max Algos product -> Sharekhan productType.
# NRML (carry forward) for derivatives must map to INVESTMENT, because
# Sharekhan rejects BT (BIGTRADE) in the NF (NSE F&O) segment.
PRODUCT_MAP = {
    "CNC": "INVESTMENT",
    "NRML": "INVESTMENT",
    "MIS": "BIGTRADEPLUS",
}

# Standard reverse mapping. INVESTMENT is resolved dynamically based on exchange.
REVERSE_PRODUCT_MAP = {
    "INVESTMENT": "CNC",
    "BIGTRADE": "NRML",
    "BIGTRADEPLUS": "MIS",
}

REVERSE_PRODUCT_MAP_KEYS = REVERSE_PRODUCT_MAP.keys()

# Max Algos pricetype -> Sharekhan orderType. Sharekhan's SDK examples only
# ever show "NORMAL" - trigger/limit behavior is driven by price/triggerPrice
# being non-zero rather than a distinct orderType value.
PRICETYPE_MAP = {
    "MARKET": "NORMAL",
    "LIMIT": "NORMAL",
    "SL": "NORMAL",
    "SL-M": "NORMAL",
}



def map_exchange(exchange: str) -> str:
    """Max Algos exchange -> Sharekhan exchange code."""
    return EXCHANGE_MAP.get(exchange, exchange)


def reverse_map_exchange(brexchange: str) -> str:
    """Sharekhan exchange code -> Max Algos exchange."""
    return REVERSE_EXCHANGE_MAP.get(brexchange, brexchange)


def map_product_type(product: str) -> str:
    return PRODUCT_MAP.get(product, "BIGTRADEPLUS")


def reverse_map_product_type(product_type: str, exchange: str = None) -> str:
    product_type_upper = (product_type or "").upper()
    if product_type_upper == "INVESTMENT":
        if exchange and str(exchange).upper() in ("NFO", "BFO", "CDS", "MCX", "NF", "BM", "NX", "MX"):
            return "NRML"
        return "CNC"
    return REVERSE_PRODUCT_MAP.get(product_type_upper, "MIS")


# Exchanges that trade index derivatives (NFO/BFO for index F&O, NX for currency)
_INDEX_DERIVATIVE_EXCHANGES = {"NFO", "BFO"}
_CURRENCY_DERIVATIVE_EXCHANGES = {"CDS"}


def _get_sharekhan_payload_fields(symbol: str, exchange: str) -> dict:
    from broker.sharekhan.database.master_contract_db import get_sharekhan_symbol_info
    from utils.logging import get_logger
    import pandas as pd

    logger = get_logger(__name__)
    info = get_sharekhan_symbol_info(symbol, exchange)

    if not info:
        raise ValueError(
            f"Symbol {symbol} (Exchange: {exchange}) was not found in the Sharekhan master contract database. "
            f"Please go to Broker Management and download the Sharekhan master contract."
        )

    scrip_code = int(info.token)
    trading_symbol = info.brsymbol
    # The DB stores normalized values: CE, PE, FUT, EQ (set by master_contract_db.process_sharekhan_master)
    # Map these back to Sharekhan's instrumentType codes required in the order payload:
    #   FS=Future Stocks, FI=Future Index, OI=Option Index, OS=Option Stocks,
    #   FUTCUR=Future Currency, OPTCUR=Option Currency, EQ=Equity
    raw_inst = (info.instrumenttype or "").upper()

    base_symbol = (info.name or "").upper()
    is_index = base_symbol in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
        "SENSEX",
        "BANKEX",
        "SENSEX50",
        "INDIAVIX",
    )
    is_currency_exchange = exchange.upper() in _CURRENCY_DERIVATIVE_EXCHANGES

    if raw_inst in ("CE", "PE"):
        # Option — distinguish index vs stock
        if is_currency_exchange:
            instrument_type = "OPTCUR"
        elif is_index:
            instrument_type = "OI"
        else:
            instrument_type = "OS"
    elif raw_inst == "FUT":
        # Future — distinguish index vs stock
        if is_currency_exchange:
            instrument_type = "FUTCUR"
        elif is_index:
            instrument_type = "FI"
        else:
            instrument_type = "FS"
    elif raw_inst in ("FUTCUR", "FI", "FS", "OI", "OS", "OPTCUR"):
        # Already a valid Sharekhan instrumentType code — pass through
        instrument_type = raw_inst
    elif raw_inst in ("OPTIDX", "OPTIDX_CE", "OPTIDX_PE"):
        instrument_type = "OI"
    elif raw_inst == "OPTSTK":
        instrument_type = "OS"
    elif raw_inst in ("FUTIDX",):
        instrument_type = "FI"
    elif raw_inst in ("FUTSTK",):
        instrument_type = "FS"
    else:
        instrument_type = "EQ"

    expiry = ""
    # Expiry: stored in DB as DDMMMYY (e.g. 14JUL26), convert to DD/MM/YYYY for Sharekhan payload
    if info.expiry and info.expiry != "0":
        try:
            expiry = pd.to_datetime(info.expiry, format="%d%b%y").strftime("%d/%m/%Y")
        except Exception:
            try:
                expiry = pd.to_datetime(info.expiry).strftime("%d/%m/%Y")
            except Exception:
                expiry = str(info.expiry)

    strike_price = -1
    option_type = "XX"
    # Strike and Option Type — required for all option instrument types
    if instrument_type in ("OI", "OS", "OPTCUR"):
        strike_price = info.strike if info.strike else -1
        sym_upper = symbol.upper()
        if sym_upper.endswith("CE") or "CE" in sym_upper:
            option_type = "CE"
        elif sym_upper.endswith("PE") or "PE" in sym_upper:
            option_type = "PE"
        else:
            # Fall back to the raw_inst stored value (CE/PE)
            if raw_inst == "CE":
                option_type = "CE"
            elif raw_inst == "PE":
                option_type = "PE"
            else:
                option_type = "XX"

    # Format strike_price to string
    if strike_price == -1:
        strike_str = "-1"
    else:
        try:
            val_float = float(strike_price)
            if val_float.is_integer():
                strike_str = str(int(val_float))
            else:
                strike_str = f"{val_float:.2f}"
        except Exception:
            strike_str = str(strike_price)

    return {
        "scripCode": scrip_code,
        "tradingSymbol": trading_symbol,
        "instrumentType": instrument_type,
        "strikePrice": strike_str,
        "expiry": expiry,
        "optionType": option_type,
    }



def transform_data(data: dict, customer_id: str) -> dict:
    """Transform a Max Algos order request into Sharekhan's placeOrder params.

    Args:
        data: Max Algos order dict (symbol, exchange, action, quantity, ...).
        customer_id: Sharekhan customer/login ID, extracted at auth time and
            required on every order request (also used as channelUser, per
            the SDK docs: "Use LoginId as ChannelUser").
    """
    exchange = data["exchange"]
    br_exchange = map_exchange(exchange)
    symbol = data["symbol"]

    # Resolve symbol properties from helper
    sym_fields = _get_sharekhan_payload_fields(symbol, exchange)

    action = data["action"].upper()
    transaction_type = "B" if action == "BUY" else "S"

    pricetype = data.get("pricetype", "MARKET")
    price = str(data.get("price", 0) or 0)
    trigger_price = str(data.get("trigger_price", 0) or 0)
    # Sharekhan has no distinct MARKET order type - a MARKET order is a
    # NORMAL order with price "0".
    if pricetype == "MARKET":
        price = "0"

    transformed = {
        "customerId": customer_id,
        "scripCode": sym_fields["scripCode"],
        "tradingSymbol": sym_fields["tradingSymbol"],
        "exchange": br_exchange,
        "transactionType": transaction_type,
        "quantity": int(data.get("quantity", 0)),
        "disclosedQty": int(data.get("disclosed_quantity", 0) or 0),
        "price": price,
        "triggerPrice": trigger_price,
        "rmsCode": "ANY",
        "afterHour": "N",
        "orderType": PRICETYPE_MAP.get(pricetype, "NORMAL"),
        "channelUser": customer_id,
        "validity": "GFD",
        "requestType": "NEW",
        "productType": map_product_type(data.get("product", "MIS")),
        "instrumentType": sym_fields["instrumentType"],
        "strikePrice": sym_fields["strikePrice"],
        "expiry": sym_fields["expiry"],
        "optionType": sym_fields["optionType"],
    }

    return transformed


def transform_modify_order_data(data: dict, customer_id: str) -> dict:
    exchange = data["exchange"]
    pricetype = data.get("pricetype", "MARKET")
    price = str(data.get("price", 0) or 0)
    if pricetype == "MARKET":
        price = "0"

    # Resolve symbol properties from helper
    sym_fields = _get_sharekhan_payload_fields(data["symbol"], exchange)

    return {
        "orderId": data["orderid"],
        "customerId": customer_id,
        "scripCode": sym_fields["scripCode"],
        "tradingSymbol": sym_fields["tradingSymbol"],
        "exchange": map_exchange(exchange),
        "transactionType": "B" if data["action"].upper() == "BUY" else "S",
        "quantity": int(data.get("quantity", 0)),
        "disclosedQty": int(data.get("disclosed_quantity", 0) or 0),
        "price": price,
        "triggerPrice": str(data.get("trigger_price", 0) or 0),
        "rmsCode": "ANY",
        "afterHour": "N",
        "orderType": PRICETYPE_MAP.get(pricetype, "NORMAL"),
        "channelUser": customer_id,
        "validity": "GFD",
        "requestType": "MODIFY",
        "productType": map_product_type(data.get("product", "MIS")),
        "instrumentType": sym_fields["instrumentType"],
        "strikePrice": sym_fields["strikePrice"],
        "expiry": sym_fields["expiry"],
        "optionType": sym_fields["optionType"],
    }

