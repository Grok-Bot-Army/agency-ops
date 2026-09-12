"""CLI: run a sample day of ops events and print a quiet summary."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agency_ops.agent import OpsAgent, build_ops_agent
from agency_ops.events import DayDeck, OpsEvent, format_event_prompt, load_day
from agency_ops.hooks import APPROVAL_INTERRUPT
from agency_ops.policy import classify

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REPO_ROOT / "fixtures" / "day.json"
DEFAULT_CSV = REPO_ROOT / "fixtures" / "sku_issues.csv"


@dataclass
class EventOutcome:
    event: OpsEvent
    classification: str
    summary: str
    interrupted: bool = False
    approved: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)


def default_fixtures() -> tuple[Path, Path]:
    return DEFAULT_JSON, DEFAULT_CSV


def decide_approval(interrupt: Any, policy: str, ask: Callable[[str], str]) -> str:
    reason = interrupt.reason if isinstance(interrupt.reason, dict) else {"risk": str(interrupt.reason)}
    tool = reason.get("tool") or "action"
    risk = reason.get("risk") or "This action has customer-visible side effects."
    prompt = f"         Approve {tool}? {risk} [y/N] "
    if policy in {"y", "yes"}:
        print(f"{prompt}→ y (demo)")
        return "y"
    if policy in {"n", "no"}:
        print(f"{prompt}→ n (demo)")
        return "n"
    try:
        return ask(prompt)
    except EOFError:
        print("n")
        return "n"


def run_event(
    bundle: OpsAgent,
    event: OpsEvent,
    *,
    approve: str,
    ask: Callable[[str], str] = input,
) -> EventOutcome:
    classification, _ = classify(event)
    bundle.tracer.traces.clear()
    result = bundle.agent(format_event_prompt(event))
    interrupted = False
    approved: list[str] = []
    declined: list[str] = []

    while getattr(result, "stop_reason", None) == "interrupt":
        interrupted = True
        responses = []
        for interrupt in result.interrupts or []:
            name = getattr(interrupt, "name", "")
            if APPROVAL_INTERRUPT not in name and "approval" not in name:
                continue
            answer = decide_approval(interrupt, approve, ask)
            reason = interrupt.reason if isinstance(interrupt.reason, dict) else {}
            tool = str(reason.get("tool") or "action")
            if str(answer).strip().lower() in {"y", "yes", "approve", "approved", "a"}:
                approved.append(tool)
            else:
                declined.append(tool)
            responses.append(
                {
                    "interruptResponse": {
                        "interruptId": interrupt.id,
                        "response": answer,
                    }
                }
            )
        if not responses:
            break
        result = bundle.agent(responses)

    tools = [trace.name for trace in bundle.tracer.traces]
    summary = str(result).strip() or "Handled."
    return EventOutcome(
        event=event,
        classification=classification,
        summary=summary.splitlines()[0],
        interrupted=interrupted,
        approved=approved,
        declined=declined,
        tools=tools,
    )


def print_report(deck: DayDeck, outcomes: list[EventOutcome], *, offline: bool) -> None:
    mode = "offline policy model" if offline else "Amazon Bedrock"
    print()
    print(f"{deck.agency} · {deck.date} · {deck.operator}")
    print(f"Quiet ops desk — {mode}. Only pinging you when it matters.")
    print()

    auto = 0
    human = 0
    for outcome in outcomes:
        event = outcome.event
        clock = event.ts[11:16] if len(event.ts) >= 16 else "----"
        tag = "human" if outcome.classification == "needs_human" else "auto "
        if outcome.classification == "needs_human":
            human += 1
        else:
            auto += 1
        print(f"  {clock}  {event.title:<42} {tag}  {outcome.summary}")
        if outcome.approved:
            print(f"         ↳ approved: {', '.join(outcome.approved)}")
        if outcome.declined:
            print(f"         ↳ held: {', '.join(outcome.declined)}")

    print()
    print(f"{auto} handled quietly · {human} needed you")
    print()


def run_day(
    *,
    json_path: Path,
    csv_path: Path | None,
    live: bool,
    approve: str,
    only: set[str] | None = None,
    verbose: bool = False,
    ask: Callable[[str], str] = input,
) -> list[EventOutcome]:
    deck = load_day(json_path, csv_path)
    events = [event for event in deck.events if not only or event.id in only]
    if not events:
        raise SystemExit("No events matched. Check --only against fixture ids.")

    # Quiet by default. --verbose restores the SDK's streaming printer.
    bundle = build_ops_agent(live=live) if verbose else build_ops_agent(live=live, callback_handler=None)

    outcomes = [
        run_event(bundle, event, approve=approve, ask=ask)
        for event in events
    ]
    print_report(deck, outcomes, offline=bundle.offline)
    return outcomes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agency-ops",
        description="Run a sample day of agency ops events through a Strands agent.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use Amazon Bedrock (requires AWS credentials). Default is the offline demo model.",
    )
    parser.add_argument(
        "--approve",
        choices=("ask", "y", "n"),
        default="ask",
        help="How to answer high-stakes interrupts: interactive (ask), always yes, or always no.",
    )
    parser.add_argument(
        "--events",
        default=str(DEFAULT_JSON),
        help="Path to the JSON day fixture.",
    )
    parser.add_argument(
        "--sku-csv",
        default=str(DEFAULT_CSV),
        help="Path to the SKU CSV fixture. Pass empty string to skip.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated event ids to run (e.g. evt-002,evt-004).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Stream Strands callback output (noisy). Default is a quiet summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    csv_path = Path(args.sku_csv) if args.sku_csv else None
    only = {item.strip() for item in args.only.split(",") if item.strip()} or None
    approve = args.approve
    if approve == "ask" and not sys.stdin.isatty():
        approve = "n"
        print("stdin is not a TTY — defaulting high-stakes interrupts to 'n'. Pass --approve y to auto-approve.")

    run_day(
        json_path=Path(args.events),
        csv_path=csv_path,
        live=args.live,
        approve=approve,
        only=only,
        verbose=args.verbose,
    )
    return 0
