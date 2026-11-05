"""Central, validated configuration. All tunables live here and come from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:  # fail fast: a mistyped threshold must not silently change behaviour
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    return int(_get_float(name, float(default)))


def _get_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass(frozen=True)
class Settings:
    # --- LLM -------------------------------------------------------------------------
    openai_api_key: str = field(default="", repr=False)  # never printed in logs / reprs
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    request_timeout_s: float = 90.0
    llm_max_attempts: int = 2

    # --- Paths -----------------------------------------------------------------------
    kb_dir: Path = PROJECT_ROOT / "knowledge_base"
    log_dir: Path = PROJECT_ROOT / "logs"
    ticket_log_name: str = "tickets.csv"

    # --- Retrieval -------------------------------------------------------------------
    top_k: int = 4
    min_coverage: float = 0.42  # share of (idf-weighted) query terms a chunk must cover
    retriever: str = "lexical"  # "lexical" (default, offline) | "hybrid" (adds embedding rerank)
    embedding_model: str = "text-embedding-3-small"
    cache_dir: Path = PROJECT_ROOT / ".cache"

    # --- Policy ----------------------------------------------------------------------
    confidence_threshold: float = 0.6  # below this the ticket is escalated
    max_complaint_chars: int = 2000
    min_complaint_chars: int = 8
    rate_limit_per_minute: int = 6

    # --- Misc ------------------------------------------------------------------------
    company_name: str = "Brightwell"
    log_level: str = "INFO"
    demo_mode: bool = False  # explicit opt-in: simulated agents instead of the LLM (never silent)

    @property
    def ticket_log_path(self) -> Path:
        return self.log_dir / self.ticket_log_name

    @property
    def llm_configured(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key) and not key.startswith("your-") and key != "sk-..."

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables (loading .env if python-dotenv exists)."""
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env", override=False)
        except ImportError:  # python-dotenv is optional at import time
            pass

        settings = cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=_get_float("LLM_TEMPERATURE", 0.0),
            request_timeout_s=_get_float("LLM_TIMEOUT_SECONDS", 90.0),
            llm_max_attempts=max(1, _get_int("LLM_MAX_ATTEMPTS", 2)),
            kb_dir=_get_path("KB_DIR", PROJECT_ROOT / "knowledge_base"),
            log_dir=_get_path("LOG_DIR", PROJECT_ROOT / "logs"),
            top_k=max(1, _get_int("RETRIEVAL_TOP_K", 4)),
            min_coverage=_get_float("RETRIEVAL_MIN_COVERAGE", 0.42),
            retriever=os.getenv("RETRIEVER", "lexical").strip().lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            cache_dir=_get_path("CACHE_DIR", PROJECT_ROOT / ".cache"),
            confidence_threshold=_get_float("CONFIDENCE_THRESHOLD", 0.6),
            max_complaint_chars=_get_int("MAX_COMPLAINT_CHARS", 2000),
            rate_limit_per_minute=_get_int("RATE_LIMIT_PER_MINUTE", 6),
            company_name=os.getenv("COMPANY_NAME", "Brightwell"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            demo_mode=os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes"},
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError("LLM_TEMPERATURE must be between 0 and 1")
        if not 0.0 < self.min_coverage < 1.0:
            raise ValueError("RETRIEVAL_MIN_COVERAGE must be between 0 and 1")
        if self.retriever not in {"lexical", "hybrid"}:
            raise ValueError("RETRIEVER must be 'lexical' or 'hybrid'")
        if not 0.0 < self.confidence_threshold <= 1.0:
            raise ValueError("CONFIDENCE_THRESHOLD must be in (0, 1]")
        if self.max_complaint_chars < self.min_complaint_chars:
            raise ValueError("MAX_COMPLAINT_CHARS must be >= the minimum length")
