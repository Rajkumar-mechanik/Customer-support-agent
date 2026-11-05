"""finalize_ticket: the single place where a ticket becomes a logged, final decision.

Called by the Log Agent's `log_ticket` tool (normal path) and by the pipeline (recovery paths).
Everything the customer will read or the human team will rely on is decided *here*, in code:

    1. fill any gap an agent left (heuristic analysis, deterministic retrieval, template reply)
    2. raise urgency / sentiment to the safety floor (never lower an LLM rating)
    3. run the output guardrails and swap in a safe reply if the draft can't be trusted
    4. compute blended confidence and apply the escalation policy
    5. persist exactly one row and return the final result

The function is synchronous and free of UI callbacks so it can run in a worker thread.
"""

from __future__ import annotations

import time
from datetime import datetime

from . import escalation, heuristics
from .deps import Deps
from .fallback import compose_degraded_reply, heuristic_analysis
from .guardrails import redact_pii, retrieval_text, safe_fallback_reply, validate_output
from .logging_setup import get_logger
from .models import Analysis, RequestContext, Resolution, Sentiment, TicketResult, Urgency

log = get_logger("ticketing")

ESCALATION_FOOTER = (
    "\n\nI have also flagged your ticket for a member of our support team, who will review it "
    "and follow up with you directly."
)

_SENTIMENT_ORDER = [Sentiment.POSITIVE, Sentiment.NEUTRAL, Sentiment.FRUSTRATED, Sentiment.ANGRY]


def _max_urgency(a: Urgency, b: Urgency) -> Urgency:
    return a if a.rank >= b.rank else b


def _max_sentiment(a: Sentiment, b: Sentiment) -> Sentiment:
    return a if _SENTIMENT_ORDER.index(a) >= _SENTIMENT_ORDER.index(b) else b


def finalize_ticket(
    ctx: RequestContext,
    deps: Deps,
    *,
    agent_escalation: bool = False,
    agent_reason: str = "",
    degraded: bool = False,
) -> TicketResult:
    """Idempotent and thread-safe: a second call returns the first result and writes no second row."""
    with ctx.finalize_lock:
        if ctx.result is not None:
            return ctx.result
        return _finalize(ctx, deps, agent_escalation, agent_reason, degraded)


