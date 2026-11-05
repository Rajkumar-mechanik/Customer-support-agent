"""Deterministic text signals.

These do three jobs:
  1. *Safety floor* – they can RAISE urgency / force escalation even if the LLM under-rates
     a message (legal threats, fraud, physical-safety hazards). They never lower it.
  2. *Fallback brain* – when the LLM is unreachable the desk degrades to these rules instead
     of failing, so the customer still gets a logged ticket and a human follow-up.
  3. *Baseline for evaluation* – the offline eval reports how far the LLM adds on top.
"""

from __future__ import annotations

import re

from .models import Category, Sentiment, Urgency

_FLAGS = re.IGNORECASE

LEGAL_RE = re.compile(
    r"\b(lawyer|attorney|advocate|solicitor|sue\b|suing|lawsuit|legal\s+action|legal\s+notice|"
    r"court|consumer\s+(?:forum|court|commission|protection)|police|ombudsman|"
    r"take\s+(?:this|it)\s+to\s+(?:court|the\s+media)|defamation)",
    _FLAGS,
)
FRAUD_RE = re.compile(
    r"\b(fraud|fraudulent|scam|scammed|cheated|cheating|unauthori[sz]ed|stolen|hacked|"
    r"phishing|identity\s+theft|not\s+made\s+by\s+me|i\s+did(?:n'?t| not)\s+(?:make|authori[sz]e))",
    _FLAGS,
)
PAYMENT_DISPUTE_RE = re.compile(
    r"\b(charge\s*back|chargeback|dispute\s+(?:the\s+)?(?:charge|payment|transaction)|"
    r"contact(?:ing)?\s+(?:my\s+)?bank|call(?:ing)?\s+(?:my\s+)?bank|bank\s+dispute|"
    r"double[-\s]?charg\w*|duplicate\s+charg\w*|"
    r"(?:charge[ds]?|deduct\w*|debit\w*|bill(?:ed)?)\b[^.!?\n]{0,30}?\b"
    r"(?:twice|thrice|again|two\s+times|three\s+times|\d+\s+times|multiple\s+times|several\s+times)|"
    r"(?:twice|thrice|two\s+times|three\s+times|\d+\s+times|multiple\s+times)\s+(?:charged|deducted|debited|billed))",
    _FLAGS,
)
SAFETY_RE = re.compile(
    r"\b(caught\s+fire|on\s+fire|catch(?:ing)?\s+fire|set\s+(?:\w+\s+)?on\s+fire|started\s+a\s+fire|fire\s+(?:broke|hazard|risk)|smok(?:e|ing)|burn(?:t|ing|ed)?\b|"
    r"explod\w+|explosion|swollen|swelling|bulging|overheat\w*|melt(?:ed|ing)|"
    r"electric\s+shock|shocked\s+me|sparks?\b|sparking|injur\w+|hospital)",
    _FLAGS,
)

_ANGER_WORDS = re.compile(
    r"\b(furious|outraged|disgusting|unacceptable|worst|pathetic|ridiculous|useless|"
    r"fed\s+up|sick\s+of|rubbish|garbage|trash|incompetent|liar|liars|fraud|scam|"
    r"idiots?|stupid|terrible|horrible|awful|never\s+(?:buying|ordering|shopping)|"
    r"disgrace|nonsense|joke|damn|hell|wtf|bloody)\b",
    _FLAGS,
)
_FRUSTRATION_WORDS = re.compile(
    r"\b(frustrat\w+|annoy\w+|disappoint\w+|still\s+(?:waiting|not)|again|nobody|no\s+one|"
    r"no\s+reply|not\s+replying|ignored|waiting\s+for\s+days|days\s+late|delay\w*|"
    r"yet\s+again|third\s+time|several\s+times|unhappy|upset)\b",
    _FLAGS,
)
_POSITIVE_WORDS = re.compile(r"\b(thanks|thank\s+you|love|great|happy|appreciate|awesome|good)\b", _FLAGS)

_URGENT_WORDS = re.compile(
    r"\b(urgent|urgently|asap|immediately|right\s+now|emergency|today\s+itself|"
    r"within\s+(?:the\s+)?(?:hour|day)|fix\s+this\s+now)\b",
    _FLAGS,
)

