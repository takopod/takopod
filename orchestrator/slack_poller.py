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
import time
import uuid
from pathlib import Path

import httpx
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from orchestrator.db import get_db
from orchestrator.settings import get_setting
from orchestrator.slack_routes import _read_slack_config

logger = logging.getLogger(__name__)

SLACK_MESSAGE_CHAR_LIMIT = 40_000


MIN_POLL_INTERVAL = 10  # seconds — floor for per-channel intervals
BACKOFF_STEP = 10  # seconds added per consecutive failure

THREAD_BASE_INTERVAL = 10  # seconds — initial poll interval for threads
THREAD_MAX_INTERVAL = 21600  # 6 hours — cap after idle backoff

# In-memory last-poll monotonic timestamps per thread row_id.
# The actual interval is persisted in the DB; this only tracks timing.
_thread_last_poll: dict[str, float] = {}


async def run_slack_poller() -> None:
    """Main polling loop — polls each configured channel on its own interval."""
    logger.info("Slack poller started")
    # Track last poll time per channel row id (monotonic)
    last_poll: dict[str, float] = {}
    # Track consecutive failures per channel for backoff
    fail_count: dict[str, int] = {}

    while True:
        try:
            enabled = (await get_setting("slack_polling_enabled", "false")) == "true"
            if enabled:
                channels = await _get_polling_channels()
                now = asyncio.get_running_loop().time()
                for ch in channels:
                    row_id = ch["id"]
                    base_interval = max(ch["interval_seconds"], MIN_POLL_INTERVAL)
                    backoff = fail_count.get(row_id, 0) * BACKOFF_STEP
                    max_backoff = max(base_interval * 2, 60) - base_interval
                    interval = base_interval + min(backoff, max_backoff)
                    if now - last_poll.get(row_id, 0) >= interval:
                        try:
                            await _poll_channel(ch["channel_id"], ch["last_ts"])
                            last_poll[row_id] = now
                            fail_count.pop(row_id, None)
                        except Exception:
                            last_poll[row_id] = now
                            fail_count[row_id] = fail_count.get(row_id, 0) + 1
                            at_max = backoff >= max_backoff
                            if at_max:
                                logger.error(
                                    "Slack poller giving up on channel %s "
                                    "after %d consecutive failures, "
                                    "disabling channel",
                                    ch["channel_id"],
                                    fail_count[row_id],
                                )
                                await _disable_channel(row_id)
                                fail_count.pop(row_id, None)
                            else:
                                next_interval = base_interval + min(
                                    fail_count[row_id] * BACKOFF_STEP,
                                    max_backoff,
                                )
                                logger.exception(
                                    "Slack poller failed for channel %s "
                                    "(attempt %d, next retry in %ds)",
                                    ch["channel_id"],
                                    fail_count[row_id],
                                    next_interval,
                                )
                # Clean up removed channels from tracking
                active_ids = {ch["id"] for ch in channels}
                for rid in list(last_poll):
                    if rid not in active_ids:
                        del last_poll[rid]
                        fail_count.pop(rid, None)

            # Poll active threads regardless of channel polling toggle
            await _poll_active_threads()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Slack poller tick failed")
        await asyncio.sleep(5)  # base tick — individual intervals checked above


