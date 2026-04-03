"""Ollama embedding service: singleton container lifecycle on the shared Podman network."""

import asyncio
import logging

from orchestrator.container_manager import NETWORK, PODMAN, _run

logger = logging.getLogger(__name__)

OLLAMA_CONTAINER_NAME = "ollama"
OLLAMA_IMAGE = "ollama/ollama:latest"
OLLAMA_MODEL = "nomic-embed-text"


async def start_ollama() -> None:
    """Start the Ollama container if not already running."""
    proc = await asyncio.create_subprocess_exec(
        PODMAN, "inspect", "--format", "{{.State.Status}}", OLLAMA_CONTAINER_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0 and stdout.decode().strip() == "running":
        logger.info("Ollama container already running")
        return

    # Remove any stopped/dead container with the same name
    await _run([PODMAN, "rm", "-f", OLLAMA_CONTAINER_NAME], check=False)

    await _run([
        PODMAN, "run", "-d",
        "--name", OLLAMA_CONTAINER_NAME,
        "--network", NETWORK,
        "--memory", "4g",
        "--cpus", "2",
        "--label", "rhclaw.managed=true",
        "--label", "rhclaw.role=ollama",
        "-v", "ollama-models:/root/.ollama:Z",
        OLLAMA_IMAGE,
    ])
    logger.info("Ollama container started")


async def stop_ollama() -> None:
    """Stop and remove the Ollama container. Idempotent."""
    await _run([PODMAN, "stop", "-t", "10", OLLAMA_CONTAINER_NAME], check=False)
    await _run([PODMAN, "rm", "-f", OLLAMA_CONTAINER_NAME], check=False)
    logger.info("Ollama container stopped")


async def wait_for_ollama(max_retries: int = 10, base_delay: float = 1.0) -> None:
    """Block until Ollama's HTTP server is ready. Exponential backoff, cap at 16s."""
    for attempt in range(max_retries):
        proc = await asyncio.create_subprocess_exec(
            PODMAN, "exec", OLLAMA_CONTAINER_NAME,
            "ollama", "list",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            logger.info("Ollama health check passed")
            return

        delay = min(base_delay * (2 ** attempt), 16.0)
        logger.info(
            "Ollama not ready (attempt %d/%d), retrying in %.1fs",
            attempt + 1, max_retries, delay,
        )
        await asyncio.sleep(delay)

    raise RuntimeError("Ollama failed to become healthy after %d retries" % max_retries)



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
