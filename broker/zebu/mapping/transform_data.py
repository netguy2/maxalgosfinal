# Mapping Max Algos API Request https://maxalgos.in/docs
# Mapping Zebu Broking Parameters

from broker.zebu.api.data import BrokerData
from database.token_db import get_br_symbol
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def transform_data(data, token, auth_token=None, zebu_uid=None):
    """
    Transforms the new API request structure to the current expected structure.
    For market orders, fetches quotes and adjusts price using MPP (Market Price Protection):
    - EQ/FUT: Price < 100: 2%, 100-500: 1%, > 500: 0.5%
    - OPT (CE/PE): Price < 10: 5%, 10-100: 3%, 100-500: 2%, > 500: 1%

    Args:
        data: Order data dictionary
        token: Instrument token
        auth_token: Authentication token for fetching quotes (passed from order_api)
        zebu_uid: Already-resolved Zebu user ID, if the caller has one (e.g.
            place_order_api resolves it before calling this function). Passing
            it in skips a second get_zebu_userid() call here, which otherwise
            re-scans every active AuthBrokerSession/Auth row and decrypts each
            one's token to find a match -- redundant work on the order
            placement hot path when the caller already did exactly that.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Handle special characters in symbol
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    # Default values
    raw_pricetype = str(data.get("pricetype", "MARKET")).upper().strip()
    action = str(data.get("action", "BUY")).upper().strip()

    price_val = 0.0
    try:
        price_val = float(data.get("price", 0) or 0)
    except (ValueError, TypeError):
        price_val = 0.0

    order_type = map_order_type(raw_pricetype)

    # Force convert MARKET orders to LIMIT (LMT) for Zebu API compliance
    if raw_pricetype in ("MARKET", "MKT"):
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, Exchange={data['exchange']}, Action={action}"
        )

        base_price = price_val
        instrument_type = get_instrument_type_from_symbol(data["symbol"])
        tick_size = None

        # Try to resolve live market price if base_price <= 0
        if base_price <= 0 and auth_token:
            try:
                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], data["exchange"])
                logger.info(
                    f"MPP Quote Response: Symbol={data['symbol']}, Exchange={data['exchange']}, "
                    f"LTP={quote_data.get('ltp')}, Bid={quote_data.get('bid')}, Ask={quote_data.get('ask')}"
                )
                tick_size = quote_data.get("tick_size")
                ltp = float(quote_data.get("ltp", 0) or 0)
                ask = float(quote_data.get("ask", 0) or 0)
                bid = float(quote_data.get("bid", 0) or 0)

                if action == "BUY" and ask > 0:
                    base_price = ask
                elif action == "SELL" and bid > 0:
                    base_price = bid
                elif ltp > 0:
                    base_price = ltp
            except Exception as e:
                # Do NOT swallow this -- previously this just logged and fell
                # through with base_price still 0, which (combined with the
                # order_type being forced to LMT below) produced a LIMIT
                # order with prc="0" that Zebu rejects with "Order price
                # cannot be zero". Re-raise as a clear error instead of
                # silently submitting a doomed order to the broker.
                logger.error(
                    f"MPP Error fetching quote for Symbol={data['symbol']}, Error={e}"
                )
                raise ValueError(
                    f"Unable to fetch live market price for {data['symbol']} to place "
                    f"MARKET order (Zebu requires MARKET orders to be converted to LIMIT "
                    f"with a real price via Market Price Protection): {e}"
                ) from e

        # Fallback to other keys in data dict
        if base_price <= 0:
            for k in ("ltp", "ask", "bid", "last_price", "close"):
                try:
                    v = float(data.get(k, 0) or 0)
                    if v > 0:
                        base_price = v
                        break
                except (ValueError, TypeError):
                    continue

        if base_price <= 0:
            # Never submit a LIMIT order with price=0 -- Zebu's API rejects
            # it outright ("Order price cannot be zero"), and this used to
            # happen silently (see the removed else-branch that defaulted to
            # price="0" and forced order_type="LMT" regardless). Fail loudly
            # here instead so the caller sees a clear, actionable error
            # rather than a rejected order after a slow round-trip.
            raise ValueError(
                f"Unable to determine a market price for {data['symbol']} to place a "
                f"MARKET order via Zebu's required LIMIT+MPP conversion. No live quote "
                f"was available (auth_token={'present' if auth_token else 'missing'})."
            )

        order_type = "LMT"
        protected_price = calculate_protected_price(
            price=base_price,
            action=action,
            symbol=data["symbol"],
            instrument_type=instrument_type,
            tick_size=tick_size,
        )
        price = str(protected_price)
        logger.info(
            f"MPP Conversion Complete: Symbol={data['symbol']}, OrderType=MARKET->LIMIT, "
            f"BasePrice={base_price}, FinalPrice={protected_price}"
        )
    else:
        price = str(price_val if price_val > 0 else data.get("price", "0"))

    # Resolve Zebu User ID (uid / actid) -- reuse the caller's already-resolved
    # value if provided, otherwise fall back to resolving it here (same cost
    # as before for any caller that doesn't pass it in).
    if not zebu_uid:
        from broker.zebu.api.order_api import get_zebu_userid
        zebu_uid = get_zebu_userid(auth_token, fallback_userid=data.get("uid") or data.get("actid") or data.get("apikey"))

    # Basic mapping
    transformed = {
        "uid": str(zebu_uid),
        "actid": str(zebu_uid),
        "exch": str(data.get("exchange", "NSE")),
        "tsym": str(symbol),
        "qty": str(data.get("quantity", "1")),
        "prc": str(price),
        "trgprc": str(data.get("trigger_price", "0")),
        "dscqty": str(data.get("disclosed_quantity", "0")),
        "prd": str(map_product_type(data.get("product", "MIS"))),
        "trantype": "B" if str(action).upper() == "BUY" else "S",
        "prctyp": str(order_type),
        "mkt_protection": "0",
        "ret": "DAY",
        "ordersource": "API",
    }
    transformed = {k: str(v) for k, v in transformed.items()}

    # Log order data without sensitive fields
    safe_log = {k: v for k, v in transformed.items() if k not in ("uid", "actid")}
    logger.info(f"Transformed order data: {safe_log}")
    return transformed


def transform_modify_order_data(data, token):
    # Handle special characters in symbol
    symbol = data["symbol"]
    if symbol and "&" in symbol:
        symbol = symbol.replace("&", "%26")

    result = {
        "uid": data["apikey"],
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": "0" if data["pricetype"] == "MARKET" else str(data.get("price", "0")),
        "qty": str(data["quantity"]),
        "tsym": symbol,
        "ret": "DAY",
        "dscqty": str(data.get("disclosed_quantity") or 0),
    }

    # Only include trigger price for SL/SL-M orders
    # Sending trgprc=0 for LIMIT orders causes "Trigger price invalid - 0.00" error
    if data["pricetype"] in ["SL", "SL-M"]:
        result["trgprc"] = str(data.get("trigger_price") or 0)

    return result


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS",
    }
    return reverse_product_type_mapping.get(product)
