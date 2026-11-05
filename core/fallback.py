"""Degraded mode: what the desk does when the LLM is unreachable, slow or misconfigured.

The customer still gets a logged ticket, a reply built from the *knowledge base itself*, and a
human follow-up, never a stack trace and never silence.
"""

from __future__ import annotations

import re

from . import heuristics
from .models import Analysis, Passage


def heuristic_analysis(text: str) -> Analysis:
    sentiment = heuristics.detect_sentiment(text)
    return Analysis(
        category=heuristics.classify_category(text),
        urgency=heuristics.heuristic_urgency(text, sentiment),
        sentiment=sentiment,
        summary=heuristics.one_line_summary(text),
        source="heuristic",
    )


def _first_sentences(text: str, limit: int = 420) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        if len(out) + len(sentence) > limit and out:
            break
        out = f"{out} {sentence}".strip()
    return out


def compose_degraded_reply(passages: list[Passage], company: str, customer_name: str = "") -> str:
    greeting = f"Hello {customer_name}," if customer_name else "Hello,"
    if not passages:
        return (
            f"{greeting}\n\nThank you for contacting us. I could not find this in our support documentation "
            "and I do not want to guess and give you wrong information. A member of our support team "
            f"will review your request and reply to you directly.\n\nRegards,\n{company} Support"
        )
    top = passages[0]
    return (
        f"{greeting}\n\nThank you for contacting us, and we are sorry for the trouble. "
        f"Here is what our documentation says that may help: {_first_sentences(top.text)}\n\n"
        f"A member of our support team will also review your request to make sure it is fully resolved."
        f"\n\nRegards,\n{company} Support"
    )
