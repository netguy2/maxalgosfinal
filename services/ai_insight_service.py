# services/ai_insight_service.py
"""
Advisory-only "AI Insight" for the Charts page. This is the ONLY module
that talks to an external AI provider.

Design constraints (see the approved plan -- these are not incidental):
  - Advisory only. This module never places or suggests placing a
    specific order; it returns a structured sentiment/summary that the
    UI renders as a read-only card. Order placement is untouched and
    lives entirely in services/order_router_service.py's existing path.
  - Structured output only. The AI is instructed to return strict JSON
    matching AI_INSIGHT_SCHEMA below, which is re-validated here before
    ever reaching the frontend -- same "never trust the output, validate
    against a fixed contract" posture as services/custom_indicator_service.py's
    formula re-validation on every compute call. Malformed output is
    surfaced as a clean error, never rendered as if it were real.
  - Public market data only. Callers must never pass broker credentials,
    positions, or account balance into build_prompt() -- only OHLCV bars
    and already-computed indicator values the user is already looking at
    on screen. Trade-level suggestions (stop-loss/target/position size)
    are expressed in price terms and as a PERCENTAGE OF CAPITAL, computed
    from ATR/support-resistance already derived from the same public
    bars -- the actual account balance figure is applied client-side
    (blueprints/ai_insight.py never sends it to the external provider),
    so the third-party AI still never sees real account data.
  - Uses the shared utils.httpx_client.get_httpx_client() (generic,
    no-args, connection-pooled) rather than opening a new httpx.Client
    per call.
"""

import json
from typing import Any

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are an advisory market research assistant embedded in a self-hosted "
    "trading platform. You analyze the technical indicators and recent price "
    "action a user is already viewing on their own chart, plus a small set "
    "of broader market-context readings when provided (e.g. India VIX, "
    "GIFT NIFTY). You are NOT a broker, investment advisor, or execution "
    "agent -- you never instruct the user to place a specific order, and "
    "you never claim certainty about future price movement. Respond with "
    "your analysis as a single JSON object, and nothing else: no markdown "
    "fences, no prose outside the JSON.\n\n"
    "CRITICAL -- sentiment and confidence must be derived from THIS "
    "symbol's own numbers, not a generic template answer. Ground your "
    "call in specific thresholds:\n"
    "  - 'price_change_pct' (if present): the symbol's own % move over the "
    "provided window. This is the single strongest, most symbol-specific "
    "signal you have -- a clearly positive value should pull toward "
    "bullish, a clearly negative value toward bearish, and a value near "
    "zero toward neutral or low confidence, before anything else is "
    "weighed.\n"
    "  - RSI (if present): >60 leans bullish, <40 leans bearish, "
    "40-60 is neutral/no strong momentum signal.\n"
    "  - Price vs EMA/SMA/VWAP (if present): price above leans bullish, "
    "below leans bearish.\n"
    "  - confidence must vary with how CLEARLY the signals above agree or "
    "conflict -- strong agreement across price_change_pct/RSI/moving-"
    "average position warrants 70-90; a mixed or thin picture warrants "
    "40-55; near-zero movement with conflicting indicators warrants "
    "30-45 with sentiment leaning neutral. Do not default to a "
    "middle-of-the-road number out of caution -- compute it from what the "
    "data actually shows.\n"
    "  'market_context', when present, is the SAME market-wide reading "
    "(India VIX, GIFT NIFTY) on every single request regardless of which "
    "symbol is being analyzed -- it is a minor secondary modifier (e.g. "
    "nudge confidence down a few points in elevated-VIX conditions) and "
    "must NEVER be the primary reason for a bullish/bearish call, and "
    "must NEVER by itself produce the same sentiment/confidence across "
    "different symbols. If two different symbols show different "
    "price_change_pct, RSI, or moving-average positioning, they MUST get "
    "different sentiment and/or confidence values, even when "
    "market_context is identical between them. Returning the same "
    "sentiment and confidence for multiple different symbols in a row is "
    "a failure to follow these instructions -- re-check the symbol's own "
    "numbers before finalizing your answer.\n\n"
    "The JSON object must have exactly these fields:\n"
    '  "sentiment": one of "bullish", "bearish", "neutral"\n'
    '  "confidence": an integer 0-100\n'
    '  "summary": a 1-2 sentence plain-English explanation\n'
    '  "key_drivers": an array of short strings, each citing one concrete '
    "observation from the data provided (e.g. an indicator value, a price "
    "level, a market_context reading) -- do not invent data not given to "
    "you. At least one key_driver MUST reference this symbol's own price "
    "or indicator data specifically (not market_context alone). You have "
    "NOT been given any news, earnings, or fundamentals -- never cite a "
    "headline or company-specific event that wasn't explicitly provided. "
    "You MAY mention broader market risk (e.g. elevated India VIX implying "
    "wider stops, or a GIFT NIFTY premium/discount implying gap-open risk) "
    "ONLY as a secondary, minor factor when a 'market_context' field is "
    "present -- base every driver strictly on the price/indicator/"
    "market_context data given\n"
    '  "watch_level": a numeric price level worth watching (support/'
    "resistance/band edge), or null if none stands out\n"
    '  "trade_levels": if, and only if, "atr" and/or "support_resistance" '
    "data is provided in the user message, an object with:\n"
    '    "stop_loss": a numeric price level (use ATR-based distance from '
    "current price, or the nearest support/resistance level in the "
    "opposing direction of the sentiment, whichever is more conservative)\n"
    '    "target": a numeric price level (nearest meaningful '
    "support/resistance level in the direction of the sentiment, or an "
    "ATR-multiple if none is available)\n"
    '    "position_size_pct": a number 1-100, the SUGGESTED MAXIMUM percentage '
    "of available trading capital to risk on this single position, based on "
    "conviction (confidence) and volatility (ATR relative to price) -- lower "
    "for higher volatility or lower confidence, never above 25\n"
    '    "rationale": one short sentence explaining the levels chosen\n'
    "  If neither atr nor support_resistance data is provided, or the "
    "sentiment is neutral with no clear directional case, set "
    '"trade_levels" to null rather than inventing levels.'
)

