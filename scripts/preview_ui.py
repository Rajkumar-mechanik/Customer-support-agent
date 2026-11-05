"""Render the console's HTML components with real pipeline output into a static page for screenshots.

    python scripts/preview_ui.py preview.html
    google-chrome --headless --screenshot=preview.png --window-size=1360,1500 file://$PWD/preview.html

This does not need Streamlit. It exercises the same ui/ functions the app uses, driven by the
simulated agent team, so it is a faithful check of typography, colour and layout of the components.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings  # noqa: E402
from core.deps import Deps  # noqa: E402
from core.pipeline import SupportDesk  # noqa: E402
from core.simulated import SimulatedRunner  # noqa: E402
from ui import components as C  # noqa: E402
from ui import theme  # noqa: E402
from ui import timeline as T  # noqa: E402


def run(desk: SupportDesk, text: str, name: str):
    steps, notes = T.new_steps(), []
    T.start_first(steps, time.time())
    result = desk.handle_sync(text, name, "ORD-4512", session_id=text, on_event=lambda e: T.apply_event(steps, notes, e))
    T.finish(steps, result)
    return result, steps, notes


def main(out: str) -> None:
    tmp = Path(tempfile.mkdtemp())
    deps = Deps.build(Settings(log_dir=tmp))
    desk = SupportDesk(deps, runner=SimulatedRunner(deps, delay_s=0.05))
    resolved = run(desk, "My Aero earbuds only play sound in the left one. What can I do?", "Divya")
    escalated = run(desk, "You charged my card three times! Fix this now or I'm contacting my bank and a lawyer.", "Kavya")

    def case(item, customer):
        result, steps, notes = item
        return (
            f'<div class="panel-title">Case file</div>{C.timeline_html(steps, notes)}{C.result_html(result, customer)}'
            f'<div class="sec-label">Evidence retrieved from the knowledge base</div>{C.evidence_html(result.passages[:2])}'
        )

    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>{theme.css()}
body{{margin:0}} .shell{{display:grid;grid-template-columns:270px 1fr;min-height:100vh}}
.rail{{background:var(--rail);padding:26px 20px}} .main{{padding:32px 40px}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:36px}}
</style></head><body><div class="shell"><div class="rail">{C.wordmark_html()}
<div style="margin-top:8px;color:#fff;font-weight:600;padding:9px 12px;background:rgba(255,255,255,.1);box-shadow:inset 3px 0 0 var(--amber);border-radius:6px">Desk</div>
<div style="color:#fff;font-weight:600;padding:9px 12px">Ticket log</div><div style="color:#fff;font-weight:600;padding:9px 12px">Insights</div>
{C.system_status_html(desk.health())}</div>
<div class="main">{C.page_header_html("Desk", "Log a customer complaint. Four agents read it, check it against the company documents, write the reply and record the ticket.")}
<div class="cols"><div>{case(resolved, "Divya")}</div><div>{case(escalated, "Kavya")}</div></div></div></div></body></html>"""
    Path(out).write_text(page, encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "preview.html")
