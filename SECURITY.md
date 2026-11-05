# Security notes

* Secrets only via environment / `.env` (git-ignored); `Settings.openai_api_key` is excluded from `repr`.
* Customer text is untrusted: length-limited, normalised, control characters stripped, fenced as data in prompts, scanned for injection.
* Sensitive data (card numbers, emails, phone numbers, Aadhaar, API keys, credentials) is redacted before it reaches the ticket log or traces.
* Agent output is checked before it can reach a customer (ungrounded facts, prompt/tool leakage, unauthorised commitments).
* CSV cells beginning with `= + - @` are neutralised to prevent spreadsheet formula injection.
* Container runs as a non-root user with a read-only root filesystem and all capabilities dropped.
* There is no authentication in the Streamlit console: put it behind your SSO / reverse proxy before exposing it to anyone but the support team.
