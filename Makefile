.PHONY: install run test eval eval-heuristic eval-live kb smoke docker lint clean

install:
	pip install -r requirements.txt

run:
	streamlit run app.py

test:
	python -m unittest discover -s tests -t .

eval:            ## offline, deterministic, gates CI
	python -m evals.run_eval

eval-heuristic:  ## rule-based baseline
	python -m evals.run_eval --heuristic --no-gate

eval-live:       ## real gpt-4o-mini (needs OPENAI_API_KEY)
	python -m evals.run_eval --live --no-gate

kb:
	python scripts/validate_kb.py

smoke:           ## the six assignment complaints against the real model
	python scripts/smoke_live.py

lint:
	ruff check .

docker:
	docker compose up --build

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .cache