_REQUIRED_FIELDS = {"sentiment", "confidence", "summary", "key_drivers", "watch_level"}
_VALID_SENTIMENTS = {"bullish", "bearish", "neutral"}
_TRADE_LEVEL_FIELDS = {"stop_loss", "target", "position_size_pct", "rationale"}


class AiInsightError(Exception):
    """Raised for any failure that should surface as a clean user-facing message."""


def build_prompt(
    symbol: str,
    exchange: str,
    interval: str,
    recent_bars: list[dict[str, Any]],
    indicator_snapshot: dict[str, Any],
    live_price: float | None = None,
    session_ohlc: dict[str, Any] | None = None,
    atr: float | None = None,
    support_resistance: dict[str, list[dict[str, Any]]] | None = None,
    market_context: dict[str, Any] | None = None,
) -> str:
    """Builds the user-turn prompt from already-computed, public market
    data only. `recent_bars` should be a short window (e.g. last 20 bars)
    to keep token cost bounded -- callers must not pass full history.
    `indicator_snapshot` is a flat dict of the LAST value of whichever
    indicators the user currently has enabled on their chart, e.g.
    {"RSI_14": 71.2, "EMA_20": 1234.5, "MACD": {"macd": 3.1, "signal": 2.8}}.
    `live_price` and `session_ohlc` give the model where price actually is
    right now, since `recent_bars`' last entry is only the last CLOSED
    candle -- without this the model was reasoning as if the market froze
    at the previous bar close, which could be stale by up to one full
    interval. `atr` (current Average True Range) and `support_resistance`
    (from services/indicator_series_service.py's real swing-point
    detection, not a fixed formula) are the inputs the model needs to
    ground stop-loss/target suggestions in something more concrete than a
    guess -- both are computed server-side from the same public bars,
    independent of whichever overlay indicators the user has toggled on
    for display. `market_context` is a small, best-effort bundle of
    broader market-risk readings (currently: India VIX level, GIFT NIFTY
    premium/discount vs the prior NIFTY close) fetched live via the same
    public broker-quote API the Charts page itself uses -- NOT news or
    fundamentals. Any reading that failed to fetch (broker/symbol doesn't
    carry it) is simply omitted, never fabricated."""
    payload = {
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "recent_bars": recent_bars,
        "indicators": indicator_snapshot,
    }
    # Explicit, unambiguous %-move over the provided window -- computed
    # server-side rather than left for the model to derive from
    # recent_bars, so every request has one concrete, symbol-specific
    # number to ground its sentiment call in. This is the fix for the
    # model previously converging on the same generic verdict for every
    # symbol: without a clear numeric anchor, a thin/ambiguous indicator
    # snapshot made it easy to default to a middle-of-the-road answer.
    if recent_bars:
        window_open = recent_bars[0].get("close") or recent_bars[0].get("open")
        window_close = live_price if live_price is not None else recent_bars[-1].get("close")
        if window_open and window_close:
            payload["price_change_pct"] = round((window_close - window_open) / window_open * 100, 2)
    if live_price is not None:
        payload["live_price"] = live_price
    if session_ohlc:
        payload["session_ohlc"] = session_ohlc
    if atr is not None:
        payload["atr"] = atr
    if support_resistance and (
        support_resistance.get("support") or support_resistance.get("resistance")
    ):
        payload["support_resistance"] = support_resistance
    if market_context:
        payload["market_context"] = market_context
    return (
        "Analyze this market data and respond with the JSON object described "
        "in your instructions. 'price_change_pct' (if present) is THIS "
        "SYMBOL's own %% price change over the provided window -- your "
        "single strongest, most symbol-specific signal; ground your "
        "sentiment and confidence in this number first, per your "
        "instructions. 'live_price' (if present) is the current "
        "quoted price, more recent than the last candle in 'recent_bars' -- "
        "weight it as the true current price. 'session_ohlc' (if present) "
        "is today's open/high/low and the previous close. 'atr' (if present) "
        "is the current Average True Range -- a measure of recent volatility "
        "in price units, useful for sizing a stop-loss distance. "
        "'support_resistance' (if present) lists real detected swing-based "
        "levels with touch counts (more touches = stronger level), not a "
        "fixed pivot formula. 'market_context' (if present) holds broader "
        "market-risk readings, e.g. 'india_vix' (the current India VIX "
        "level -- higher means the broader market expects more volatility, "
        "a reason to widen stops or lower conviction/position size "
        "regardless of this symbol's own indicators) and "
        "'gift_nifty_change_pct' (GIFT NIFTY's % change vs the prior NIFTY "
        "close -- a positive/negative reading signals likely gap-up/"
        "gap-down risk at the next session open). These are quantitative "
        "market-wide readings, not news or fundamentals -- treat them the "
        "same as any other data field, not as an off-chart source.\n\n"
        + json.dumps(payload, default=str)
    )


