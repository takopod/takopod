.PHONY: build install build-worker setup-ollama dev clean clean-all

build: install build-worker
	cd web && npm run build

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

dev: build-worker
	.venv/bin/python -m uvicorn orchestrator.main:app --host 0.0.0.0 --port 8000

clean:
	rm -rf web/dist

clean-all: clean
	rm -rf data/
