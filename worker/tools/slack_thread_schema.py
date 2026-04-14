"""Slack thread monitoring tool schemas."""

register_slack_thread_schema = {
    "name": "register_slack_thread",
    "description": (
        "Start monitoring a Slack thread. New replies that mention you "
        "(e.g. 'agentname: message') will be dispatched to you automatically. "
        "Use when the user asks you to watch, monitor, or follow a Slack thread."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "string",
                "description": (
                    "The Slack channel ID (e.g. C0123ABC). "
                    "Use the Slack list_channels tool to find IDs."
                ),
            },
            "thread_ts": {
                "type": "string",
                "description": (
                    "The thread timestamp (e.g. 1234567890.123456). "
                    "This is the ts of the parent message that started the thread."
                ),
            },
        },
        "required": ["channel_id", "thread_ts"],
    },
}

unregister_slack_thread_schema = {
    "name": "unregister_slack_thread",
    "description": (
        "Stop monitoring a Slack thread. Use when the user asks you to stop "
        "watching or unfollow a thread."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "string",
                "description": "The Slack channel ID.",
            },
            "thread_ts": {
                "type": "string",
                "description": "The thread timestamp of the parent message.",
            },
        },
        "required": ["channel_id", "thread_ts"],
    },
}

list_slack_threads_schema = {
    "name": "list_slack_threads",
    "description": (
        "List all Slack threads you are currently monitoring."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

all_schemas = [
    register_slack_thread_schema,
    unregister_slack_thread_schema,
    list_slack_threads_schema,
]
