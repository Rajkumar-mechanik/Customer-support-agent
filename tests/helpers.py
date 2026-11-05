"""Shared test helpers: temp-dir dependencies and fake agent runners."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agents.knowledge_agent import make_search_kb
from agents.query_agent import make_record_analysis
from agents.resolution_agent import make_submit_reply
from core.config import Settings
from core.deps import Deps
from core.models import RequestContext
from core.pipeline import SupportDesk
from core.simulated import SimulatedRunner

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge_base"


def make_settings(**overrides) -> Settings:
    base = dict(log_dir=Path(tempfile.mkdtemp()), rate_limit_per_minute=0, llm_max_attempts=2)
    base.update(overrides)
    return Settings(**base)


def make_deps(**overrides) -> Deps:
    return Deps.build(make_settings(**overrides))


def make_desk(runner=None, **overrides) -> SupportDesk:
    deps = make_deps(**overrides)
    return SupportDesk(deps, runner=runner or SimulatedRunner(deps))


class FailingRunner:
    """Every call raises, like an OpenAI outage."""

    def __init__(self, exc: Exception | None = None):
        self.exc, self.calls = exc or ConnectionError("simulated outage"), 0

    async def run(self, ctx: RequestContext) -> None:
        self.calls += 1
        raise self.exc


class SkipLogRunner:
    """Runs the first three agents but the Log Agent never calls its tool."""

    def __init__(self, deps: Deps, reply: str | None = None, analysis: dict | None = None):
        self.deps, self.reply, self.analysis = deps, reply, analysis

    async def run(self, ctx: RequestContext) -> None:
        a = self.analysis or dict(category="Account", urgency="Low", sentiment="Neutral", summary="Cannot log in")
        await make_record_analysis(ctx)(**a)
        await make_search_kb(ctx, self.deps)("forgot password reset login")
        reply = self.reply or (
            "Hello, sorry you are locked out. Choose Forgot password on the login page and use the link within "
            "15 minutes.\n\nRegards,\nBrightwell Support"
        )
        await make_submit_reply(ctx)(reply, "high", sorted({p.source for p in ctx.passages}), False, "")


class ScriptedRunner:
    """Calls the four real tools with caller-supplied arguments (stand-in for the LLM)."""

    def __init__(self, deps: Deps, analysis: dict, query: str, reply: str, confidence: str = "high",
                 needs_human: bool = False, escalate: bool = False):
        self.deps, self.analysis, self.query, self.reply = deps, analysis, query, reply
        self.confidence, self.needs_human, self.escalate = confidence, needs_human, escalate

    async def run(self, ctx: RequestContext) -> None:
        from agents.log_agent import make_log_ticket

        await make_record_analysis(ctx)(**self.analysis)
        await make_search_kb(ctx, self.deps)(self.query)
        await make_submit_reply(ctx)(
            self.reply, self.confidence, sorted({p.source for p in ctx.passages}), self.needs_human, ""
        )
        await make_log_ticket(ctx, self.deps)(self.escalate, "scripted")
