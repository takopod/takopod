"""Slack channel poller: monitors a Slack channel for @Agent-Name mentions.

Runs as a single asyncio background task created in main.py lifespan,
following the same pattern as scheduler.py. When a message mentions an
agent by name, it is routed through the normal message pipeline. When
the agent completes, the response is posted back as a Slack thread reply.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from orchestrator.db import get_db
from orchestrator.settings import get_setting
from orchestrator.slack_routes import _read_slack_config

logger = logging.getLogger(__name__)

SLACK_MESSAGE_CHAR_LIMIT = 40_000


MIN_POLL_INTERVAL = 10  # seconds — floor for per-channel intervals


async def run_slack_poller() -> None:
    """Main polling loop — polls each configured channel on its own interval."""
    logger.info("Slack poller started")
    # Track last poll time per channel row id (monotonic)
    last_poll: dict[str, float] = {}

    while True:
        try:
            enabled = (await get_setting("slack_polling_enabled", "false")) == "true"
            if enabled:
                channels = await _get_polling_channels()
                now = asyncio.get_running_loop().time()
                for ch in channels:
                    row_id = ch["id"]
                    interval = max(ch["interval_seconds"], MIN_POLL_INTERVAL)
                    if now - last_poll.get(row_id, 0) >= interval:
                        try:
                            await _poll_channel(ch["channel_id"], ch["last_ts"])
                            last_poll[row_id] = now
                        except Exception:
                            logger.exception(
                                "Slack poller failed for channel %s",
                                ch["channel_id"],
                            )
                # Clean up removed channels from tracking
                active_ids = {ch["id"] for ch in channels}
                for rid in list(last_poll):
                    if rid not in active_ids:
                        del last_poll[rid]
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Slack poller tick failed")
        await asyncio.sleep(5)  # base tick — individual intervals checked above


async def _get_polling_channels() -> list[dict]:
    """Fetch all enabled polling channels from the DB."""
    db = await get_db()
    async with db.execute(
        "SELECT id, channel_id, interval_seconds, last_ts "
        "FROM slack_polling_channels WHERE enabled = 1",
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "channel_id": r[1],
            "interval_seconds": r[2],
            "last_ts": r[3],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Channel polling
# ---------------------------------------------------------------------------


async def _poll_channel(channel_id: str, last_ts: str) -> None:
    """Fetch new messages from the channel and dispatch agent mentions."""
    client = _build_slack_client()
    if client is None:
        return

    try:
        response = await asyncio.to_thread(
            client.conversations_history,
            channel=channel_id,
            oldest=last_ts,
            limit=50,
        )
    except SlackApiError as e:
        logger.warning("Slack API error polling channel %s: %s", channel_id, e)
        return

    messages = response.get("messages", [])
    if not messages:
        return

    # Load active agent names for mention matching
    agent_map = await _load_agent_map()
    if not agent_map:
        return

    highest_ts = last_ts

    # Slack returns newest-first; process oldest-first for correct ordering
    for msg in reversed(messages):
        ts = msg.get("ts", "")

        # Skip bot messages and subtypes (joins, leaves, etc.)
        if msg.get("bot_id") or msg.get("subtype"):
            continue

        text = msg.get("text", "")
        if not text:
            continue

        mentioned = _parse_agent_mentions(text, agent_map)
        for agent_name in mentioned:
            agent_id = agent_map[agent_name]
            # Strip the @AgentName prefix from the prompt
            prompt = _extract_prompt(text, agent_name)
            if not prompt.strip():
                continue
            try:
                await _dispatch_to_agent(agent_id, prompt, channel_id, ts)
                logger.info(
                    "Dispatched Slack message to agent %s (%s)",
                    agent_name, agent_id[:8],
                )
            except Exception:
                logger.exception(
                    "Failed to dispatch Slack message to agent %s", agent_name,
                )
                await post_slack_reply(
                    channel_id, ts,
                    f"Failed to dispatch message to agent '{agent_name}'.",
                )

        # Messages without agent mentions are silently ignored.
        # Slack channels contain @user, @here, @channel mentions that
        # should not trigger "agent not found" errors.

        if ts > highest_ts:
            highest_ts = ts

    # Persist high-water mark so we don't reprocess on next tick
    if highest_ts > last_ts:
        db = await get_db()
        await db.execute(
            "UPDATE slack_polling_channels SET last_ts = ? WHERE channel_id = ?",
            (highest_ts, channel_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Agent mention parsing
# ---------------------------------------------------------------------------


async def _load_agent_map() -> dict[str, str]:
    """Return {lowercase_name: agent_id} for all active agents."""
    db = await get_db()
    async with db.execute(
        "SELECT id, name FROM agents WHERE status = 'active'",
    ) as cur:
        rows = await cur.fetchall()
    return {name.lower(): aid for aid, name in rows}


def _parse_agent_mentions(
    text: str, agent_map: dict[str, str],
) -> list[str]:
    """Find @AgentName mentions that match known agents.

    Returns list of lowercase agent names that were mentioned.
    Matches longest names first to handle overlapping prefixes.
    """
    lower_text = text.lower()
    matched: list[str] = []
    # Sort by length descending so "Research Agent" matches before "Research"
    for name in sorted(agent_map, key=len, reverse=True):
        pattern = f"@{name}"
        if pattern in lower_text:
            matched.append(name)
            # Remove matched mention to prevent substring matches
            lower_text = lower_text.replace(pattern, "", 1)
    return matched


def _extract_prompt(text: str, agent_name: str) -> str:
    """Remove the @AgentName mention from the text to get the prompt."""
    # Case-insensitive removal of the first @AgentName occurrence
    pattern = re.compile(re.escape(f"@{agent_name}"), re.IGNORECASE)
    return pattern.sub("", text, count=1).strip()


# ---------------------------------------------------------------------------
# Dispatch to agent
# ---------------------------------------------------------------------------


async def _dispatch_to_agent(
    agent_id: str,
    content: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    """Route a Slack message through the normal message pipeline."""
    from orchestrator.ipc import _inflight_source, store_slack_message
    from orchestrator.routes import _get_or_create_session, ensure_worker_headless

    session_id = await _get_or_create_session(agent_id)
    await ensure_worker_headless(agent_id, session_id)

    message_id = str(uuid.uuid4())

    # Track source metadata so the completion hook can post the reply
    _inflight_source[message_id] = {
        "source": "slack",
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }

    await store_slack_message(
        session_id, message_id, content, channel_id, thread_ts,
    )


# ---------------------------------------------------------------------------
# Slack reply posting
# ---------------------------------------------------------------------------


async def post_slack_reply(
    channel_id: str, thread_ts: str, text: str,
) -> None:
    """Post a message as a thread reply in Slack.

    Called from ipc._process_event on completion and from the poller
    for error replies. This is an orchestrator-internal function, not
    an MCP tool.
    """
    client = _build_slack_client()
    if client is None:
        logger.warning("Cannot post Slack reply: no credentials configured")
        return

    # Respect Slack's message length limit
    if len(text) > SLACK_MESSAGE_CHAR_LIMIT:
        text = text[: SLACK_MESSAGE_CHAR_LIMIT - 30] + "\n\n[Response truncated]"

    try:
        await asyncio.to_thread(
            client.chat_postMessage,
            channel=channel_id,
            thread_ts=thread_ts,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError:
        logger.exception(
            "Failed to post Slack reply to channel=%s thread=%s",
            channel_id, thread_ts,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_slack_client() -> WebClient | None:
    """Build a WebClient from stored credentials, or None if not configured."""
    config = _read_slack_config()
    if not config:
        return None
    return WebClient(
        token=config["xoxc_token"],
        headers={"Cookie": f"d={config['d_cookie']}"},
    )
