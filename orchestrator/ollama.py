"""Ollama embedding service: health check for the shared Podman network container."""

import asyncio

from orchestrator.container_manager import PODMAN

OLLAMA_CONTAINER_NAME = "ollama"
OLLAMA_MODEL = "nomic-embed-text"


async def check_ollama_status() -> dict:
    """Check Ollama container state for the health endpoint."""
    proc = await asyncio.create_subprocess_exec(
        PODMAN, "inspect", "--format", "{{.State.Status}}", OLLAMA_CONTAINER_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0 and stdout.decode().strip() == "running":
        return {"status": "healthy", "model": OLLAMA_MODEL}
    return {"status": "unhealthy", "model": OLLAMA_MODEL}
