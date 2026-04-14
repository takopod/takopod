"""Slack thread monitoring tools — register/unregister threads for polling.

All tools communicate with the orchestrator via request/response IPC files.
"""

import json
import sys
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.tools.ipc import ipc_request
from worker.tools.slack_thread_schema import (
    list_slack_threads_schema,
    register_slack_thread_schema,
    unregister_slack_thread_schema,
)

TOOL_NAMES = [
    "mcp__slack_thread__register_slack_thread",
    "mcp__slack_thread__unregister_slack_thread",
    "mcp__slack_thread__list_slack_threads",
]


def create_slack_thread_server():
    """Build an in-process MCP server with Slack thread monitoring tools."""

    @tool(
        register_slack_thread_schema["name"],
        register_slack_thread_schema["description"],
        register_slack_thread_schema["input_schema"],
    )
    async def register_slack_thread(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("register_slack_thread", {
            "channel_id": args["channel_id"],
            "thread_ts": args["thread_ts"],
        })
        sys.stderr.write(
            f"agent: registered slack thread {args['channel_id']}/{args['thread_ts']}\n"
        )
        sys.stderr.flush()
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        unregister_slack_thread_schema["name"],
        unregister_slack_thread_schema["description"],
        unregister_slack_thread_schema["input_schema"],
    )
    async def unregister_slack_thread(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("unregister_slack_thread", {
            "channel_id": args["channel_id"],
            "thread_ts": args["thread_ts"],
        })
        sys.stderr.write(
            f"agent: unregistered slack thread {args['channel_id']}/{args['thread_ts']}\n"
        )
        sys.stderr.flush()
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        list_slack_threads_schema["name"],
        list_slack_threads_schema["description"],
        list_slack_threads_schema["input_schema"],
    )
    async def list_slack_threads(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("list_slack_threads", {})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    return create_sdk_mcp_server(
        name="slack_thread",
        version="1.0.0",
        tools=[register_slack_thread, unregister_slack_thread, list_slack_threads],
    )
