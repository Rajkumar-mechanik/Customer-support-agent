"""HTML fragments for the console. Every dynamic value is escaped; none of these import Streamlit."""

from __future__ import annotations

from html import escape as _e
from typing import Any

from core.models import Passage, TicketResult

from .timeline import Step


def e(value: Any) -> str:
    return _e(str(value), quote=True)


def paras(value: Any) -> str:
    """Escape text and render blank-line-separated paragraphs as <p> (no blank lines in the output)."""
    blocks = [b for b in str(value).replace("\r\n", "\n").split("\n\n") if b.strip()]
    return "".join(f"<p>{e(b.strip()).replace(chr(10), '<br>')}</p>" for b in blocks)


def eb(value: Any) -> str:
    """Escape and keep line breaks as <br>. Blank lines would end a raw-HTML block in markdown."""
    return e(value).replace("\r\n", "\n").replace("\n", "<br>")


def wordmark_html() -> str:
    return (
        '<div class="wordmark"><span class="bulb"></span>Brightwell</div>'
        '<div class="wordmark-sub">Support desk</div>'
    )


def system_status_html(health: dict[str, Any]) -> str:
    live = health.get("mode") == "live"
    breaker = str(health.get("breaker", "closed"))
    tone = "ok" if live and breaker == "closed" else ("bad" if breaker == "open" else "warn")
    rows = [
        ("Mode", f'<span class="dot {tone}"></span>{e(health.get("mode", ""))}'),
        ("Model", e(health.get("model", ""))),
        ("Retrieval", e(health.get("retriever", ""))),
        ("Documents", f'{e(health.get("documents", 0))} ({e(health.get("products", 0))} products)'),
        ("Prompts", f'v{e(health.get("prompt_version", ""))}'),
        ("Session", f'{e(health.get("tickets", 0))} tickets, {e(health.get("escalated", 0))} escalated'),
    ]
    body = "".join(f'<div class="row"><span class="k">{k}</span><span class="v">{v}</span></div>' for k, v in rows)
    return f'<div class="sysbox">{body}</div>'


def empty_state_html() -> str:
    return (
        '<div class="empty"><b>No ticket yet.</b><br>'
        "Submit a complaint and four agents will work on it in turn: they read it, find the answer in "
        "the company documents, write a reply from those facts only, and log the ticket. "
        "Anything urgent, risky or not covered by the documents is handed to a person.</div>"
    )


def timeline_html(steps: list[Step], notes: list[str] | None = None) -> str:
    rows = []
    for s in steps:
        secs = f'<span class="time">{s.seconds:.1f}s</span>' if s.seconds is not None and s.state == "done" else ""
        out = f'<div class="out">{eb(s.text)}</div>' if s.text and s.state in ("done", "fail", "skip") else ""
        state_label = {"run": "Working", "pending": "Waiting"}.get(s.state, "")
        role = e(s.role) if not state_label else f"{e(s.role)} ({state_label.lower()})"
        rows.append(
            f'<div class="step {s.state}"><span class="node"></span>'
            f'<div class="name">{e(s.name)}{secs}</div><div class="role">{role}</div>{out}</div>'
        )
    note_html = "".join(f"<div>{e(n)}</div>" for n in (notes or []))
    note_block = f'<div class="notes">{note_html}</div>' if note_html else ""
    return f'<div class="pipeline">{"".join(rows)}</div>{note_block}'


def _facts(category: str, urgency: str, sentiment: str, confidence: str) -> str:
    items = [("Category", category), ("Urgency", urgency), ("Sentiment", sentiment), ("Confidence", confidence)]
    return '<div class="facts">' + "".join(
        f'<div class="fact"><div class="l">{l}</div><div class="v">{e(v)}</div></div>' for l, v in items
    ) + "</div>"


def _case_html(
    *, ticket_id: str, status: str, category: str, urgency: str, sentiment: str, confidence: str,
    reply: str, reasons: list[str], sources: list[str], customer: str = "",
) -> str:
    cls = "escalated" if status == "Escalated" else "resolved"
    parts = [
        f'<div class="casefile {cls}">',
        f'<div class="cf-head"><span class="cf-id">{e(ticket_id)}</span><span class="badge {cls}">{e(status)}</span></div>',
        _facts(category, urgency, sentiment, confidence),
        f'<div class="sec-label">{"Reply to " + e(customer) if customer else "Reply to customer"}</div>',
        f'<div class="reply">{paras(reply)}</div>',
    ]
    if status == "Escalated" and reasons:
        items = "".join(f"<li>{e(r)}</li>" for r in reasons)
        parts += ['<div class="sec-label">Why this went to a person</div>', f'<ul class="reasons">{items}</ul>']
    if sources:
        chips = "".join(f'<span class="src">{e(s)}</span>' for s in sources)
        parts += ['<div class="sec-label">Answered from</div>', f'<div class="sources">{chips}</div>']
    parts.append("</div>")
    return "".join(parts)


def result_html(r: TicketResult, customer: str = "") -> str:
    return _case_html(
        ticket_id=r.ticket_id, status=r.status.value, category=r.category.value, urgency=r.urgency.value,
        sentiment=r.sentiment.value, confidence=f"{r.confidence:.2f}", reply=r.reply,
        reasons=r.escalation_reasons, sources=r.kb_sources, customer=customer,
    )


def row_html(row: dict[str, Any]) -> str:
    """Render one ticket-log row (a dict of strings) in the same case-file layout."""
    reasons = [x.strip() for x in str(row.get("escalation_reason", "")).split(";") if x.strip()]
    sources = [x.strip() for x in str(row.get("kb_sources", "")).split(";") if x.strip()]
    return _case_html(
        ticket_id=str(row.get("ticket_id", "")), status=str(row.get("status", "")),
        category=str(row.get("category", "")), urgency=str(row.get("urgency", "")),
        sentiment=str(row.get("sentiment", "")), confidence=str(row.get("confidence", "")),
        reply=str(row.get("response", "")), reasons=reasons, sources=sources,
        customer=str(row.get("customer_name", "")),
    )


def evidence_html(passages: list[Passage]) -> str:
    if not passages:
        return '<div class="ev"><div class="t">No document in the knowledge base answered this question.</div></div>'
    out = []
    for p in passages:
        text = p.text.strip()
        text = text if len(text) <= 420 else text[:417].rstrip() + "..."
        width = max(4, min(100, int(p.coverage * 100)))
        out.append(
            f'<div class="ev"><div class="h">{e(p.source)}: {e(p.heading)}</div>'
            f'<div class="cov" title="Query coverage {p.coverage:.2f}"><i style="width:{width}%"></i></div>'
            f'<div class="t">{eb(text)}</div></div>'
        )
    return "".join(out)


def page_header_html(title: str, subtitle: str) -> str:
    return f'<div class="page-title">{e(title)}</div><p class="page-sub">{e(subtitle)}</p>'
