"""Slack MCP server for rhclaw.

Provides tools to read Slack channels and send messages to yourself.
Runs on the host (orchestrator) side — credentials never enter worker containers.

Usage (standalone testing):
    SLACK_XOXC_TOKEN=xoxc-... SLACK_D_COOKIE=xoxd-... MY_MEMBER_ID=U01234567 \
        python -m integrations.slack_mcp
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

mcp = FastMCP("SlackIntegration")

SLACK_TOKEN = os.environ.get("SLACK_XOXC_TOKEN", "")
SLACK_COOKIE = os.environ.get("SLACK_D_COOKIE", "")
MY_MEMBER_ID = os.environ.get("MY_MEMBER_ID", "")

client = WebClient(
    token=SLACK_TOKEN,
    headers={"Cookie": f"d={SLACK_COOKIE}"},
)


def _format_message(msg: dict) -> str:
    """Format a single Slack message for display."""
    user = msg.get("user", "unknown")
    text = msg.get("text", "")
    ts = msg.get("ts", "")
    return f"[{ts}] {user}: {text}"


@mcp.tool()
async def list_channels() -> str:
    """List Slack channels you belong to. Returns channel ID and name for each."""
    try:
        channels = []
        cursor = None
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor or "",
            )
            for ch in response["channels"]:
                if ch.get("is_member"):
                    channels.append(f"{ch['id']}: #{ch['name']}")
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        if not channels:
            return "You are not a member of any channels."
        return "\n".join(channels)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def read_channel(channel_id: str, limit: int = 20) -> str:
    """Read recent messages from a Slack channel.

    Args:
        channel_id: The channel ID (e.g. C0123ABC). Use list_channels to find IDs.
        limit: Number of messages to retrieve (max 100, default 20).
    """
    limit = min(max(1, limit), 100)
    try:
        response = client.conversations_history(channel=channel_id, limit=limit)
        if not response["messages"]:
            return "No messages found in this channel."
        lines = [_format_message(m) for m in reversed(response["messages"])]
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def search_messages(query: str, limit: int = 10) -> str:
    """Search Slack messages across all accessible channels.

    Args:
        query: Search query string.
        limit: Number of results to return (max 50, default 10).
    """
    limit = min(max(1, limit), 50)
    try:
        response = client.search_messages(query=query, count=limit)
        matches = response.get("messages", {}).get("matches", [])
        if not matches:
            return f"No messages found matching '{query}'."
        lines = []
        for m in matches:
            channel_name = m.get("channel", {}).get("name", "unknown")
            user = m.get("user", m.get("username", "unknown"))
            text = m.get("text", "")
            ts = m.get("ts", "")
            lines.append(f"[{ts}] #{channel_name} | {user}: {text}")
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def send_note_to_self(message: str) -> str:
    """Send a private message to your own Slack DM.

    This is the only way to send messages — it is hardcoded to your own
    member ID so no messages can be sent to other users or channels.

    Args:
        message: The message text to send to yourself.
    """
    if not MY_MEMBER_ID:
        return "Error: MY_MEMBER_ID is not configured."
    try:
        dm = client.conversations_open(users=[MY_MEMBER_ID])
        channel_id = dm["channel"]["id"]
        prefixed = f"[rhclaw]: {message}"
        response = client.chat_postMessage(
            channel=channel_id,
            text=prefixed,
            unfurl_links=False,
            unfurl_media=False,
            metadata={"event_type": "rhclaw_note", "event_payload": {}},
        )
        return f"Sent to yourself! (Timestamp: {response['ts']})"
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


@mcp.tool()
async def read_my_notes(limit: int = 5) -> str:
    """Read the latest messages from your personal Slack DM history.

    Args:
        limit: Number of messages to retrieve (max 50, default 5).
    """
    if not MY_MEMBER_ID:
        return "Error: MY_MEMBER_ID is not configured."
    limit = min(max(1, limit), 50)
    try:
        dm = client.conversations_open(users=[MY_MEMBER_ID])
        channel_id = dm["channel"]["id"]
        response = client.conversations_history(channel=channel_id, limit=limit)
        if not response["messages"]:
            return "No messages in your personal DM."
        lines = [_format_message(m) for m in reversed(response["messages"])]
        return "\n".join(lines)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"


if __name__ == "__main__":
    mcp.run()
