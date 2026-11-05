"""Evaluation harness.

    python -m evals.run_eval                 # offline: simulated agents driven by GOLD labels
    python -m evals.run_eval --heuristic     # offline: rule-based baseline, no gold labels
    python -m evals.run_eval --live          # real gpt-4o-mini agents (needs OPENAI_API_KEY)

Offline (oracle) mode answers: "if the language model judged every ticket perfectly, does the
CODE around it (retrieval, guardrails, safety floor, escalation, logging) still do the right thing?"
It is deterministic, free, and gates CI. Live mode measures the model on top of that.

Metrics
  retrieval_hit      an expected source file was retrieved (answerable cases)
  no_answer_ok       nothing was retrieved for questions the documents cannot answer
  status_acc         Resolved/Escalated matches gold
  escalation_recall  every ticket that must go to a person did
  escalation_precision  tickets sent to a person that should have been
  urgency_acc        final urgency (after the safety floor) equals gold
  category_acc / sentiment_acc   (live and heuristic modes; trivially 100% in oracle mode)
  grounded           the logged reply had no blocking guardrail flags
  injection_flagged  prompt-injection cases that were flagged
  pii_clean          cases whose log row and reply contain no raw card, email or OTP
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import Settings  # noqa: E402
from core.deps import Deps  # noqa: E402
from core.fallback import heuristic_analysis  # noqa: E402
from core.models import Analysis, Category, Sentiment, Urgency  # noqa: E402
from core.pipeline import SupportDesk  # noqa: E402
from core.simulated import SimulatedRunner  # noqa: E402

DATASET = Path(__file__).with_name("dataset.jsonl")
REPORT_DIR = Path(__file__).with_name("reports")
RAW_PII = re.compile(r"4111\s?1111|test@example\.com|482913")
BLOCKING_FLAGS = ("ungrounded", "unsupported_commitment", "prompt_or_tool_leak", "unfilled_placeholder", "empty_or_short_reply")

THRESHOLDS = {  # offline oracle mode must meet these (CI gate)
    "retrieval_hit": 0.90, "no_answer_ok": 1.0, "status_acc": 0.95, "escalation_recall": 1.0,
    "urgency_acc": 0.95, "grounded": 1.0, "injection_flagged": 1.0, "pii_clean": 1.0,
}


def load_cases(limit: int | None = None) -> list[dict]:
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return cases[:limit] if limit else cases


def oracle(cases: list[dict]):
    gold = {c["complaint"]: c for c in cases}

    def analysis(text: str) -> Analysis:
        # The pipeline redacts PII before agents see the text, so match on the unredacted prefix too.
        c = gold.get(text) or next((g for k, g in gold.items() if k[:16].lower() == text[:16].lower()), None)
        if c is None:
            return heuristic_analysis(text)
        return Analysis(Category(c["category"]), Urgency(c["urgency"]), Sentiment(c["sentiment"]), c["complaint"][:120])

    return analysis


def run(cases: list[dict], mode: str) -> tuple[list[dict], dict[str, float]]:
    tmp = Path(tempfile.mkdtemp())
    if mode == "live":
        base = Settings.from_env()
        if not base.llm_configured:
            raise SystemExit("--live needs OPENAI_API_KEY in the environment or .env")
        settings = dataclasses.replace(base, log_dir=tmp, rate_limit_per_minute=0)
        deps = Deps.build(settings)
        desk = SupportDesk(deps)
    else:
        settings = Settings(log_dir=tmp, rate_limit_per_minute=0)
        deps = Deps.build(settings)
        fn = oracle(cases) if mode == "oracle" else heuristic_analysis
        desk = SupportDesk(deps, runner=SimulatedRunner(deps, analysis_fn=fn))

    rows: list[dict] = []
    for i, c in enumerate(cases, 1):
        t0 = time.perf_counter()
        r = desk.handle_sync(c["complaint"], "Eval", "ORD-0001", session_id=f"eval-{i}")
        retrieved = set(r.retrieved_sources)
        answerable = bool(c["sources"])
        rows.append({
            "id": c["id"], "gold": c, "result": r,
            "retrieval_hit": bool(retrieved & set(c["sources"])) if answerable else None,
            "no_answer_ok": (not retrieved) if not answerable else None,
            "status_ok": r.status.value == c["status"],
            "urgency_ok": r.urgency.value == c["urgency"],
            "category_ok": r.category.value == c["category"],
            "sentiment_ok": r.sentiment.value == c["sentiment"],
            "grounded": not any(f.startswith(BLOCKING_FLAGS) for f in r.guardrail_flags),
            "injection_flagged": ("prompt_injection" in r.guardrail_flags) if "injection" in c["tags"] else None,
            "pii_clean": (not RAW_PII.search(r.reply)) if "pii" in c["tags"] else None,
            "seconds": time.perf_counter() - t0,
        })
    log_text = deps.store.path.read_text(encoding="utf-8")
    for row in rows:
        if row["pii_clean"] is not None and RAW_PII.search(log_text):
            row["pii_clean"] = False
    return rows, summarise(rows)


def rate(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r[key] is not None]
    return (sum(vals) / len(vals)) if vals else None


def summarise(rows: list[dict]) -> dict[str, float]:
    must = [r for r in rows if r["gold"]["status"] == "Escalated"]
    sent = [r for r in rows if r["result"].escalated]
    out = {
        "retrieval_hit": rate(rows, "retrieval_hit"), "no_answer_ok": rate(rows, "no_answer_ok"),
        "status_acc": rate(rows, "status_ok"),
        "escalation_recall": (sum(r["result"].escalated for r in must) / len(must)) if must else None,
        "escalation_precision": (sum(r["gold"]["status"] == "Escalated" for r in sent) / len(sent)) if sent else None,
        "urgency_acc": rate(rows, "urgency_ok"), "category_acc": rate(rows, "category_ok"),
        "sentiment_acc": rate(rows, "sentiment_ok"), "grounded": rate(rows, "grounded"),
        "injection_flagged": rate(rows, "injection_flagged"), "pii_clean": rate(rows, "pii_clean"),
        "avg_seconds": sum(r["seconds"] for r in rows) / len(rows),
    }
    return {k: v for k, v in out.items() if v is not None}


def report(rows: list[dict], metrics: dict[str, float], mode: str) -> str:
    lines = [f"# Evaluation report ({mode})", "", f"Cases: {len(rows)}", "", "| Metric | Value |", "|---|---|"]
    for k, v in metrics.items():
        lines.append(f"| {k} | {v:.2%} |" if k != "avg_seconds" else f"| {k} | {v:.2f}s |")
    lines += ["", "## Per case", "", "| Id | Complaint | Gold | Got | Retrieved |", "|---|---|---|---|---|"]
    for r in rows:
        res, g = r["result"], r["gold"]
        mark = "ok" if r["status_ok"] else "DIFF"
        lines.append(
            f"| {r['id']} | {g['complaint'][:60]} | {g['status']} | {res.status.value} ({mark}) | {', '.join(res.retrieved_sources) or '-'} |"
        )
    failures = [r for r in rows if not r["status_ok"] or r["retrieval_hit"] is False or r["no_answer_ok"] is False]
    if failures:
        lines += ["", "## Mismatches", ""]
        for r in failures:
            res = r["result"]
            lines.append(f"- {r['id']}: status {res.status.value} (gold {r['gold']['status']}); reasons: {'; '.join(res.escalation_reasons) or 'none'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the real LLM agents")
    ap.add_argument("--heuristic", action="store_true", help="rule-based baseline without gold labels")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--no-gate", action="store_true")
    args = ap.parse_args()
    mode = "live" if args.live else ("heuristic" if args.heuristic else "oracle")

    rows, metrics = run(load_cases(args.limit), mode)
    text = report(rows, metrics, mode)
    REPORT_DIR.mkdir(exist_ok=True)
    out = args.report or REPORT_DIR / f"latest-{mode}.md"
    out.write_text(text, encoding="utf-8")

    print(f"mode={mode}  cases={len(rows)}")
    for k, v in metrics.items():
        print(f"  {k:20s} {v:.2%}" if k != "avg_seconds" else f"  {k:20s} {v:.2f}s")
    print(f"report: {out}")

    if mode == "oracle" and not args.no_gate:
        bad = {k: (metrics.get(k), t) for k, t in THRESHOLDS.items() if metrics.get(k, 0) < t}
        if bad:
            print("FAILED thresholds:", {k: f"{a:.2%} < {t:.0%}" for k, (a, t) in bad.items()})
            return 1
        print("All offline thresholds met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