def _extract_json(text: str) -> dict[str, Any]:
    """AI providers sometimes wrap JSON in markdown fences, or (some models,
    e.g. Llama-family models on OpenAI-compatible endpoints like Groq, more
    often than GPT-4o/Claude) prepend conversational preamble text before
    the fence/JSON despite instructions not to -- strip both before
    parsing, but never eval or otherwise execute the response.
    json.loads is the only thing ever called on the extracted text."""
    stripped = text.strip()

    # Strip a leading markdown fence wherever it starts, not just at
    # position 0 -- handles "Sure, here you go:\n```json\n{...}\n```".
    fence_start = stripped.find("```")
    if fence_start != -1:
        after_fence = stripped[fence_start + 3 :]
        if after_fence.startswith("json"):
            after_fence = after_fence[4:]
        fence_end = after_fence.find("```")
        if fence_end != -1:
            stripped = after_fence[:fence_end].strip()
        else:
            stripped = after_fence.strip()
        return json.loads(stripped)

    # No fence at all -- some models still prepend prose before a bare
    # JSON object. Locate the first '{' and let json.loads parse from
    # there, using raw_decode so trailing prose/whitespace after the
    # object doesn't cause a spurious "Extra data" error.
    brace_start = stripped.find("{")
    if brace_start > 0:
        stripped = stripped[brace_start:]
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(stripped)
    return obj


