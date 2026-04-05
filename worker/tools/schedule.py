"""Schedule management tools — CRUD operations for recurring agentic tasks.

All tools communicate with the orchestrator via request/response IPC files.
"""

import json
import sys
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.tools.ipc import ipc_request

TOOL_NAMES = [
    "mcp__schedule__create_schedule",
    "mcp__schedule__list_schedules",
    "mcp__schedule__get_schedule",
    "mcp__schedule__update_schedule",
    "mcp__schedule__delete_schedule",
    "mcp__schedule__pause_schedule",
    "mcp__schedule__resume_schedule",
]


def create_schedule_server():
    """Build an in-process MCP server with schedule management tools."""

    @tool(
        "create_schedule",
        "Create a recurring scheduled task. Use when the user asks you to monitor, check, or periodically do something.",
        {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The instruction to execute on each run. Be specific - "
                        "include URLs, channel names, criteria, and what action to take."
                    ),
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools the scheduled task needs (e.g., WebFetch, WebSearch, Bash).",
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "How often to run, in minutes (minimum 5).",
                },
            },
            "required": ["prompt", "interval_minutes"],
        },
    )
    async def create_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("create_schedule", {
            "prompt": args.get("prompt", ""),
            "allowed_tools": args.get("allowed_tools", []),
            "interval_minutes": args.get("interval_minutes", 60),
        })
        sys.stderr.write(f"agent: created schedule {data.get('task_id', '')[:8]}\n")
        sys.stderr.flush()
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "list_schedules",
        "List all scheduled tasks. Returns id, prompt, interval, status, and last execution time for each task.",
        {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional: filter by 'active' or 'paused'.",
                },
            },
            "required": [],
        },
    )
    async def list_schedules(args: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if args.get("status"):
            params["status"] = args["status"]
        data = await ipc_request("list_schedules", params)
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "get_schedule",
        "Get details of a specific scheduled task including its last execution result.",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The ID of the scheduled task.",
                },
            },
            "required": ["task_id"],
        },
    )
    async def get_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("get_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "update_schedule",
        "Update a scheduled task's prompt, interval, or allowed tools.",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The ID of the scheduled task to update.",
                },
                "prompt": {
                    "type": "string",
                    "description": "New instruction for the task.",
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "New interval in minutes (minimum 5).",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New list of allowed tools.",
                },
            },
            "required": ["task_id"],
        },
    )
    async def update_schedule(args: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"task_id": args["task_id"]}
        for key in ("prompt", "interval_minutes", "allowed_tools"):
            if key in args:
                params[key] = args[key]
        data = await ipc_request("update_schedule", params)
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "delete_schedule",
        "Delete a scheduled task permanently.",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The ID of the scheduled task to delete.",
                },
            },
            "required": ["task_id"],
        },
    )
    async def delete_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("delete_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "pause_schedule",
        "Pause an active scheduled task. It will stop executing until resumed.",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The ID of the scheduled task to pause.",
                },
            },
            "required": ["task_id"],
        },
    )
    async def pause_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("pause_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        "resume_schedule",
        "Resume a paused scheduled task.",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The ID of the scheduled task to resume.",
                },
            },
            "required": ["task_id"],
        },
    )
    async def resume_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("resume_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    return create_sdk_mcp_server(
        name="schedule",
        version="1.0.0",
        tools=[
            create_schedule, list_schedules, get_schedule,
            update_schedule, delete_schedule,
            pause_schedule, resume_schedule,
        ],
    )
