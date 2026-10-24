.PHONY: predemo install lint format test check up down demo e2e

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

# Demo API + front on http://127.0.0.1:$(DEMO_PORT), assembled data loaded into FalkorDB.
# make demo DEMO_PORT=8001 when 8000 is taken; DEMO_ARGS="--travel live" adds live Bright Data travel.
DEMO_PORT ?= 8000
DEMO_ARGS ?=
demo:
	uv run python scripts/run_demo.py --port $(DEMO_PORT) $(DEMO_ARGS)

# 5 minutes before the demo: FalkorDB check, fresh demo on a reset graph, OK/FAIL table.
predemo:
	DEMO_PORT=$(DEMO_PORT) bash scripts/predemo.sh

# Full journey against the real API process and FalkorDB (FALKORDB_PORT, default 6380).
e2e:
	CONFERGE_E2E=1 FALKORDB_PORT=$${FALKORDB_PORT:-6380} uv run pytest -v -rA -p no:cacheprovider tests/e2e

# Each window owns scripts/probes/<name>.py; the shared Makefile never changes.
probe-%:
	uv run python scripts/run_probe.py "$*"
