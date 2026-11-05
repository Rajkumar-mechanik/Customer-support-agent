"""Application logging: console + rotating file, with secret masking on every record."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .config import Settings

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+")
_configured = False


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_RE.sub(r"\1…[masked]", str(record.msg))
        if record.args:
            record.args = tuple(
                _SECRET_RE.sub(r"\1…[masked]", a) if isinstance(a, str) else a for a in record.args
            ) if isinstance(record.args, tuple) else record.args
        return True


def setup_logging(settings: Settings) -> None:
    """Idempotent: Streamlit re-runs the script on every interaction."""
    global _configured
    if _configured:
        return
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("support_desk")
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    root.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(SecretMaskingFilter())
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(SecretMaskingFilter())
    root.addHandler(file_handler)

    # Third-party loggers can echo request headers at DEBUG; keep them at WARNING.
    for noisy in ("httpx", "openai", "autogen_core", "autogen_agentchat", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"support_desk.{name}")
