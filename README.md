# rhclaw

A multi-agent AI platform where each agent runs in an isolated Podman container with persistent memory, file workspace, and real-time streaming chat. Agents are powered by Claude (via Vertex AI) and can be extended with MCP servers and integrations.

## Prerequisites

### Python 3.12+

Verify with `python3 --version`. Install via your OS package manager or [python.org](https://www.python.org/downloads/).

### uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

See [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for other methods.

### Node.js 22+ and npm

Required for building the web UI. Install via [nvm](https://github.com/nvm-sh/nvm) (recommended) or [nodejs.org](https://nodejs.org/).

```bash
# via nvm
nvm install 22
nvm use 22
```

### Podman

Used for running agent containers and the Ollama embedding service.

- **macOS**: Install [Podman Desktop](https://podman-desktop.io/) — this installs the Podman CLI to `/opt/podman/bin/podman`, which is the path rhclaw expects.
- **Linux**: Install via your package manager (`sudo apt install podman` / `sudo dnf install podman`). You may need to symlink or update the path — the Makefile currently hardcodes `/opt/podman/bin/podman`.

After installing, initialize and start the Podman machine (macOS only):

```bash
podman machine init
podman machine start
```

### Google Cloud credentials (Vertex AI)

Agent containers use Claude via Vertex AI. You need authenticated GCP credentials:

```bash
gcloud auth application-default login
```

This populates `~/.config/gcloud/`, which is mounted read-only into each worker container. Set the following environment variables to point at your GCP project:

- `GOOGLE_CLOUD_PROJECT` — your GCP project ID
- `GOOGLE_CLOUD_REGION` — GCP region to use

## Setup

1. Clone the repository and `cd` into it.

2. Run the full build (installs Python and Node dependencies, builds the worker container image, and builds the web UI):

```bash
make
```

This runs three targets in sequence:
- `make install` — `uv sync` (creates `.venv/` and installs Python deps) + `npm install` in `web/`
- `make build-worker` — builds the `rhclaw-worker` Podman image from `worker/Containerfile`
- `make web-ui` — runs `npm run build` in `web/`

3. Set up the Ollama embedding service (optional but recommended):

```bash
make setup-ollama
```

This pulls the Ollama container image and downloads the `nomic-embed-text` model. Ollama provides hybrid BM25 + vector search for agent memory. If you skip this, set `OLLAMA_ENABLED=false` as an environment variable before starting.

## Running

### Start Ollama (if using embeddings)

```bash
make start-ollama
```

This starts the Ollama container on the `rhclaw-internal` Podman network with 4 GB memory and 2 CPUs. The network is created automatically by the orchestrator on first start.

### Start rhclaw

```bash
source .venv/bin/activate
rhclaw start
```

The service runs on `http://localhost:8000` by default. Logs are written to `data/rhclaw.log`.

Options:

```bash
rhclaw start --host 127.0.0.1 --port 9000
```

### Check status

```bash
rhclaw status
```

Shows the running PID, schema version, and managed container count.

### Stop

```bash
rhclaw stop
```

To stop Ollama separately:

```bash
make stop-ollama
```

### Development mode

For development with auto-reload, build the worker image and start uvicorn directly:

```bash
make dev
```

For frontend development with hot module replacement:

```bash
cd web
npm run dev
```

## Environment Variables

All optional. Defaults work for standard setups.

- `GOOGLE_CLOUD_PROJECT` — GCP project ID for Vertex AI
- `GOOGLE_CLOUD_REGION` — GCP region for Vertex AI
- `OLLAMA_ENABLED` — Enable/disable Ollama embeddings (default: `true`)
- `OLLAMA_HOST_URL` — Ollama endpoint for the orchestrator (default: `http://localhost:11434`)
- `SHUTDOWN_TIMEOUT_SECONDS` — Graceful shutdown timeout (default: `30`)
- `IDLE_TIMEOUT_SECONDS` — Container idle reaper timeout (default: `300`)

### Slack integration (optional)

To enable Slack monitoring, set these before starting:

- `SLACK_XOXC_TOKEN` — Slack user token (`xoxc-...`)
- `SLACK_D_COOKIE` — Slack auth cookie (`xoxd-...`)
- `MY_MEMBER_ID` — Your Slack user ID (`U...`)

## Architecture

See `ARCHITECTURE.md` for the full system design.

Each agent runs in an isolated Podman container with a bind-mounted workspace directory (`data/agents/<agent-id>/`). The orchestrator and worker communicate via four JSON files, using atomic writes (temp file + fsync + rename) and poll-based consumption.

### IPC Channels

Message channel (user conversations):

- `input.json`: Orchestrator writes batched messages, worker reads and deletes (ACK).
- `output.json`: Worker writes streaming events (tokens, tool calls, completion), orchestrator reads and deletes.

Tool channel (worker requests to orchestrator):

- `request.json`: Worker writes a request (e.g., schedule CRUD, MCP tool call), orchestrator reads and deletes.
- `response.json`: Orchestrator writes the result, worker reads and deletes.

Each agent has its own set of these four files in its own workspace directory. A dedicated orchestrator polling loop (asyncio task, 0.5s tick) watches each agent's directory independently. The tool channel polls at 0.1s for lower latency.
