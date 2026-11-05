"""Customer Query Agent: turns free text into a structured analysis.

The agent can only answer through `record_analysis`, whose arguments are enum-typed in the OpenAI
function schema, so it cannot return a category or urgency that does not exist. Code later raises
(never lowers) the ratings if a hard signal such as a legal threat or a safety hazard is present.
"""

from typing import Annotated

from core.deps import Deps
from core.models import Analysis, Category, CategoryLit, RequestContext, Sentiment, SentimentLit, Urgency, UrgencyLit

from .prompts import COMPANY, DATA_NOTICE, ONE_TOOL_RULE

NAME = "query_agent"
DISPLAY = "Customer Query Agent"
DESCRIPTION = "Reads the complaint and extracts category, urgency, sentiment and a one-line summary."

SYSTEM_MESSAGE = f"""You are the Customer Query Agent in an AI support desk. {COMPANY}
{DATA_NOTICE}

YOUR ONLY JOB
Understand the complaint and record it by calling record_analysis. You do not answer the customer.

CATEGORY: choose the single primary category.
- Billing: money wrongly taken, duplicate or failed charge, invoice, GST, coupon problems.
- Refund: wants money back, wants to return an item (change of mind or not), cancellation.
- Product: an item is broken, defective, dead on arrival, not working, or needs setup help; wants a replacement.
- Warranty: repair or warranty claim on a product used for a while.
- Shipping: late delivery, tracking, lost, damaged-in-transit or wrongly delivered parcel, address change.
- Account: login, password, OTP, profile or email change, account security.
- Other: anything that is none of the above, or is unrelated to Brightwell.
If several apply, choose the one the customer needs resolved first. Money wrongly taken is Billing even if they also want a refund.

URGENCY
- High: safety hazard (overheating, smoke, swelling, shock), duplicate or unauthorised charge, suspected fraud or hacked account, legal threat, or a stated hard deadline.
- Medium: order late beyond the promised date, broken or defective product, refund taking too long, customer already wrote before and got no answer.
- Low: how-to or information questions, routine return or exchange, password reset, general enquiries.

SENTIMENT
- Angry: insults, threats, profanity, shouting in capital letters. Use this sparingly.
- Frustrated: clearly unhappy but civil.
- Neutral: factual, no emotion. Positive: friendly or thankful.

FIELDS
- summary: one factual sentence in English, no emotional words, no personal data.
- product_mentioned: the product the customer names (for example "Aero earbuds"), otherwise an empty string.
Never invent facts the customer did not state.

EXAMPLES
"Where is my order? It was supposed to arrive yesterday." -> Shipping, Medium, Neutral
"I want to return the shoes I bought last week. How do I get a refund?" -> Refund, Low, Neutral, product "shoes"
"I forgot my password and can't log in." -> Account, Low, Neutral
"The blender I received is broken. Can I get a replacement?" -> Product, Medium, Neutral, product "blender"
"You charged my card three times! Fix this now or I'm contacting my bank and a lawyer." -> Billing, High, Angry
"My power bank is swelling and getting very hot" -> Product, High, Frustrated, product "power bank"
"Do you sell gift cards for a company of 500 employees?" -> Other, Low, Neutral

{ONE_TOOL_RULE}"""


def make_record_analysis(ctx: RequestContext):
    async def record_analysis(
        category: Annotated[CategoryLit, "Primary category of the complaint"],
        urgency: Annotated[UrgencyLit, "Low, Medium or High"],
        sentiment: Annotated[SentimentLit, "Customer sentiment"],
        summary: Annotated[str, "One factual sentence, no emotional words"],
        product_mentioned: Annotated[str, "Product name the customer mentioned, or empty string"] = "",
    ) -> str:
        """Record the structured analysis of the complaint."""
        ctx.analysis = Analysis(
            category=Category(category),
            urgency=Urgency(urgency),
            sentiment=Sentiment(sentiment),
            summary=" ".join(summary.split())[:300],
            product_mentioned=" ".join(product_mentioned.split())[:80],
        )
        ctx.emit(
            DISPLAY, "output", f"{category}, {urgency} urgency, {sentiment}",
            category=category, urgency=urgency, sentiment=sentiment, summary=ctx.analysis.summary,
        )
        return (
            f"ANALYSIS: category={category}; urgency={urgency}; sentiment={sentiment}; "
            f"product={ctx.analysis.product_mentioned or 'none'}; summary={ctx.analysis.summary}"
        )

    return record_analysis


def build_query_agent(model_client, ctx: RequestContext, deps: Deps):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool

    tool = FunctionTool(make_record_analysis(ctx), description="Record the structured analysis of the complaint.", name="record_analysis")
    return AssistantAgent(
        NAME, model_client=model_client, tools=[tool], description=DESCRIPTION,
        system_message=SYSTEM_MESSAGE, reflect_on_tool_use=False,
    )
