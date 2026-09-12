from pathlib import Path

from agency_ops.events import load_csv_sku_events, load_day, load_json_events
from agency_ops.policy import AUTO_HANDLE, NEEDS_HUMAN, classify, plan_actions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_json_and_csv_merge_in_time_order():
    deck = load_day(FIXTURES / "day.json", FIXTURES / "sku_issues.csv")
    ids = [event.id for event in deck.events]
    assert ids == ["evt-001", "evt-002", "evt-003", "evt-006", "evt-004", "evt-005"]
    assert deck.agency == "Northline Studio"


def test_csv_sku_units_drive_severity():
    events = load_csv_sku_events(FIXTURES / "sku_issues.csv")
    assert events[0].severity == "low"
    assert events[0].payload["units"] == 8


def test_auto_vs_human_classification():
    deck = load_json_events(FIXTURES / "day.json")
    by_id = {event.id: event for event in deck.events}
    assert classify(by_id["evt-001"])[0] == AUTO_HANDLE
    assert classify(by_id["evt-002"])[0] == AUTO_HANDLE
    assert classify(by_id["evt-003"])[0] == AUTO_HANDLE
    assert classify(by_id["evt-004"])[0] == NEEDS_HUMAN
    assert classify(by_id["evt-005"])[0] == NEEDS_HUMAN


def test_plans_include_gated_tools_only_for_human_events():
    deck = load_json_events(FIXTURES / "day.json")
    by_id = {event.id: event for event in deck.events}
    lead = plan_actions(by_id["evt-002"])
    assert [tool.name for tool in lead.tools] == ["log_ops_event", "draft_reply"]
    stripe = plan_actions(by_id["evt-004"])
    assert [tool.name for tool in stripe.tools] == ["log_ops_event", "retry_n8n_workflow"]
    sold_out = plan_actions(by_id["evt-005"])
    assert [tool.name for tool in sold_out.tools] == ["log_ops_event", "pause_sku"]
