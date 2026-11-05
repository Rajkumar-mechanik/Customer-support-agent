# Brightwell AI Support Desk (AutoGen, gpt-4o-mini, Streamlit)

A multi-agent customer support desk: **Query -> Knowledge -> Resolution -> Log**, built on AutoGen
(`autogen-agentchat` v0.4+ API, `RoundRobinGroupChat`). Knowledge base: 8 policy documents plus
**20 product support sheets** (`knowledge_base/`).

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # put your OPENAI_API_KEY in .env
streamlit run app.py        # http://localhost:8501
```
Docker: `docker compose up --build`. Without a key the desk runs in safe mode (every ticket goes to a human).

## Architecture: the LLM proposes, the code disposes

| Agent | Job | Tool (typed schema) |
|---|---|---|
| `query_agent` | category, urgency, sentiment, summary | `record_analysis` (enum-typed args) |
| `knowledge_agent` | retrieve passages + source file | `search_kb` |
| `resolution_agent` | grounded reply + confidence | `submit_reply` |
| `log_agent` | write ticket, recommend escalation | `log_ticket` |

Each tool is a closure over one per-request context, so the model never copies IDs or text and
concurrent tickets cannot leak into each other. Termination: `TextMentionTermination("LOGGED")`
plus `max_turns=4`.

**Where prompts work best:** language understanding (classification rubric with examples, tone, writing).
**Where code works best (`core/`):**
- `guardrails.py`: input validation, prompt-injection detection, PII redaction (Luhn card check), rate limit;
  output check that every number, email, URL and phone in the reply exists in the retrieved passages, plus
  leak, placeholder and forbidden-commitment checks. A failing draft is replaced by a safe reply.
- `kb.py`: BM25 + synonym canonicalisation + a **coverage gate** so "no matching document" is a real, escalatable outcome.
- `heuristics.py` / `escalation.py`: the LLM can raise urgency or escalation, never lower what rules require
  (legal, fraud, payment dispute, safety, High urgency, Angry, no document, low confidence).
- `store.py`: CSV log with file locking, fsync, unique IDs, spreadsheet-formula protection.
- `fallback.py` + `pipeline.py`: timeout, retry, then degraded mode (ticket still logged and escalated).

## Log
`logs/tickets.csv` has all required columns plus confidence, guardrail flags, mode, latency and tokens.
`logs/traces.jsonl` holds per-ticket agent traces.

## Config
`.env`: `OPENAI_API_KEY`, `OPENAI_MODEL` (default gpt-4o-mini), `CONFIDENCE_THRESHOLD`, `RETRIEVAL_MIN_COVERAGE`,
`RATE_LIMIT_PER_MINUTE`. Never commit `.env` (it is in `.gitignore`).

## Status (be honest in validation)
Verified offline here: knowledge-base retrieval, guardrails, escalation, store and the full degraded pipeline.
**Not yet run:** the live AutoGen path with a real OpenAI key, the Streamlit UI, unit tests and the eval set.
Run the six assignment complaints against your key and screenshot before submitting.
