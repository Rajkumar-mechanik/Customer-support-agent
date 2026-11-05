"""Optional embedding reranker (enable with RETRIEVER=hybrid).

Lexical retrieval stays the gatekeeper ("is there anything relevant at all?"); embeddings only help
choose the *best order* among passages that already passed. Vectors are cached on disk keyed by a
hash of (model, text), so a restart never re-pays for the 300 or so knowledge-base chunks.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Callable
from pathlib import Path

from .kb import Chunk
from .logging_setup import get_logger

log = get_logger("embeddings")
EmbedFn = Callable[[list[str]], list[list[float]]]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def openai_embed_fn(api_key: str, model: str = "text-embedding-3-small", timeout: float = 20.0) -> EmbedFn:
    from openai import OpenAI  # installed as a dependency of autogen-ext[openai]

    client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    def embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):
            resp = client.embeddings.create(model=model, input=texts[i : i + 96])
            out.extend(d.embedding for d in resp.data)
        return out

    return embed


class CachedEmbeddingReranker:
    def __init__(self, embed: EmbedFn, cache_path: Path, model: str = "text-embedding-3-small"):
        self._embed, self._path, self._model = embed, Path(cache_path), model
        self._lock = threading.Lock()
        self._cache: dict[str, list[float]] = {}
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("Ignoring unreadable embedding cache %s", self._path)

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self._model}\n{text}".encode()).hexdigest()

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            missing = [t for t in dict.fromkeys(texts) if self._key(t) not in self._cache]
            if missing:
                for text, vec in zip(missing, self._embed(missing)):
                    self._cache[self._key(text)] = vec
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._cache), encoding="utf-8")
                tmp.replace(self._path)
            return [self._cache[self._key(t)] for t in texts]

    def similarities(self, query: str, chunks: list[Chunk]) -> list[float]:
        vecs = self._vectors([query, *[c.embed_text for c in chunks]])
        return [cosine(vecs[0], v) for v in vecs[1:]]
