"""Typed domain objects shared by agents, pipeline, store and UI."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

# Literal aliases are used as tool-argument types so the OpenAI function schema carries an
# enum. The model cannot return "Shiping" or "Super urgent": the API rejects it up front.
CategoryLit = Literal["Shipping", "Refund", "Product", "Account", "Billing", "Warranty", "Other"]
UrgencyLit = Literal["Low", "Medium", "High"]
SentimentLit = Literal["Positive", "Neutral", "Frustrated", "Angry"]
ConfidenceLit = Literal["high", "medium", "low"]

CONFIDENCE_SCORES: dict[str, float] = {"high": 0.9, "medium": 0.7, "low": 0.3}


class Category(str, Enum):
    SHIPPING = "Shipping"
    REFUND = "Refund"
    PRODUCT = "Product"
    ACCOUNT = "Account"
    BILLING = "Billing"
    WARRANTY = "Warranty"
    OTHER = "Other"


class Urgency(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"

    @property
    def rank(self) -> int:
        return {"Low": 0, "Medium": 1, "High": 2}[self.value]


class Sentiment(str, Enum):
    POSITIVE = "Positive"
    NEUTRAL = "Neutral"
    FRUSTRATED = "Frustrated"
    ANGRY = "Angry"


class Status(str, Enum):
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"


@dataclass(frozen=True)
class TicketInput:
    """A complaint after validation, sanitising and PII redaction."""

    complaint: str
    customer_name: str = ""
    order_id: str = ""
    flags: tuple[str, ...] = ()
    pii_redactions: int = 0


@dataclass
class Analysis:
    category: Category
    urgency: Urgency
    sentiment: Sentiment
    summary: str
    product_mentioned: str = ""
    source: str = "llm"  # "llm" | "heuristic"


@dataclass(frozen=True)
class Passage:
    source: str  # file name, e.g. refund_policy.md
    title: str
    heading: str
    text: str
    score: float
    coverage: float
    doc_type: str = "policy"

    def as_prompt_block(self) -> str:
        return f"[source: {self.source} | {self.title} > {self.heading}]\n{self.text.strip()}"


@dataclass
class Resolution:
    reply: str
    llm_confidence: str = "medium"  # high | medium | low
    sources_used: list[str] = field(default_factory=list)
    needs_human: bool = False
    note: str = ""


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reasons: tuple[str, ...] = ()

    @property
    def status(self) -> Status:
        return Status.ESCALATED if self.escalate else Status.RESOLVED

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class AgentEvent:
    """One step in the live timeline shown by the UI."""

    agent: str
    kind: str  # start | tool | output | error | info
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)


@dataclass
class TicketResult:
    ticket_id: str
    status: Status
    reply: str
    category: Category
    urgency: Urgency
    sentiment: Sentiment
    summary: str
    kb_sources: list[str]
    escalation_reasons: list[str]
    confidence: float
    guardrail_flags: list[str]
    mode: str  # "autogen" | "degraded"
    latency_ms: int
    tokens: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""
    retrieved_sources: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)  # evidence shown in the UI

    @property
    def escalated(self) -> bool:
        return self.status is Status.ESCALATED


EventCallback = Callable[[AgentEvent], None]


@dataclass
class RequestContext:
    """Mutable per-request state. Agents' tools read and write it; nothing is global.

    Because every tool is a closure over one RequestContext, concurrent tickets can never
    leak into each other and the LLM never has to copy IDs or complaint text correctly.
    """

    ticket_input: TicketInput
    on_event: EventCallback | None = None
    started: float = field(default_factory=time.perf_counter)
    analysis: Analysis | None = None
    kb_queries: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    resolution: Resolution | None = None
    result: TicketResult | None = None
    events: list[AgentEvent] = field(default_factory=list)
    mode: str = "autogen"
    tokens: dict[str, int] = field(default_factory=dict)
    usage_probe: Callable[[], dict[str, int]] | None = None
    finalize_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    notes: list[str] = field(default_factory=list)  # pipeline-level flags, e.g. log_agent_skipped

    def token_usage(self) -> dict[str, int]:
        if self.usage_probe is not None:
            try:
                return dict(self.usage_probe())
            except Exception:
                return dict(self.tokens)
        return dict(self.tokens)

    def emit(self, agent: str, kind: str, text: str, **data: Any) -> None:
        event = AgentEvent(agent=agent, kind=kind, text=text, data=data)
        self.events.append(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # a UI callback must never be able to break the pipeline
                pass

    def reset_outputs(self) -> None:
        self.analysis = None
        self.kb_queries.clear()
        self.passages.clear()
        self.resolution = None
        self.result = None
        self.notes.clear()
