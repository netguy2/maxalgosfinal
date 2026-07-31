"""
Mapping utilities for Dhan broker integration.
Provides exchange code mappings between Max Algos and Dhan formats.
"""

from typing import Dict

# Exchange code mappings
# Max Algos exchange code -> Dhan exchange code
MAX_ALGOS_TO_DHAN_EXCHANGE = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I",
}

# Dhan exchange code -> Max Algos exchange code
DHAN_TO_MAX_ALGOS_EXCHANGE = {v: k for k, v in MAX_ALGOS_TO_DHAN_EXCHANGE.items()}


def get_dhan_exchange(maxalgos_exchange: str) -> str:
    """
    Convert Max Algos exchange code to Dhan exchange code.

    Args:
        maxalgos_exchange (str): Exchange code in Max Algos format

    Returns:
        str: Exchange code in Dhan format
    """
    return MAX_ALGOS_TO_DHAN_EXCHANGE.get(maxalgos_exchange, maxalgos_exchange)


def get_maxalgos_exchange(dhan_exchange: str) -> str:
    """
    Convert Dhan exchange code to Max Algos exchange code.

    Args:
        dhan_exchange (str): Exchange code in Dhan format

    Returns:
        str: Exchange code in Max Algos format
    """
    return DHAN_TO_MAX_ALGOS_EXCHANGE.get(dhan_exchange, dhan_exchange)
