"""Sharekhan order/trade/position/holdings response -> Max Algos format.

IMPORTANT: Sharekhan's published SDK (shareconnectpython) and API docs do
not document exact response field names for reports/trades/holdings - the
SDK only proxies raw JSON through to the caller. The field names below
(orderId/tradingSymbol/exchange/transactionType/status/...) are the
*request*-side field names from the SDK's own examples, used here as the
best-available guess for response fields too, since Sharekhan's OMS
typically echoes the same field names back. This MUST be verified against
a real account's actual responses and adjusted if any field name differs -
see broker/sharekhan/api/order_api.py for where these are called.
"""

from database.token_db import get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# Sharekhan order status strings -> Max Algos order_status.
_STATUS_MAP = {
    "COMPLETE": "complete",
    "EXECUTED": "complete",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "OPEN": "open",
    "PENDING": "open",
    "TRIGGER PENDING": "trigger pending",
}


def _extract_list(data):
    """Sharekhan wraps most list responses as {"data": [...]}. Some
    endpoints may return the list directly - handle both."""
    if isinstance(data, dict):
        inner = data.get("data")
        if inner is None:
            return []
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            return [inner]
        return []
    if isinstance(data, list):
        return data
    return []


def map_order_data(order_data):
    orders = _extract_list(order_data)
    for order in orders:
        exchange = _reverse_exchange(order.get("exchange", ""))
        symbol = order.get("tradingSymbol") or order.get("scripCode")
        if symbol:
            order["tradingSymbol"] = get_oa_symbol(brsymbol=str(symbol), exchange=exchange)
        order["_oa_exchange"] = exchange
    return orders


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        txn = (order.get("transactionType") or "").upper()
        if txn in ("B", "BUY"):
            total_buy_orders += 1
        elif txn in ("S", "SELL"):
            total_sell_orders += 1

        status = _STATUS_MAP.get((order.get("orderStatus") or order.get("status") or "").upper())
        if status == "complete":
            total_completed_orders += 1
        elif status == "open":
            total_open_orders += 1
        elif status == "rejected":
            total_rejected_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]

    transformed_orders = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue

        status = _STATUS_MAP.get((order.get("orderStatus") or order.get("status") or "").upper(), "open")
        txn = (order.get("transactionType") or "").upper()
        action = "BUY" if txn in ("B", "BUY") else "SELL"

        exchange = order.get("_oa_exchange") or _reverse_exchange(order.get("exchange", ""))
        action = "BUY" if txn in ("B", "BUY") else "SELL"

        transformed_orders.append(
            {
                "symbol": order.get("tradingSymbol", ""),
                "exchange": exchange,
                "action": action,
                "quantity": order.get("quantity", 0),
                "price": float(order.get("price", 0) or 0),
                "trigger_price": float(order.get("triggerPrice", 0) or 0),
                "pricetype": order.get("orderType", ""),
                "product": _reverse_product(order.get("productType", ""), exchange=exchange),
                "orderid": str(order.get("orderId", "")),
                "order_status": status,
                "timestamp": order.get("orderTime") or order.get("orderDateTime", ""),
            }
        )
    return transformed_orders


def map_trade_data(trade_data):
    return map_order_data(trade_data)


def transform_tradebook_data(tradebook_data):
    transformed_data = []
    for trade in tradebook_data or []:
        qty = trade.get("quantity", 0)
        avg_price = float(trade.get("price", 0) or trade.get("averagePrice", 0) or 0)
        exchange = trade.get("_oa_exchange") or _reverse_exchange(trade.get("exchange", ""))
        transformed_data.append(
            {
                "symbol": trade.get("tradingSymbol", ""),
                "exchange": exchange,
                "product": _reverse_product(trade.get("productType", ""), exchange=exchange),
                "action": "BUY" if (trade.get("transactionType") or "").upper() in ("B", "BUY") else "SELL",
                "quantity": qty,
                "average_price": avg_price,
                "trade_value": qty * avg_price,
                "orderid": str(trade.get("orderId", "")),
                "timestamp": trade.get("orderTime") or trade.get("orderDateTime", ""),
            }
        )
    return transformed_data


def map_position_data(position_data):
    positions = _extract_list(position_data)
    for position in positions:
        exchange = _reverse_exchange(position.get("exchange", ""))
        symbol = position.get("tradingSymbol") or position.get("scripCode")
        if symbol:
            position["tradingSymbol"] = get_oa_symbol(brsymbol=str(symbol), exchange=exchange)
        position["_oa_exchange"] = exchange
    return positions


def transform_positions_data(positions_data):
    transformed_data = []
    for position in positions_data or []:
        avg_price = float(position.get("averagePrice", 0) or position.get("buyAvgPrice", 0) or 0)
        exchange = position.get("_oa_exchange") or _reverse_exchange(position.get("exchange", ""))
        transformed_data.append(
            {
                "symbol": position.get("tradingSymbol", ""),
                "exchange": exchange,
                "product": _reverse_product(position.get("productType", ""), exchange=exchange),
                "quantity": position.get("netQuantity", position.get("quantity", "0")),
                "pnl": round(float(position.get("pnl", 0) or position.get("mtm", 0) or 0), 2),
                "average_price": f"{avg_price:.2f}",
                "ltp": round(float(position.get("ltp", 0) or position.get("lastTradedPrice", 0) or 0), 2),
            }
        )
    return transformed_data


def transform_holdings_data(holdings_data):
    transformed_data = []
    for holding in holdings_data or []:
        avg_price = float(holding.get("averagePrice", 0) or holding.get("buyAvgPrice", 0) or 0)
        ltp = float(holding.get("ltp", 0) or holding.get("lastTradedPrice", 0) or 0)
        pnlpercent = 0.0 if avg_price == 0 else round((ltp - avg_price) / avg_price * 100, 2)

        transformed_data.append(
            {
                "symbol": holding.get("tradingSymbol", ""),
                "exchange": holding.get("_oa_exchange") or _reverse_exchange(holding.get("exchange", "")),
                "quantity": holding.get("quantity", 0),
                "product": "CNC",
                "pnl": round((ltp - avg_price) * float(holding.get("quantity", 0) or 0), 2),
                "pnlpercent": pnlpercent,
            }
        )
    return transformed_data


def _reverse_exchange(brexchange: str) -> str:
    from broker.sharekhan.mapping.transform_data import reverse_map_exchange

    return reverse_map_exchange(brexchange)


def _reverse_product(product_type: str, exchange: str = None) -> str:
    from broker.sharekhan.mapping.transform_data import reverse_map_product_type

    return reverse_map_product_type(product_type, exchange)
