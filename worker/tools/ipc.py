"""IPC client for worker-to-orchestrator request/response communication.

Writes request.json, polls for response.json with matching request_id.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

WORKSPACE = Path("/workspace")
REQUEST_PATH = WORKSPACE / "request.json"
RESPONSE_PATH = WORKSPACE / "response.json"

POLL_INTERVAL = 0.1  # seconds between polls
DEFAULT_TIMEOUT = 10.0  # seconds


def _atomic_write(path: Path, data: bytes) -> None:
    """Write data to path atomically via temp file + rename."""
    temp_path = path.parent / f"{path.name}.tmp.{os.getpid()}"
    try:
        fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(str(temp_path), str(path))
    except BaseException:
        try:
            os.unlink(str(temp_path))
        except FileNotFoundError:
            pass
        raise


async def ipc_request(
    action: str,
    parameters: dict,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Send a request to the orchestrator and wait for the response.

    Raises RuntimeError on timeout or error response.
    """
    from worker.worker import flush_responses

    request_id = str(uuid.uuid4())
    request = {
        "request_id": request_id,
        "action": action,
        "parameters": parameters,
    }
    _atomic_write(REQUEST_PATH, json.dumps(request).encode())

    elapsed = 0.0
    while elapsed < timeout:
        flush_responses()
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        if not RESPONSE_PATH.exists():
            continue

        try:
            with open(RESPONSE_PATH) as f:
                response = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if response.get("request_id") != request_id:
            continue

        # Matched — consume the file
        try:
            os.remove(RESPONSE_PATH)
        except OSError:
            pass

        if response.get("status") == "error":
            raise RuntimeError(response.get("error", "Unknown error"))

        return response.get("data", {})

    raise RuntimeError(f"IPC request timed out after {timeout}s (action={action})")