async def _disable_channel(row_id: str) -> None:
    """Disable a polling channel after non-retryable failure."""
    db = await get_db()
    await db.execute(
        "UPDATE slack_polling_channels SET enabled = 0 WHERE id = ?",
        (row_id,),
    )
    await db.commit()


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
    logger.info(
        "Polled channel %s: %d new message(s)",
        channel_id, len(messages),
    )
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

        # Skip bot messages and non-content subtypes (joins, leaves, etc.)
        # Allow "file_share" subtype — that's a user sharing files/images.
        if msg.get("bot_id"):
            continue
        subtype = msg.get("subtype")
        if subtype and subtype != "file_share":
            continue

        text = msg.get("text", "")
        has_files = bool(msg.get("files"))
        if not text:
            continue

        # Skip messages posted by agents (feedback loop guard).
        # The bot_id check above is a no-op with xoxc user-session tokens,
        # so this prefix check is the effective guard.
        if text.startswith("[bot:"):
            continue

        mentioned = _parse_agent_mentions(text, agent_map)
        slack_files = msg.get("files", [])
        slack_config = _read_slack_config() if slack_files else None
        for agent_name in mentioned:
            agent_id = agent_map[agent_name]
            # Strip the @AgentName prefix from the prompt
            prompt = _extract_prompt(text, agent_name)
            if not prompt.strip() and not has_files:
                continue

            # Download any attached files into the agent workspace
            attachments: list[str] = []
            if slack_files and slack_config:
                attachments = await _download_slack_files(
                    slack_files, agent_id, slack_config,
                )

            if not prompt.strip():
                prompt = "See attached files."

            try:
                await _dispatch_to_agent(
                    agent_id, prompt, channel_id, ts,
                    attachments=attachments or None,
                )
                logger.info(
                    "Dispatched Slack message to agent %s (%s), "
                    "%d attachment(s)",
                    agent_name, agent_id[:8], len(attachments),
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
# Thread polling
# ---------------------------------------------------------------------------


async def _poll_active_threads() -> None:
    """Poll all active threads for new replies and dispatch to agents."""
    db = await get_db()

    # Expire stale threads based on configurable TTL (default 7 days)
    ttl_days = int(await get_setting("slack_thread_ttl_days", "7"))
    if ttl_days > 0:
        await db.execute(
            "DELETE FROM slack_active_threads "
            "WHERE last_activity_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (f"-{ttl_days} days",),
        )
        await db.commit()

    async with db.execute(
        "SELECT t.id, t.channel_id, t.thread_ts, t.agent_id, t.last_ts, "
        "t.poll_interval, a.name AS agent_name "
        "FROM slack_active_threads t "
        "JOIN agents a ON a.id = t.agent_id AND a.status = 'active'",
    ) as cur:
        threads = await cur.fetchall()

    if not threads:
        return

    client = _build_slack_client()
    if client is None:
        return

    config = _read_slack_config()
    now = asyncio.get_running_loop().time()
    active_ids: set[str] = set()

    for row_id, channel_id, thread_ts, agent_id, last_ts, poll_interval, agent_name in threads:
        active_ids.add(row_id)
        last = _thread_last_poll.get(row_id, 0)
        if now - last < poll_interval:
            continue
        try:
            dispatched = await _poll_thread(
                client, row_id, channel_id, thread_ts,
                agent_id, agent_name, last_ts, config,
            )
            _thread_last_poll[row_id] = now
            new_interval = (
                THREAD_BASE_INTERVAL
                if dispatched
                else min(poll_interval * 2, THREAD_MAX_INTERVAL)
            )
            if new_interval != poll_interval:
                await db.execute(
                    "UPDATE slack_active_threads SET poll_interval = ? "
                    "WHERE id = ?",
                    (new_interval, row_id),
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to poll thread %s/%s for agent %s",
                channel_id, thread_ts, agent_name,
            )

    # Clean up timing state for removed threads
    for rid in list(_thread_last_poll):
        if rid not in active_ids:
            del _thread_last_poll[rid]


async def _poll_thread(
    client: WebClient,
    row_id: str,
    channel_id: str,
    thread_ts: str,
    agent_id: str,
    agent_name: str,
    last_ts: str,
    config: dict | None,
) -> bool:
    """Fetch new replies in a thread and dispatch to the agent.

    Only replies that mention the agent (``AgentName: message``) are
    dispatched — same mention-matching as channel polling.  When a mention
    is found, the full thread history is fetched and prepended as context
    so the agent can produce an informed response.

    Returns True if any messages were dispatched, False otherwise.
    """
    try:
        response = await asyncio.to_thread(
            client.conversations_replies,
            channel=channel_id,
            ts=thread_ts,
            oldest=last_ts,
            limit=50,
        )
    except SlackApiError as e:
        logger.warning(
            "Slack API error polling thread %s/%s: %s",
            channel_id, thread_ts, e,
        )
        return False

    messages = response.get("messages", [])
    if not messages:
        return False

    highest_ts = last_ts
    agent_map = {agent_name.lower(): agent_id}

    # Collect messages that mention the agent
    to_dispatch: list[dict] = []

    for msg in messages:
        ts = msg.get("ts", "")
        if ts <= last_ts:
            continue
        if ts > highest_ts:
            highest_ts = ts

        if msg.get("bot_id"):
            continue
        subtype = msg.get("subtype")
        if subtype and subtype != "file_share":
            continue

        text = msg.get("text", "")
        if not text:
            continue

        # Skip agent-posted messages (feedback loop guard)
        if text.startswith("[bot:"):
            continue

        mentioned = _parse_agent_mentions(text, agent_map)
        if not mentioned:
            continue

        prompt = _extract_prompt(text, agent_name.lower())
        has_files = bool(msg.get("files"))
        if not prompt.strip() and not has_files:
            continue

        to_dispatch.append({"msg": msg, "prompt": prompt, "has_files": has_files})

    # Fetch full thread history once if any mentions were found.
    # Exclude the triggering message(s) — they appear in "Respond to:" instead.
    thread_context = ""
    if to_dispatch:
        # When there's a single dispatch (common case), exclude its ts
        # to avoid duplicating it in context + "Respond to:".
        exclude = to_dispatch[-1]["msg"].get("ts", "") if len(to_dispatch) == 1 else ""
        thread_context = await _fetch_thread_context(
            client, channel_id, thread_ts, exclude_ts=exclude,
        )

    for item in to_dispatch:
        msg = item["msg"]
        prompt = item["prompt"]

        # Download any attached files
        attachments: list[str] = []
        slack_files = msg.get("files", [])
        if slack_files and config:
            attachments = await _download_slack_files(
                slack_files, agent_id, config,
            )

        if not prompt.strip():
            prompt = "See attached files."

        # Prepend thread context so the agent has full conversation history
        if thread_context:
            prompt = (
                f"Here is the Slack thread conversation so far:\n"
                f"---\n{thread_context}\n---\n\n"
                f"Respond to: {prompt}"
            )

        try:
            await _dispatch_to_agent(
                agent_id, prompt, channel_id, thread_ts,
                attachments=attachments or None,
            )
            logger.info(
                "Dispatched thread reply to agent %s, %d attachment(s)",
                agent_name, len(attachments),
            )
        except Exception:
            logger.exception(
                "Failed to dispatch thread reply to agent %s",
                agent_name,
            )
            await post_slack_reply(
                channel_id, thread_ts,
                f"Failed to dispatch message to agent '{agent_name}'.",
            )

    # Update high-water mark and last activity timestamp
    if highest_ts > last_ts:
        db = await get_db()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.execute(
            "UPDATE slack_active_threads SET last_ts = ?, last_activity_at = ? "
            "WHERE id = ?",
            (highest_ts, now, row_id),
        )
        await db.commit()

    return bool(to_dispatch)


_THREAD_CONTEXT_MAX_MESSAGES = 500


async def _fetch_thread_context(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    *,
    exclude_ts: str = "",
) -> str:
    """Fetch full thread history and format as readable context.

    If *exclude_ts* is provided, the message with that timestamp is
    omitted from the output (used to avoid duplicating the triggering
    message that also appears in the "Respond to:" suffix).
    """
    all_messages: list[dict] = []
    cursor: str | None = None

    try:
        while len(all_messages) < _THREAD_CONTEXT_MAX_MESSAGES:
            kwargs: dict = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor

            response = await asyncio.to_thread(
                client.conversations_replies, **kwargs,
            )

            all_messages.extend(response.get("messages", []))

            if not response.get("has_more"):
                break
            cursor = (
                response.get("response_metadata", {}).get("next_cursor")
            )
            if not cursor:
                break
    except SlackApiError:
        logger.exception("Failed to fetch thread context %s/%s", channel_id, thread_ts)
        return ""

    if not all_messages:
        return ""

    lines: list[str] = []
    for msg in all_messages:
        if exclude_ts and msg.get("ts") == exclude_ts:
            continue
        user = msg.get("user", "bot")
        text = msg.get("text", "")
        if not text:
            continue
        lines.append(f"{user}: {text}")

    return "\n".join(lines)


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
    """Find agent mentions using the ``AgentName: message`` format.

    Returns list of lowercase agent names that were mentioned.
    Matches longest names first to handle overlapping prefixes.
    """
    lower_text = text.lower()
    matched: list[str] = []
    for name in sorted(agent_map, key=len, reverse=True):
        pattern = f"{name}:"
        if pattern in lower_text:
            matched.append(name)
            lower_text = lower_text.replace(pattern, "", 1)
    return matched


def _extract_prompt(text: str, agent_name: str) -> str:
    """Remove the ``AgentName:`` mention from the text to get the prompt."""
    pattern = re.compile(re.escape(f"{agent_name}:"), re.IGNORECASE)
    return pattern.sub("", text, count=1).strip()


# ---------------------------------------------------------------------------
# Slack file downloads
# ---------------------------------------------------------------------------

UPLOAD_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


async def _download_slack_files(
    files: list[dict], agent_id: str, config: dict,
) -> list[str]:
    """Download Slack file attachments into the agent workspace.

    Returns a list of relative paths (relative to host_dir) suitable for
    passing as ``attachments`` to the message queue.
    """
    db = await get_db()
    async with db.execute(
        "SELECT host_dir FROM agents WHERE id = ? AND status = 'active'",
        (agent_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        logger.warning("Cannot download Slack files: agent %s not found", agent_id)
        return []

    host_dir = Path(row[0]).resolve()
    upload_id = str(uuid.uuid4())[:8]
    upload_dir = host_dir / "uploads" / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    token = config["xoxc_token"]
    cookie = f"d={config['d_cookie']}"
    headers = {"Authorization": f"Bearer {token}", "Cookie": cookie}

    downloaded: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for f in files:
            url = f.get("url_private_download") or f.get("url_private")
            if not url:
                continue
            size = f.get("size", 0)
            if size > UPLOAD_MAX_FILE_SIZE:
                logger.warning(
                    "Skipping Slack file %s: too large (%d bytes)",
                    f.get("name", "?"), size,
                )
                continue

            name = f.get("name", "attachment")
            safe_name = Path(name).name
            if not safe_name or safe_name in (".", ".."):
                safe_name = "attachment"

            try:
                resp = await client.get(url, headers=headers, follow_redirects=True)
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.exception("Failed to download Slack file %s", safe_name)
                continue

            dest = upload_dir / safe_name
            # Avoid clobbering if multiple files share the same name
            if dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                counter = 1
                while dest.exists():
                    dest = upload_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            dest.write_bytes(resp.content)
            rel_path = str(dest.relative_to(host_dir))
            downloaded.append(rel_path)
            logger.info("Downloaded Slack file %s → %s", safe_name, rel_path)

    # Clean up empty upload dir if nothing was downloaded
    if not downloaded:
        try:
            upload_dir.rmdir()
        except OSError:
            pass

    return downloaded


# ---------------------------------------------------------------------------
# Dispatch to agent
# ---------------------------------------------------------------------------


async def _dispatch_to_agent(
    agent_id: str,
    content: str,
    channel_id: str,
    thread_ts: str,
    *,
    attachments: list[str] | None = None,
) -> None:
    """Route a Slack message through the normal message pipeline."""
    from orchestrator.ipc import _inflight_source, store_slack_message
    from orchestrator.routes import ensure_worker_headless

    await ensure_worker_headless(agent_id)

    message_id = str(uuid.uuid4())

    # Track source metadata so the completion hook can post the reply
    _inflight_source[message_id] = {
        "source": "slack",
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }

    await store_slack_message(
        agent_id, message_id, content, channel_id, thread_ts,
        attachments=attachments,
    )


# ---------------------------------------------------------------------------
# Slack reply posting
# ---------------------------------------------------------------------------


async def post_slack_reply(
    channel_id: str, thread_ts: str, text: str,
    *, agent_name: str = "",
) -> str | None:
    """Post a message as a thread reply in Slack.

    Called from ipc._process_event on completion and from the poller
    for error replies. This is an orchestrator-internal function, not
    an MCP tool.

    Returns the ``ts`` of the posted message, or ``None`` on failure.
    """
    client = _build_slack_client()
    if client is None:
        logger.warning("Cannot post Slack reply: no credentials configured")
        return None

    # Prefix agent responses so pollers can skip them (feedback loop guard)
    if agent_name:
        text = f"[bot:{agent_name}] {text}"

    # Respect Slack's message length limit
    if len(text) > SLACK_MESSAGE_CHAR_LIMIT:
        text = text[: SLACK_MESSAGE_CHAR_LIMIT - 30] + "\n\n[Response truncated]"

    try:
        resp = await asyncio.to_thread(
            client.chat_postMessage,
            channel=channel_id,
            thread_ts=thread_ts,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )
        return resp.get("ts")
    except SlackApiError:
        logger.exception(
            "Failed to post Slack reply to channel=%s thread=%s",
            channel_id, thread_ts,
        )
        return None


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
