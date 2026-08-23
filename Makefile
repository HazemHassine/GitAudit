.PHONY: install dev api web test

install:
	python3 -m pip install -e 'apps/api[dev]'
	npm --prefix apps/web install

dev:
	@echo "Run 'make api' and 'make web' in separate terminals."

api:
	uvicorn maintainer_api.main:app --reload --app-dir apps/api/src --port 8001

web:
	npm --prefix apps/web run dev

test:
	python3 -m pytest apps/api/tests
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
