import unittest

from core import escalation, heuristics
from core.config import Settings
from core.models import Analysis, Category, Passage, Resolution, Sentiment, Urgency


def analysis(**kw) -> Analysis:
    base = dict(category=Category.SHIPPING, urgency=Urgency.LOW, sentiment=Sentiment.NEUTRAL, summary="s")
    base.update(kw)
    return Analysis(**base)


def passage(cov=0.9) -> Passage:
    return Passage("shipping_policy.md", "t", "h", "text", 5.0, cov)


def decide(**kw):
    args = dict(
        analysis=analysis(), passages=[passage()], resolution=Resolution("reply", "high"), triggers=[],
        input_flags=(), output_blocking=[], confidence=0.9, settings=Settings(),
    )
    args.update(kw)
    return escalation.decide(**args)


class TriggerTests(unittest.TestCase):
    def test_each_trigger_family(self):
        cases = {
            "legal_threat": ["I will sue you", "my lawyer will call", "taking this to consumer court", "legal action soon"],
            "fraud": ["this is fraud", "unauthorised transaction on my card", "my account was hacked"],
            "payment_dispute": ["you charged me twice", "charged my card three times", "I will contact my bank", "double charged"],
            "safety_hazard": ["it caught fire", "the battery is swollen", "smoke came out", "it overheats badly", "electric shock"],
        }
        for code, texts in cases.items():
            for text in texts:
                self.assertIn(code, heuristics.trigger_codes(text), text)

    def test_ordinary_messages_have_no_triggers(self):
        for text in ["Where is my order?", "How do I reset my password?", "The earbuds sound great but one is silent",
                     "I want a refund for the shoes", "the fire-engine red colour is lovely"]:
            self.assertEqual(heuristics.trigger_codes(text), [], text)


class SentimentAndUrgencyTests(unittest.TestCase):
    def test_sentiment(self):
        self.assertIs(heuristics.detect_sentiment("THIS IS RIDICULOUS!!! You are USELESS and I am sick of this"), Sentiment.ANGRY)
        self.assertIs(heuristics.detect_sentiment("I am still waiting and a bit disappointed"), Sentiment.FRUSTRATED)
        self.assertIs(heuristics.detect_sentiment("Where is my order?"), Sentiment.NEUTRAL)
        self.assertIs(heuristics.detect_sentiment("Thanks, the earbuds are great"), Sentiment.POSITIVE)

    def test_urgency_floor_only_raises_for_hard_signals(self):
        self.assertIs(heuristics.urgency_floor("my lawyer will contact you"), Urgency.HIGH)
        self.assertIs(heuristics.urgency_floor("it caught fire"), Urgency.HIGH)
        self.assertIs(heuristics.urgency_floor("I need this urgently"), Urgency.HIGH)
        self.assertIs(heuristics.urgency_floor("How do I pair the earbuds?"), Urgency.LOW)

    def test_category_baseline(self):
        self.assertIs(heuristics.classify_category("I forgot my password"), Category.ACCOUNT)
        self.assertIs(heuristics.classify_category("charged twice on my card"), Category.BILLING)
        self.assertIs(heuristics.classify_category("order is late, tracking not updating"), Category.SHIPPING)
        self.assertIs(heuristics.classify_category("blah blah"), Category.OTHER)


class EscalationRuleTests(unittest.TestCase):
    """One test per rule in the brief, plus the one-directional guarantee."""

    def test_clean_ticket_is_resolved(self):
        d = decide()
        self.assertFalse(d.escalate)
        self.assertEqual(d.status.value, "Resolved")

    def test_high_urgency(self):
        self.assertIn("High urgency", decide(analysis=analysis(urgency=Urgency.HIGH)).reasons)

    def test_angry_customer(self):
        self.assertIn("Customer is very angry", decide(analysis=analysis(sentiment=Sentiment.ANGRY)).reasons)

    def test_no_matching_document(self):
        d = decide(passages=[], confidence=0.2)
        self.assertTrue(d.escalate)
        self.assertIn("No matching knowledge-base document", d.reasons)

    def test_legal_fraud_payment_safety(self):
        for code in ("legal_threat", "fraud", "payment_dispute", "safety_hazard"):
            self.assertTrue(decide(triggers=[code]).escalate, code)

    def test_low_confidence(self):
        d = decide(confidence=0.4)
        self.assertTrue(d.escalate)
        self.assertTrue(any(r.startswith("Low confidence") for r in d.reasons))

    def test_confidence_at_threshold_is_ok(self):
        self.assertFalse(decide(confidence=0.6).escalate)

    def test_guardrail_and_injection_and_degraded(self):
        self.assertTrue(decide(input_flags=("prompt_injection",)).escalate)
        self.assertTrue(decide(output_blocking=["ungrounded_numbers:30"]).escalate)
        self.assertTrue(decide(degraded=True).escalate)

    def test_agent_can_request_escalation_but_not_cancel_one(self):
        self.assertTrue(decide(resolution=Resolution("r", "high", needs_human=True, note="odd request")).escalate)
        must = decide(analysis=analysis(urgency=Urgency.HIGH), resolution=Resolution("r", "high", needs_human=False))
        self.assertTrue(must.escalate)

    def test_other_category_with_weak_match_escalates(self):
        d = decide(analysis=analysis(category=Category.OTHER), passages=[passage(0.45)])
        self.assertIn("Request is outside the support scope or unclear", d.reasons)

    def test_reasons_are_deduplicated_and_readable(self):
        d = decide(analysis=analysis(urgency=Urgency.HIGH, sentiment=Sentiment.ANGRY), triggers=["legal_threat", "legal_threat"])
        self.assertEqual(len(d.reasons), len(set(d.reasons)))
        self.assertIn("High urgency", d.reason_text)


class ConfidenceBlendTests(unittest.TestCase):
    def test_blend(self):
        self.assertEqual(escalation.final_confidence(Resolution("r", "high"), [passage(0.9)]), 0.9)
        self.assertEqual(escalation.final_confidence(Resolution("r", "low"), [passage(0.9)]), 0.3)
        self.assertLessEqual(escalation.final_confidence(Resolution("r", "high"), [passage(0.45)]), 0.8)
        self.assertEqual(escalation.final_confidence(Resolution("r", "high"), []), 0.2)
        self.assertEqual(escalation.final_confidence(None, [passage()]), 0.0)


if __name__ == "__main__":
    unittest.main()
