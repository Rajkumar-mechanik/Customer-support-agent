"""Deterministic backend for the Brightwell AI Support Desk.

Design rule used throughout this package:

    The LLM *proposes*, the code *disposes*.

Language understanding and writing are delegated to the AutoGen agents. Everything
that must be correct every single time (input safety, retrieval, grounding checks,
escalation, persistence) is plain, tested Python in this package.
"""

__version__ = "1.0.0"
