"""Claude API integration via Vertex AI with manual agentic loop."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from anthropic import AnthropicVertex

WORKSPACE = Path("/workspace")
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
REGION = os.environ.get("GOOGLE_CLOUD_REGION", "")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_AGENTIC_TURNS = 25
BASH_TIMEOUT = 60

TOOLS = [
    {
        "name": "bash",
        "description": (
            "Execute a shell command. The command runs in /workspace with a "
            "60-second timeout. Returns stdout and stderr."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to /workspace.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to /workspace.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories in a workspace path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to /workspace. Defaults to '.'.",
                    "default": ".",
                },
            },
        },
    },
]


def _validate_workspace_path(rel_path: str) -> Path:
    """Resolve a relative path and ensure it stays within /workspace."""
    resolved = (WORKSPACE / rel_path).resolve()
    if not resolved.is_relative_to(WORKSPACE.resolve()):
        raise ValueError(f"Path escapes workspace: {rel_path}")
    return resolved


def execute_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Execute a tool and return its output as a string."""
    try:
        if name == "bash":
            result = subprocess.run(
                ["sh", "-c", tool_input["command"]],
                capture_output=True,
                text=True,
                timeout=BASH_TIMEOUT,
                cwd=str(WORKSPACE),
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output or "(no output)"

        elif name == "read_file":
            path = _validate_workspace_path(tool_input["path"])
            if not path.is_file():
                return f"Error: file not found: {tool_input['path']}"
            return path.read_text()

        elif name == "write_file":
            path = _validate_workspace_path(tool_input["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tool_input["content"])
            return f"Written {len(tool_input['content'])} bytes to {tool_input['path']}"

        elif name == "list_files":
            rel = tool_input.get("path", ".")
            path = _validate_workspace_path(rel)
            if not path.is_dir():
                return f"Error: not a directory: {rel}"
            entries = sorted(path.iterdir())
            lines = []
            for e in entries:
                suffix = "/" if e.is_dir() else ""
                lines.append(f"{e.name}{suffix}")
            return "\n".join(lines) or "(empty directory)"

        else:
            return f"Error: unknown tool: {name}"

    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {BASH_TIMEOUT}s"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def build_system_prompt() -> str:
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


Emit = Callable[[dict[str, Any]], None]


def run_query(
    message_id: str,
    content: str,
    session_messages: list[dict[str, Any]],
    emit: Emit,
) -> dict[str, Any]:
    """Run a query through the Vertex AI Claude API with an agentic tool loop.

    Mutates session_messages in place (appends user + assistant + tool turns).
    Returns usage dict.
    """
    client = AnthropicVertex(project_id=PROJECT_ID, region=REGION)
    system_prompt = build_system_prompt()

    session_messages.append({"role": "user", "content": content})

    total_usage = {"input_tokens": 0, "output_tokens": 0}
    seq = 0
    full_text_parts: list[str] = []

    for turn in range(MAX_AGENTIC_TURNS):
        emit({"type": "status", "status": "generating", "message_id": message_id})

        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=system_prompt,
            messages=session_messages,
            tools=TOOLS,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        seq += 1
                        emit({
                            "type": "token",
                            "content": event.delta.text,
                            "message_id": message_id,
                            "seq": seq,
                        })

            response = stream.get_final_message()

        # Accumulate usage
        if response.usage:
            total_usage["input_tokens"] += response.usage.input_tokens
            total_usage["output_tokens"] += response.usage.output_tokens

        # Append assistant message to session history
        # Convert content blocks to serializable dicts
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                full_text_parts.append(block.text)
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                emit({
                    "type": "tool_call",
                    "tool_name": block.name,
                    "tool_input": block.input,
                    "tool_call_id": block.id,
                    "message_id": message_id,
                })

        session_messages.append({"role": "assistant", "content": assistant_content})

        # If Claude is done, break
        if response.stop_reason == "end_turn":
            break

        # If Claude wants to use tools, execute them
        if response.stop_reason == "tool_use":
            emit({"type": "status", "status": "tool_calling", "message_id": message_id})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
                    emit({
                        "type": "tool_result",
                        "tool_call_id": block.id,
                        "output": output,
                        "message_id": message_id,
                    })

            session_messages.append({"role": "user", "content": tool_results})

        else:
            # Unexpected stop reason (max_tokens, etc.) — break
            sys.stderr.write(
                f"agent: unexpected stop_reason={response.stop_reason}\n"
            )
            sys.stderr.flush()
            break

    full_text = "".join(full_text_parts)
    emit({
        "type": "complete",
        "content": full_text,
        "message_id": message_id,
        "usage": total_usage,
    })

    return total_usage
