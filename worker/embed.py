"""Embedding client: calls Ollama's HTTP API over the shared Podman network."""

import asyncio
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434"
DEFAULT_MODEL = "nomic-embed-text"


def _embed_sync(text: str, model: str) -> list[float]:
    """Synchronous embedding call via urllib (no extra dependencies)."""
    url = f"{OLLAMA_URL}/api/embed"
    payload = json.dumps({"model": model, "input": text}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["embeddings"][0]


async def embed(
    text: str, model: str = DEFAULT_MODEL, max_retries: int = 3,
) -> list[float]:
    """Return an embedding vector for the given text.

    Retries with exponential backoff on connection failure.
    Raises ConnectionError if Ollama is unreachable after all retries.
    """
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(_embed_sync, text, model)
        except (urllib.error.URLError, OSError, ConnectionError) as e:
            last_err = e
            delay = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(
                "Ollama embed failed (attempt %d/%d): %s — retrying in %ds",
                attempt + 1, max_retries, e, delay,
            )
            await asyncio.sleep(delay)

    raise ConnectionError(
        f"Cannot reach Ollama at {OLLAMA_URL} after {max_retries} retries: {last_err}"
    )