def _validate_insight(
    data: Any,
    live_price: float | None = None,
    atr: float | None = None,
    support_resistance: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AiInsightError("AI returned an unexpected format")
    if not _REQUIRED_FIELDS.issubset(data.keys()):
        raise AiInsightError("AI returned an unexpected format")
    if data["sentiment"] not in _VALID_SENTIMENTS:
        raise AiInsightError("AI returned an unexpected format")
    try:
        confidence = int(data["confidence"])
    except (TypeError, ValueError) as e:
        raise AiInsightError("AI returned an unexpected format") from e
    confidence = max(0, min(100, confidence))
    if not isinstance(data["key_drivers"], list):
        raise AiInsightError("AI returned an unexpected format")
    key_drivers = [str(d) for d in data["key_drivers"]][:10]
    watch_level = data.get("watch_level")
    if watch_level is not None:
        try:
            watch_level = float(watch_level)
        except (TypeError, ValueError):
            watch_level = None

    model_shape = _validate_trade_levels(data.get("trade_levels"))
    # trade_levels' numbers are always recomputed from real data -- see
    # compute_deterministic_trade_levels' docstring. The model's own
    # trade_levels output is used only as a signal that IT thought a
    # directional case existed (worth attempting a computation) and, if
    # shape-valid, for its rationale sentence.
    trade_levels = (
        compute_deterministic_trade_levels(
            sentiment=data["sentiment"],
            confidence=confidence,
            live_price=live_price,
            atr=atr,
            support_resistance=support_resistance,
            model_rationale=model_shape["rationale"] if model_shape else None,
        )
        if model_shape is not None
        else None
    )

    return {
        "sentiment": data["sentiment"],
        "confidence": confidence,
        "summary": str(data["summary"])[:1000],
        "key_drivers": key_drivers,
        "watch_level": watch_level,
        "trade_levels": trade_levels,
    }


def _validate_trade_levels(raw: Any) -> dict[str, Any] | None:
    """Validates the optional trade_levels object the model returned.
    Malformed or partial data degrades to None (the UI simply omits the
    section) rather than raising -- trade_levels is an enhancement to the
    core sentiment/summary response, not a required field, so a bad
    trade_levels payload should never turn an otherwise-valid insight into
    a full AiInsightError.

    This only validates SHAPE. The actual stop_loss/target/position_size_pct
    numbers are discarded and recomputed deterministically by
    compute_deterministic_trade_levels() -- see that function's docstring
    for why: an LLM asked to "use ATR-based distance" can write any
    plausible-looking number into the JSON field, and nothing here could
    tell a genuinely ATR-derived level apart from one the model simply
    invented. Only `rationale` (free text, not a number a trader could act
    on directly) survives from the model's own output."""
    if not isinstance(raw, dict) or not _TRADE_LEVEL_FIELDS.issubset(raw.keys()):
        return None
    try:
        float(raw["stop_loss"])
        float(raw["target"])
        float(raw["position_size_pct"])
    except (TypeError, ValueError):
        return None
    return {"rationale": str(raw["rationale"])[:300]}


def compute_deterministic_trade_levels(
    sentiment: str,
    confidence: int,
    live_price: float | None,
    atr: float | None,
    support_resistance: dict[str, list[dict[str, Any]]] | None,
    model_rationale: str | None,
) -> dict[str, Any] | None:
    """Computes stop_loss/target/position_size_pct directly from the real,
    already-computed ATR and support/resistance data -- the same inputs the
    prompt hands the model -- instead of trusting the model to have done
    that arithmetic correctly inside a JSON response.

    Why this exists: the model is EXCELLENT at reading a chart's story
    (sentiment, which indicators agree, how to phrase a rationale) and
    UNRELIABLE at precise numeric derivation. Telling it "use ATR-based
    distance from current price, or the nearest support/resistance level"
    in the system prompt does not guarantee the number it writes into
    stop_loss/target actually equals that computation -- there is nothing
    server-side that could tell a genuinely-derived level apart from a
    plausible-looking invented one, and a trader seeing a specific rupee
    figure reasonably assumes it was calculated, not guessed. So the
    figures shown are now always real arithmetic on real data; the model
    only contributes qualitative sentiment/summary/key_drivers and (if it
    returned trade_levels at all) a short rationale sentence.

    Returns None when there isn't enough real data to ground a level in
    (no live_price, no ATR AND no support/resistance, or a neutral
    sentiment with no directional case) -- same "omit rather than invent"
    rule the model itself was instructed to follow.
    """
    if sentiment == "neutral" or live_price is None or live_price <= 0:
        return None
    if atr is None and not support_resistance:
        return None

    bullish = sentiment == "bullish"
    resistance_levels = sorted(
        (lv["price"] for lv in (support_resistance or {}).get("resistance", []) if lv.get("price")),
    )
    support_levels = sorted(
        (lv["price"] for lv in (support_resistance or {}).get("support", []) if lv.get("price")),
        reverse=True,
    )

    # Target: nearest real level in the direction of the call; fall back to
    # a 2x-ATR projection only when no detected level exists on that side.
    if bullish:
        nearer_resistance = next((p for p in resistance_levels if p > live_price), None)
        target = (
            nearer_resistance
            if nearer_resistance is not None
            else (live_price + 2 * atr if atr else None)
        )
    else:
        nearer_support = next((p for p in support_levels if p < live_price), None)
        target = (
            nearer_support
            if nearer_support is not None
            else (live_price - 2 * atr if atr else None)
        )

    # Stop-loss: the ATR-based distance and the nearest opposing real level
    # are both computed, and the MORE CONSERVATIVE (tighter to price) one
    # wins -- matches the system prompt's own stated rule, but now actually
    # enforced by arithmetic instead of asked of the model.
    atr_stop = (live_price - atr if bullish else live_price + atr) if atr else None
    if bullish:
        opposing_support = next((p for p in support_levels if p < live_price), None)
        candidates = [p for p in (atr_stop, opposing_support) if p is not None]
        stop_loss = max(candidates) if candidates else None
    else:
        opposing_resistance = next((p for p in resistance_levels if p > live_price), None)
        candidates = [p for p in (atr_stop, opposing_resistance) if p is not None]
        stop_loss = min(candidates) if candidates else None

    if stop_loss is None or target is None:
        return None

    # Position size scales down with lower confidence and with higher
    # relative volatility (ATR as a % of price) -- both real, both already
    # available -- capped at 25% of capital on any single position
    # regardless of how confident the read is.
    risk_pct = abs(live_price - stop_loss) / live_price * 100 if live_price else 0
    size_from_confidence = max(1.0, min(25.0, confidence / 4))
    size_from_volatility = max(1.0, min(25.0, 15.0 / risk_pct)) if risk_pct > 0 else 25.0
    position_size_pct = round(min(size_from_confidence, size_from_volatility), 1)

    return {
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "position_size_pct": position_size_pct,
        "rationale": model_rationale
        or (
            "ATR/support-resistance derived level."
            if atr or support_resistance
            else "Estimated from available data."
        ),
    }


def _call_openai_compatible(
    api_key: str, model: str, base_url: str, prompt: str, system_prompt: str = SYSTEM_PROMPT
) -> str:
    client = get_httpx_client()
    response = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
    )
    response.raise_for_status()
    body = response.json()
    return body["choices"][0]["message"]["content"]


