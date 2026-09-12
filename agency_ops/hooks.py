"""Strands hooks: interrupt high-stakes tools and trace every tool call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from agency_ops.tools import HIGH_STAKES_TOOLS

APPROVAL_INTERRUPT = "agency-ops-approval"


def _tool_name(event: BeforeToolCallEvent | AfterToolCallEvent) -> str:
    return str(event.tool_use.get("name") or "")


def _tool_input(event: BeforeToolCallEvent | AfterToolCallEvent) -> dict[str, Any]:
    raw = event.tool_use.get("input") or {}
    return raw if isinstance(raw, dict) else {"value": raw}


@dataclass
class ToolTrace:
    name: str
    input: dict[str, Any]
    cancelled: bool = False
    cancel_message: str | None = None
    result_text: str = ""


class ApprovalHook(HookProvider):
    """Pause on BeforeToolCallEvent for tools that can charge, send, or unpublish."""

    def __init__(self, app_name: str = "agency-ops") -> None:
        self.app_name = app_name

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.approve)

    def approve(self, event: BeforeToolCallEvent) -> None:
        name = _tool_name(event)
        if name not in HIGH_STAKES_TOOLS:
            return

        tool_input = _tool_input(event)
        approval = event.interrupt(
            f"{self.app_name}-approval",
            reason={
                "tool": name,
                "event_id": tool_input.get("event_id"),
                "risk": _risk_copy(name, tool_input),
                "input": tool_input,
            },
        )
        answer = str(approval).strip().lower()
        if answer not in {"y", "yes", "approve", "approved", "a"}:
            event.cancel_tool = f"Operator declined {name}"


class TraceHook(HookProvider):
    """Collect tool outcomes so the CLI can print a quiet day summary."""

    def __init__(self) -> None:
        self.traces: list[ToolTrace] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self.record)

    def record(self, event: AfterToolCallEvent) -> None:
        result_text = ""
        result = event.result
        if isinstance(result, dict):
            chunks = result.get("content") or []
            texts = [str(chunk.get("text", "")) for chunk in chunks if isinstance(chunk, dict)]
            result_text = " ".join(part for part in texts if part)
        self.traces.append(
            ToolTrace(
                name=_tool_name(event),
                input=_tool_input(event),
                cancelled=bool(event.cancel_message),
                cancel_message=event.cancel_message,
                result_text=result_text,
            )
        )


def _risk_copy(tool: str, tool_input: dict[str, Any]) -> str:
    if tool == "retry_n8n_workflow":
        workflow = tool_input.get("workflow_name") or tool_input.get("workflow_id")
        return f"Retrying '{workflow}' can duplicate a charge or fulfillment."
    if tool == "pause_sku":
        sku = tool_input.get("sku")
        return f"Pausing SKU {sku} hides the listing from buyers immediately."
    if tool == "send_customer_email":
        return f"This email goes to {tool_input.get('to_email')} as written."
    return "This action has customer-visible side effects."
