.PHONY: install dev api api-no-migrate web db-upgrade test test-e2e build

PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_UVICORN := $(VENV)/bin/uvicorn
API_PORT ?= 8001
WEB_PORT ?= 3000

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

install: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install -e 'apps/api[dev]'
	npm --prefix apps/web ci

dev: db-upgrade
	@$(MAKE) api-no-migrate & api_pid=$$!; \
	$(MAKE) web & web_pid=$$!; \
	trap 'kill $$api_pid $$web_pid 2>/dev/null || true' INT TERM EXIT; \
	wait $$api_pid $$web_pid

api: db-upgrade
	$(MAKE) api-no-migrate

api-no-migrate:
	$(VENV_UVICORN) maintainer_api.main:app --reload --app-dir apps/api/src --port $(API_PORT)

web:
	npm --prefix apps/web run dev -- --port $(WEB_PORT)

db-upgrade:
	$(VENV_PYTHON) -m alembic -c apps/api/alembic.ini upgrade head

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(VENV_PYTHON) -m pytest -p pytest_asyncio.plugin apps/api/tests
	$(VENV_PYTHON) -m ruff check apps/api/src apps/api/tests
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck

test-e2e:
	npm --prefix apps/web run test:e2e

build:
	npm --prefix apps/web run build
