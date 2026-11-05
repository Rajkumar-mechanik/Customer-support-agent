"""Log Agent: records the ticket and recommends whether a human should take over.

The model gives a recommendation. The binding decision is made by core/escalation.py, which also
applies mandatory rules (High urgency, angry customer, no document, legal/fraud/payment/safety
triggers, low confidence). The recommendation can add an escalation but never remove one.
"""

import asyncio
from typing import Annotated

from core.deps import Deps
from core.models import RequestContext
from core.ticketing import finalize_ticket

from .prompts import DATA_NOTICE, ONE_TOOL_RULE

NAME = "log_agent"
DISPLAY = "Log Agent"
DESCRIPTION = "Records the ticket and decides whether to escalate it to human support."

SYSTEM_MESSAGE = f"""You are the Log Agent in an AI support desk for Brightwell.
{DATA_NOTICE}

YOUR ONLY JOB
Look at the analysis, the retrieved passages and the drafted reply, then call log_ticket once.

Set escalate=true if ANY of these is true:
- urgency is High, or the customer is very angry
- the Knowledge Base Agent found no matching document
- the customer mentions a lawyer or legal action, fraud, unauthorised activity, a payment dispute, or a safety hazard
- the Resolution Agent's confidence is low, or it asked for human review
- the customer asks for something only a person can decide (compensation, an exception to policy)
- anything else a careful human agent would want to take over

Otherwise set escalate=false. When unsure, escalate.
reason: a short phrase of at most 15 words, for example "High urgency and angry customer".
The system also applies its own mandatory rules, so your recommendation can only add an escalation.

{ONE_TOOL_RULE}"""


def make_log_ticket(ctx: RequestContext, deps: Deps):
    async def log_ticket(
        escalate: Annotated[bool, "True to escalate to human support"],
        reason: Annotated[str, "Short reason for the decision, at most 15 words"],
    ) -> str:
        """Write the ticket to the log and return the final status."""
        result = await asyncio.to_thread(
            finalize_ticket, ctx, deps, agent_escalation=bool(escalate), agent_reason=" ".join(reason.split())[:200]
        )
        ctx.emit(
            DISPLAY, "output", f"{result.ticket_id} logged as {result.status.value}",
            ticket_id=result.ticket_id, status=result.status.value,
        )
        return f"LOGGED {result.ticket_id} status={result.status.value}"

    return log_ticket


def build_log_agent(model_client, ctx: RequestContext, deps: Deps):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool

    tool = FunctionTool(make_log_ticket(ctx, deps), description="Log the ticket and decide escalation.", name="log_ticket")
    return AssistantAgent(
        NAME, model_client=model_client, tools=[tool], description=DESCRIPTION,
        system_message=SYSTEM_MESSAGE, reflect_on_tool_use=False,
    )
