# services/ai_strategy_generator_service.py
"""
AI-assisted Python strategy generation for the Python Strategy Host
(blueprints/python_strategy.py, frontend/src/pages/python-strategy/NewPythonStrategy.tsx).

The user describes a strategy in plain English; this module asks their own
configured AI provider (database/ai_settings_db.py -- the same per-user,
Fernet-encrypted OpenAI/Anthropic/Gemini/custom key already used by the
Charts page's "AI Insight" feature, services/ai_insight_service.py) to fill
in ONLY the strategy-specific pieces of a FIXED, already-proven script
scaffold -- not to write a whole script freely. This is a deliberate
reliability choice: the AI is asked to return small JSON fields (symbol,
exchange, quantity, product, timeframe, lookback_days, a short signal
description, and the body of one check_for_signal(data) function), which
get spliced into the exact same HEADER/CONFIGURATION/OrderManager/
RUNTIME_TAIL scaffold frontend/src/lib/python-strategy-generator.ts already
uses for the marketplace-template generator -- guaranteeing correct maxalgos
SDK usage (client.history/client.placeorder), correct env-var contract
(MAX_ALGOS_API_KEY/HOST_SERVER/WEBSOCKET_URL auto-injected by the /python
runner), and correct OrderManager position-tracking, regardless of what the
AI actually returns for the trading logic itself.

The generated script still goes through the EXACT SAME upload path as any
hand-written or template-generated strategy
(blueprints/python_strategy.py's POST /python/new: ast.parse() syntax
validation, filename sanitization, path-traversal check) -- this module
does not bypass or weaken that in any way. It also runs its own additional
AST-based safety check (_validate_signal_body below) specifically on the
AI-authored check_for_signal() body before ever splicing it into the
script, since unlike the fixed template generator, this is genuinely
AI-authored code -- see that function's docstring for exactly what it
allows/rejects.
"""

import ast
import json
from typing import Any

from database.ai_settings_db import get_ai_settings_decrypted
from services.ai_insight_service import (
    AiInsightError,
    _call_anthropic,
    _call_gemini,
    _call_openai,
    _call_openai_compatible,
    _extract_json,
)
from utils.logging import get_logger

logger = get_logger(__name__)


class AiStrategyGenerationError(Exception):
    """Raised for any failure that should surface as a clean user-facing message."""


SYSTEM_PROMPT = (
    "You are a trading-strategy assistant embedded in a self-hosted algo "
    "trading platform. A user will describe a trading strategy in plain "
    "English. You must translate it into a small, constrained JSON object "
    "-- NOT a full Python script -- describing the strategy's parameters "
    "and a single Python function body that computes a trade signal from "
    "an OHLCV pandas DataFrame.\n\n"
    "Respond with a single JSON object, and nothing else: no markdown "
    "fences, no prose outside the JSON. The object must have exactly "
    "these fields:\n"
    '  "symbol": a trading symbol string, e.g. "RELIANCE" or "NIFTY" '
    "(uppercase, no exchange suffix)\n"
    '  "exchange": one of "NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", '
    '"BSE_INDEX", "CRYPTO" -- infer from the symbol/description; default '
    'to "NSE" for an equity symbol if unclear\n'
    '  "quantity": a positive integer, default 1 if not specified\n'
    '  "product": one of "MIS" (intraday), "CNC" (delivery), "NRML" '
    "(carry) -- infer from the description (day-trading language implies "
    'MIS), default "MIS" if unclear\n'
    '  "timeframe": one of "1m", "5m", "15m", "30m", "1h", "D" -- infer '
    'from the description, default "5m" if unclear\n'
    '  "lookback_days": an integer 1-30, how many days of history the '
    "signal function needs to compute its indicator (e.g. 5 for a 14-period "
    "RSI on 5m bars, 15-30 for slower daily-bar indicators), default 5 if "
    "unclear\n"
    '  "summary": a 1-2 sentence plain-English restatement of the '
    "strategy's entry/exit logic, for the user to review\n"
    '  "signal_function_body": a STRING containing the complete Python '
    "source of a `check_for_signal(data)` function (including its `def` "
    "line), which:\n"
    "    - Takes one argument `data`, a pandas DataFrame with columns "
    "'open','high','low','close','volume','timestamp', oldest row last "
    "closed bar at data.iloc[-2] (the LAST row, data.iloc[-1], is the "
    "currently-forming incomplete bar and must never be used for a "
    "signal decision -- always reason from data.iloc[-2] and earlier).\n"
    "    - Returns the Python string \"BUY\" to open a long, \"SELL\" to "
    "open a short, \"EXIT\" to close an open position, or None/no return "
    "for no action.\n"
    "    - May use `pandas` (imported as `pd`) and pandas' own vectorized "
    "operations (.ewm, .rolling, .diff, .clip, etc.) to compute indicators "
    "(EMA, SMA, RSI, MACD, ATR, Bollinger Bands, VWAP, etc.) directly -- do "
    "NOT import or call ANY other library, do NOT use `eval`, `exec`, "
    "`import`, `open`, `os`, `sys`, network calls, or file I/O of any "
    "kind. This function computes a signal from the DataFrame ONLY -- it "
    "must never place an order itself (order placement is handled "
    "elsewhere).\n"
    "    - Must guard against insufficient data (return None if "
    "`len(data)` is too small for the indicator window) before indexing.\n"
    "    - May define module-level parameter constants (e.g. "
    "RSI_PERIOD = 14) directly above the function using literal values "
    "(numbers/strings only, no os.getenv calls -- the scaffold's own "
    "CONFIGURATION block already handles environment variables).\n\n"
    "If the user's description is too vague to produce a concrete signal "
    "(e.g. no indicator or condition mentioned at all), still produce your "
    "best reasonable interpretation rather than refusing -- explain your "
    "assumptions in \"summary\"."
)

