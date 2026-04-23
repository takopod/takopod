"""Schedule management tools — CRUD operations for recurring agentic tasks.

All tools communicate with the orchestrator via request/response IPC files.
"""

import json
import sys
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from worker.tools.ipc import ipc_request
from worker.tools.schema import (
    create_schedule_schema,
    delete_schedule_schema,
    get_schedule_schema,
    list_schedules_schema,
    pause_schedule_schema,
    resume_schedule_schema,
    signal_activity_schema,
    update_schedule_schema,
)

TOOL_NAMES = [
    "mcp__schedule__create_schedule",
    "mcp__schedule__list_schedules",
    "mcp__schedule__get_schedule",
    "mcp__schedule__update_schedule",
    "mcp__schedule__delete_schedule",
    "mcp__schedule__pause_schedule",
    "mcp__schedule__resume_schedule",
    "mcp__schedule__signal_activity",
]


def create_schedule_server():
    """Build an in-process MCP server with schedule management tools."""

    @tool(
        create_schedule_schema["name"],
        create_schedule_schema["description"],
        create_schedule_schema["input_schema"],
    )
    async def create_schedule(args: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "prompt": args.get("prompt", ""),
            "allowed_tools": args.get("allowed_tools", []),
            "interval_minutes": args.get("interval_minutes", 60),
        }
        if args.get("trigger_type"):
            params["trigger_type"] = args["trigger_type"]
        if args.get("watch_dir"):
            params["watch_dir"] = args["watch_dir"]
        for key in ("base_interval_minutes", "max_interval_minutes"):
            if key in args:
                params[key] = args[key]
        data = await ipc_request("create_schedule", params)
        sys.stderr.write(f"agent: created schedule {data.get('task_id', '')[:8]}\n")
        sys.stderr.flush()
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        list_schedules_schema["name"],
        list_schedules_schema["description"],
        list_schedules_schema["input_schema"],
    )
    async def list_schedules(args: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if args.get("status"):
            params["status"] = args["status"]
        data = await ipc_request("list_schedules", params)
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        get_schedule_schema["name"],
        get_schedule_schema["description"],
        get_schedule_schema["input_schema"],
    )
    async def get_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("get_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        update_schedule_schema["name"],
        update_schedule_schema["description"],
        update_schedule_schema["input_schema"],
    )
    async def update_schedule(args: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"task_id": args["task_id"]}
        for key in ("prompt", "interval_minutes", "allowed_tools",
                     "base_interval_minutes", "max_interval_minutes"):
            if key in args:
                params[key] = args[key]
        data = await ipc_request("update_schedule", params)
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        delete_schedule_schema["name"],
        delete_schedule_schema["description"],
        delete_schedule_schema["input_schema"],
    )
    async def delete_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("delete_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        pause_schedule_schema["name"],
        pause_schedule_schema["description"],
        pause_schedule_schema["input_schema"],
    )
    async def pause_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("pause_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        resume_schedule_schema["name"],
        resume_schedule_schema["description"],
        resume_schedule_schema["input_schema"],
    )
    async def resume_schedule(args: dict[str, Any]) -> dict[str, Any]:
        data = await ipc_request("resume_schedule", {"task_id": args["task_id"]})
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    @tool(
        signal_activity_schema["name"],
        signal_activity_schema["description"],
        signal_activity_schema["input_schema"],
    )
    async def signal_activity(args: dict[str, Any]) -> dict[str, Any]:
        from worker.worker import _current_agentic_task_id
        task_id = args.get("task_id") or _current_agentic_task_id
        params: dict[str, Any] = {}
        if task_id:
            params["task_id"] = task_id
        data = await ipc_request("signal_activity", params)
        return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}

    return create_sdk_mcp_server(
        name="schedule",
        version="1.0.0",
        tools=[
            create_schedule, list_schedules, get_schedule,
            update_schedule, delete_schedule,
            pause_schedule, resume_schedule,
            signal_activity,
        ],
    )
