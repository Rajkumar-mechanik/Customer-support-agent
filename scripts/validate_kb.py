"""Validate the knowledge base. Exit code 1 on any problem (used by CI).

    python scripts/validate_kb.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings  # noqa: E402
from core.kb import KnowledgeBase  # noqa: E402


def main() -> int:
    kb = KnowledgeBase(Settings().kb_dir)
    problems = kb.validate()
    print(f"{len(kb.docs)} documents, {len(kb.chunks)} chunks, {len(kb.product_docs())} product sheets")
    for p in problems:
        print(f"  PROBLEM: {p}")
    print("Knowledge base OK" if not problems else f"{len(problems)} problem(s) found")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