def _finalize(
    ctx: RequestContext, deps: Deps, agent_escalation: bool, agent_reason: str, degraded: bool
) -> TicketResult:
    settings, ticket = deps.settings, ctx.ticket_input
    text = ticket.complaint
    flags: list[str] = list(ticket.flags) + list(ctx.notes)

    # 1 -- fill gaps -------------------------------------------------------------------
    analysis = ctx.analysis
    if analysis is None:
        analysis = heuristic_analysis(text)
        flags.append("analysis_from_heuristics")

    if not ctx.passages and not ctx.kb_queries:  # the Knowledge Agent never searched
        product = deps.kb.find_product(f"{text} {analysis.product_mentioned}")
        query = " ".join(filter(None, [product.title if product else "", retrieval_text(analysis.summary or text)]))
        ctx.passages = deps.kb.search(
            query,
            k=settings.top_k,
            min_coverage=settings.min_coverage,
            category_hint=analysis.category.value,
            context=text,
        )
        ctx.kb_queries.append(query)
        flags.append("retrieval_by_pipeline")
    passages = ctx.passages

    resolution = ctx.resolution
    template_reply = False
    if resolution is None:
        template_reply = True
        resolution = Resolution(
            reply=compose_degraded_reply(passages, settings.company_name, ticket.customer_name),
            llm_confidence="low",
            sources_used=sorted({p.source for p in passages}),
            needs_human=True,
            note="No reply was drafted by the resolution agent",
        )
        flags.append("reply_from_template")

    # 2 -- safety floor (rules may raise a rating, never lower it) ------------------------
    sentiment = _max_sentiment(analysis.sentiment, heuristics.detect_sentiment(text))
    urgency = _max_urgency(analysis.urgency, heuristics.urgency_floor(text, sentiment))
    if urgency is not analysis.urgency or sentiment is not analysis.sentiment:
        flags.append("rating_raised_by_rules")
    analysis = Analysis(
        category=analysis.category,
        urgency=urgency,
        sentiment=sentiment,
        summary=redact_pii(analysis.summary)[0],  # defence in depth: never persist model-echoed PII
        product_mentioned=redact_pii(analysis.product_mentioned)[0],
        source=analysis.source,
    )
    triggers = heuristics.trigger_codes(text)

    # 3 -- output guardrails -----------------------------------------------------------
    check = validate_output(resolution.reply, passages, complaint=text, order_id=ticket.order_id)
    reply = check.reply
    flags.extend(f for f in check.flags if f not in flags)
    safe_reply_used = not check.ok
    if safe_reply_used:
        reply = safe_fallback_reply(settings.company_name, ticket.customer_name, honest_no_answer=not passages)
        log.warning("Draft reply replaced by safe fallback: %s", check.blocking)

    # 4 -- confidence + escalation -----------------------------------------------------
    confidence = escalation.final_confidence(resolution, passages)
    if check.blocking:
        confidence = min(confidence, 0.3)
    note = redact_pii(agent_reason if (agent_escalation and agent_reason) else resolution.note)[0]
    effective = Resolution(
        reply=reply,
        llm_confidence=resolution.llm_confidence,
        sources_used=resolution.sources_used,
        needs_human=resolution.needs_human or agent_escalation,
        note=note,
    )
    decision = escalation.decide(
        analysis=analysis,
        passages=passages,
        resolution=effective,
        triggers=triggers,
        input_flags=ticket.flags,
        output_blocking=check.blocking,
        confidence=confidence,
        settings=settings,
        degraded=degraded,
    )
    # Code-written replies already say a person will follow up; only add the line to model drafts.
    if decision.escalate and not (safe_reply_used or template_reply or degraded):
        reply = reply.rstrip() + ESCALATION_FOOTER

    # 5 -- persist ---------------------------------------------------------------------
    retrieved = sorted({p.source for p in passages})
    cited = sorted(set(resolution.sources_used) & set(retrieved))
    kb_sources = cited or retrieved  # prefer the files the reply actually relied on
    usage = ctx.token_usage()
    latency_ms = int((time.perf_counter() - ctx.started) * 1000)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = "degraded" if degraded else ctx.mode
    unique_flags = list(dict.fromkeys(flags))

    ticket_id = deps.store.append(
        {
            "timestamp": timestamp,
            "customer_name": ticket.customer_name,
            "order_id": ticket.order_id,
            "complaint": text,
            "category": analysis.category.value,
            "urgency": analysis.urgency.value,
            "sentiment": analysis.sentiment.value,
            "summary": analysis.summary,
            "kb_sources": "; ".join(kb_sources),
            "response": reply,
            "status": decision.status.value,
            "escalation_reason": decision.reason_text,
            "confidence": f"{confidence:.2f}",
            "guardrail_flags": "; ".join(unique_flags),
            "pipeline_mode": mode,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
    )

    ctx.result = TicketResult(
        ticket_id=ticket_id,
        status=decision.status,
        reply=reply,
        category=analysis.category,
        urgency=analysis.urgency,
        sentiment=analysis.sentiment,
        summary=analysis.summary,
        kb_sources=kb_sources,
        escalation_reasons=list(decision.reasons),
        confidence=confidence,
        guardrail_flags=unique_flags,
        mode=mode,
        latency_ms=latency_ms,
        tokens=usage,
        timestamp=timestamp,
        retrieved_sources=retrieved,
        passages=list(passages),
    )
    log.info(
        "ticket=%s status=%s category=%s urgency=%s confidence=%.2f sources=%s mode=%s",
        ticket_id, decision.status.value, analysis.category.value, analysis.urgency.value,
        confidence, kb_sources, mode,
    )
    return ctx.result
