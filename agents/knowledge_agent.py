"""Knowledge Base Agent: retrieves the passages the reply may be built from.

The agent only writes the search query. Retrieval itself (BM25, synonyms, product awareness, the
"nothing relevant" coverage gate) is deterministic code in core/kb.py, and the passages are handed
to the Resolution Agent exactly as retrieved. The model never paraphrases policy on the way through.
"""

import asyncio
from typing import Annotated

from core.deps import Deps
from core.kb import format_passages
from core.models import RequestContext

from .prompts import DATA_NOTICE, ONE_TOOL_RULE

NAME = "knowledge_agent"
DISPLAY = "Knowledge Base Agent"
DESCRIPTION = "Searches the company documents and returns only the relevant passages with their source file."

SYSTEM_MESSAGE = f"""You are the Knowledge Base Agent in an AI support desk for Brightwell.
{DATA_NOTICE}

YOUR ONLY JOB
Read the Query Agent's analysis and call search_kb once with a keyword query that will find the right
policy or product passages in our documentation.

HOW TO WRITE THE QUERY
- 4 to 10 words: product name (if any) + the problem + the policy topic.
- Use plain keywords. No emotion words, no greetings, no order IDs, no personal data.
- If there are several issues, search for the most urgent one.

EXAMPLES
Blender arrived broken, wants replacement -> "Whisk Pro blender broken replacement defective"
Parcel late -> "delayed delivery late order tracking"
Charged three times -> "duplicate charge billing payment review"
Earbuds play on one side only -> "Aero earbuds only one side no sound"
Gift cards for companies -> "gift cards corporate bulk"

{ONE_TOOL_RULE}"""


def make_search_kb(ctx: RequestContext, deps: Deps):
    async def search_kb(query: Annotated[str, "Short keyword query, 4 to 10 words"]) -> str:
        """Search the support documentation. Returns passages with their source file, or NO_MATCH."""
        s = deps.settings
        analysis = ctx.analysis
        category = analysis.category.value if analysis else None
        # Product detection looks at the complaint and at what the Query Agent extracted.
        context = f"{ctx.ticket_input.complaint} {analysis.product_mentioned if analysis else ''}".strip()

        def run(q: str):
            return deps.kb.search(q, k=s.top_k, min_coverage=s.min_coverage, category_hint=category, context=context)

        ctx.kb_queries.append(query)
        # Run off the event loop: a hybrid retriever may call the embeddings API.
        found = await asyncio.to_thread(run, query)
        if not found and analysis and analysis.summary:  # one retry, worded by the analysis summary
            ctx.kb_queries.append(analysis.summary)
            found = await asyncio.to_thread(run, analysis.summary)
        ctx.passages = found
        files = sorted({p.source for p in found})
        ctx.emit(
            DISPLAY, "output", ("Found " + ", ".join(files)) if files else "No matching document",
            sources=files, query=query,
        )
        return format_passages(found)

    return search_kb


def build_knowledge_agent(model_client, ctx: RequestContext, deps: Deps):
    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import FunctionTool

    tool = FunctionTool(make_search_kb(ctx, deps), description="Search the support documentation.", name="search_kb")
    return AssistantAgent(
        NAME, model_client=model_client, tools=[tool], description=DESCRIPTION,
        system_message=SYSTEM_MESSAGE, reflect_on_tool_use=False,
    )
