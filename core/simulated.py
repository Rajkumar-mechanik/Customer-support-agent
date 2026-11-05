"""SimulatedRunner: a deterministic stand-in for the four LLM agents.

It calls the SAME tool functions, in the SAME order, with the SAME events as the AutoGen team, so
everything downstream (guardrails, escalation, store, UI timeline) is exercised for real. Only the
language judgement is rule-based instead of model-based. Uses:

  * unit tests and offline evals (optionally driven by gold labels instead of heuristics)
  * screenshots and demos without an API key (the UI labels this mode clearly, never as "AI")
  * a safety net: it is never used silently in production; DEMO_MODE=true must be set explicitly
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from agents import knowledge_agent, log_agent, query_agent, resolution_agent
from agents.knowledge_agent import make_search_kb
from agents.log_agent import make_log_ticket
from agents.query_agent import make_record_analysis
from agents.resolution_agent import make_submit_reply

from . import heuristics
from .guardrails import retrieval_text
from .deps import Deps
from .fallback import heuristic_analysis
from .models import Analysis, Category, Passage, RequestContext, Sentiment

AnalysisFn = Callable[[str], Analysis]

_QUERY_NOISE = re.compile(r"[^a-z0-9₹\s-]")


def compose_reply(passages: list[Passage], company: str, name: str, sentiment: Sentiment) -> str:
    """A grounded reply assembled from the top passage (no invented content)."""
    greeting = f"Hello {name}," if name else "Hello,"
    if not passages:
        return (
            f"{greeting}\n\nThank you for getting in touch. I could not find this in our support "
            "documentation and I do not want to guess and give you wrong information. A colleague will "
            f"review your request and reply to you directly.\n\nRegards,\n{company} Support"
        )
    empathy = (
        "I am sorry for the trouble this has caused. " if sentiment in (Sentiment.FRUSTRATED, Sentiment.ANGRY) else ""
    )
    body = passages[0].text.strip()
    if len(body) > 650:
        cut = body[:650]
        body = cut[: max(cut.rfind(". "), cut.rfind("\n")) + 1] or cut
    return f"{greeting}\n\n{empathy}Here is what you need to know.\n\n{body}\n\nRegards,\n{company} Support"


class SimulatedRunner:
    simulated = True

    def __init__(self, deps: Deps, analysis_fn: AnalysisFn | None = None, delay_s: float = 0.0):
        self.deps = deps
        self.analysis_fn = analysis_fn or heuristic_analysis
        self.delay_s = delay_s

    async def _pause(self) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)

    async def run(self, ctx: RequestContext) -> None:
        deps, text = self.deps, ctx.ticket_input.complaint
        ctx.mode = "simulated"

        ctx.emit(query_agent.DISPLAY, "start", "Working")
        await self._pause()
        a = self.analysis_fn(text)
        product = deps.kb.find_product(text)
        if product and a.category is Category.OTHER:
            a.category = Category.PRODUCT  # a named product means a product question, not "Other"
        await make_record_analysis(ctx)(
            a.category.value, a.urgency.value, a.sentiment.value, a.summary,
            a.product_mentioned or (product.title if product else ""),
        )

        ctx.emit(knowledge_agent.DISPLAY, "start", "Working")
        await self._pause()
        words = _QUERY_NOISE.sub(" ", f"{product.title if product else ''} {retrieval_text(text)}".lower()).split()
        await make_search_kb(ctx, deps)(" ".join(words[:14]) or text[:60])

        ctx.emit(resolution_agent.DISPLAY, "start", "Working")
        await self._pause()
        passages = ctx.passages
        confidence = "low" if not passages else ("high" if passages[0].coverage >= 0.6 else "medium")
        reply = compose_reply(passages, deps.settings.company_name, ctx.ticket_input.customer_name, a.sentiment)
        await make_submit_reply(ctx)(
            reply, confidence, sorted({p.source for p in passages}), not passages,
            "No matching document" if not passages else "",
        )

        ctx.emit(log_agent.DISPLAY, "start", "Working")
        await self._pause()
        escalate = a.urgency.rank >= 2 or a.sentiment is Sentiment.ANGRY or not passages or bool(heuristics.trigger_codes(text))
        await make_log_ticket(ctx, deps)(escalate, "Simulated recommendation")
