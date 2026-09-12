"""Local JSONL store for logs, drafts, reminders, and gated actions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path(os.environ.get("AGENCY_OPS_DATA_DIR", "data"))


def data_dir() -> Path:
    path = Path(os.environ.get("AGENCY_OPS_DATA_DIR", str(DEFAULT_DATA_DIR)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append(name: str, record: dict[str, Any]) -> Path:
    target = data_dir() / name
    payload = {"recorded_at": datetime.now(timezone.utc).isoformat(), **record}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def log_event(record: dict[str, Any]) -> Path:
    return _append("ops_log.jsonl", record)


def save_draft(record: dict[str, Any]) -> Path:
    return _append("drafts.jsonl", record)


def queue_reminder(record: dict[str, Any]) -> Path:
    return _append("reminders.jsonl", record)


def record_gated_action(record: dict[str, Any]) -> Path:
    return _append("gated_actions.jsonl", record)


def read_jsonl(name: str) -> list[dict[str, Any]]:
    target = data_dir() / name
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
