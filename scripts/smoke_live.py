"""Run the six complaints from the assignment through the REAL AutoGen team and gpt-4o-mini.

    python scripts/smoke_live.py

Needs OPENAI_API_KEY in .env. Prints one block per ticket (use it for your README screenshots) and
writes every ticket to logs/tickets.csv. Exits 1 if the pipeline fell back to safe mode, because that
means the live model path did not actually run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings  # noqa: E402
from core.deps import Deps  # noqa: E402
from core.pipeline import SupportDesk  # noqa: E402

COMPLAINTS = [
    ("Where is my order? It was supposed to arrive yesterday.", "Resolved"),
    ("I want to return the shoes I bought last week. How do I get a refund?", "Resolved"),
    ("I forgot my password and can't log in.", "Resolved"),
    ("The blender I received is broken. Can I get a replacement?", "Resolved"),
    ("You charged my card three times! Fix this now or I'm contacting my bank and a lawyer.", "Escalated"),
    ("Do you sell gift cards for a company of 500 employees with custom branding?", "Escalated"),
]


def main() -> int:
    settings = Settings.from_env()
    if not settings.llm_configured:
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 2
    desk = SupportDesk(Deps.build(settings))
    print(f"mode: {desk.health()['mode']}  model: {settings.model}\n")
    degraded = mismatches = 0
    for i, (text, expected) in enumerate(COMPLAINTS, 1):
        r = desk.handle_sync(text, "Priya Sharma", "ORD-4512", session_id=f"smoke-{i}")
        degraded += r.mode == "degraded"
        mismatches += r.status.value != expected
        print(f"[{r.ticket_id}] {r.status.value} (expected {expected})  {r.category.value}/{r.urgency.value}/{r.sentiment.value}"
              f"  confidence={r.confidence:.2f}  mode={r.mode}")
        print(f"  complaint : {text}")
        print(f"  sources   : {', '.join(r.kb_sources) or '-'}")
        if r.escalation_reasons:
            print(f"  escalated : {'; '.join(r.escalation_reasons)}")
        print("  reply     : " + r.reply.replace("\n", "\n              ") + "\n")
    print(f"{len(COMPLAINTS)} tickets, {degraded} degraded, {mismatches} differ from the brief's expected status")
    return 1 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
