import json
import tempfile
import unittest
from pathlib import Path

from core.embeddings import CachedEmbeddingReranker, cosine
from core.kb import KnowledgeBase, KnowledgeBaseError, format_passages, tokenize

from .helpers import KB_DIR

# (question, file that must be among the retrieved sources)
GOLDEN = [
    ("Where is my order? It was supposed to arrive yesterday.", "shipping_policy.md"),
    ("I want to return the shoes I bought last week. How do I get a refund?", "refund_policy.md"),
    ("I forgot my password and can't log in.", "account_and_login.md"),
    ("The blender I received is broken. Can I get a replacement?", "whisk_pro_blender.md"),
    ("You charged my card three times! Fix this now or I'm contacting my bank and a lawyer.", "billing_and_payments.md"),
    ("charged twice for one order", "billing_and_payments.md"),
    ("my Aero earbuds only left one works", "aero_wireless_earbuds.md"),
    ("How long does the warranty on the air purifier filter last", "pure_air_purifier.md"),
    ("my parcel says delivered but I never got it", "shipping_policy.md"),
    ("how do I cancel my order before it ships", "order_changes_and_cancellations.md"),
    ("robot vacuum won't go back to dock", "sweep_r1_robot_vacuum.md"),
    ("I got the wrong item in my package", "order_changes_and_cancellations.md"),
    ("router red light no internet", "stream_wifi6_router.md"),
    ("how do I get a GST invoice", "billing_and_payments.md"),
    ("my power bank is swelling and hot", "volt_power_bank.md"),
    ("how much is the tablet", "slate_10_tablet.md"),
    ("which products work with the Brightwell Home app", "product_faq.md"),
    ("where is the serial number for warranty", "product_faq.md"),
    ("camera shows card error", "glide_4k_action_camera.md"),
    ("my keyboard key does not register", "type_mechanical_keyboard.md"),
    ("monitor has no signal", "view_27_monitor.md"),
]
OUT_OF_SCOPE = [
    "Do you sell gift cards for a company of 500 employees with custom branding?",
    "what is the capital of France",
    "can I get a job at your company",
    "do you sell laptops with 32GB RAM and RTX graphics",
    "I want to bulk order 1000 units with my logo printed",
    "who won the cricket match yesterday",
]


class KnowledgeBaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase(KB_DIR)

    def test_corpus_shape(self):
        self.assertEqual(len(self.kb.product_docs()), 20)
        self.assertGreaterEqual(len(self.kb.docs), 28)
        for required in ["shipping_policy.md", "refund_policy.md", "account_and_login.md", "product_faq.md"]:
            self.assertIn(required, self.kb.docs)

    def test_validates_clean(self):
        self.assertEqual(self.kb.validate(), [])

    def test_golden_retrieval(self):
        misses = [q for q, src in GOLDEN if src not in [p.source for p in self.kb.search(q, context=q)]]
        self.assertEqual(misses, [])

    def test_out_of_scope_returns_nothing(self):
        leaks = {q: [p.source for p in self.kb.search(q, context=q)] for q in OUT_OF_SCOPE if self.kb.search(q, context=q)}
        self.assertEqual(leaks, {})

    def test_every_product_is_findable_by_name_and_sku(self):
        for doc in self.kb.product_docs():
            self.assertIs(self.kb.find_product(f"my {doc.title} is broken"), doc, doc.title)
            self.assertIs(self.kb.find_product(f"order BW {doc.sku} problem"), doc, doc.sku)

    def test_every_product_sheet_answers_its_own_troubleshooting(self):
        for doc in self.kb.product_docs():
            q = f"{doc.title} not working troubleshooting"
            self.assertIn(doc.file, [p.source for p in self.kb.search(q, context=q, category_hint="Product")], doc.file)

    def test_passages_carry_source_file_names(self):
        p = self.kb.search("forgot password", context="")[0]
        self.assertTrue(p.source.endswith(".md"))
        self.assertIn(p.source, format_passages([p]))
        self.assertTrue(format_passages([]).startswith("NO_MATCH"))

    def test_policy_sits_beside_product_sheet(self):
        q = "The blender I received is broken. Can I get a replacement?"
        types = {p.doc_type for p in self.kb.search(q, context=q)}
        self.assertEqual(types, {"product", "policy"})

    def test_empty_and_stopword_only_queries(self):
        self.assertEqual(self.kb.search(""), [])
        self.assertEqual(self.kb.search("please help me thanks"), [])

    def test_tokenizer_canonicalises_synonyms(self):
        self.assertEqual(tokenize("refunded")[0], tokenize("refund")[0])
        self.assertEqual(tokenize("broken")[0], tokenize("defective")[0])

    def test_loader_rejects_duplicates_and_empty_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(KnowledgeBaseError):
                KnowledgeBase(Path(d))
            (Path(d) / "a").mkdir()
            (Path(d) / "b").mkdir()
            for sub in "ab":
                (Path(d) / sub / "same.md").write_text("---\ntitle: T\n---\n## S\nsome long enough section text here.\n")
            with self.assertRaises(KnowledgeBaseError):
                KnowledgeBase(Path(d))


class FakeReranker:
    """Prefers chunks from one file, to prove the reranker can reorder but not widen results."""

    def __init__(self, prefer: str):
        self.prefer = prefer

    def similarities(self, query, chunks):
        return [1.0 if c.doc.file == self.prefer else 0.0 for c in chunks]


class RerankerTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase(KB_DIR)
        self.q = "The blender I received is broken. Can I get a replacement?"

    def test_reranker_reorders_but_never_adds_results(self):
        base = self.kb.search(self.q, context=self.q)
        self.kb.attach_reranker(FakeReranker("replacement_and_warranty_policy.md"))
        reranked = self.kb.search(self.q, context=self.q)
        self.assertEqual(reranked[0].source, "replacement_and_warranty_policy.md")
        self.assertTrue({p.source for p in reranked} <= {p.source for p in base} | {"replacement_and_warranty_policy.md"})

    def test_reranker_cannot_turn_no_match_into_a_match(self):
        self.kb.attach_reranker(FakeReranker("shipping_policy.md"))
        self.assertEqual(self.kb.search("what is the capital of France"), [])

    def test_reranker_failure_falls_back_to_lexical_order(self):
        base = [p.source for p in self.kb.search(self.q, context=self.q)]

        class Broken:
            def similarities(self, query, chunks):
                raise RuntimeError("embeddings API down")

        self.kb.attach_reranker(Broken())
        self.assertEqual([p.source for p in self.kb.search(self.q, context=self.q)], base)

    def test_embedding_cache_is_reused(self):
        calls = []

        def embed(texts):
            calls.append(list(texts))
            return [[float(len(t) % 7), 1.0, float(len(t) % 3)] for t in texts]

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "emb.json"
            r1 = CachedEmbeddingReranker(embed, path)
            chunks = self.kb.chunks[:3]
            first = r1.similarities("query text", chunks)
            self.assertTrue(path.exists())
            n_before = sum(len(c) for c in calls)
            r2 = CachedEmbeddingReranker(embed, path)  # new instance reads the disk cache
            self.assertEqual(r2.similarities("query text", chunks), first)
            self.assertEqual(sum(len(c) for c in calls), n_before)
            json.loads(path.read_text())

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)


if __name__ == "__main__":
    unittest.main()
