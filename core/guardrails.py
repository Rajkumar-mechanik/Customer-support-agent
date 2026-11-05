"""Input and output guardrails. Pure functions, no LLM, fully unit-tested.

INPUT  (before any token is spent): length, encoding, junk, ID formats, rate limiting,
       prompt-injection detection, PII redaction, delimiter neutralising.
OUTPUT (before the customer sees a word): grounding of every number and contact detail in the
       retrieved passages, prompt/tool leakage, forbidden commitments, unfilled placeholders.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .models import Passage, TicketInput

# --------------------------------------------------------------------------------------
# Input side
# --------------------------------------------------------------------------------------

ORDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,24}$")
NAME_RE = re.compile(r"^[^\W\d_][\w .'\-]{0,59}$", re.UNICODE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠﻿]")
_DELIMITER_RE = re.compile(r"</?\s*(?:customer_complaint|system|assistant|user|instructions?)\s*>", re.IGNORECASE)

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|rules?|prompts?|messages?)",
    r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions?|rules?|guidelines?|polic(?:y|ies))",
    r"forget\s+(?:everything|all|your)\s+(?:above|previous|instructions?|rules?)",
    r"(?:reveal|show|print|repeat|output|leak)\s+(?:me\s+)?(?:your\s+|the\s+)?(?:system\s+|hidden\s+|initial\s+)?(?:prompt|instructions?)",
    r"\bsystem\s+prompt\b",
    r"you\s+are\s+now\s+(?:a|an|the|in)\b",
    r"\b(?:developer|god|admin|dan)\s+mode\b",
    r"\bdo\s+anything\s+now\b",
    r"\bjailbreak",
    r"act\s+as\s+(?:a|an|the)\s+(?:different|new|unrestricted|unfiltered|admin|system)",
    r"pretend\s+(?:to\s+be|you\s+are)\b",
    r"new\s+instructions?\s*:",
    r"override\s+(?:the\s+)?(?:policy|policies|rules|safety|instructions?)",
    r"(?:approve|issue|process)\s+(?:a\s+)?(?:full\s+)?refund\s+(?:regardless|no\s+matter|without\s+(?:checking|verif))",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w\-])(?:\+?91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
_CARD_RE = re.compile(r"(?<![\w\-])(?:\d[ \-]?){13,19}(?!\d)")
_AADHAAR_RE = re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")
_SECRET_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")
_CREDENTIAL_RE = re.compile(
    r"\b(password|passcode|passwd|pwd|pin|otp|cvv|cvc)\b(\s*(?:is|was|:|=)\s*)([^\s,;]*\d[^\s,;]*)",
    re.IGNORECASE,
)


class InputRejected(ValueError):
    """Raised for inputs that must not reach the LLM. `.errors` is safe to show to the user."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, int]:
    """Mask card numbers, IDs, emails, phones, secrets and spoken credentials."""
    count = 0

    def card(m: re.Match[str]) -> str:
        nonlocal count
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            count += 1
            return f"[CARD ending {digits[-4:]}]"
        return m.group(0)

    def sub(pattern: re.Pattern[str], repl: str, s: str) -> str:
        nonlocal count
        s, n = pattern.subn(repl, s)
        count += n
        return s

    text = _CARD_RE.sub(card, text)
    text = sub(_SECRET_RE, "[SECRET REMOVED]", text)
    text = sub(_AADHAAR_RE, "[ID NUMBER REMOVED]", text)
    text = sub(_EMAIL_RE, "[EMAIL]", text)
    text = sub(_PHONE_RE, "[PHONE]", text)

    def cred(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{m.group(2)}[REMOVED]"

    return _CREDENTIAL_RE.sub(cred, text), count


def detect_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


_PLACEHOLDER_TOKEN_RE = re.compile(r"\[[A-Z][A-Za-z0-9 ]{1,30}\]")


def retrieval_text(text: str) -> str:
    """The complaint as a search query: injected sentences and redaction placeholders removed.

    Prompt-injection text and "[CARD ending 1111]" markers are noise (or worse) for retrieval, so
    anything that builds a search query from the raw complaint should go through this.
    """
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    kept = [s for s in sentences if s and not _INJECTION_RE.search(s)]
    return _PLACEHOLDER_TOKEN_RE.sub(" ", " ".join(kept) if kept else text).strip()


def validate_input(
    complaint: str,
    customer_name: str = "",
    order_id: str = "",
    *,
    min_chars: int = 8,
    max_chars: int = 2000,
) -> TicketInput:
    """Validate and sanitise raw form input. Raises InputRejected with user-safe messages."""
    errors: list[str] = []
    text = unicodedata.normalize("NFKC", complaint or "")
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text:
        errors.append("Please describe the problem you are facing.")
    elif len(text) < min_chars:
        errors.append(f"Please add a little more detail (at least {min_chars} characters).")
    elif len(text) > max_chars:
        errors.append(f"Your message is too long ({len(text)} characters). Please keep it under {max_chars}.")
    else:
        letters = sum(c.isalpha() for c in text)
        if letters < 3 or letters / max(len(text), 1) < 0.3:
            errors.append("That does not look like a description of a problem. Please rephrase it in words.")

    name = " ".join((customer_name or "").split())
    if name and not NAME_RE.match(name):
        errors.append("Customer name contains unsupported characters (max 60 characters).")

    order = (order_id or "").strip().upper()
    if order and not ORDER_ID_RE.match(order):
        errors.append("Order ID may contain only letters, numbers and hyphens (3 to 25 characters).")

    if errors:
        raise InputRejected(errors)

    flags: list[str] = []
    if detect_injection(text):
        flags.append("prompt_injection")
    if _DELIMITER_RE.search(text):
        flags.append("delimiter_tampering")
        text = _DELIMITER_RE.sub("[tag removed]", text)

    text, redactions = redact_pii(text)
    if redactions:
        flags.append("pii_redacted")

    return TicketInput(
        complaint=text,
        customer_name=name,
        order_id=order,
        flags=tuple(flags),
        pii_redactions=redactions,
    )


class RateLimiter:
    """Sliding-window limiter keyed by session. Thread-safe, in-memory."""

    def __init__(self, max_per_minute: int, window_s: float = 60.0):
        self.max = max_per_minute
        self.window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        if self.max <= 0:
            return True, 0.0
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.max:
                return False, max(0.0, self.window - (now - hits[0]))
            hits.append(now)
            return True, 0.0


# --------------------------------------------------------------------------------------
# Output side
# --------------------------------------------------------------------------------------

MAX_REPLY_CHARS = 1500
MIN_REPLY_CHARS = 30

_LEAK_RE = re.compile(
    r"(system\s+prompt|my\s+instructions|as\s+an?\s+(?:ai|language\s+model)|openai|autogen|gpt-?4|"
    r"search_kb|submit_reply|record_analysis|log_ticket|knowledge\s+base\s+agent|resolution\s+agent|"
    r"query\s+agent|log\s+agent|retrieved\s+passages?)",
    re.IGNORECASE,
)
_COMMITMENT_PATTERNS = {
    "guarantee": re.compile(r"\bguarantee[ds]?\b", re.IGNORECASE),
    "promise": re.compile(r"\b(?:we|i)\s+promise\b", re.IGNORECASE),
    "liability": re.compile(r"\b(?:legally\s+(?:liable|responsible)|admit\s+(?:liability|fault)|our\s+fault\s+entirely)\b", re.IGNORECASE),
    "compensation": re.compile(r"\bcompensat\w+\b", re.IGNORECASE),
    "hundred_percent": re.compile(r"\b100\s*%", re.IGNORECASE),
}
_PLACEHOLDER_RE = re.compile(r"(\[[A-Za-z][A-Za-z _\-]{2,30}\]|\{\{[^}]+\}\}|<[A-Za-z][^>]{2,30}>|lorem ipsum)", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s)>\]]+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[-*•])\s+")
_TICKET_REF_RE = re.compile(r"\b[A-Z]{2,5}-\d{3,}\b")


