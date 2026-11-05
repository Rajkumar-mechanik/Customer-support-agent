"""Escalation policy: deterministic, auditable, and one-directional.

The LLM may *recommend* escalation; it can never *cancel* one the rules require. Every rule
below maps to a line in the assignment's escalation section and to a unit test.
"""

from __future__ import annotations

from .config import Settings
from .models import (
    CONFIDENCE_SCORES,
    Analysis,
    Category,
    EscalationDecision,
    Passage,
    Resolution,
    Sentiment,
    Urgency,
)

_TRIGGER_TEXT = {
    "legal_threat": "Legal threat detected",
    "fraud": "Possible fraud or unauthorised activity",
    "payment_dispute": "Payment dispute / duplicate charge",
    "safety_hazard": "Physical safety hazard reported",
}
_GUARDRAIL_TEXT = {
    "prompt_injection": "Possible prompt-injection attempt in the message",
}


def final_confidence(resolution: Resolution | None, passages: list[Passage]) -> float:
    """Blend the model's own (categorical) confidence with how well retrieval covered the query."""
    if resolution is None:
        return 0.0
    llm = CONFIDENCE_SCORES.get(resolution.llm_confidence, 0.5)
    if not passages:
        return round(min(llm, 0.2), 2)
    retrieval_cap = min(1.0, max(passages[0].coverage, 0.0) + 0.35)
    return round(min(llm, retrieval_cap), 2)


def decide(
    *,
    analysis: Analysis,
    passages: list[Passage],
    resolution: Resolution | None,
    triggers: list[str],
    input_flags: tuple[str, ...] | list[str],
    output_blocking: list[str],
    confidence: float,
    settings: Settings,
    degraded: bool = False,
) -> EscalationDecision:
    reasons: list[str] = []

    if analysis.urgency is Urgency.HIGH:
        reasons.append("High urgency")
    if analysis.sentiment is Sentiment.ANGRY:
        reasons.append("Customer is very angry")
    if not passages:
        reasons.append("No matching knowledge-base document")
    if analysis.category is Category.OTHER and passages and passages[0].coverage < 0.6:
        reasons.append("Request is outside the support scope or unclear")
    for code in triggers:
        reasons.append(_TRIGGER_TEXT.get(code, code))
    for flag in input_flags:
        if flag in _GUARDRAIL_TEXT:
            reasons.append(_GUARDRAIL_TEXT[flag])
    if output_blocking:
        reasons.append("Draft reply failed guardrails (" + ", ".join(output_blocking) + ")")
    if resolution is not None and resolution.needs_human:
        reasons.append("Agent recommended human review" + (f": {resolution.note}" if resolution.note else ""))
    if confidence < settings.confidence_threshold and passages:
        reasons.append(f"Low confidence ({confidence:.2f} < {settings.confidence_threshold:.2f})")
    if degraded:
        reasons.append("AI model unavailable; automated draft needs human review")

    return EscalationDecision(escalate=bool(reasons), reasons=tuple(dict.fromkeys(reasons)))
