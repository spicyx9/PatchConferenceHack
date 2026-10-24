.PHONY: install lint format test check up down

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

# Each window owns scripts/probes/<name>.py; the shared Makefile never changes.
probe-%:
	uv run python scripts/run_probe.py "$*"
