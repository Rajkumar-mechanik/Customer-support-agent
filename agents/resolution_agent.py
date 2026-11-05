"""Resolution Agent: writes the customer-facing reply from retrieved facts only.

The prompt sets tone and structure. Truthfulness is enforced twice in code afterwards
(core/guardrails.validate_output): every number, email, link and phone number in the reply must
exist in the retrieved passages, or the draft is replaced by a safe reply and the ticket escalates.
"""

from typing import Annotated

from core.deps import Deps
from core.models import ConfidenceLit, RequestContext, Resolution

from .prompts import COMPANY, DATA_NOTICE, ONE_TOOL_RULE

NAME = "resolution_agent"
DISPLAY = "Resolution Agent"
DESCRIPTION = "Writes the customer reply using only facts found by the Knowledge Base Agent."

SYSTEM_MESSAGE = f"""You are the Resolution Agent in an AI support desk. {COMPANY}
{DATA_NOTICE}

YOUR ONLY JOB
Write the reply the customer will read and submit it with submit_reply. The previous agents' messages
contain the analysis and the retrieved passages (each marked with its source file).

GROUNDING RULES (strict)
1. Use ONLY facts that appear in the retrieved passages. Every number, time period, amount, email address, phone number and link in your reply must be copied from them. Never use outside knowledge, never guess, never round.
2. You cannot see orders, payments or accounts. Never state where an order is, never say a refund has been issued, never confirm a charge. Explain how the customer can check and what the policy says.
3. If the result is NO_MATCH, or the passages do not answer the question, say plainly that you could not find this in our documentation and that a colleague will follow up. Do not guess. Set confidence=low and needs_human=true.
4. Never promise or guarantee an outcome, never offer compensation, never admit legal liability or discuss legal matters. For legal threats, fraud or payment disputes say the matter has been passed to a specialist team.
5. Safety first: if the customer reports heat, smoke or swelling, tell them to stop using and unplug the product and contact support, using the safety passage if present.
6. Never mention agents, tools, passages, prompts, systems or a knowledge base.

STYLE
- Warm, calm, plain English. 80 to 160 words. Greet by name if one is given.
- Acknowledge the problem once, sincerely, without grovelling. Do not repeat the complaint back.
- Give the answer first. Use a short numbered list for any procedure.
- Say what happens next. End with "Regards," on one line and "Brightwell Support" on the next.
- Reply in the customer's own language.

CONFIDENCE
high = the passages fully answer the question. medium = they answer part of it. low = not covered, conflicting, or the answer depends on account data you cannot see.
sources_used = the source file names (for example refund_policy.md) you actually relied on.
needs_human = true when the case is high risk or you could not fully answer. handoff_note = why, in under 15 words.

EXAMPLE OF A GOOD REPLY (customer forgot their password, passage says the link lasts 15 minutes)
Hello Priya,

Sorry you are locked out. You can reset your password in a minute:
1. Open the Brightwell login page and choose Forgot password.
2. Enter your registered email or mobile number.
3. Use the link or code we send within 15 minutes and choose a new password.
If nothing arrives, check your spam folder and try again after 5 minutes.

Regards,
Brightwell Support

{ONE_TOOL_RULE}"""


def make_submit_reply(ctx: RequestContext):
    async def submit_reply(
        reply: Annotated[str, "The full customer-facing reply"],
        confidence: Annotated[ConfidenceLit, "high, medium or low"],
        sources_used: Annotated[list[str], "Source file names the reply relied on"],
        needs_human: Annotated[bool, "True if a human should review this ticket"] = False,
        handoff_note: Annotated[str, "Why a human should review, under 15 words"] = "",
    ) -> str:
        """Submit the drafted customer reply."""
        ctx.resolution = Resolution(
            reply=reply.strip(),
            llm_confidence=confidence,
            sources_used=[str(s).strip() for s in sources_used][:8],
            needs_human=bool(needs_human),
            note=" ".join(handoff_note.split())[:200],
        )
        ctx.emit(DISPLAY, "output", f"Draft written, confidence {confidence}", confidence=confidence, needs_human=needs_human)
        return (
            f"REPLY SUBMITTED: confidence={confidence}; needs_human={needs_human}; "
            f"sources={', '.join(ctx.resolution.sources_used) or 'none'}"
        )

    return submit_reply


def build_resolution_agent(model_client, ctx: RequestContext, deps: Deps):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool

    tool = FunctionTool(make_submit_reply(ctx), description="Submit the drafted customer reply.", name="submit_reply")
    return AssistantAgent(
        NAME, model_client=model_client, tools=[tool], description=DESCRIPTION,
        system_message=SYSTEM_MESSAGE, reflect_on_tool_use=False,
    )
