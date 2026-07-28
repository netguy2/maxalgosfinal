"""Webhook ingestion: audit logging + duplicate suppression.

One entry point (`ingest`) that every webhook route calls before doing any work.
It records the delivery for audit and tells the caller whether this request is a
duplicate that should be suppressed.

Why suppression matters: signal sources (TradingView, ChartInk, GoCharting) retry
on timeout or 5xx. Every webhook path in this codebase places real broker orders,
so an un-deduped retry is a second live trade with real money. The webhook route
also returns 200 *before* the order is placed (processing is async), which makes
retries more likely to be triggered by a slow — not failed — request.

Dedup is deliberately conservative: only byte-identical payloads to the same
webhook inside a short window are suppressed. A source that varies its body per
retry (changing timestamp/nonce) is not deduped, because we cannot prove those
are repeats rather than genuine rapid-fire signals.

The audit write is best-effort and never raises — an audit failure must not stop
a trade, and must not turn into a 500 for the caller.
"""

import os

from database.webhook_delivery_db import (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE,
    OUTCOME_FAILED,
    OUTCOME_PROCESSED,
    OUTCOME_REJECTED,
    append_stage,
    compute_payload_hash,
    find_recent_duplicate,
    record_received,
    update_outcome,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def _dedup_window_seconds():
    """Duplicate-suppression window, in seconds.

    Read per-call rather than cached at import so operators can change it via
    .env without a code change, and so tests can override it. 0 disables
    suppression entirely (deliveries are still logged).

    Default of 5s matches the window specified in
    docs/plans/2026-02-06-strategy-risk-management-prd.md.
    """
    try:
        return float(os.getenv("WEBHOOK_DEDUP_WINDOW_SECONDS", "5"))
    except (TypeError, ValueError):
        logger.warning("Invalid WEBHOOK_DEDUP_WINDOW_SECONDS; falling back to 5s")
        return 5.0


class DeliveryHandle:
    """Result of ingesting one webhook request.

    `delivery_id` is None when the audit write failed — callers must treat all
    the recording methods as no-ops in that case rather than branching on it.
    """

    __slots__ = ("delivery_id", "is_duplicate", "duplicate_of")

    def __init__(self, delivery_id=None, is_duplicate=False, duplicate_of=None):
        self.delivery_id = delivery_id
        self.is_duplicate = is_duplicate
        self.duplicate_of = duplicate_of

    def stage(self, stage, outcome, detail=None, ms=None):
        """Record one processing-stage decision against this delivery."""
        append_stage(self.delivery_id, stage, outcome, detail=detail, ms=ms)

    def accepted(self, detail=None):
        """Signal passed validation and was queued for processing.

        Not terminal — the async worker later calls processed()/failed().
        """
        update_outcome(self.delivery_id, OUTCOME_ACCEPTED, reason_detail=detail, completed=False)

    def rejected(self, reason_code, detail=None):
        """Signal was refused before reaching the engine (terminal)."""
        update_outcome(
            self.delivery_id, OUTCOME_REJECTED, reason_code=reason_code, reason_detail=detail
        )

    def processed(self, order_ids=None, detail=None):
        """Signal completed processing (terminal)."""
        update_outcome(
            self.delivery_id,
            OUTCOME_PROCESSED,
            reason_detail=detail,
            order_ids=order_ids,
        )

    def failed(self, reason_code, detail=None):
        """Signal errored during processing (terminal)."""
        update_outcome(
            self.delivery_id, OUTCOME_FAILED, reason_code=reason_code, reason_detail=detail
        )


def ingest(
    webhook_id,
    payload,
    source_type="strategy",
    strategy_id=None,
    strategy_name=None,
    user_id=None,
    signal=None,
    remote_ip=None,
    dedup=True,
):
    """Record an inbound webhook request and check it for duplication.

    Returns a DeliveryHandle. When `handle.is_duplicate` is True the caller
    should NOT process the signal — the request has already been logged with
    outcome "duplicate" and the caller need only return its response.

    Args:
        webhook_id: The webhook identifier from the URL.
        payload: The parsed JSON body (dict).
        source_type: Which webhook subsystem ("strategy", "chartink", "flow").
        strategy_id / strategy_name / user_id: Denormalized context for display.
        signal: The extracted action/signal string, when already known.
        remote_ip: Requesting IP, for audit.
        dedup: Set False for endpoints where identical repeat payloads are
            legitimate and must not be suppressed.

    Never raises.
    """
    try:
        payload_hash = compute_payload_hash(webhook_id, payload)

        duplicate_of = None
        if dedup:
            window = _dedup_window_seconds()
            if window > 0:
                duplicate_of = find_recent_duplicate(webhook_id, payload_hash, window)

        delivery_id = record_received(
            webhook_id=webhook_id,
            payload=payload,
            source_type=source_type,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            user_id=user_id,
            signal=signal,
            remote_ip=remote_ip,
            payload_hash=payload_hash,
        )

        if duplicate_of:
            logger.warning(
                f"Duplicate webhook signal suppressed for {source_type} webhook "
                f"{webhook_id} (matches delivery {duplicate_of})"
            )
            update_outcome(
                delivery_id,
                OUTCOME_DUPLICATE,
                reason_code="duplicate_signal",
                reason_detail=(
                    f"Identical payload received within "
                    f"{_dedup_window_seconds()}s (delivery {duplicate_of})"
                ),
            )
            return DeliveryHandle(
                delivery_id=delivery_id, is_duplicate=True, duplicate_of=duplicate_of
            )

        return DeliveryHandle(delivery_id=delivery_id)

    except Exception:
        # Ingestion must never break the webhook. Fall through with an empty
        # handle so processing continues un-audited rather than failing closed:
        # dropping a real trading signal is worse than losing its audit row.
        logger.exception("Webhook delivery ingestion failed; continuing without audit")
        return DeliveryHandle()
