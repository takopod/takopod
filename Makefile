.PHONY: install build dev dev-api dev-web clean

install:
	uv sync
	cd web && npm install

build:
	cd web && npm run build

dev:
	@lsof -ti:8000 -ti:5173 | xargs kill 2>/dev/null || true
	@sleep 0.5
	$(MAKE) dev-api &
	$(MAKE) dev-web &
	@trap 'kill 0' INT TERM; wait

dev-api:
	uv run uvicorn orchestrator.main:app --reload --port 8000

dev-web:
	cd web && npx vite --strictPort

clean:
	rm -rf web/dist data/
