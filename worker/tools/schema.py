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
            "interval_minutes": {
                "type": "integer",
                "description": "How often to run, in minutes (minimum 5). Required for interval triggers.",
            },
            "trigger_type": {
                "type": "string",
                "enum": ["interval", "file_watch", "webhook", "github_pr", "github_issues", "slack_channel"],
                "description": (
                    "Type of trigger. 'interval' runs on a timer. "
                    "'file_watch' runs when new files appear in a directory. "
                    "'webhook' runs when an HTTP POST is received. "
                    "'github_pr' polls a GitHub PR for new comments/reviews/commits. "
                    "'github_issues' polls repo issues matching labels/state. "
                    "'slack_channel' passively observes a Slack channel for new messages."
                ),
            },
            "watch_dir": {
                "type": "string",
                "description": "For file_watch triggers: directory within /workspace to watch (e.g., 'inbox'). Must be a relative path within the workspace.",
            },
            "github_repo": {
                "type": "string",
                "description": "For github_pr/github_issues triggers: repository in 'owner/repo' format.",
            },
            "github_pr_number": {
                "type": "integer",
                "description": "For github_pr trigger: specific PR number to watch. If omitted, watches all PRs in the repo.",
            },
            "github_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "For github_pr/github_issues triggers: only match PRs/issues with these labels.",
            },
            "github_state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "For github_pr/github_issues triggers: state filter (default: open).",
            },
            "slack_channel_id": {
                "type": "string",
                "description": "For slack_channel trigger: the Slack channel ID (e.g., 'C1234567890').",
            },
            "slack_channel_name": {
                "type": "string",
                "description": "For slack_channel trigger: optional human-readable channel name for display.",
            },
            "base_interval_minutes": {
                "type": "integer",
                "description": "Enable idle backoff: base (fastest) polling interval in minutes. When the task finds no activity, the interval doubles up to max_interval_minutes. Call signal_activity to reset.",
            },
            "max_interval_minutes": {
                "type": "integer",
                "description": "Maximum polling interval in minutes when idle backoff is active (e.g., 360 for 6 hours). Required when base_interval_minutes is set.",
            },
        },
        "required": ["prompt"],
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
            "base_interval_minutes": {
                "type": "integer",
                "description": "Enable idle backoff: base (fastest) polling interval in minutes. Set to 0 to disable backoff.",
            },
            "max_interval_minutes": {
                "type": "integer",
                "description": "Maximum polling interval in minutes when idle backoff is active.",
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

signal_activity_schema = {
    "name": "signal_activity",
    "description": (
        "Signal that meaningful activity was detected during a scheduled task "
        "execution. Resets the polling interval back to the base rate so the "
        "next check happens sooner. Only useful for tasks with idle backoff "
        "enabled (base_interval_minutes and max_interval_minutes set). "
        "Call this when you find new comments, CI failures, status changes, "
        "or anything worth following up on quickly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The scheduled task ID to reset. Auto-detected when running inside a scheduled task.",
            },
        },
        "required": [],
    },
}

all_schemas = [
    create_schedule_schema, list_schedules_schema, get_schedule_schema,
    update_schedule_schema, delete_schedule_schema,
    pause_schedule_schema, resume_schedule_schema,
    signal_activity_schema,
]
