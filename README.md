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

## Architecture

Each agent runs in an isolated Podman container with a bind-mounted workspace directory (`data/agents/<agent-id>/`). The orchestrator and worker communicate via four JSON files, using atomic writes (temp file + fsync + rename) and poll-based consumption.

### IPC Channels

Message channel (user conversations):

- `input.json`: Orchestrator writes batched messages, worker reads and deletes (ACK).
- `output.json`: Worker writes streaming events (tokens, tool calls, completion), orchestrator reads and deletes.

Tool channel (worker requests to orchestrator):

- `request.json`: Worker writes a request (e.g., schedule CRUD, MCP tool call), orchestrator reads and deletes.
- `response.json`: Orchestrator writes the result, worker reads and deletes.

Each agent has its own set of these four files in its own workspace directory. A dedicated orchestrator polling loop (asyncio task, 0.5s tick) watches each agent's directory independently. The tool channel polls at 0.1s for lower latency.
