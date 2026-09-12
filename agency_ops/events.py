"""Ops event models and fixture ingest."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpsEvent:
    """A single inbound ops event from n8n, intake, or a storefront."""

    id: str
    ts: str
    source: str
    type: str
    title: str
    severity: str = "medium"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "source": self.source,
            "type": self.type,
            "title": self.title,
            "severity": self.severity,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class DayDeck:
    """A sample day of events plus operator context."""

    date: str
    operator: str
    agency: str
    events: list[OpsEvent]


def _event_from_mapping(raw: dict[str, Any], defaults: dict[str, Any] | None = None) -> OpsEvent:
    data = {**(defaults or {}), **raw}
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return OpsEvent(
        id=str(data["id"]),
        ts=str(data.get("ts") or ""),
        source=str(data.get("source") or "unknown"),
        type=str(data.get("type") or "unknown"),
        title=str(data.get("title") or data.get("id")),
        severity=str(data.get("severity") or "medium"),
        payload=payload,
    )


def load_json_events(path: Path) -> DayDeck:
    """Load a day deck from a JSON fixture."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    events = [_event_from_mapping(item) for item in raw.get("events", [])]
    return DayDeck(
        date=str(raw.get("date") or "unknown"),
        operator=str(raw.get("operator") or "operator"),
        agency=str(raw.get("agency") or "agency"),
        events=events,
    )


def load_csv_sku_events(path: Path) -> list[OpsEvent]:
    """Load SKU / stock issues from a CSV fixture."""
    events: list[OpsEvent] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            units = int(row.get("units") or 0)
            threshold = int(row.get("threshold") or 0)
            severity = "high" if units <= 0 else "low"
            events.append(
                OpsEvent(
                    id=str(row["id"]),
                    ts=str(row.get("ts") or ""),
                    source=str(row.get("source") or "gumroad"),
                    type="sku_issue",
                    title=str(row.get("title") or f"SKU issue: {row.get('sku')}"),
                    severity=severity,
                    payload={
                        "sku": row.get("sku"),
                        "product": row.get("product"),
                        "units": units,
                        "threshold": threshold,
                        "action_hint": row.get("action_hint") or ("unpublish" if units <= 0 else "reorder_reminder"),
                        "note": row.get("note") or "",
                    },
                )
            )
    return events


def load_day(json_path: Path, csv_path: Path | None = None) -> DayDeck:
    """Merge the JSON day deck with optional CSV SKU events, de-duplicated by id."""
    deck = load_json_events(json_path)
    extra = load_csv_sku_events(csv_path) if csv_path else []
    seen = {event.id for event in deck.events}
    merged = list(deck.events)
    for event in extra:
        if event.id not in seen:
            merged.append(event)
            seen.add(event.id)
    merged.sort(key=lambda item: item.ts)
    return DayDeck(date=deck.date, operator=deck.operator, agency=deck.agency, events=merged)


def format_event_prompt(event: OpsEvent) -> str:
    """Render an event as the user turn the agent classifies."""
    payload = json.dumps(event.to_dict(), indent=2)
    return (
        "Process this ops event. Classify it as auto-handle or needs-human, "
        "then take the smallest safe action. Keep the final reply to one quiet line.\n\n"
        f"```ops-event\n{payload}\n```"
    )
