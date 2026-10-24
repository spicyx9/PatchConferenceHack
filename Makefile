.PHONY: predemo install lint format test check up down demo e2e
SHELL := /bin/bash

# FalkorDB port for every target (up, demo, predemo, e2e): one variable, one default.
# Order: make ... FALKORDB_PORT=N, then the environment, then FALKORDB_PORT in .env, then 6379.
FALKORDB_PORT ?= $(or $(shell grep -E '^FALKORDB_PORT=[0-9]+' .env 2>/dev/null | tail -n1 | cut -d= -f2),6379)
export FALKORDB_PORT

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

# Fails in under 5 s when the port is taken by anything but this project's FalkorDB.
up:
	@if [[ -z "$$(docker compose ps -q --status running falkordb 2>/dev/null)" ]] && \
	   (exec 3<>/dev/tcp/127.0.0.1/$(FALKORDB_PORT)) 2>/dev/null; then \
	  echo "Port $(FALKORDB_PORT) busy: run make up FALKORDB_PORT=6402 && make demo FALKORDB_PORT=6402"; \
	  exit 1; fi
	docker compose up -d

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

# Full journey against the real API process and FalkorDB (FALKORDB_PORT, see the top).
e2e:
	CONFERGE_E2E=1 uv run pytest -v -rA -p no:cacheprovider tests/e2e

# Each window owns scripts/probes/<name>.py; the shared Makefile never changes.
probe-%:
	uv run python scripts/run_probe.py "$*" $(ARGS)
