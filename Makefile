.PHONY: build install build-worker setup-ollama start-ollama stop-ollama dev web-ui clean clean-all

build: install build-worker web-ui

install:
	uv sync
	cd web && npm install

build-worker:
	/opt/podman/bin/podman build -t rhclaw-worker -f worker/Containerfile worker/

setup-ollama:
	/opt/podman/bin/podman pull ollama/ollama:latest
	/opt/podman/bin/podman run -d --name ollama-setup -v ollama-models:/root/.ollama:Z ollama/ollama:latest
	/opt/podman/bin/podman exec ollama-setup ollama pull nomic-embed-text
	/opt/podman/bin/podman rm -f ollama-setup

start-ollama:
	/opt/podman/bin/podman rm -f ollama 2>/dev/null || true
	/opt/podman/bin/podman run -d --name ollama --network rhclaw-internal --memory 4g --cpus 2 --label rhclaw.role=ollama -v ollama-models:/root/.ollama:Z ollama/ollama:latest

stop-ollama:
	/opt/podman/bin/podman stop -t 10 ollama 2>/dev/null || true
	/opt/podman/bin/podman rm -f ollama 2>/dev/null || true

web-ui:
	cd web && npm run build

dev: build-worker
	.venv/bin/python -m uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000

clean:
	rm -rf web/dist

clean-all: clean
	rm -rf data/
