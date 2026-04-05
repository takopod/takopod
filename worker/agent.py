"""Claude Agent SDK integration.

Translates SDK messages into events (token, tool_call, tool_result, complete)
persisted via the worker's emit() callback for the orchestrator to consume.
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

from worker.tools import TOOL_NAMES as SCHEDULE_TOOL_NAMES, create_schedule_server

WORKSPACE = Path("/workspace")
MAX_TURNS = 25

Emit = Callable[[dict[str, Any]], None]


def _build_system_prompt(
    retrieved_context: str | None = None,
    memory_context: str | None = None,
    continuation_summary: str | None = None,
) -> str:
    """Assemble system prompt from identity files, memory, and retrieved context."""
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

    if memory_context:
        parts.append(memory_context)

    if retrieved_context:
        parts.append(
            "## Relevant Past Conversations\n\n"
            "The following excerpts are from previous conversations and may be relevant:\n\n"
            + retrieved_context
        )

    if continuation_summary:
        parts.append(
            "## Continuation Context\n\n"
            "The conversation was automatically split due to context length. "
            "Below is a summary of the prior conversation:\n\n"
            + continuation_summary
        )

    return "\n\n".join(parts)


async def run_query(
    message_id: str,
    content: str,
    session_id: str | None,
    emit: Emit,
    retrieved_context: str | None = None,
    memory_context: str | None = None,
    continuation_summary: str | None = None,
) -> tuple[str | None, dict[str, Any], str]:
    """Run a query through the Claude Agent SDK.

    Returns (captured_session_id, usage_dict, full_response_text).
    """
    system_prompt = _build_system_prompt(
        retrieved_context, memory_context, continuation_summary,
    )
    sys.stderr.write(
        f"agent: system_prompt ({len(system_prompt)} chars):\n{system_prompt}\n"
    )
    sys.stderr.flush()

    # Emit tool events via hooks so the frontend can display them
    async def on_pre_tool(input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "unknown")
        sys.stderr.write(f"agent: tool_call {tool_name} id={tool_use_id[:12]}\n")
        sys.stderr.flush()
        emit({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_input": input_data.get("tool_input", {}),
            "tool_call_id": tool_use_id,
            "message_id": message_id,
        })
        return {}

    async def on_post_tool(input_data, tool_use_id, context):
        output = input_data.get("output", "")
        if isinstance(output, dict):
            output = json.dumps(output)
        output_str = str(output)

        sys.stderr.write(f"agent: tool_result id={tool_use_id[:12]}\n")
        sys.stderr.flush()
        emit({
            "type": "tool_result",
            "tool_call_id": tool_use_id,
            "output": output_str[:4000],
            "message_id": message_id,
        })
        return {}

    schedule_server = create_schedule_server()

    opts_kwargs: dict[str, Any] = {
        "cwd": str(WORKSPACE),
        "allowed_tools": [
            "Read", "Write", "Edit", "Bash",
            "Glob", "Grep", "WebSearch", "WebFetch",
            *SCHEDULE_TOOL_NAMES,
        ],
        "permission_mode": "acceptEdits",
        "system_prompt": system_prompt,
        "max_turns": MAX_TURNS,
        "mcp_servers": {"schedule": schedule_server},
        "hooks": {
            "PreToolUse": [HookMatcher(matcher=".*", hooks=[on_pre_tool])],
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[on_post_tool])],
        },
    }
    if session_id:
        opts_kwargs["resume"] = session_id

    options = ClaudeAgentOptions(**opts_kwargs)

    # Log the full query() call for debugging
    log_kwargs = {k: v for k, v in opts_kwargs.items() if k not in ("hooks", "mcp_servers")}
    log_kwargs["prompt"] = content
    sys.stderr.write(f"agent: query() call:\n{json.dumps(log_kwargs, indent=2)}\n")
    sys.stderr.flush()

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
            sys.stderr.write(f"agent: AssistantMessage seq={seq}\n")
            sys.stderr.flush()

        elif isinstance(msg, ResultMessage):
            sys.stderr.write("agent: ResultMessage (query complete)\n")
            sys.stderr.flush()

    full_text = "\n\n".join(full_text_parts)
    sys.stderr.write(
        f"agent: emitting complete, {len(full_text_parts)} text blocks, "
        f"{total_usage.get('input_tokens', 0)}+{total_usage.get('output_tokens', 0)} tokens\n"
    )
    sys.stderr.flush()
    emit({
        "type": "complete",
        "content": full_text,
        "message_id": message_id,
        "usage": total_usage,
    })

    return captured_session_id, total_usage, full_text
