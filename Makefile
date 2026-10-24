.PHONY: install lint format test check up down demo e2e

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

# Full journey against the real API process and FalkorDB (FALKORDB_PORT, default 6380).
e2e:
	CONFERGE_E2E=1 FALKORDB_PORT=$${FALKORDB_PORT:-6380} uv run pytest -v -p no:cacheprovider tests/e2e

# Each window owns scripts/probes/<name>.py; the shared Makefile never changes.
probe-%:
	uv run python scripts/run_probe.py "$*"
