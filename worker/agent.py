"""Claude Agent SDK integration.

Translates SDK messages into the JSONL protocol expected by the orchestrator's
stream reader (token, tool_call, tool_result, complete events on stdout).
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

WORKSPACE = Path("/workspace")
MAX_TURNS = 25

Emit = Callable[[dict[str, Any]], None]


def _build_system_prompt() -> str:
    """Assemble system prompt from CLAUDE.md, SOUL.md, and agents.json."""
    parts: list[str] = []

    claude_md = WORKSPACE / "CLAUDE.md"
    if claude_md.is_file():
        parts.append(claude_md.read_text().strip())

    soul_md = WORKSPACE / "SOUL.md"
    if soul_md.is_file():
        parts.append(soul_md.read_text().strip())

    agents_json = WORKSPACE / "agents.json"
    if agents_json.is_file():
        try:
            agents = json.loads(agents_json.read_text())
            if agents:
                agent_list = "\n".join(
                    f"- {a['name']} ({a.get('agent_type', 'unknown')})"
                    for a in agents
                )
                parts.append(
                    f"## Available Delegation Targets\n\n"
                    f"The following agents are available for delegation:\n{agent_list}"
                )
        except (json.JSONDecodeError, KeyError):
            pass

    return "\n\n".join(parts)


async def run_query(
    message_id: str,
    content: str,
    session_id: str | None,
    emit: Emit,
) -> tuple[str | None, dict[str, Any]]:
    """Run a query through the Claude Agent SDK.

    Returns (captured_session_id, usage_dict).
    """
    system_prompt = _build_system_prompt()

    # Emit tool events via hooks so the frontend can display them
    async def on_pre_tool(input_data, tool_use_id, context):
        emit({
            "type": "tool_call",
            "tool_name": input_data.get("tool_name", "unknown"),
            "tool_input": input_data.get("tool_input", {}),
            "tool_call_id": tool_use_id,
            "message_id": message_id,
        })
        return {}

    async def on_post_tool(input_data, tool_use_id, context):
        output = input_data.get("output", "")
        if isinstance(output, dict):
            output = json.dumps(output)
        emit({
            "type": "tool_result",
            "tool_call_id": tool_use_id,
            "output": str(output)[:4000],
            "message_id": message_id,
        })
        return {}

    opts_kwargs: dict[str, Any] = {
        "cwd": str(WORKSPACE),
        "allowed_tools": [
            "Read", "Write", "Edit", "Bash",
            "Glob", "Grep", "WebSearch", "WebFetch",
        ],
        "permission_mode": "acceptEdits",
        "system_prompt": system_prompt,
        "max_turns": MAX_TURNS,
        "hooks": {
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[on_pre_tool])],
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[on_post_tool])],
        },
    }
    if session_id:
        opts_kwargs["resume"] = session_id

    options = ClaudeAgentOptions(**opts_kwargs)

    captured_session_id = session_id
    total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    full_text_parts: list[str] = []
    seq = 0

    emit({"type": "status", "status": "generating", "message_id": message_id})

    async for msg in query(prompt=content, options=options):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            captured_session_id = msg.data.get("session_id")
            sys.stderr.write(
                f"agent: SDK session_id={captured_session_id}\n"
            )
            sys.stderr.flush()

        elif isinstance(msg, AssistantMessage):
            if msg.usage:
                total_usage["input_tokens"] += msg.usage.get("input_tokens", 0)
                total_usage["output_tokens"] += msg.usage.get("output_tokens", 0)

            for block in msg.content:
                if isinstance(block, TextBlock):
                    seq += 1
                    full_text_parts.append(block.text)
                    emit({
                        "type": "token",
                        "content": block.text,
                        "message_id": message_id,
                        "seq": seq,
                    })

        elif isinstance(msg, ResultMessage):
            # ResultMessage signals completion; text already captured above
            pass

    full_text = "".join(full_text_parts)
    emit({
        "type": "complete",
        "content": full_text,
        "message_id": message_id,
        "usage": total_usage,
    })

    return captured_session_id, total_usage
