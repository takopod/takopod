.PHONY: install build build-worker dev dev-api dev-web prod clean

install:
	uv sync
	cd web && npm install

build:
	cd web && npm run build

build-worker:
	/opt/podman/bin/podman build -t rhclaw-worker -f worker/Containerfile worker/

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

prod: build build-worker
	uv run uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000

clean:
	rm -rf web/dist data/
