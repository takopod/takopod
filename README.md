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
