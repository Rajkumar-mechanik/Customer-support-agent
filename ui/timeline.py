"""Live pipeline timeline state. Pure Python so the event handling is unit-tested without Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import AgentEvent, TicketResult

AGENTS: list[tuple[str, str]] = [
    ("Customer Query Agent", "Reads the complaint: category, urgency and sentiment"),
    ("Knowledge Base Agent", "Searches the policies and product sheets"),
    ("Resolution Agent", "Writes the reply from the retrieved facts only"),
    ("Log Agent", "Records the ticket and decides on escalation"),
]


@dataclass
class Step:
    name: str
    role: str
    state: str = "pending"  # pending | run | done | fail | skip
    text: str = ""
    started: float | None = None
    finished: float | None = None

    @property
    def seconds(self) -> float | None:
        if self.started is None or self.finished is None:
            return None
        return max(0.0, self.finished - self.started)


def new_steps() -> list[Step]:
    return [Step(name, role) for name, role in AGENTS]


def start_first(steps: list[Step], at: float) -> None:
    if steps and steps[0].state == "pending":
        steps[0].state, steps[0].started = "run", at


def apply_event(steps: list[Step], notes: list[str], event: AgentEvent) -> None:
    """Fold one pipeline event into the timeline."""
    by_name = {s.name: i for i, s in enumerate(steps)}
    idx = by_name.get(event.agent)
    if idx is None:  # events from "Pipeline" or "Guardrails" are notes, not steps
        if event.text and event.text not in notes:
            notes.append(event.text)
        return
    step = steps[idx]
    if event.kind == "start":
        if step.state == "pending":
            step.state, step.started = "run", event.at
    elif event.kind == "output":
        if step.started is None:
            step.started = event.at
        step.state, step.text, step.finished = "done", event.text, event.at
        if idx + 1 < len(steps) and steps[idx + 1].state == "pending":
            steps[idx + 1].state, steps[idx + 1].started = "run", event.at
    elif event.kind == "error":
        step.state, step.text, step.finished = "fail", event.text, event.at


def finish(steps: list[Step], result: TicketResult) -> None:
    """Close out any step that never reported (safe mode, or an agent that skipped its tool)."""
    for step in steps:
        if step.state in ("pending", "run"):
            step.state = "skip"
            step.text = "Not run: safe mode handled this step" if result.mode == "degraded" else "Completed by the system"
