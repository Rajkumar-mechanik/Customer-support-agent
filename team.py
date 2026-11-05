"""Wires the four agents into one AutoGen RoundRobinGroupChat: Query -> Knowledge -> Resolution -> Log.

Everything that imports `autogen_*` is imported lazily inside functions, so the deterministic
backend, the unit tests and the offline evals run without the AutoGen packages installed.
"""

from __future__ import annotations

from agents import knowledge_agent, log_agent, query_agent, resolution_agent
from core.config import Settings
from core.deps import Deps
from core.logging_setup import get_logger
from core.models import RequestContext, TicketInput

log = get_logger("team")

AGENT_ORDER = [query_agent, knowledge_agent, resolution_agent, log_agent]
DISPLAY_NAMES = {m.NAME: m.DISPLAY for m in AGENT_ORDER}
DISPLAY_ORDER = [m.DISPLAY for m in AGENT_ORDER]


def build_task(ticket: TicketInput) -> str:
    """The opening message every agent sees. The complaint is fenced as data."""
    return (
        "New support ticket.\n"
        f"Customer name: {ticket.customer_name or 'not given'}\n"
        f"Order ID: {ticket.order_id or 'not given'}\n"
        "<customer_complaint>\n"
        f"{ticket.complaint}\n"
        "</customer_complaint>"
    )


def make_model_client(settings: Settings):
    """OpenAI client for AutoGen (gpt-4o-mini by default), deterministic and time-limited."""
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    kwargs = dict(
        model=settings.model,
        api_key=settings.openai_api_key,
        temperature=settings.temperature,
        timeout=settings.request_timeout_s,
        max_retries=2,
    )
    try:
        return OpenAIChatCompletionClient(seed=7, **kwargs)
    except (TypeError, ValueError):  # older/newer client versions may not accept `seed`
        return OpenAIChatCompletionClient(**kwargs)


def build_team(model_client, ctx: RequestContext, deps: Deps):
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat

    participants = [
        query_agent.build_query_agent(model_client, ctx, deps),
        knowledge_agent.build_knowledge_agent(model_client, ctx, deps),
        resolution_agent.build_resolution_agent(model_client, ctx, deps),
        log_agent.build_log_agent(model_client, ctx, deps),
    ]
    # Semantic stop: the Log Agent's tool result contains "LOGGED". Safety nets: max_turns=4 allows
    # exactly one turn per agent, and MaxMessageTermination bounds any unexpected chatter.
    return RoundRobinGroupChat(
        participants,
        termination_condition=TextMentionTermination("LOGGED") | MaxMessageTermination(10),
        max_turns=4,
    )


class AutoGenRunner:
    """Runs the four-agent team for one ticket. Implements core.pipeline.AgentRunner."""

    def __init__(self, deps: Deps):
        self.deps = deps

    async def run(self, ctx: RequestContext) -> None:
        client = make_model_client(self.deps.settings)

        def usage() -> dict[str, int]:
            u = client.total_usage()
            return {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens}

        ctx.usage_probe = usage
        started: set[str] = set()
        try:
            team = build_team(client, ctx, self.deps)
            async for msg in team.run_stream(task=build_task(ctx.ticket_input)):
                source = getattr(msg, "source", "")
                if source in DISPLAY_NAMES and source not in started:
                    started.add(source)
                    ctx.emit(DISPLAY_NAMES[source], "start", "Working")
        finally:
            ctx.tokens = usage()
            close = getattr(client, "close", None)
            if close is not None:
                await close()
