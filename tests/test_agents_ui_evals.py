import json
import typing
import unittest
from pathlib import Path

from agents import knowledge_agent, log_agent, query_agent, resolution_agent
from agents.prompts import DATA_NOTICE, ONE_TOOL_RULE, PROMPT_VERSION
from core.models import AgentEvent, RequestContext, TicketInput
from core.guardrails import validate_input
import team
from ui import components, timeline

from .helpers import ROOT, make_deps, make_desk

MODULES = [query_agent, knowledge_agent, resolution_agent, log_agent]


class AgentContractTests(unittest.TestCase):
    def test_four_agents_in_the_required_order(self):
        self.assertEqual(
            team.DISPLAY_ORDER,
            ["Customer Query Agent", "Knowledge Base Agent", "Resolution Agent", "Log Agent"],
        )

    def test_every_system_message_carries_the_safety_contract(self):
        for m in MODULES:
            msg = m.SYSTEM_MESSAGE
            self.assertIn("customer_complaint", msg, m.NAME)
            self.assertIn("exactly once", msg, m.NAME)
            self.assertTrue(m.DESCRIPTION, m.NAME)

    def test_prompt_fragments(self):
        self.assertIn("DATA", DATA_NOTICE)
        self.assertIn("exactly once", ONE_TOOL_RULE)
        self.assertRegex(PROMPT_VERSION, r"^\d+\.\d+$")

    def test_tool_signatures_resolve_for_autogen_schema_generation(self):
        """AutoGen builds the JSON schema from type hints; unresolved hints would break at runtime."""
        deps = make_deps()
        ctx = RequestContext(ticket_input=validate_input("hello there, where is my order"))
        tools = [
            query_agent.make_record_analysis(ctx),
            knowledge_agent.make_search_kb(ctx, deps),
            resolution_agent.make_submit_reply(ctx),
            log_agent.make_log_ticket(ctx, deps),
        ]
        for fn in tools:
            hints = typing.get_type_hints(fn, include_extras=True)
            self.assertIn("return", hints, fn.__name__)
            self.assertTrue(fn.__doc__ and len(fn.__doc__) > 10, fn.__name__)

    def test_enum_tool_arguments_are_closed_sets(self):
        hints = typing.get_type_hints(query_agent.make_record_analysis(RequestContext(ticket_input=validate_input("hello there ok"))), include_extras=True)
        flat = repr(hints)
        for value in ("Shipping", "Refund", "Billing", "Account", "Product", "Warranty", "Other", "High", "Angry"):
            self.assertIn(value, flat)

    def test_build_task_fences_the_complaint(self):
        t = team.build_task(TicketInput(complaint="Where is my order?", customer_name="Priya", order_id="ORD-1"))
        self.assertIn("<customer_complaint>\nWhere is my order?\n</customer_complaint>", t)
        self.assertIn("Priya", t)

    def test_tool_rejects_bad_enum_values(self):
        ctx = RequestContext(ticket_input=validate_input("where is my order please"))
        fn = query_agent.make_record_analysis(ctx)
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(fn(category="Nonsense", urgency="Low", sentiment="Neutral", summary="s"))
        self.assertIsNone(ctx.analysis)


class TimelineTests(unittest.TestCase):
    def ev(self, agent, kind, text="", at=1.0):
        return AgentEvent(agent=agent, kind=kind, text=text, at=at)

    def test_events_advance_the_steps(self):
        steps, notes = timeline.new_steps(), []
        timeline.start_first(steps, 0.0)
        self.assertEqual(steps[0].state, "run")
        timeline.apply_event(steps, notes, self.ev("Customer Query Agent", "output", "done", 2.0))
        self.assertEqual((steps[0].state, steps[1].state), ("done", "run"))
        self.assertEqual(steps[0].seconds, 2.0)

    def test_unknown_agent_becomes_a_note_once(self):
        steps, notes = timeline.new_steps(), []
        for _ in range(2):
            timeline.apply_event(steps, notes, self.ev("Guardrails", "note", "Possible prompt injection"))
        self.assertEqual(notes, ["Possible prompt injection"])

    def test_error_marks_failed_and_finish_closes_the_rest(self):
        desk = make_desk()
        r = desk.handle_sync("I forgot my password and can't log in.")
        steps, notes = timeline.new_steps(), []
        timeline.apply_event(steps, notes, self.ev("Customer Query Agent", "error", "boom"))
        self.assertEqual(steps[0].state, "fail")
        timeline.finish(steps, r)
        self.assertNotIn("pending", [s.state for s in steps])
        self.assertNotIn("run", [s.state for s in steps])


class ComponentTests(unittest.TestCase):
    XSS = '<script>alert(1)</script><img src=x onerror=alert(1)>'

    def test_result_html_escapes_user_and_model_text(self):
        r = make_desk().handle_sync("Where is my order? It is late " + self.XSS)
        html = components.result_html(r, customer=self.XSS)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn(r.ticket_id, html)

    def test_row_html_handles_missing_fields_and_escapes(self):
        html = components.row_html({"ticket_id": "TKT-1", "response": self.XSS, "kb_sources": "a.md; b.md"})
        self.assertNotIn("<script>", html)
        self.assertIn("a.md", html)

    def test_evidence_html_empty_and_populated(self):
        self.assertIn("No document", components.evidence_html([]))
        r = make_desk().handle_sync("I forgot my password and can't log in.")
        self.assertIn("account_and_login.md", components.evidence_html(r.passages))

    def test_timeline_and_status_render(self):
        steps = timeline.new_steps()
        self.assertEqual(components.timeline_html(steps).count("<"), components.timeline_html(steps).count(">"))
        self.assertIn("safe mode", components.system_status_html({"mode": "safe mode", "breaker": "closed"}).lower())


class EvalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "evals" / "dataset.jsonl"
        cls.cases = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_dataset_shape(self):
        self.assertGreaterEqual(len(self.cases), 40)
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.cases:
            for k in ("id", "complaint", "category", "urgency", "sentiment", "status"):
                self.assertIn(k, c, c.get("id"))

    def test_includes_the_six_assignment_complaints_and_adversarial_cases(self):
        text = " ".join(c["complaint"] for c in self.cases).lower()
        for needle in ("charged my card three times", "gift cards", "forgot my password", "ignore"):
            self.assertIn(needle, text)

    def test_oracle_eval_meets_thresholds(self):
        from evals import run_eval

        rows, metrics = run_eval.run(run_eval.load_cases(), "oracle")
        failing = {k: (metrics.get(k), t) for k, t in run_eval.THRESHOLDS.items() if metrics.get(k, 0) < t}
        self.assertEqual(failing, {})
        self.assertEqual(len(rows), len(self.cases))


if __name__ == "__main__":
    unittest.main()