_REQUIRED_FIELDS = {
    "symbol",
    "exchange",
    "quantity",
    "product",
    "timeframe",
    "lookback_days",
    "summary",
    "signal_function_body",
}
_VALID_EXCHANGES = {"NSE", "BSE", "NFO", "BFO", "MCX", "NSE_INDEX", "BSE_INDEX", "CRYPTO"}
_VALID_PRODUCTS = {"MIS", "CNC", "NRML"}
_VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "D"}

# Modules/names an AI-generated signal body is allowed to reference.
# check_for_signal() only ever needs to read the DataFrame and do pandas
# math -- it never places orders, reads files, or makes network calls
# (that's the fixed scaffold's job), so anything outside this list is
# rejected rather than silently allowed through.
_ALLOWED_NAMES = {"data", "pd", "check_for_signal", "None", "True", "False"}
_FORBIDDEN_NODE_TYPES = (ast.Import, ast.ImportFrom)


def build_prompt(description: str) -> str:
    return (
        "Translate this trading strategy description into the JSON object "
        "described in your instructions:\n\n" + description.strip()
    )


def _validate_signal_body(source: str) -> None:
    """AST-based safety check on the AI-authored check_for_signal() body,
    since (unlike the fixed template scaffold) this text is genuinely
    AI-authored. Rejects:
      - any import statement (the function must only use `pd`, already
        imported by the surrounding scaffold)
      - any call to eval/exec/open/compile/__import__ or attribute access
        on os/sys/subprocess-like names
      - anything that isn't exactly one function definition named
        check_for_signal
    This is defense-in-depth alongside the SYSTEM_PROMPT's own
    instructions -- never trust the model's compliance with the prompt
    alone. Raises AiStrategyGenerationError with a clear reason on
    rejection."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise AiStrategyGenerationError(
            f"AI generated invalid Python (syntax error on line {e.lineno}: {e.msg}). "
            "Try rephrasing your strategy description, or edit the generated code manually."
        ) from e

    # The prompt explicitly allows module-level constants (RSI_PERIOD = 14,
    # etc.) directly above the function, so every top-level statement must
    # be either a simple literal assignment or the one function def --
    # never an arbitrary top-level statement (a bare call, a class, a
    # loop, ...).
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "check_for_signal":
        raise AiStrategyGenerationError(
            "AI did not return a single check_for_signal(data) function. Try rephrasing your "
            "strategy description."
        )
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            continue
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            continue
        raise AiStrategyGenerationError(
            "Generated signal logic contains something other than parameter constants and the "
            "check_for_signal function. Try rephrasing your strategy description."
        )

    forbidden_calls = {"eval", "exec", "compile", "__import__", "open", "input"}
    forbidden_attr_roots = {"os", "sys", "subprocess", "socket", "shutil", "importlib"}

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            raise AiStrategyGenerationError(
                "Generated signal logic must not import anything -- only pandas ('pd') is "
                "available. Try rephrasing your strategy description."
            )
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in forbidden_calls:
                raise AiStrategyGenerationError(
                    f"Generated signal logic called a disallowed function ({name}). Try "
                    "rephrasing your strategy description."
                )
        if isinstance(node, ast.Name) and node.id in forbidden_attr_roots:
            raise AiStrategyGenerationError(
                f"Generated signal logic referenced a disallowed module ({node.id}). Only "
                "pandas ('pd') is available. Try rephrasing your strategy description."
            )
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id in forbidden_attr_roots:
                raise AiStrategyGenerationError(
                    f"Generated signal logic referenced a disallowed module ({base.id}). Try "
                    "rephrasing your strategy description."
                )


def _validate_generated(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AiStrategyGenerationError("AI returned an unexpected format")
    if not _REQUIRED_FIELDS.issubset(data.keys()):
        raise AiStrategyGenerationError("AI returned an unexpected format")

    symbol = str(data["symbol"]).strip().upper()
    if not symbol or not all(c.isalnum() or c == "_" for c in symbol):
        raise AiStrategyGenerationError("AI returned an invalid symbol")

    exchange = str(data["exchange"]).strip().upper()
    if exchange not in _VALID_EXCHANGES:
        exchange = "NSE"

    try:
        quantity = int(data["quantity"])
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    product = str(data["product"]).strip().upper()
    if product not in _VALID_PRODUCTS:
        product = "MIS"

    timeframe = str(data["timeframe"]).strip()
    if timeframe not in _VALID_TIMEFRAMES:
        timeframe = "5m"

    try:
        lookback_days = int(data["lookback_days"])
    except (TypeError, ValueError):
        lookback_days = 5
    lookback_days = max(1, min(30, lookback_days))

    signal_function_body = str(data["signal_function_body"])
    _validate_signal_body(signal_function_body)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "quantity": quantity,
        "product": product,
        "timeframe": timeframe,
        "lookback_days": lookback_days,
        "summary": str(data["summary"])[:500],
        "signal_function_body": signal_function_body,
    }


_HEADER = '''"""
===============================================================================
                {strategy_name}
                        Max Algos Trading Bot — AI-generated from a plain-English description