def numbers_in(text: str) -> set[str]:
    """Numeric tokens in text, normalised (thousands commas removed, trailing .0 dropped)."""
    out: set[str] = set()
    for raw in _NUMBER_RE.findall(text):
        tok = raw.replace(",", "").rstrip(".")
        if "." in tok:
            tok = tok.rstrip("0").rstrip(".")
        out.add(tok)
    return out


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass
class OutputCheck:
    reply: str
    flags: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)  # flags that force the safe fallback reply

    @property
    def ok(self) -> bool:
        return not self.blocking


def validate_output(
    reply: str,
    passages: list[Passage],
    *,
    complaint: str = "",
    order_id: str = "",
) -> OutputCheck:
    """Check a drafted customer reply against what the knowledge base actually said."""
    check = OutputCheck(reply=(reply or "").strip())
    text = check.reply

    if len(text) < MIN_REPLY_CHARS:
        check.blocking.append("empty_or_short_reply")
        return check

    if len(text) > MAX_REPLY_CHARS:
        cut = text[:MAX_REPLY_CHARS]
        end = max(cut.rfind(". "), cut.rfind("\n"))
        check.reply = text = (cut[: end + 1] if end > 400 else cut).rstrip()
        check.flags.append("reply_truncated")

    if _LEAK_RE.search(text):
        check.blocking.append("prompt_or_tool_leak")

    if _PLACEHOLDER_RE.search(text):
        check.blocking.append("unfilled_placeholder")

    kb_text = "\n".join(p.text for p in passages)
    for name, pattern in _COMMITMENT_PATTERNS.items():
        if pattern.search(text) and not pattern.search(kb_text):
            check.blocking.append(f"unsupported_commitment:{name}")

    # Every number the customer will rely on must come from the KB (or from their own message).
    allowed = numbers_in(kb_text) | numbers_in(complaint) | numbers_in(order_id)
    allowed_digit_runs = {_digits_only(a) for a in allowed}
    body = _TICKET_REF_RE.sub("", _LIST_MARKER_RE.sub("", text))
    stray = sorted(n for n in numbers_in(body) if n not in allowed and _digits_only(n) not in allowed_digit_runs)
    if stray:
        check.blocking.append("ungrounded_numbers:" + ",".join(stray[:5]))

    # Emails, phone numbers and links must also be quoted from the KB, never invented.
    kb_lower = kb_text.lower()
    kb_digits = _digits_only(kb_text)
    for email in _EMAIL_RE.findall(text):
        if email.lower() not in kb_lower:
            check.blocking.append("ungrounded_contact:email")
    for url in _URL_RE.findall(text):
        if url.lower().rstrip(".,") not in kb_lower:
            check.blocking.append("ungrounded_contact:url")
    for phone in re.findall(r"(?<!\d)(?:\+?\d[\d\s\-]{8,}\d)(?!\d)", text):
        d = _digits_only(phone)
        if d and d not in kb_digits:
            check.blocking.append("ungrounded_contact:phone")

    scrubbed, n = redact_pii(check.reply)
    if n:
        check.reply = scrubbed
        check.flags.append("pii_in_reply_redacted")

    check.blocking = list(dict.fromkeys(check.blocking))
    check.flags.extend(check.blocking)
    return check


def safe_fallback_reply(company: str, customer_name: str = "", *, honest_no_answer: bool = False) -> str:
    """Code-written reply used whenever the model's draft cannot be trusted."""
    greeting = f"Hello {customer_name}," if customer_name else "Hello,"
    if honest_no_answer:
        body = (
            "Thank you for getting in touch. I could not find this in our support documentation, "
            "and I do not want to guess and give you wrong information. I have passed your request "
            "to a member of our support team, who will review it and reply to you directly."
        )
    else:
        body = (
            "Thank you for getting in touch, and we are sorry for the trouble. Your request needs a "
            "closer look from a person, so I have passed it to our support team. A specialist will "
            "review your case and reply to you directly."
        )
    return f"{greeting}\n\n{body}\n\nRegards,\n{company} Support"
