"""Deterministic classification used by the offline demo model and tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agency_ops.events import OpsEvent

AUTO_HANDLE = "auto_handle"
NEEDS_HUMAN = "needs_human"

TRANSIENT_ERRORS = (
    "etimedout",
    "timeout",
    "timed out",
    "econnreset",
    "429",
    "rate limit",
    "503",
    "502",
    "504",
)

PAYMENT_HINTS = (
    "stripe",
    "checkout",
    "payment",
    "charge",
    "fulfill",
    "invoice",
    "refund",
)

SENSITIVE_LEAD_HINTS = (
    "refund",
    "chargeback",
    "legal",
    "lawyer",
    "enterprise",
    "nda",
    "urgent cancel",
)


@dataclass(frozen=True)
class PlannedTool:
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ActionPlan:
    classification: str
    rationale: str
    tools: list[PlannedTool]


def _contains_token(blob: str, token: str) -> bool:
    """Match a phrase as a whole word so 'nda' does not hit 'standard'."""
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w])", blob) is not None


def _text_blob(event: OpsEvent) -> str:
    payload = event.payload
    parts = [
        event.title,
        event.type,
        event.source,
        event.severity,
        str(payload.get("error") or ""),
        str(payload.get("workflow") or ""),
        str(payload.get("action_hint") or ""),
        str(payload.get("intent") or ""),
        str(payload.get("message") or ""),
        str(payload.get("stakes") or ""),
        str(payload.get("side_effects") or ""),
        str(payload.get("note") or ""),
    ]
    return " ".join(parts).lower()


def classify(event: OpsEvent) -> tuple[str, str]:
    """Return (classification, rationale) for an event."""
    blob = _text_blob(event)
    payload = event.payload

    if event.type == "sku_issue":
        units = payload.get("units")
        hint = str(payload.get("action_hint") or "").lower()
        if units == 0 or hint in {"unpublish", "pause", "takedown"}:
            return NEEDS_HUMAN, "Sold-out or takedown — pausing a live SKU is irreversible to buyers."
        return AUTO_HANDLE, "Stock is low but still available — log it and remind the operator to reorder."

    if event.type == "new_lead":
        if any(_contains_token(blob, token) for token in SENSITIVE_LEAD_HINTS):
            return NEEDS_HUMAN, "Lead mentions refund, legal, or enterprise stakes — a human should send."
        return AUTO_HANDLE, "Standard inbound inquiry — draft a reply, do not send it."

    if event.type == "workflow_failure":
        side_effects = str(payload.get("side_effects") or "").lower()
        risky_side_effects = side_effects not in {"", "none", "null"}
        paymentish = any(_contains_token(blob, token) for token in PAYMENT_HINTS)
        authish = "401" in blob or "403" in blob or "unauthorized" in blob or "forbidden" in blob
        if authish or paymentish or risky_side_effects:
            return NEEDS_HUMAN, "Auth or payment-path failure — a retry can double-charge or double-fulfill."
        if any(token in blob for token in TRANSIENT_ERRORS):
            return AUTO_HANDLE, "Transient automation failure with no customer side effects — log and remind."
        return NEEDS_HUMAN, "Unrecognized workflow failure — hold for the operator."

    if event.severity == "high":
        return NEEDS_HUMAN, "Marked high severity without a safe auto-handle pattern."
    return AUTO_HANDLE, "Low-stakes event — log it and stay quiet."


def plan_actions(event: OpsEvent) -> ActionPlan:
    """Choose the smallest set of tools for this event."""
    classification, rationale = classify(event)
    payload = event.payload
    tools: list[PlannedTool] = [
        PlannedTool(
            name="log_ops_event",
            input={
                "event_id": event.id,
                "summary": f"{event.title} — {rationale}",
                "classification": classification,
                "source": event.source,
            },
        )
    ]

    if event.type == "new_lead" and classification == AUTO_HANDLE:
        name = str(payload.get("name") or "there")
        email = str(payload.get("email") or "unknown@example.com")
        intent = str(payload.get("intent") or "your project")
        tools.append(
            PlannedTool(
                name="draft_reply",
                input={
                    "event_id": event.id,
                    "to_name": name,
                    "to_email": email,
                    "subject": f"Re: {intent}",
                    "body": (
                        f"Hi {name.split()[0]},\n\n"
                        f"Thanks for reaching out about {intent}. "
                        "I have a couple of openings this month — "
                        "happy to send a short scope and range if you share a timeline "
                        "and any must-have pages.\n\n"
                        "— Avery"
                    ),
                },
            )
        )

    if event.type == "new_lead" and classification == NEEDS_HUMAN:
        email = str(payload.get("email") or "unknown@example.com")
        tools.append(
            PlannedTool(
                name="send_customer_email",
                input={
                    "event_id": event.id,
                    "to_email": email,
                    "subject": f"Re: {payload.get('intent') or event.title}",
                    "body": str(payload.get("message") or "Following up on your request."),
                },
            )
        )

    if event.type == "workflow_failure" and classification == AUTO_HANDLE:
        tools.append(
            PlannedTool(
                name="queue_reminder",
                input={
                    "event_id": event.id,
                    "when": "+2h",
                    "message": f"Check whether n8n '{payload.get('workflow')}' recovered after {payload.get('error')}.",
                    "channel": "ops",
                },
            )
        )

    if event.type == "workflow_failure" and classification == NEEDS_HUMAN:
        tools.append(
            PlannedTool(
                name="retry_n8n_workflow",
                input={
                    "event_id": event.id,
                    "workflow_id": str(payload.get("workflow_id") or "unknown"),
                    "workflow_name": str(payload.get("workflow") or event.title),
                    "reason": rationale,
                },
            )
        )

    if event.type == "sku_issue" and classification == AUTO_HANDLE:
        tools.append(
            PlannedTool(
                name="queue_reminder",
                input={
                    "event_id": event.id,
                    "when": "+1d",
                    "message": (
                        f"Reorder {payload.get('product')} ({payload.get('sku')}): "
                        f"{payload.get('units')} left, threshold {payload.get('threshold')}."
                    ),
                    "channel": "ops",
                },
            )
        )

    if event.type == "sku_issue" and classification == NEEDS_HUMAN:
        tools.append(
            PlannedTool(
                name="pause_sku",
                input={
                    "event_id": event.id,
                    "sku": str(payload.get("sku") or "unknown"),
                    "product": str(payload.get("product") or event.title),
                    "reason": rationale,
                },
            )
        )

    return ActionPlan(classification=classification, rationale=rationale, tools=tools)


def quiet_summary(event: OpsEvent, tool_results: list[dict[str, Any]]) -> str:
    """One-line operator-facing summary after tools finish."""
    cancelled = [item for item in tool_results if item.get("cancelled")]
    executed = [item.get("name") for item in tool_results if not item.get("cancelled")]
    if cancelled:
        names = ", ".join(item.get("name", "action") for item in cancelled)
        return f"Held {names} on {event.id} — you declined. Nothing left the building."
    if "draft_reply" in executed:
        return f"Drafted a reply for {event.payload.get('name') or 'the lead'}. Not sent."
    if "retry_n8n_workflow" in executed:
        return f"Retried n8n '{event.payload.get('workflow')}' after your approval."
    if "pause_sku" in executed:
        return f"Paused SKU {event.payload.get('sku')} after your approval."
    if "send_customer_email" in executed:
        return f"Sent the customer email after your approval."
    if "queue_reminder" in executed:
        return f"Logged and queued a reminder. No decision needed."
    return f"Logged {event.id}. Staying quiet."
