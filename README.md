# Brightwell AI Customer Support Desk

A multi-agent support desk built on **AutoGen v0.4+** (`AssistantAgent`, `RoundRobinGroupChat`) with
**OpenAI gpt-4o-mini** and a **Streamlit** console. A customer complaint passes through four agents,
is answered only from a markdown knowledge base, is escalated to a human when the rules say so, and is
written to a ticket log. Built for the *Social Eagle: AI Customer Support Automation* assignment.

**Design stance: the model proposes, code disposes.** The LLM does what only an LLM can (read messy
language, choose what to search, write a warm reply). Everything that must be exactly right
(categories, numbers in the reply, escalation, IDs, the log, PII) is typed, checked and decided by
deterministic code. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Where each rubric item lives

| Rubric (points) | What to look at |
|---|---|
| Agent design (20) | `agents/` has one file per agent: `NAME`, `SYSTEM_MESSAGE`, exactly one typed tool (`record_analysis`, `search_kb`, `submit_reply`, `log_ticket`). `team.py` builds the `RoundRobinGroupChat` (Query -> Knowledge -> Resolution -> Log) with `TextMentionTermination("LOGGED") | MaxMessageTermination`. Prompts are versioned (`agents/prompts.py::PROMPT_VERSION`). |
| Knowledge grounding (20) | `core/kb.py` (BM25 + coverage gate), `knowledge_base/` (30 files, 20 products), `core/guardrails.py::validate_output` (every number, email, URL, phone in a reply must exist in a retrieved passage). The reply cites source file names. |
| Workflow and escalation (20) | `core/escalation.py` implements all five rules from the brief plus guardrail, injection and outage triggers. `core/ticketing.py::finalize_ticket` is the single decision point. |
| Logging (15) | `core/store.py` writes `logs/tickets.csv` (all required columns plus audit columns), locked, unique IDs, xlsx/csv export. `logs/traces.jsonl` holds per-ticket traces. |
| Streamlit UI (15) | `app.py`, `ui/`. Submit a complaint, watch the four agents run, see the reply with its sources, the retrieved passages, the escalation reasons, and the ticket log with filters and export. |
| Code quality and README (10) | Typed, small modules, 114 unit tests, offline evals, CI, Docker, this file. |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.10+
pip install -r requirements.txt
cp .env.example .env                                  # put your OPENAI_API_KEY in .env
streamlit run app.py                                  # http://localhost:8501
```

Docker: `cp .env.example .env` (add the key), then `docker compose up --build`. Tickets persist in `./logs`.

Run the six complaints from the assignment against the real model (good for README screenshots):

```bash
python scripts/smoke_live.py
```

**No API key?** The app does not pretend. Without a key it starts in **safe mode**: every ticket is
logged and escalated to a human with a conservative templated reply, and the sidebar says so. Set
`DEMO_MODE=true` to run a clearly labelled *simulated* agent team (same tools, same guardrails, no LLM)
for UI demos. The mode is shown in the UI and stored in each log row (`pipeline_mode`).

## The four agents

| # | Agent | Job | Its single tool |
|---|---|---|---|
| 1 | Customer Query Agent | Category, urgency, sentiment, one-line summary | `record_analysis` (enum arguments) |
| 2 | Knowledge Base Agent | Search the KB and hand back passages with their source file names | `search_kb` |
| 3 | Resolution Agent | Draft the reply from the passages only; report confidence; may request a human | `submit_reply` |
| 4 | Log Agent | Final escalation recommendation and the ticket record | `log_ticket` |

Escalation reasons (any one is enough): High urgency; very angry customer; no matching document; legal,
fraud or payment-dispute language; safety hazard; low confidence (blended model + retrieval, threshold
0.6); possible prompt injection; reply failed a guardrail; outside support scope; AI model unavailable.
Code can raise urgency and force escalation; nothing can lower them.

## Guardrails

* **Input**: length and character validation, Unicode normalisation, control-character stripping, delimiter neutralising, injection detection (flag + escalate), per-session rate limit.
* **Prompt**: complaint fenced in `<customer_complaint>` and declared to be data; one tool per agent; temperature 0.
* **Output**: ungrounded numbers/emails/URLs/phones, prompt or tool-name leakage, unauthorised commitments and placeholders all cause the draft to be replaced by a safe reply and the ticket escalated.
* **Data**: PII redacted before logging (cards via Luhn, emails, phones, Aadhaar, keys, credentials); CSV formula-injection protection.
* **Reliability**: timeout, retries, circuit breaker, safe mode, idempotent finalisation, concurrency-safe ticket IDs.

## Knowledge base (20 products, 30 documents, 321 chunks)

General documents:

| File | Title |
|---|---|
| `account_and_login.md` | Brightwell Account and Login Help |
| `billing_and_payments.md` | Brightwell Billing and Payments |
| `contact_and_escalation.md` | Brightwell Contact and Escalation Information |
| `order_changes_and_cancellations.md` | Brightwell Order Changes and Cancellations |
| `product_care_and_safety.md` | Brightwell Product Care and Safety Guide |
| `product_catalog.md` | Brightwell Product Catalog and Warranty Summary |
| `product_faq.md` | Brightwell Product FAQ |
| `refund_policy.md` | Brightwell Returns and Refund Policy |
| `replacement_and_warranty_policy.md` | Brightwell Replacement and Warranty Policy |
| `shipping_policy.md` | Brightwell Shipping and Delivery Policy |

Product sheets (each has specs, setup, troubleshooting, warranty, returns notes):

| Product | SKU | File |
|---|---|---|
| Aero Wireless Earbuds | `BW-EB200` | `products/aero_wireless_earbuds.md` |
| Breeze Tower Fan | `BW-TF30` | `products/breeze_tower_fan.md` |
| Brew Smart Coffee Maker | `BW-CM12` | `products/brew_smart_coffee_maker.md` |
| Core Wireless Mouse | `BW-MS55` | `products/core_wireless_mouse.md` |
| Crisp Air Fryer 5L | `BW-AF50` | `products/crisp_air_fryer.md` |
| Glide 4K Action Camera | `BW-AC400` | `products/glide_4k_action_camera.md` |
| Guard Wi-Fi Security Camera | `BW-SC20` | `products/guard_wifi_security_camera.md` |
| Hub Mini Smart Speaker | `BW-SP100` | `products/hub_mini_speaker.md` |
| Lumen Smart LED Bulb 4-pack | `BW-LB04` | `products/lumen_smart_bulb.md` |
| Pulse Smartwatch | `BW-SW310` | `products/pulse_smartwatch.md` |
| Pure Air Purifier | `BW-AP200` | `products/pure_air_purifier.md` |
| Slate 10 Tablet | `BW-TB10` | `products/slate_10_tablet.md` |
| Stream Wi-Fi 6 Router | `BW-RT600` | `products/stream_wifi6_router.md` |
| Stride Run Shoes | `BW-FS410` | `products/stride_run_shoes.md` |
| Sweep R1 Robot Vacuum | `BW-RV100` | `products/sweep_r1_robot_vacuum.md` |
| Trek 40L Travel Backpack | `BW-BP40` | `products/trek_40l_travel_backpack.md` |
| Type Mechanical Keyboard | `BW-KB87` | `products/type_mechanical_keyboard.md` |
| View 27 Monitor | `BW-MN27` | `products/view_27_monitor.md` |
| Volt 20000mAh Power Bank | `BW-PB20` | `products/volt_power_bank.md` |
| Whisk Pro Blender 900W | `BW-BL900` | `products/whisk_pro_blender.md` |

Add or change knowledge by editing markdown in `knowledge_base/`; no code change is needed.
`python scripts/validate_kb.py` checks structure (front matter, unique files, section sizes).

## Ticket log schema (`logs/tickets.csv`)

`ticket_id, timestamp, customer_name, order_id, complaint, category, urgency, sentiment, summary, kb_sources, response, status, escalation_reason, confidence, guardrail_flags, pipeline_mode, latency_ms, prompt_tokens, completion_tokens`

The first twelve (minus `summary`) are the assignment's required columns; the rest are audit columns.
`status` is `Resolved` or `Escalated`; `escalation_reason` lists every rule that fired.

## Tests and evaluation

```bash
make test            # 114 unit tests: guardrails, heuristics, escalation rules, KB retrieval, store, pipeline, UI, agents
make eval            # offline "oracle" eval, 45 cases, gates CI
make eval-heuristic  # rule-only baseline
make eval-live       # real gpt-4o-mini agents (needs a key)
```

Offline results (45 cases, includes the assignment's six, paraphrases, angry/legal/fraud/safety cases,
out-of-scope questions, injection and PII cases):

| Mode | Status | Escalation recall | Retrieval hit | No-answer ok | Urgency | Category |
|---|---|---|---|---|---|---|
| Oracle (perfect model, real code) | 100% | 100% | 100% | 100% | 100% | 100% |
| Heuristic baseline (no LLM) | 100% | 100% | 100% | 100% | 68.9% | 84.4% |

How to read this honestly:

* The **oracle** mode tests the code around the model (retrieval, guardrails, safety floor, escalation, logging), not the model. A perfect score there says the plumbing is right; it says nothing about gpt-4o-mini's accuracy.
* The dataset and the rules were developed together, so the offline numbers are optimistic. Run `make eval-live` for the model's real numbers.
* The heuristic row shows the floor: rules alone get status right but cannot judge urgency or category well, which is exactly where the LLM earns its place.
* The AutoGen/OpenAI path and the Streamlit app need network access and a key, so they were exercised with scripted stand-ins in the tests (the real tool functions, termination handling and fallbacks run; the network call does not). Please run `streamlit run app.py` and `scripts/smoke_live.py` once with your key before submitting.

## Screenshots

Add yours to `screenshots/` after running the app (suggested: the six assignment tickets, an
escalated billing case, the ticket log). `python scripts/preview_ui.py out.html` renders the UI
components statically if you need a quick visual check without Streamlit.

## Project layout

```
app.py                Streamlit console           team.py        AutoGen team + runner
agents/               prompts + one module per agent
core/                 config, models, guardrails, kb, embeddings, escalation, ticketing,
                      store, pipeline, resilience, fallback, simulated
ui/                   theme, components, live timeline
knowledge_base/       policies + products/ (20 sheets)
evals/                dataset.jsonl, run_eval.py, reports/
tests/                114 tests          scripts/   validate_kb, smoke_live, preview_ui
Dockerfile  docker-compose.yml  Makefile  pyproject.toml  .github/workflows/ci.yml
```

## Known limitations

* Retrieval is lexical (English). `RETRIEVER=hybrid` adds embedding re-ranking but is untested against the live API here.
* The desk cannot see real order status; replies explain policy and next steps and say so.
* The CSV log suits a demo and a single node; use a database for multiple replicas.
* The console has no login; put it behind your own authentication.
* Prompt-injection detection is pattern-based; the real protection is that the model has no powerful tools and code makes every decision that matters.
