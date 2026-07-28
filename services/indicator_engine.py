import logging
from services.indicator_registry import IndicatorRegistry

logger = logging.getLogger(__name__)


def calculate_indicator(name: str, symbol: str, exchange: str, **kwargs) -> float:
    """
    Look up the indicator plugin by name and calculate its value
    for the specified instrument.
    """
    plugin = IndicatorRegistry.get(name)
    if not plugin:
        logger.warning(f"Indicator {name} not found in registry. Returning 0.0")
        return 0.0
    
    try:
        val = plugin.calculate(symbol, exchange, **kwargs)
        return float(val)
    except Exception as e:
        logger.exception(f"Error calculating indicator {name} for {symbol}: {e}")
        return 0.0


def get_rsi(symbol: str, exchange: str, period: int = 14) -> float:
    return calculate_indicator("RSI", symbol, exchange, period=period)


def get_ema(symbol: str, exchange: str, period: int = 20) -> float:
    return calculate_indicator("EMA", symbol, exchange, period=period)


def get_sma(symbol: str, exchange: str, period: int = 20) -> float:
    return calculate_indicator("SMA", symbol, exchange, period=period)


def get_vwap(symbol: str, exchange: str) -> float:
    return calculate_indicator("VWAP", symbol, exchange)


def get_pcr(symbol: str, exchange: str) -> float:
    return calculate_indicator("PCR", symbol, exchange)


def get_oi(symbol: str, exchange: str) -> float:
    return calculate_indicator("OI", symbol, exchange)


def get_iv(symbol: str, exchange: str) -> float:
    return calculate_indicator("IV", symbol, exchange)
