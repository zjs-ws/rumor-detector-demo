COMPOSE_PROD := docker compose -f compose.prod.yaml

.PHONY: install dev gateway test lint format check up stop ps logs frontend-check

install:
	uv sync

dev:
	uv run langgraph dev --no-browser --allow-blocking --no-reload

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uvx ruff check .

format:
	uvx ruff check . --fix && uvx ruff format .

check:
	./scripts/doctor.sh
	$(COMPOSE_PROD) config -q

up:
	$(COMPOSE_PROD) up -d --build

stop:
	$(COMPOSE_PROD) down

ps:
	$(COMPOSE_PROD) ps

logs:
	$(COMPOSE_PROD) logs -f

frontend-check:
	corepack pnpm --dir frontend test
	corepack pnpm --dir frontend lint
	corepack pnpm --dir frontend typecheck