_CATEGORY_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.SHIPPING: (
        "deliver", "delivery", "delivered", "arrive", "arrived", "shipping", "shipped", "ship",
        "tracking", "track", "courier", "package", "parcel", "dispatch", "late", "delayed",
        "where is my order", "out for delivery", "address",
    ),
    Category.REFUND: ("refund", "return", "money back", "reimburse", "cancel", "cancellation", "exchange"),
    Category.BILLING: (
        "charge", "charged", "billing", "invoice", "payment", "paid", "card", "transaction",
        "deducted", "gst", "emi", "coupon", "promo", "price",
    ),
    Category.ACCOUNT: (
        "password", "login", "log in", "sign in", "signin", "account", "otp", "locked",
        "two-factor", "2fa", "verification code", "reset link", "username",
    ),
    Category.PRODUCT: (
        "broken", "defective", "not working", "stopped working", "doesn't work", "does not work",
        "battery", "setup", "set up", "pair", "pairing", "connect", "error", "noise", "damaged",
        "replacement", "replace", "crack", "faulty", "charging", "wifi", "wi-fi", "firmware",
    ),
    Category.WARRANTY: ("warranty", "repair", "service centre", "service center", "guarantee"),
}

# Tie-break priority when two categories score equally (specific beats generic).
_PRIORITY = [
    Category.BILLING, Category.ACCOUNT, Category.REFUND, Category.WARRANTY,
    Category.SHIPPING, Category.PRODUCT,
]


def trigger_codes(text: str) -> list[str]:
    """Return the hard escalation triggers found in the text."""
    codes: list[str] = []
    if LEGAL_RE.search(text):
        codes.append("legal_threat")
    if FRAUD_RE.search(text):
        codes.append("fraud")
    if PAYMENT_DISPUTE_RE.search(text):
        codes.append("payment_dispute")
    if SAFETY_RE.search(text):
        codes.append("safety_hazard")
    return codes


def classify_category(text: str) -> Category:
    lowered = text.lower()
    scores: dict[Category, int] = {}
    for category, words in _CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", lowered))
    best = max(scores.values(), default=0)
    if best == 0:
        return Category.OTHER
    for category in _PRIORITY:
        if scores.get(category) == best:
            # "refund" + "broken" => the customer wants money back for a broken item: Refund wins
            return category
    return Category.OTHER


def detect_sentiment(text: str) -> Sentiment:
    letters = [c for c in text if c.isalpha()]
    caps_ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) if len(letters) > 20 else 0.0
    anger_hits = len(_ANGER_WORDS.findall(text))
    exclaims = text.count("!")
    if anger_hits >= 2 or (anger_hits >= 1 and (caps_ratio > 0.5 or exclaims >= 3)) or caps_ratio > 0.7:
        return Sentiment.ANGRY
    if LEGAL_RE.search(text) and (anger_hits or exclaims >= 2):
        return Sentiment.ANGRY
    if anger_hits or _FRUSTRATION_WORDS.search(text) or exclaims >= 3:
        return Sentiment.FRUSTRATED
    if _POSITIVE_WORDS.search(text) and not _FRUSTRATION_WORDS.search(text):
        return Sentiment.POSITIVE
    return Sentiment.NEUTRAL


def urgency_floor(text: str, sentiment: Sentiment | None = None) -> Urgency:
    """Minimum urgency implied by the text. The pipeline takes max(LLM, floor)."""
    codes = trigger_codes(text)
    if any(c in codes for c in ("legal_threat", "fraud", "payment_dispute", "safety_hazard")):
        return Urgency.HIGH
    if _URGENT_WORDS.search(text):
        return Urgency.HIGH
    if (sentiment or detect_sentiment(text)) is Sentiment.ANGRY:
        return Urgency.HIGH
    return Urgency.LOW


def heuristic_urgency(text: str, sentiment: Sentiment) -> Urgency:
    floor = urgency_floor(text, sentiment)
    if floor is Urgency.HIGH:
        return floor
    if sentiment is Sentiment.FRUSTRATED or re.search(r"\b(days?\s+late|still\s+waiting|not\s+working|broken|defective)\b", text, _FLAGS):
        return Urgency.MEDIUM
    return Urgency.LOW


def one_line_summary(text: str, limit: int = 140) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    first = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]
    return (first if len(first) <= limit else first[: limit - 1].rstrip() + "…")
