"""Deterministic custom Model so the demo runs without AWS credentials."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, AsyncIterable, Iterable
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel
from strands.models import Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

from agency_ops.events import OpsEvent
from agency_ops.policy import PlannedTool, plan_actions, quiet_summary

T = TypeVar("T", bound=BaseModel)

OPS_EVENT_RE = re.compile(r"```ops-event\s*(.*?)\s*```", re.DOTALL)


class OfflinePolicyModel(Model):
    """Scripted model that classifies fixtures and emits the matching tool calls.

    Used for the default local demo and tests. Live Bedrock is opt-in via --live.
    """

    def __init__(self) -> None:
        self.config: dict[str, Any] = {
            "model_id": "agency-ops-offline-policy",
            "provider": "offline",
        }

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self.config

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        if False:  # pragma: no cover - interface requirement
            yield {}

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        event = _latest_event(messages)
        tool_results = _latest_tool_results(messages)
        if tool_results:
            text = quiet_summary(event, tool_results) if event else "Done."
            for chunk in _message_events([{"text": text}]):
                yield chunk
            return

        if event is None:
            for chunk in _message_events([{"text": "No ops event found. Standing by."}]):
                yield chunk
            return

        plan = plan_actions(event)
        content: list[dict[str, Any]] = []
        for planned in plan.tools:
            content.append(_tool_use_block(planned))
        for chunk in _message_events(content):
            yield chunk


def _tool_use_block(planned: PlannedTool) -> dict[str, Any]:
    return {
        "toolUse": {
            "toolUseId": f"tooluse_{planned.name}_{uuid4().hex[:8]}",
            "name": planned.name,
            "input": planned.input,
        }
    }


def _message_events(content: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    stop_reason = "end_turn"
    yield {"messageStart": {"role": "assistant"}}
    for block in content:
        if "text" in block:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
            yield {"contentBlockStop": {}}
        if "toolUse" in block:
            stop_reason = "tool_use"
            tool = block["toolUse"]
            yield {
                "contentBlockStart": {
                    "start": {
                        "toolUse": {
                            "name": tool["name"],
                            "toolUseId": tool["toolUseId"],
                        }
                    }
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool["input"])}}}}
            yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": stop_reason}}


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and "text" in block:
            parts.append(str(block["text"]))
    return "\n".join(parts)


def _latest_event(messages: Messages) -> OpsEvent | None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = _extract_text(message.get("content"))
        match = OPS_EVENT_RE.search(text)
        if not match:
            continue
        raw = json.loads(match.group(1))
        return OpsEvent(
            id=str(raw["id"]),
            ts=str(raw.get("ts") or ""),
            source=str(raw.get("source") or ""),
            type=str(raw.get("type") or ""),
            title=str(raw.get("title") or raw["id"]),
            severity=str(raw.get("severity") or "medium"),
            payload=raw.get("payload") or {},
        )
    return None


def _latest_tool_results(messages: Messages) -> list[dict[str, Any]] | None:
    if not messages:
        return None
    last = messages[-1]
    if last.get("role") != "user":
        return None
    content = last.get("content") or []
    if not isinstance(content, list):
        return None
    results: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict) or "toolResult" not in block:
            continue
        result = block["toolResult"]
        status = str(result.get("status") or "success")
        texts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and "text" in item:
                texts.append(str(item["text"]))
        name = ""
        # Recover the tool name from the preceding assistant toolUse when possible.
        if len(messages) >= 2:
            prior = messages[-2]
            for prior_block in prior.get("content") or []:
                if not isinstance(prior_block, dict):
                    continue
                tool_use = prior_block.get("toolUse") or {}
                if tool_use.get("toolUseId") == result.get("toolUseId"):
                    name = str(tool_use.get("name") or "")
        cancelled = status != "success" or "declined" in " ".join(texts).lower()
        results.append({"name": name, "cancelled": cancelled, "text": " ".join(texts)})
    return results or None
