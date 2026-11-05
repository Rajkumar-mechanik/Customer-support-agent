"""Knowledge-base loader and retriever (BM25 + coverage gate + product awareness).

Why not embeddings? For a corpus this size (policies + 20 product sheets) a lexical ranker with
synonym canonicalisation is more *predictable* than a vector store: it is deterministic, needs no
network, and, crucially, supports an explicit "nothing relevant" decision through the coverage
gate. A model asked to answer from the top-k nearest vectors will always get *something*;
the coverage gate lets us say "we do not know" and escalate. The interface (`KnowledgeBase.search`)
is small on purpose so a vector retriever can be dropped in behind it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from .models import Passage

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from get got had has have hello hi
    how i if in into is it its me my of on or our please so than that the their them then there these
    they this to us was we were what when where which who why will with would you your want need help
    know like just also very any some about am im ive dont cant not no yes thanks thank company
    one two bought received supposed yesterday today tomorrow last week ago since already again now really
    something anything nothing everything thing things times time fix contact contacting tell let gave give
    made make going went come came did said say using use used try tried trying able still even ever lot
    plz pls kindly sir madam team regards only ridiculous useless sick pathetic terrible worst horrible awful
    furious unacceptable disgusting stupid idiots idiot nonsense fed hell damn rubbish garbage incompetent
    ending""".split()
)

# Canonical concept for common support vocabulary (applied to documents AND queries).
_SYNONYMS: dict[str, str] = {}


def _syn(canon: str, *words: str) -> None:
    for w in words:
        _SYNONYMS[w] = canon


_syn("refund", "refund", "refunded", "refunds", "reimburse", "reimbursed", "reimbursement", "repay", "payback")
_syn("return", "return", "returns", "returned", "returning", "sendback")
_syn("defect", "broken", "broke", "damaged", "damage", "defective", "defect", "faulty", "cracked", "crack", "dead", "malfunction", "malfunctioning", "doa")
_syn("delay", "late", "delayed", "delay", "overdue", "stuck", "slow", "missing", "lost")
_syn("order", "order", "orders", "purchase", "purchased", "ordered")
_syn("deliver", "deliver", "delivered", "delivery", "deliveries", "arrive", "arrives", "arrived", "arriving", "reach", "shipment", "shipped", "shipping", "ship", "dispatch", "dispatched", "parcel", "package", "courier")
_syn("password", "password", "passwords", "passcode", "passwd", "pwd", "forgot", "forgotten")
_syn("login", "login", "signin", "logon", "log", "locked", "lockout")
_syn("charge", "charge", "charged", "charges", "billed", "debited", "deducted", "deduction")
_syn("replace", "replace", "replaced", "replacement", "swap", "exchange", "exchanged")
_syn("warranty", "warranty", "guarantee", "guaranteed", "repair", "repaired")
_syn("cancel", "cancel", "cancelled", "canceled", "cancellation", "cancelling")
_syn("track", "track", "tracking", "trace", "whereabouts")
_syn("pair", "pair", "pairing", "paired", "bluetooth", "connect", "connecting", "connection")
_syn("charging", "charging", "recharge", "recharging", "charger")
_syn("wifi", "wifi", "wi", "internet", "network", "wireless")
_syn("battery", "battery", "batteries", "backup")
_syn("invoice", "invoice", "bill", "receipt", "gst")
_syn("shoe", "shoe", "shoes", "footwear", "sneakers", "sneaker")
_syn("earbud", "earbud", "earbuds", "earphone", "earphones", "headphone", "headphones")
_syn("fan", "fan", "fans")
_syn("overseas", "international", "internationally", "overseas", "abroad", "outside", "foreign", "worldwide", "global")
_syn("work", "work", "works", "working", "worked", "plays", "play", "playing", "functions", "function")
_syn("price", "price", "prices", "priced", "pricing", "cost", "costs", "much", "rupee", "rupees", "inr")
_syn("noise", "noise", "noisy", "loud", "rattle", "rattling", "buzz", "buzzing", "buzzes", "humming", "hum")
_syn("hot", "hot", "heat", "heated", "heating", "overheat", "overheating", "warm", "burning")
_syn("duplicate", "duplicate", "duplicated", "duplicates", "double", "doubled", "twice", "thrice", "three", "multiple", "repeated", "extra")


def stem(token: str) -> str:
    if token in _SYNONYMS:
        return _SYNONYMS[token]
    for suffix, repl in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return _SYNONYMS.get(token[: -len(suffix)] + repl, token[: -len(suffix)] + repl)
    return token


