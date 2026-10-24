.PHONY: install lint format test check up down demo

install:
	uv sync --group dev

lint:
	uv run ruff check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest -q

check: lint test

up:
	docker compose up -d falkordb

down:
	docker compose down

# Demo API + front on http://127.0.0.1:8000, assembled data loaded into FalkorDB.
demo:
	uv run python scripts/run_demo.py

# Each window owns scripts/probes/<name>.py; the shared Makefile never changes.
probe-%:
	uv run python scripts/run_probe.py "$*"
