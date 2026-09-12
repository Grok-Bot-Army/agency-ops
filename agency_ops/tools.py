"""Strands @tool functions for quiet auto-handle and gated high-stakes actions."""

from __future__ import annotations

from strands import tool

from agency_ops import store

# Tools that must pause for a human via BeforeToolCallEvent.interrupt.
HIGH_STAKES_TOOLS = frozenset(
    {
        "retry_n8n_workflow",
        "pause_sku",
        "send_customer_email",
    }
)


@tool
def log_ops_event(event_id: str, summary: str, classification: str, source: str) -> str:
    """Record an ops event in the local log. Safe — never notifies a customer.

    Args:
        event_id: Unique event identifier from the fixture.
        summary: One-line description of what happened and what you decided.
        classification: Either auto_handle or needs_human.
        source: Origin system such as n8n, gumroad, or intake.
    """
    path = store.log_event(
        {
            "event_id": event_id,
            "summary": summary,
            "classification": classification,
            "source": source,
        }
    )
    return f"Logged {event_id} as {classification} → {path}"


@tool
def draft_reply(event_id: str, to_name: str, to_email: str, subject: str, body: str) -> str:
    """Draft a lead or customer reply and save it locally. Does not send.

    Args:
        event_id: Related event id.
        to_name: Recipient display name.
        to_email: Recipient email.
        subject: Email subject line.
        body: Full draft body the operator can edit before sending.
    """
    path = store.save_draft(
        {
            "event_id": event_id,
            "to_name": to_name,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "status": "draft",
        }
    )
    return f"Draft saved for {to_name} <{to_email}> → {path}"


@tool
def queue_reminder(event_id: str, when: str, message: str, channel: str = "ops") -> str:
    """Queue a follow-up reminder for the operator. Safe — does not notify customers.

    Args:
        event_id: Related event id.
        when: When to fire, ISO-8601 or a relative hint like +2h.
        message: Reminder text.
        channel: Destination such as ops or slack.
    """
    path = store.queue_reminder(
        {
            "event_id": event_id,
            "when": when,
            "message": message,
            "channel": channel,
            "status": "queued",
        }
    )
    return f"Reminder queued ({when}, {channel}) → {path}"


@tool
def retry_n8n_workflow(event_id: str, workflow_id: str, workflow_name: str, reason: str) -> str:
    """Retry a failed n8n workflow. HIGH STAKES — can duplicate charges or fulfillments.

    Args:
        event_id: Related event id.
        workflow_id: n8n workflow id.
        workflow_name: Human-readable workflow name.
        reason: Why a retry is justified after the failure.
    """
    path = store.record_gated_action(
        {
            "action": "retry_n8n_workflow",
            "event_id": event_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "reason": reason,
            "status": "executed",
        }
    )
    return f"Retried n8n workflow {workflow_name} ({workflow_id}) → {path}"


@tool
def pause_sku(event_id: str, sku: str, product: str, reason: str) -> str:
    """Unpublish or pause a Gumroad SKU. HIGH STAKES — buyers stop seeing the listing.

    Args:
        event_id: Related event id.
        sku: SKU code.
        product: Product display name.
        reason: Why the SKU should be paused.
    """
    path = store.record_gated_action(
        {
            "action": "pause_sku",
            "event_id": event_id,
            "sku": sku,
            "product": product,
            "reason": reason,
            "status": "executed",
        }
    )
    return f"Paused SKU {sku} ({product}) → {path}"


@tool
def send_customer_email(event_id: str, to_email: str, subject: str, body: str) -> str:
    """Send an email to a customer. HIGH STAKES — it leaves the building.

    Args:
        event_id: Related event id.
        to_email: Recipient email.
        subject: Subject line.
        body: Message body that will be sent as-is.
    """
    path = store.record_gated_action(
        {
            "action": "send_customer_email",
            "event_id": event_id,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "status": "executed",
        }
    )
    return f"Sent email to {to_email} ({subject}) → {path}"


ALL_TOOLS = [
    log_ops_event,
    draft_reply,
    queue_reminder,
    retry_n8n_workflow,
    pause_sku,
    send_customer_email,
]