def _call_openai(api_key: str, model: str, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    return _call_openai_compatible(
        api_key, model or "gpt-4o-mini", "https://api.openai.com/v1", prompt, system_prompt
    )


def _call_anthropic(
    api_key: str, model: str, prompt: str, system_prompt: str = SYSTEM_PROMPT
) -> str:
    client = get_httpx_client()
    response = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model or "claude-3-5-haiku-latest",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    body = response.json()
    return body["content"][0]["text"]


def _call_gemini(api_key: str, model: str, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    client = get_httpx_client()
    model_name = model or "gemini-1.5-flash"
    response = client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        f"?key={api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        },
    )
    response.raise_for_status()
    body = response.json()
    return body["candidates"][0]["content"]["parts"][0]["text"]


def get_ai_insight(
    provider: str,
    api_key: str,
    model: str | None,
    base_url: str | None,
    symbol: str,
    exchange: str,
    interval: str,
    recent_bars: list[dict[str, Any]],
    indicator_snapshot: dict[str, Any],
    live_price: float | None = None,
    session_ohlc: dict[str, Any] | None = None,
    atr: float | None = None,
    support_resistance: dict[str, list[dict[str, Any]]] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calls the configured provider and returns a validated insight dict.
    Raises AiInsightError for any failure that should surface as a clean
    user-facing message (never a raw exception/stack trace)."""
    prompt = build_prompt(
        symbol,
        exchange,
        interval,
        recent_bars,
        indicator_snapshot,
        live_price,
        session_ohlc,
        atr,
        support_resistance,
        market_context,
    )

    try:
        if provider == "openai":
            raw = _call_openai(api_key, model, prompt)
        elif provider == "anthropic":
            raw = _call_anthropic(api_key, model, prompt)
        elif provider == "gemini":
            raw = _call_gemini(api_key, model, prompt)
        elif provider == "custom":
            if not base_url:
                raise AiInsightError("Custom provider requires a base URL")
            # No sane universal default model exists across arbitrary
            # OpenAI-compatible endpoints (Groq, local Ollama, etc.) --
            # falling back to "gpt-4o-mini" here would silently send a
            # meaningless model name to a non-OpenAI provider and fail with
            # a confusing "model not found" instead of a clear message.
            if not model:
                raise AiInsightError(
                    "Enter the model name your custom endpoint expects (e.g. "
                    "llama-3.3-70b-versatile for Groq) in AI Settings"
                )
            raw = _call_openai_compatible(api_key, model, base_url, prompt)
        else:
            raise AiInsightError(f"Unknown provider: {provider}")
    except AiInsightError:
        raise
    except Exception as e:
        # Never leak provider response bodies (may echo the key back in some
        # error formats) -- log full detail server-side, return a generic message.
        logger.exception(f"AI provider call failed (provider={provider}): {e}")
        raise AiInsightError(
            "The AI provider request failed. Check your API key and try again."
        ) from e

    try:
        parsed = _extract_json(raw)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        logger.warning(f"AI provider returned unparseable response (provider={provider}): {e}")
        raise AiInsightError("AI returned an unexpected format") from e

    return _validate_insight(parsed, live_price, atr, support_resistance)
