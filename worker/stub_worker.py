#!/usr/bin/env python3
"""Stub worker: polls /workspace/input.json, emits hardcoded responses via response.json."""

import json
import os
import sys
import time

WORKSPACE = "/workspace"
INPUT_PATH = os.path.join(WORKSPACE, "input.json")
RESPONSE_PATH = os.path.join(WORKSPACE, "response.json")
POLL_INTERVAL = 0.5
HARDCODED_TOKENS = ["Hello", " from", " the", " stub", " worker", "!"]

_pending_events: list[dict] = []


def atomic_write(path: str, data: bytes) -> None:
    """Write data to path atomically via temp file + rename."""
    temp_path = f"{path}.tmp.{os.getpid()}"
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def flush_responses() -> None:
    """Write pending events to response.json if absent."""
    if os.path.exists(RESPONSE_PATH) or not _pending_events:
        return
    atomic_write(RESPONSE_PATH, json.dumps(_pending_events).encode())
    _pending_events.clear()


def emit(event: dict) -> None:
    _pending_events.append(event)
    flush_responses()


def process_message(msg: dict) -> None:
    message_id = msg.get("message_id", "unknown")
    full_text = "".join(HARDCODED_TOKENS)

    emit({"type": "status", "status": "thinking", "message_id": message_id})
    time.sleep(0.2)

    for seq, token in enumerate(HARDCODED_TOKENS, start=1):
        emit({
            "type": "token",
            "content": token,
            "message_id": message_id,
            "seq": seq,
        })
        time.sleep(0.1)

    emit({
        "type": "complete",
        "content": full_text,
        "message_id": message_id,
        "usage": {"input_tokens": 10, "output_tokens": len(HARDCODED_TOKENS)},
    })
    emit({"type": "status", "status": "done", "message_id": message_id})


def main() -> None:
    sys.stderr.write("stub_worker: started, polling for input.json\n")
    sys.stderr.flush()

    # Clean up stale state
    if os.path.exists(RESPONSE_PATH):
        os.remove(RESPONSE_PATH)

    while True:
        time.sleep(POLL_INTERVAL)

        # Flush any pending events that couldn't be written earlier
        flush_responses()

        if not os.path.exists(INPUT_PATH):
            continue

        try:
            with open(INPUT_PATH) as f:
                data = json.load(f)
            os.remove(INPUT_PATH)
        except (json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"stub_worker: error reading input.json: {e}\n")
            sys.stderr.flush()
            continue

        messages = data if isinstance(data, list) else [data]
        for msg in messages:
            process_message(msg)


if __name__ == "__main__":
    main()