===============================================================================

{summary}

Run standalone:
    export MAX_ALGOS_API_KEY="your-api-key"
    python strategy.py

Run via Max Algos's /python strategy runner:
    MAX_ALGOS_API_KEY, HOST_SERVER, WEBSOCKET_URL, MAX_ALGOS_STRATEGY_EXCHANGE,
    STRATEGY_ID, STRATEGY_NAME are all injected automatically. No code changes
    required — edit the CONFIGURATION block below to tune parameters.

Review this AI-generated strategy carefully before running it live. Test in
Sandbox mode first.
"""

import os
import time
from datetime import datetime, timedelta

import pandas as pd
from maxalgos import api

# ===============================================================================
# CONFIGURATION
# ===============================================================================

API_KEY = os.getenv("MAX_ALGOS_API_KEY", "maxalgos-apikey")
API_HOST = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
WS_URL = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8785")

SYMBOL = os.getenv("SYMBOL", "{symbol}")
EXCHANGE = os.getenv("MAX_ALGOS_STRATEGY_EXCHANGE", os.getenv("EXCHANGE", "{exchange}"))
QUANTITY = int(os.getenv("QUANTITY", "{quantity}"))
PRODUCT = os.getenv("PRODUCT", "{product}")
TIMEFRAME = os.getenv("TIMEFRAME", "{timeframe}")
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "{lookback_days}"))
SIGNAL_CHECK_INTERVAL = int(os.getenv("SIGNAL_CHECK_INTERVAL", "15"))  # seconds


# ===============================================================================
# SIGNAL LOGIC (AI-generated from your description -- review before running)
# ===============================================================================

{signal_function_body}
'''

# Identical to frontend/src/lib/python-strategy-generator.ts's RUNTIME_TAIL --
# kept in sync deliberately since both generators must produce a script the
# /python runner executes identically. See that file if this ever needs
# updating; changes should be mirrored in both places.
_RUNTIME_TAIL = '''

# ===============================================================================
# RUNTIME HELPERS (shared by all generated strategies)
# ===============================================================================

STRATEGY_NAME = os.getenv("STRATEGY_NAME", "AIGeneratedStrategy")


class OrderManager:
    """Tracks the current position and places entry/exit orders via the SDK."""

    def __init__(self, client, symbol, exchange, quantity, product):
        self.client = client
        self.symbol = symbol
        self.exchange = exchange
        self.quantity = quantity
        self.product = product
        self.position = None  # "BUY" | "SELL" | None

    def enter(self, action):
        if self.position is not None:
            return
        response = self.client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=self.symbol,
            exchange=self.exchange,
            action=action,
            quantity=self.quantity,
            price_type="MARKET",
            product=self.product,
        )
        if response.get("status") == "success":
            self.position = action
            print(f"[ORDER] Entered {action} {self.symbol} qty={self.quantity}")
        else:
            print(f"[ORDER] Entry failed: {response}")

    def exit(self, reason="Signal exit"):
        if self.position is None:
            return
        exit_action = "SELL" if self.position == "BUY" else "BUY"
        response = self.client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=self.symbol,
            exchange=self.exchange,
            action=exit_action,
            quantity=self.quantity,
            price_type="MARKET",
            product=self.product,
        )
        print(f"[ORDER] Exit ({reason}) {exit_action} {self.symbol}: {response.get('status')}")
        self.position = None


def get_history(client, symbol, exchange, timeframe, lookback_days):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    return client.history(
        symbol=symbol,
        exchange=exchange,
        interval=timeframe,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )


def main():
    client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)
    order_mgr = OrderManager(client, SYMBOL, EXCHANGE, QUANTITY, PRODUCT)
    print(f"[BOT] {STRATEGY_NAME} started on {SYMBOL} ({EXCHANGE}), timeframe={TIMEFRAME}")

    try:
        while True:
            data = get_history(client, SYMBOL, EXCHANGE, TIMEFRAME, LOOKBACK_DAYS)
            signal = check_for_signal(data)
            if signal == "EXIT":
                order_mgr.exit("Signal reversed")
            elif signal in ("BUY", "SELL") and order_mgr.position is None:
                order_mgr.enter(signal)
            time.sleep(SIGNAL_CHECK_INTERVAL)
    except KeyboardInterrupt:
        if order_mgr.position:
            order_mgr.exit("Bot shutdown")


if __name__ == "__main__":
    main()
'''


def _render_script(strategy_name: str, generated: dict[str, Any]) -> str:
    header = _HEADER.format(
        strategy_name=strategy_name,
        summary=generated["summary"],
        symbol=generated["symbol"],
        exchange=generated["exchange"],
        quantity=generated["quantity"],
        product=generated["product"],
        timeframe=generated["timeframe"],
        lookback_days=generated["lookback_days"],
        signal_function_body=generated["signal_function_body"],
    )
    source = header + _RUNTIME_TAIL
    # Final end-to-end syntax check on the fully-assembled script (the
    # signal body was already validated in isolation by
    # _validate_signal_body, but splicing can still fail if the AI's
    # returned string had unbalanced indentation relative to this
    # scaffold) -- fail closed with a clear message rather than handing
    # the user a script that will only reveal a SyntaxError later at
    # upload time.
    try:
        ast.parse(source)
    except SyntaxError as e:
        raise AiStrategyGenerationError(
            f"AI-generated code did not assemble into valid Python (line {e.lineno}: {e.msg}). "
            "Try rephrasing your strategy description."
        ) from e
    return source


def generate_strategy(user_id: str, strategy_name: str, description: str) -> dict[str, Any]:
    """Generates a complete Python strategy script from a plain-English
    description, using the calling user's own configured AI provider key
    (must already be set up at /ai-settings -- see
    database/ai_settings_db.py::get_ai_settings_decrypted).

    Returns {"source": str, "summary": str, "symbol": ..., "exchange": ...,
    ...}. Raises AiStrategyGenerationError for any failure that should
    surface as a clean user-facing message (no AI configured, provider
    call failed, AI returned something unusable)."""
    if not description or not description.strip():
        raise AiStrategyGenerationError("Please describe your strategy first.")

    settings = get_ai_settings_decrypted(user_id)
    if not settings:
        raise AiStrategyGenerationError(
            "No AI provider configured. Add your OpenAI/Anthropic/Gemini API key in "
            "AI Settings first, then try again."
        )

    provider = settings["provider"]
    api_key = settings["apiKey"]
    model = settings.get("model")
    base_url = settings.get("baseUrl")

    prompt = build_prompt(description)

    try:
        if provider == "openai":
            raw = _call_openai(api_key, model, prompt)
        elif provider == "anthropic":
            raw = _call_anthropic(api_key, model, prompt)
        elif provider == "gemini":
            raw = _call_gemini(api_key, model, prompt)
        elif provider == "custom":
            if not base_url or not model:
                raise AiStrategyGenerationError(
                    "Your custom AI provider is missing a base URL or model name -- check AI "
                    "Settings."
                )
            raw = _call_openai_compatible(api_key, model, base_url, prompt)
        else:
            raise AiStrategyGenerationError(f"Unknown AI provider: {provider}")
    except AiStrategyGenerationError:
        raise
    except AiInsightError as e:
        raise AiStrategyGenerationError(str(e)) from e
    except Exception as e:
        logger.exception(f"AI strategy generation provider call failed (provider={provider}): {e}")
        raise AiStrategyGenerationError(
            "The AI provider request failed. Check your API key in AI Settings and try again."
        ) from e

    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.warning(f"AI strategy generator returned unparseable response (provider={provider}): {e}")
        raise AiStrategyGenerationError(
            "AI returned an unexpected format. Try rephrasing your strategy description."
        ) from e

    generated = _validate_generated(parsed)
    source = _render_script(strategy_name or "AIGeneratedStrategy", generated)

    return {
        "source": source,
        "summary": generated["summary"],
        "symbol": generated["symbol"],
        "exchange": generated["exchange"],
        "quantity": generated["quantity"],
        "product": generated["product"],
        "timeframe": generated["timeframe"],
    }
