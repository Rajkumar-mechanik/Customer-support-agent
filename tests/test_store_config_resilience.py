import csv
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from core.config import Settings
from core.resilience import CircuitBreaker
from core.store import COLUMNS, TicketStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = TicketStore(self.dir / "tickets.csv")

    def test_header_has_all_required_columns(self):
        required = ["ticket_id", "timestamp", "customer_name", "order_id", "complaint", "category", "urgency",
                    "sentiment", "kb_sources", "response", "status", "escalation_reason"]
        header = (self.dir / "tickets.csv").read_text().splitlines()[0].split(",")
        for col in required:
            self.assertIn(col, header)

    def test_sequential_ids_and_round_trip(self):
        ids = [self.store.append({"complaint": f"c{i}", "status": "Resolved"}) for i in range(3)]
        self.assertEqual(ids, ["TKT-0001", "TKT-0002", "TKT-0003"])
        df = self.store.read_all()
        self.assertEqual(list(df["complaint"]), ["c0", "c1", "c2"])

    def test_ids_continue_after_restart(self):
        self.store.append({"complaint": "a"})
        again = TicketStore(self.dir / "tickets.csv")
        self.assertEqual(again.append({"complaint": "b"}), "TKT-0002")

    def test_multiline_commas_quotes_unicode_survive(self):
        text = 'Line one, with "quotes"\nline two ₹3,499 नमस्ते'
        self.store.append({"complaint": text, "response": text})
        self.assertEqual(self.store.read_all()["complaint"][0], text)

    def test_csv_formula_injection_neutralised(self):
        for payload in ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)"]:
            self.store.append({"complaint": payload})
        for cell in self.store.read_all()["complaint"]:
            self.assertTrue(cell.startswith("'"), cell)

    def test_concurrent_writers_get_unique_ids_and_no_torn_rows(self):
        errors: list[Exception] = []

        def worker(n):
            try:
                for i in range(8):
                    self.store.append({"complaint": f"w{n}-{i}", "response": "x" * 200})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        df = self.store.read_all()
        self.assertEqual(len(df), 64)
        self.assertEqual(df["ticket_id"].nunique(), 64)
        rows = list(csv.reader(io.StringIO((self.dir / "tickets.csv").read_text())))
        self.assertTrue(all(len(r) == len(COLUMNS) for r in rows))

    def test_stale_lock_file_is_recovered(self):
        lock = self.dir / "tickets.csv.lock"
        lock.write_text("999999")
        old = time.time() - 120
        os.utime(lock, (old, old))
        self.assertEqual(self.store.append({"complaint": "after stale lock"}), "TKT-0001")

    def test_exports_and_stats(self):
        self.store.append({"complaint": "a", "status": "Resolved", "category": "Account", "urgency": "Low"})
        self.store.append({"complaint": "b", "status": "Escalated", "category": "Billing", "urgency": "High"})
        self.assertTrue(self.store.to_csv_bytes().startswith(b"ticket_id"))
        self.assertTrue(self.store.to_excel_bytes().startswith(b"PK"))  # xlsx is a zip
        s = self.store.stats()
        self.assertEqual((s["total"], s["resolved"], s["escalated"]), (2, 1, 1))


class ConfigTests(unittest.TestCase):
    def env(self, **kv):
        return mock.patch.dict(os.environ, kv, clear=False)

    def test_defaults_and_secret_not_in_repr(self):
        s = Settings(openai_api_key="sk-secret-value-1234567890")
        self.assertNotIn("sk-secret", repr(s))
        self.assertEqual(s.model, "gpt-4o-mini")
        self.assertTrue(s.llm_configured)

    def test_placeholder_keys_are_not_configured(self):
        for key in ["", "  ", "your-key-here", "sk-..."]:
            self.assertFalse(Settings(openai_api_key=key).llm_configured, key)

    def test_from_env_parses_and_validates(self):
        with self.env(OPENAI_MODEL="gpt-4o-mini", CONFIDENCE_THRESHOLD="0.7", RETRIEVER="hybrid", DEMO_MODE="true",
                      LOG_DIR=tempfile.mkdtemp()):
            s = Settings.from_env()
        self.assertEqual((s.confidence_threshold, s.retriever, s.demo_mode), (0.7, "hybrid", True))

    def test_invalid_values_fail_fast(self):
        for kv in [{"CONFIDENCE_THRESHOLD": "abc"}, {"CONFIDENCE_THRESHOLD": "1.5"}, {"RETRIEVER": "magic"},
                   {"RETRIEVAL_MIN_COVERAGE": "2"}, {"LLM_TEMPERATURE": "9"}]:
            with self.env(**kv), self.assertRaises(ValueError, msg=str(kv)):
                Settings.from_env()


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_after_threshold_then_half_opens_and_closes(self):
        now = [0.0]
        b = CircuitBreaker(threshold=3, cooldown_s=30, clock=lambda: now[0])
        self.assertEqual(b.state, "closed")
        for _ in range(3):
            b.record_failure()
        self.assertEqual(b.state, "open")
        self.assertFalse(b.allow())
        now[0] = 31
        self.assertEqual(b.state, "half-open")
        self.assertTrue(b.allow())
        b.record_success()
        self.assertEqual(b.state, "closed")

    def test_failure_in_half_open_reopens(self):
        now = [0.0]
        b = CircuitBreaker(threshold=2, cooldown_s=10, clock=lambda: now[0])
        b.record_failure(); b.record_failure()
        now[0] = 11
        b.record_failure()
        self.assertEqual(b.state, "open")

    def test_success_resets_failure_count(self):
        b = CircuitBreaker(threshold=3)
        b.record_failure(); b.record_failure(); b.record_success(); b.record_failure(); b.record_failure()
        self.assertEqual(b.state, "closed")


if __name__ == "__main__":
    unittest.main()