def tokenize(text: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS or len(tok) < 2 and not tok.isdigit():
            continue
        out.append(stem(tok))
    return out


@dataclass
class Doc:
    file: str
    title: str
    doc_type: str  # policy | product
    category: str
    sku: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    doc: Doc
    heading: str
    text: str
    tokens: list[str]
    tf: Counter = field(default_factory=Counter)

    @property
    def uid(self) -> str:
        return f"{self.doc.file}#{self.heading}"

    @property
    def embed_text(self) -> str:
        return f"{self.doc.title} - {self.heading}\n{self.text}"


class Reranker(Protocol):
    def similarities(self, query: str, chunks: list[Chunk]) -> list[float]: ...


_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")


class KnowledgeBaseError(RuntimeError):
    pass


class KnowledgeBase:
    K1 = 1.4
    B = 0.72

    def __init__(self, kb_dir: Path):
        self.kb_dir = Path(kb_dir)
        self.docs: dict[str, Doc] = {}
        self.chunks: list[Chunk] = []
        self._df: Counter = Counter()
        self._avg_len = 1.0
        self._alias_index: list[tuple[re.Pattern[str], Doc]] = []
        self.reranker: Reranker | None = None
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        files = sorted(self.kb_dir.rglob("*.md"))
        if not files:
            raise KnowledgeBaseError(f"No knowledge-base documents found in {self.kb_dir}")
        for path in files:
            if path.name.lower() == "readme.md":
                continue
            raw = path.read_text(encoding="utf-8")
            meta: dict = {}
            match = _FRONT_RE.match(raw)
            if match:
                meta = yaml.safe_load(match.group(1)) or {}
                raw = raw[match.end():]
            if path.name in self.docs:
                raise KnowledgeBaseError(f"Duplicate knowledge-base file name: {path.name}")
            doc = Doc(
                file=path.name,
                title=str(meta.get("title") or path.stem.replace("_", " ").title()),
                doc_type=str(meta.get("doc_type", "policy")),
                category=str(meta.get("category", "General")),
                sku=str(meta.get("sku", "")),
                aliases=[str(a) for a in (meta.get("aliases") or [])],
            )
            self.docs[doc.file] = doc
            self._chunk_document(doc, raw)

        for chunk in self.chunks:
            self._df.update(set(chunk.tokens))
        self._avg_len = sum(len(c.tokens) for c in self.chunks) / max(len(self.chunks), 1)

        for doc in self.docs.values():
            names = {doc.title, doc.sku, *doc.aliases} - {""}
            for name in sorted(names, key=len, reverse=True):
                if doc.doc_type == "product":
                    pattern = re.compile(rf"(?<![\w]){re.escape(name.lower())}(?![\w])")
                    self._alias_index.append((pattern, doc))

    def _chunk_document(self, doc: Doc, body: str) -> None:
        sections: list[tuple[str, list[str]]] = [("Overview", [])]
        parent = ""
        for line in body.splitlines():
            m = _HEADING_RE.match(line)
            if m:
                level, title = len(m.group(1)), m.group(2).strip()
                if level == 2:
                    parent = title
                    sections.append((title, []))
                else:
                    sections.append((f"{parent} > {title}" if parent else title, []))
            elif line.startswith("# "):
                continue
            else:
                sections[-1][1].append(line)
        header_tokens = tokenize(" ".join([doc.title, doc.sku, *doc.aliases]))
        for heading, lines in sections:
            text = "\n".join(lines).strip()
            if len(text) < 25:
                continue
            tokens = tokenize(text) + tokenize(heading) * 2 + header_tokens
            self.chunks.append(Chunk(doc=doc, heading=heading, text=text, tokens=tokens, tf=Counter(tokens)))

    # ------------------------------------------------------------------ public API
    @property
    def files(self) -> list[str]:
        return sorted(self.docs)

    def product_docs(self) -> list[Doc]:
        return [d for d in self.docs.values() if d.doc_type == "product"]

    def find_product(self, text: str) -> Doc | None:
        lowered = text.lower()
        for pattern, doc in self._alias_index:
            if pattern.search(lowered):
                return doc
        return None

    UNSEEN_WEIGHT = 0.5  # a term the KB has never seen counts against coverage, but only partly

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        value = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
        return value * self.UNSEEN_WEIGHT if df == 0 else value

    def search(
        self,
        query: str,
        *,
        k: int = 4,
        min_coverage: float = 0.42,
        category_hint: str | None = None,
        context: str = "",
    ) -> list[Passage]:
        """Return up to k passages, or [] when nothing in the KB credibly answers the query.

        `context` (usually the original complaint) is only used to detect a named product so that
        its sheet is preferred; it never widens the term set that must be covered.
        """
        q_terms = list(dict.fromkeys(tokenize(query)))
        if not q_terms:
            return []
        idf = {t: self._idf(t) for t in q_terms}
        total_idf = sum(idf.values()) or 1.0

        product = self.find_product(f"{query} {context}")
        scored: list[tuple[float, float, Chunk]] = []
        for chunk in self.chunks:
            matched = [t for t in q_terms if t in chunk.tf]
            if not matched:
                continue
            norm = self.K1 * (1 - self.B + self.B * len(chunk.tokens) / self._avg_len)
            score = sum(idf[t] * chunk.tf[t] * (self.K1 + 1) / (chunk.tf[t] + norm) for t in matched)
            coverage = sum(idf[t] for t in matched) / total_idf
            if product and chunk.doc.file == product.file:
                score *= 1.5
            elif chunk.doc.doc_type == "product" and not product and (category_hint or "").lower() != "product":
                score *= 0.7  # a product sheet is only a strong answer when a product is in play
            if category_hint and chunk.doc.category.lower() == category_hint.lower():
                score *= 1.3
            scored.append((score, coverage, chunk))

        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]

        # The coverage gate is the ONLY thing that can say "nothing here answers this".
        candidates = [
            (score, coverage, chunk)
            for score, coverage, chunk in scored
            if coverage >= min_coverage and score >= 0.3 * top_score
        ]
        if self.reranker is not None and len(candidates) > 1:
            candidates = self._rerank(query, candidates[: k * 4])

        picked: list[Passage] = []
        per_doc: Counter = Counter()
        for score, coverage, chunk in candidates:
            if len(picked) >= k:
                break
            if per_doc[chunk.doc.file] >= 2:
                continue
            per_doc[chunk.doc.file] += 1
            picked.append(self._passage(chunk, score, coverage))

        # A product sheet answers "how does it work"; the policy answers "what are my rights".
        # When a product is in play make sure the governing policy sits next to it.
        if product and picked and not any(p.doc_type == "policy" for p in picked):
            for score, coverage, chunk in scored:
                if chunk.doc.doc_type == "policy" and coverage >= min_coverage and score >= 0.15 * top_score:
                    picked = picked[: max(k - 1, 1)] + [self._passage(chunk, score, coverage)]
                    break
        return picked

    # ------------------------------------------------------------------ optional reranking
    RERANK_WEIGHT = 0.4  # share of the fused score that comes from embedding similarity

    def attach_reranker(self, reranker: Reranker | None) -> None:
        """Plug in an embedding reranker. It only REORDERS gate-passing candidates."""
        self.reranker = reranker

    def _rerank(
        self, query: str, candidates: list[tuple[float, float, Chunk]]
    ) -> list[tuple[float, float, Chunk]]:
        assert self.reranker is not None
        try:
            sims = self.reranker.similarities(query, [c[2] for c in candidates])
        except Exception:  # noqa: BLE001 - embeddings are an enhancement; lexical order still stands
            return candidates
        if len(sims) != len(candidates):
            return candidates
        top = max(c[0] for c in candidates) or 1.0
        lo, hi = min(sims), max(sims)
        span = (hi - lo) or 1.0
        fused = [
            ((1 - self.RERANK_WEIGHT) * (c[0] / top) + self.RERANK_WEIGHT * ((s - lo) / span), c)
            for s, c in zip(sims, candidates)
        ]
        fused.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in fused]

    # ------------------------------------------------------------------ self-validation
    REQUIRED_PRODUCT_SECTIONS = ("Overview", "Specifications", "Setup", "Troubleshooting", "Frequently asked questions")

    def validate(self) -> list[str]:
        """Return a list of knowledge-base problems (empty list means healthy). Used by CI."""
        problems: list[str] = []
        seen_alias: dict[str, str] = {}
        for doc in self.docs.values():
            if doc.doc_type == "product":
                if not doc.sku:
                    problems.append(f"{doc.file}: product without sku")
                headings = {c.heading.split(" > ")[0] for c in self.chunks if c.doc is doc}
                for section in self.REQUIRED_PRODUCT_SECTIONS:
                    if section not in headings:
                        problems.append(f"{doc.file}: missing section '{section}'")
                for alias in {a.lower() for a in doc.aliases} | {doc.sku.lower()}:
                    other = seen_alias.setdefault(alias, doc.file)
                    if other != doc.file:
                        problems.append(f"alias '{alias}' is shared by {other} and {doc.file}")
        if len(self.product_docs()) < 20:
            problems.append(f"expected 20 product sheets, found {len(self.product_docs())}")
        return problems

    @staticmethod
    def _passage(chunk: Chunk, score: float, coverage: float) -> Passage:
        return Passage(
            source=chunk.doc.file,
            title=chunk.doc.title,
            heading=chunk.heading,
            text=chunk.text,
            score=round(score, 3),
            coverage=round(coverage, 3),
            doc_type=chunk.doc.doc_type,
        )


def format_passages(passages: list[Passage]) -> str:
    if not passages:
        return "NO_MATCH: nothing in the support documentation answers this query."
    return "\n\n".join(p.as_prompt_block() for p in passages)
