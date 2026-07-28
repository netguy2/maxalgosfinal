"""
Zerodha WebSocket streaming module for Max Algos.

This module provides WebSocket integration with Zerodha's market data streaming API,
following the Max Algos WebSocket proxy architecture.
"""

from .zerodha_adapter import ZerodhaWebSocketAdapter

__all__ = ["ZerodhaWebSocketAdapter"]
