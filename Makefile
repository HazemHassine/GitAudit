.PHONY: install dev api api-no-migrate web db-upgrade test test-cov coverage-html test-e2e build build-web build-api build-wheel check-bundle validate-compose lint-docker lint-iac lint-ci

PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_UVICORN := $(VENV)/bin/uvicorn
VENV_ACTIONLINT := $(VENV)/bin/actionlint
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

lint-ci:
	$(VENV_ACTIONLINT)

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(VENV_PYTHON) -m pytest -p pytest_asyncio.plugin -p pytest_cov --cov=maintainer_api --cov-report=term-missing --cov-report=xml --cov-fail-under=80 apps/api/tests
	$(VENV_PYTHON) -m ruff check apps/api/src apps/api/tests
	$(VENV_ACTIONLINT)
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck

test-cov:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(VENV_PYTHON) -m pytest -p pytest_asyncio.plugin -p pytest_cov --cov=maintainer_api --cov-report=term-missing --cov-report=xml --cov-fail-under=80 apps/api/tests

coverage-html:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(VENV_PYTHON) -m pytest -p pytest_asyncio.plugin -p pytest_cov --cov=maintainer_api --cov-report=html:htmlcov apps/api/tests

test-e2e:
	npm --prefix apps/web run test:e2e

build: build-web build-wheel

build-web:
	npm --prefix apps/web run build
	node scripts/check_bundle_budget.mjs

check-bundle: build-web

build-wheel:
	$(VENV_PYTHON) -m build --wheel --no-isolation --outdir dist/ apps/api
	$(VENV_PYTHON) scripts/verify_wheel.py

build-api: build-wheel

validate-compose:
	docker compose config --quiet

lint-docker:
	docker run --rm -i hadolint/hadolint:v2.14.0 hadolint --ignore DL3008 --ignore DL3013 - < apps/api/Dockerfile
	docker run --rm -i hadolint/hadolint:v2.14.0 hadolint --ignore DL3008 --ignore DL3013 - < apps/web/Dockerfile

lint-iac: validate-compose
	docker run --rm -v "$(CURDIR)/apps/api/Dockerfile:/work/api/Dockerfile:ro" -v "$(CURDIR)/apps/web/Dockerfile:/work/web/Dockerfile:ro" bridgecrew/checkov:3.2.471 --framework dockerfile --directory /work --quiet
