#!/usr/bin/env python3
"""Stub worker: polls /workspace/input.json, emits hardcoded JSONL responses."""

import json
import os
import sys
import time

WORKSPACE = "/workspace"
INPUT_PATH = os.path.join(WORKSPACE, "input.json")
POLL_INTERVAL = 0.5
HARDCODED_TOKENS = ["Hello", " from", " the", " stub", " worker", "!"]


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


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

    while True:
        time.sleep(POLL_INTERVAL)

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
