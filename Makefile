.PHONY: gateway-dev gateway-test gateway-lint

gateway-dev:
	cd services/gateway && uvicorn app.main:app --reload --port 8000

gateway-test:
	cd services/gateway && pytest -q

gateway-lint:
	cd services/gateway && ruff check .
