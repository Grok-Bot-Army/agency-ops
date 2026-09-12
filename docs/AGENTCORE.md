# Deploying Agency Ops on Amazon Bedrock AgentCore

This MVP is a local CLI. It does **not** need AgentCore to demo. Use this note when you want the same agent sitting on a webhook instead of `python -m agency_ops`.

Docs: [Python deployment to AgentCore Runtime](https://strandsagents.com/docs/user-guide/deploy/deploy_to_bedrock_agentcore/python/)

## Shape

AgentCore Runtime wants an ARM64 container that exposes:

- `POST /invocations` — agent entrypoint
- `GET /ping` — health

Two official paths:

1. **SDK wrapper** — `bedrock-agentcore` + `@app.entrypoint`
2. **Custom FastAPI** — you own the HTTP surface, still ARM64 + ECR

## Sketch (SDK wrapper)

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agency_ops.agent import build_ops_agent
from agency_ops.events import OpsEvent, format_event_prompt

app = BedrockAgentCoreApp()
bundle = build_ops_agent(live=True, callback_handler=None)


@app.entrypoint
def invoke(payload: dict) -> dict:
    """Accept one ops event JSON. High-stakes tools still interrupt."""
    event = OpsEvent(
        id=payload["id"],
        ts=payload.get("ts", ""),
        source=payload.get("source", "unknown"),
        type=payload.get("type", "unknown"),
        title=payload.get("title", payload["id"]),
        severity=payload.get("severity", "medium"),
        payload=payload.get("payload") or {},
    )
    result = bundle.agent(format_event_prompt(event))
    if result.stop_reason == "interrupt":
        return {
            "status": "needs_human",
            "interrupts": [item.to_dict() for item in (result.interrupts or [])],
        }
    return {"status": "ok", "summary": str(result).strip()}


if __name__ == "__main__":
    app.run()
```

Resume an interrupt by posting `interruptResponse` blocks the same way the CLI does (`agent(responses)`). That maps cleanly to a Slack approve/deny button or an n8n wait node.

## Production notes

- Keep `ApprovalHook` on. AgentCore is not a reason to auto-retry Stripe.
- Persist session / interrupt state (`FileSessionManager` or a store) so an approve click can resume hours later.
- Inject secrets only via environment / IAM: `AWS_REGION`, Bedrock invoke permissions, later n8n/Gumroad tokens. Never commit them.
- Platform must be `linux/arm64`; listen on `8080`.
- Add `aws-opentelemetry-distro` and run under `opentelemetry-instrument` if you want CloudWatch GenAI traces.

## Local first

```bash
python -m agency_ops --approve y
```

Ship the quiet desk locally, then wrap the same `build_ops_agent(live=True)` for Runtime.
