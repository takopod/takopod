"""Schedule tool schemas — shared between worker tool definitions and orchestrator validation."""

task_id_prop = {
    "type": "string",
    "description": "The ID of the scheduled task.",
}

create_schedule_schema = {
    "name": "create_schedule",
    "description": (
        "Create a recurring scheduled task. Use when the user asks you to "
        "monitor, check, or periodically do something."
    ),
    "input_schema": {
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
}

list_schedules_schema = {
    "name": "list_schedules",
    "description": (
        "List all scheduled tasks. Returns id, prompt, interval, status, "
        "and last execution time for each task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Optional: filter by 'active' or 'paused'.",
            },
        },
        "required": [],
    },
}

get_schedule_schema = {
    "name": "get_schedule",
    "description": "Get details of a specific scheduled task including its last execution result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": task_id_prop,
        },
        "required": ["task_id"],
    },
}

update_schedule_schema = {
    "name": "update_schedule",
    "description": "Update a scheduled task's prompt, interval, or allowed tools.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {**task_id_prop, "description": "The ID of the scheduled task to update."},
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
}

delete_schedule_schema = {
    "name": "delete_schedule",
    "description": "Delete a scheduled task permanently.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {**task_id_prop, "description": "The ID of the scheduled task to delete."},
        },
        "required": ["task_id"],
    },
}

pause_schedule_schema = {
    "name": "pause_schedule",
    "description": "Pause an active scheduled task. It will stop executing until resumed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {**task_id_prop, "description": "The ID of the scheduled task to pause."},
        },
        "required": ["task_id"],
    },
}

resume_schedule_schema = {
    "name": "resume_schedule",
    "description": "Resume a paused scheduled task.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {**task_id_prop, "description": "The ID of the scheduled task to resume."},
        },
        "required": ["task_id"],
    },
}

all_schemas = [
    create_schedule_schema, list_schedules_schema, get_schedule_schema,
    update_schedule_schema, delete_schedule_schema,
    pause_schedule_schema, resume_schedule_schema,
]
