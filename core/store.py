"""Append-only ticket log (CSV) with cross-process locking.

* One row per ticket, columns exactly as the brief requires, plus operational extras.
* Safe under concurrent writers (threads and processes): an exclusive lock-file guards the
  read-last-id / append sequence, so ticket IDs are unique and rows never interleave.
* Cells that start with = + - @ are prefixed with an apostrophe so a malicious complaint can't
  become a spreadsheet formula when the log is opened in Excel (CSV injection).
* Every write is flushed and fsync'd before the ticket is reported as logged.
"""

from __future__ import annotations

import csv
import io
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

COLUMNS = [
    "ticket_id",
    "timestamp",
    "customer_name",
    "order_id",
    "complaint",
    "category",
    "urgency",
    "sentiment",
    "summary",
    "kb_sources",
    "response",
    "status",
    "escalation_reason",
    "confidence",
    "guardrail_flags",
    "pipeline_mode",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


class StoreError(RuntimeError):
    pass


class _FileLock:
    """Portable advisory lock using exclusive creation of a lock file (with stale-lock recovery)."""

    def __init__(self, path: Path, timeout: float = 10.0, stale_after: float = 30.0):
        self.path, self.timeout, self.stale_after = path, timeout, stale_after

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_after:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise StoreError(f"Timed out waiting for ticket-log lock {self.path}")
                time.sleep(0.02)

    def release(self) -> None:
        self.path.unlink(missing_ok=True)


class TicketStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._file_lock = _FileLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self._ensure_header()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self._file_lock.acquire()
            try:
                yield
            finally:
                self._file_lock.release()

    def _ensure_header(self) -> None:
        with self._locked():
            if not self.path.exists() or self.path.stat().st_size == 0:
                with self.path.open("w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow(COLUMNS)

    def _last_number(self) -> int:
        last = 0
        with self.path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                tid = (row.get("ticket_id") or "").strip()
                if tid.startswith("TKT-") and tid[4:].isdigit():
                    last = max(last, int(tid[4:]))
        return last

    def append(self, row: dict[str, object]) -> str:
        """Assign the next ticket id, persist the row durably and return the id."""
        with self._locked():
            ticket_id = f"TKT-{self._last_number() + 1:04d}"
            full = {**row, "ticket_id": ticket_id}
            full.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            line = io.StringIO()
            csv.writer(line, lineterminator="\n").writerow([_safe_cell(full.get(c, "")) for c in COLUMNS])
            with self.path.open("a", newline="", encoding="utf-8") as fh:
                fh.write(line.getvalue())
                fh.flush()
                os.fsync(fh.fileno())
            return ticket_id

    def read_all(self) -> pd.DataFrame:
        with self._locked():
            try:
                df = pd.read_csv(self.path, dtype=str, keep_default_na=False)
            except pd.errors.EmptyDataError:
                df = pd.DataFrame(columns=COLUMNS)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNS]

    def to_csv_bytes(self) -> bytes:
        return self.read_all().to_csv(index=False).encode("utf-8")

    def to_excel_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            self.read_all().to_excel(writer, index=False, sheet_name="tickets")
        return buffer.getvalue()

    def stats(self) -> dict[str, object]:
        df = self.read_all()
        if df.empty:
            return {"total": 0, "resolved": 0, "escalated": 0, "by_category": {}, "by_urgency": {}}
        return {
            "total": int(len(df)),
            "resolved": int((df["status"] == "Resolved").sum()),
            "escalated": int((df["status"] == "Escalated").sum()),
            "by_category": df["category"].value_counts().to_dict(),
            "by_urgency": df["urgency"].value_counts().to_dict(),
        }
