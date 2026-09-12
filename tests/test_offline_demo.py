from pathlib import Path

from agency_ops.agent import build_ops_agent
from agency_ops.cli import run_day
from agency_ops.store import read_jsonl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_auto_handle_lead_writes_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_OPS_DATA_DIR", str(tmp_path))
    outcomes = run_day(
        json_path=FIXTURES / "day.json",
        csv_path=None,
        live=False,
        approve="n",
        only={"evt-002"},
        verbose=False,
    )
    assert len(outcomes) == 1
    assert outcomes[0].classification == "auto_handle"
    assert outcomes[0].interrupted is False
    drafts = read_jsonl("drafts.jsonl")
    assert drafts[0]["to_email"] == "maya@example.com"
    assert drafts[0]["status"] == "draft"
    logs = read_jsonl("ops_log.jsonl")
    assert logs[0]["event_id"] == "evt-002"


def test_human_interrupt_then_approve_retries_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_OPS_DATA_DIR", str(tmp_path))
    outcomes = run_day(
        json_path=FIXTURES / "day.json",
        csv_path=None,
        live=False,
        approve="y",
        only={"evt-004"},
        verbose=False,
    )
    assert outcomes[0].interrupted is True
    assert outcomes[0].approved == ["retry_n8n_workflow"]
    gated = read_jsonl("gated_actions.jsonl")
    assert gated[0]["action"] == "retry_n8n_workflow"
    assert gated[0]["workflow_id"] == "wf_stripe_fulfill"


def test_human_interrupt_then_deny_does_not_pause_sku(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_OPS_DATA_DIR", str(tmp_path))
    outcomes = run_day(
        json_path=FIXTURES / "day.json",
        csv_path=None,
        live=False,
        approve="n",
        only={"evt-005"},
        verbose=False,
    )
    assert outcomes[0].interrupted is True
    assert outcomes[0].declined == ["pause_sku"]
    assert read_jsonl("gated_actions.jsonl") == []
    assert "Held" in outcomes[0].summary or "declined" in outcomes[0].summary.lower() or "quiet" in outcomes[0].summary.lower() or "Paused" not in outcomes[0].summary


def test_sample_day_has_auto_and_interrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENCY_OPS_DATA_DIR", str(tmp_path))
    outcomes = run_day(
        json_path=FIXTURES / "day.json",
        csv_path=FIXTURES / "sku_issues.csv",
        live=False,
        approve="n",
        verbose=False,
    )
    assert any(item.classification == "auto_handle" and not item.interrupted for item in outcomes)
    assert any(item.interrupted for item in outcomes)


def test_build_offline_agent_has_tools_and_hooks():
    bundle = build_ops_agent(live=False, callback_handler=None)
    names = list(bundle.agent.tool_registry.registry)
    assert names == [
        "log_ops_event",
        "draft_reply",
        "queue_reminder",
        "retry_n8n_workflow",
        "pause_sku",
        "send_customer_email",
    ]
    assert bundle.offline is True
