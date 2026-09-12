"""Build the Agency Ops Strands agent."""

from __future__ import annotations

import os
from dataclasses import dataclass

from strands import Agent
from strands.models import BedrockModel

from agency_ops.hooks import ApprovalHook, TraceHook
from agency_ops.offline_model import OfflinePolicyModel
from agency_ops.tools import ALL_TOOLS

SYSTEM_PROMPT = """
You are Agency Ops, a background desk for a solo operator running a small digital
agency (n8n automations, Gumroad SKUs, inbound leads).

Your job is to absorb repetitive ops busywork and stay quiet. Only surface a
human when an action could charge a card, send a customer-visible message, or
change a live listing.

Classification
- auto_handle: transient n8n failures (timeout/5xx/rate limit) with no payment
  side effects; standard inbound leads; low stock that is still > 0.
- needs_human: auth failures (401/403), payment/fulfillment workflows, refunds,
  legal/enterprise leads, sold-out SKUs, anything that retries a side-effecting
  workflow.

Tools
- Safe (call freely): log_ops_event, draft_reply, queue_reminder.
- High stakes (the runtime will pause for approval before they run):
  retry_n8n_workflow, pause_sku, send_customer_email.
- Always log_ops_event first.
- Never claim you sent, retried, or unpublished unless you called that tool.
- Draft replies. Do not send them unless the lead is a refund/legal/enterprise
  case, and then use send_customer_email so the operator can approve.
- Final message: one quiet line. No preamble, no bullet dump.
""".strip()


@dataclass
class OpsAgent:
    """Agent plus the trace hook the CLI reads after each event."""

    agent: Agent
    tracer: TraceHook
    offline: bool


def build_ops_agent(*, live: bool = False, callback_handler=None) -> OpsAgent:
    """Construct a Strands agent with tools + approval hooks.

    Default is the offline policy model (no AWS). Pass live=True to use Bedrock.
    """
    tracer = TraceHook()
    hooks = [ApprovalHook("agency-ops"), tracer]

    if live:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
        model_id = os.environ.get(
            "AGENCY_OPS_MODEL",
            "global.anthropic.claude-sonnet-4-6",
        )
        model = BedrockModel(model_id=model_id, region_name=region)
    else:
        model = OfflinePolicyModel()

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        hooks=hooks,
        callback_handler=callback_handler,
    )
    return OpsAgent(agent=agent, tracer=tracer, offline=not live)
