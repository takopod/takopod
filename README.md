# rhclaw

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js / npm
- [Podman](https://podman.io/)

## Setup

```
make
make build-worker
```

## Ollama (Embedding Service)

rhclaw uses Ollama with `nomic-embed-text` for embeddings, running as a Podman container.

One-time setup (pulls the image and model):

```
make setup-ollama
```

Start/stop the Ollama container:

```
make start-ollama
make stop-ollama
```

The container runs on the `rhclaw-internal` Podman network with 4 GB memory and 2 CPUs.

## Usage

```
source .venv/bin/activate
rhclaw start
rhclaw stop
```

The service runs on `http://localhost:8000` by default. Use `--host` and `--port` to customize:

```
rhclaw start --host 127.0.0.1 --port 9000
```
