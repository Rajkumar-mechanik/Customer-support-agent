"""Shared, process-wide dependencies (built once, injected everywhere; nothing is a hidden global)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .kb import KnowledgeBase
from .logging_setup import get_logger
from .store import TicketStore

log = get_logger("deps")


@dataclass
class Deps:
    settings: Settings
    kb: KnowledgeBase
    store: TicketStore

    @classmethod
    def build(cls, settings: Settings) -> Deps:
        kb = KnowledgeBase(settings.kb_dir)
        problems = kb.validate()
        if problems:  # a broken KB must be loud at start-up, not silent at 2 a.m.
            log.warning("Knowledge base validation found %d problem(s): %s", len(problems), "; ".join(problems[:5]))

        if settings.retriever == "hybrid":
            if settings.llm_configured:
                from .embeddings import CachedEmbeddingReranker, openai_embed_fn

                kb.attach_reranker(
                    CachedEmbeddingReranker(
                        openai_embed_fn(settings.openai_api_key, settings.embedding_model),
                        settings.cache_dir / "embeddings.json",
                        settings.embedding_model,
                    )
                )
                log.info("Hybrid retrieval enabled (%s)", settings.embedding_model)
            else:
                log.warning("RETRIEVER=hybrid needs OPENAI_API_KEY; falling back to lexical retrieval")

        return cls(settings=settings, kb=kb, store=TicketStore(settings.ticket_log_path))
