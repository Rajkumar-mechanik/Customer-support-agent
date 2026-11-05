"""SupportDesk: orchestrates validation -> AutoGen team -> finalisation, with retries and fallback.

Request lifecycle
    1. validate_input        reject junk, flag injection, redact PII        (guardrails.py)
    2. rate limit            per-session sliding window
    3. run the agent team    timeout + retry, guarded by a circuit breaker  (team.AutoGenRunner)
    4. finalize_ticket       safety floor, output guardrails, escalation, log row (ticketing.py)
    5. degraded mode         if the model is unavailable the ticket is still logged and escalated
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import Counter
from datetime import datetime
from typing import Protocol

from agents.prompts import PROMPT_VERSION

from .deps import Deps
from .guardrails import InputRejected, RateLimiter, validate_input
from .logging_setup import get_logger
from .models import EventCallback, RequestContext, TicketResult
from .resilience import CircuitBreaker
from .ticketing import finalize_ticket

log = get_logger("pipeline")
__all__ = ["SupportDesk", "InputRejected", "RateLimited", "AgentRunner"]


class RateLimited(RuntimeError):
    def __init__(self, retry_after: float):
        super().__init__(f"Too many requests. Please try again in {int(retry_after) + 1} seconds.")
        self.retry_after = retry_after


class AgentRunner(Protocol):
    """Anything that can drive the agents for one ticket. AutoGenRunner is the production one."""

    async def run(self, ctx: RequestContext) -> None: ...


class SupportDesk:
    def __init__(self, deps: Deps, runner: AgentRunner | None = None, breaker: CircuitBreaker | None = None):
        self.deps = deps
        self.limiter = RateLimiter(deps.settings.rate_limit_per_minute)
        self.breaker = breaker or CircuitBreaker()
        self._runner = runner
        self._trace_lock = threading.Lock()
        self.metrics: Counter = Counter()

    # ------------------------------------------------------------------ introspection
    @property
    def live(self) -> bool:
        """True when tickets are handled by the LLM agents (a key is set or a runner is injected)."""
        return self._runner is not None or self.deps.settings.llm_configured or self.deps.settings.demo_mode

    def health(self) -> dict[str, object]:
        s = self.deps.settings
        return {
            "mode": self._mode_label(),
            "model": s.model,
            "breaker": self.breaker.state,
            "retriever": "hybrid" if self.deps.kb.reranker is not None else "lexical",
            "documents": len(self.deps.kb.docs),
            "products": len(self.deps.kb.product_docs()),
            "prompt_version": PROMPT_VERSION,
            **{k: v for k, v in self.metrics.items()},
        }

    def _mode_label(self) -> str:
        if not self.live:
            return "safe mode"
        runner = self._runner
        simulated = getattr(runner, "simulated", False) or (
            runner is None and not self.deps.settings.llm_configured and self.deps.settings.demo_mode
        )
        return "demo (simulated agents)" if simulated else "live"

    def _get_runner(self) -> AgentRunner:
        if self._runner is None:
            s = self.deps.settings
            if s.llm_configured:
                from team import AutoGenRunner  # lazy: keeps offline tests free of the autogen import

                self._runner = AutoGenRunner(self.deps)
            else:  # only reachable with DEMO_MODE=true
                from .simulated import SimulatedRunner

                self._runner = SimulatedRunner(self.deps, delay_s=0.45)
        return self._runner

    # ------------------------------------------------------------------ main entry points
    def handle_sync(self, *args, **kwargs) -> TicketResult:
        """Convenience for scripts and Streamlit (which runs plain synchronous code)."""
        return asyncio.run(self.handle(*args, **kwargs))

    async def handle(
        self,
        complaint: str,
        customer_name: str = "",
        order_id: str = "",
        *,
        session_id: str = "default",
        on_event: EventCallback | None = None,
    ) -> TicketResult:
        s = self.deps.settings
        ticket_input = validate_input(
            complaint, customer_name, order_id, min_chars=s.min_complaint_chars, max_chars=s.max_complaint_chars
        )
        allowed, retry = self.limiter.check(session_id)
        if not allowed:
            self.metrics["rate_limited"] += 1
            raise RateLimited(retry)

        ctx = RequestContext(ticket_input=ticket_input, on_event=on_event)
        if ticket_input.flags:
            ctx.emit("Guardrails", "info", "Input flags: " + ", ".join(ticket_input.flags))

        if self.live:
            if self.breaker.allow():
                await self._run_agents(ctx)
            else:
                ctx.emit("Pipeline", "error", "AI model temporarily unavailable; using safe mode")
                log.warning("Circuit breaker open; skipping LLM")

        degraded = ctx.result is None
        if degraded:
            ctx.mode = "degraded"
            self.metrics["degraded"] += 1
            await asyncio.to_thread(finalize_ticket, ctx, self.deps, degraded=True)

        assert ctx.result is not None
        self.metrics["tickets"] += 1
        self.metrics["escalated" if ctx.result.escalated else "resolved"] += 1
        await asyncio.to_thread(self._trace, ctx)
        return ctx.result

    # ------------------------------------------------------------------ internals
    async def _run_agents(self, ctx: RequestContext) -> None:
        s = self.deps.settings
        runner = self._get_runner()
        for attempt in range(1, s.llm_max_attempts + 1):
            try:
                await asyncio.wait_for(runner.run(ctx), timeout=s.request_timeout_s)
                if ctx.result is None:  # Log Agent skipped its tool: finish deterministically
                    ctx.notes.append("log_agent_skipped")
                    await asyncio.to_thread(finalize_ticket, ctx, self.deps)
                self.breaker.record_success()
                return
            except Exception as exc:  # noqa: BLE001 - any LLM/network failure triggers retry or fallback
                log.warning("LLM attempt %d/%d failed: %s: %s", attempt, s.llm_max_attempts, type(exc).__name__, exc)
                log.debug("traceback", exc_info=True)
                if ctx.result is not None:  # ticket was already logged; do not run it twice
                    self.breaker.record_success()
                    return
                self.breaker.record_failure()
                self.metrics["llm_failures"] += 1
                ctx.reset_outputs()
                last = attempt == s.llm_max_attempts or not self.breaker.allow()
                ctx.emit("Pipeline", "error", "AI model unavailable; switching to safe mode" if last else f"Attempt {attempt} failed; retrying")
                if last:
                    return
                await asyncio.sleep(0.8 * attempt)

    def _trace(self, ctx: RequestContext) -> None:
        r = ctx.result
        if r is None:
            return
        record = {
            "ticket_id": r.ticket_id,
            "at": datetime.now().isoformat(timespec="seconds"),
            "prompt_version": PROMPT_VERSION,
            "model": self.deps.settings.model,
            "mode": r.mode,
            "status": r.status.value,
            "latency_ms": r.latency_ms,
            "tokens": r.tokens,
            "kb_queries": ctx.kb_queries,
            "retrieved": r.retrieved_sources,
            "flags": r.guardrail_flags,
            "events": [{"agent": e.agent, "kind": e.kind, "text": e.text[:300]} for e in ctx.events],
        }
        path = self.deps.settings.log_dir / "traces.jsonl"
        with self._trace_lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
