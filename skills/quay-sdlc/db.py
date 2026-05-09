#!/usr/bin/env python3
"""Shared SQLite DB for quay-sdlc multi-agent Jira pipeline."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = "/workspace/shared/quay-sdlc/sdlc.db"

PRIORITY_ORDER = {"Blocker": 0, "Critical": 1, "Highest": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}

STALE_MINUTES = 30
STALE_RECOVERY = {"triaging": "new", "assigned": "triaged"}

VALID_TRANSITIONS = {
    "new": {"triaging"},
    "triaging": {"triaged", "invalid"},
    "triaged": {"assigned"},
    "assigned": {"done", "failed"},
    "invalid": set(),
    "done": set(),
    "failed": {"triaged"},
}


def get_db() -> sqlite3.Connection:
    shared_dir = os.path.dirname(DB_PATH)
    if not os.path.isdir(shared_dir):
        print(f"ERROR: {shared_dir} does not exist. Container restart required after assigning quay-sdlc skill.", file=sys.stderr)
        sys.exit(1)
    if not os.path.ismount(shared_dir):
        print(f"WARNING: {shared_dir} is not a mount (multi-agent sync may not work).", file=sys.stderr)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cmd_init(args: argparse.Namespace) -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tickets (
            key         TEXT PRIMARY KEY,
            summary     TEXT NOT NULL,
            priority    TEXT NOT NULL DEFAULT 'Medium',
            issue_type  TEXT NOT NULL DEFAULT 'Bug',
            url         TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'new',
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ticket_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_key  TEXT NOT NULL REFERENCES tickets(key),
            from_status TEXT,
            to_status   TEXT NOT NULL,
            notes       TEXT NOT NULL DEFAULT '',
            timestamp   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_log_key ON ticket_log(ticket_key);
    """)
    conn.commit()
    conn.close()
    print("Database initialized.")


def cmd_add(args: argparse.Namespace) -> None:
    conn = get_db()
    ts = now_iso()
    try:
        conn.execute(
            "INSERT INTO tickets (key, summary, priority, issue_type, url, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'new', ?, ?)",
            (args.key, args.summary, args.priority, args.issue_type, args.url, ts, ts),
        )
        conn.execute(
            "INSERT INTO ticket_log (ticket_key, from_status, to_status, notes, timestamp) "
            "VALUES (?, NULL, 'new', 'Discovered by scanner', ?)",
            (args.key, ts),
        )
        conn.commit()
        print(f"Added {args.key}")
    except sqlite3.IntegrityError:
        print(f"{args.key} already exists, skipping.")
    conn.close()


def cmd_update(args: argparse.Namespace) -> None:
    conn = get_db()
    target = args.status
    ts = now_iso()
    notes = args.notes or ""

    valid_sources = [k for k, vs in VALID_TRANSITIONS.items() if target in vs]
    if not valid_sources:
        print(f"No valid source status for target '{target}'.", file=sys.stderr)
        sys.exit(1)

    row = conn.execute("SELECT status FROM tickets WHERE key = ?", (args.key,)).fetchone()
    if not row:
        print(f"Ticket {args.key} not found.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    from_status = row["status"]
    if from_status not in valid_sources:
        print(f"Cannot transition {args.key}: current status is '{from_status}', expected one of {valid_sources}.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    cursor = conn.execute(
        "UPDATE tickets SET status = ?, notes = ?, updated_at = ? "
        "WHERE key = ? AND status = ?",
        (target, notes, ts, args.key, from_status),
    )
    if cursor.rowcount == 0:
        print(f"Race condition: {args.key} was claimed by another agent.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    conn.execute(
        "INSERT INTO ticket_log (ticket_key, from_status, to_status, notes, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (args.key, from_status, target, notes, ts),
    )
    conn.commit()
    conn.close()
    print(f"{args.key}: {from_status} -> {target}")


def _recover_stale(conn: sqlite3.Connection, target_status: str) -> int:
    """Reset tickets stuck in a transient status back to their prior state."""
    stale_from = [k for k, v in STALE_RECOVERY.items() if v == target_status]
    if not stale_from:
        return 0
    ts = now_iso()
    placeholders = ",".join("?" * len(stale_from))
    stale_rows = conn.execute(
        f"SELECT key, status FROM tickets "
        f"WHERE status IN ({placeholders}) "
        f"AND REPLACE(REPLACE(updated_at, 'T', ' '), 'Z', '') < datetime('now', '-{STALE_MINUTES} minutes')",
        stale_from,
    ).fetchall()
    if not stale_rows:
        return 0
    recovered = 0
    for row in stale_rows:
        cursor = conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE key = ? AND status = ?",
            (target_status, ts, row["key"], row["status"]),
        )
        if cursor.rowcount == 0:
            continue
        conn.execute(
            "INSERT INTO ticket_log (ticket_key, from_status, to_status, notes, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (row["key"], row["status"], target_status, f"Auto-recovered after {STALE_MINUTES}m stale", ts),
        )
        recovered += 1
    if recovered:
        conn.commit()
        print(f"Recovered {recovered} stale ticket(s) to '{target_status}'.", file=sys.stderr)
    return recovered


def cmd_list(args: argparse.Namespace) -> None:
    conn = get_db()

    if args.status != "all":
        _recover_stale(conn, args.status)

    if args.status == "all":
        rows = conn.execute("SELECT * FROM tickets ORDER BY created_at ASC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tickets WHERE status = ? ORDER BY created_at ASC",
            (args.status,),
        ).fetchall()
    conn.close()

    if not rows:
        print(f"No tickets with status '{args.status}'.")
        return

    results = [dict(r) for r in rows]
    if args.sort == "priority":
        results.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 99))

    if args.limit:
        results = results[: args.limit]

    for r in results:
        print(json.dumps(r))


def cmd_get(args: argparse.Namespace) -> None:
    conn = get_db()
    row = conn.execute("SELECT * FROM tickets WHERE key = ?", (args.key,)).fetchone()
    conn.close()
    if not row:
        print(f"Ticket {args.key} not found.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(dict(row), indent=2))


def cmd_log(args: argparse.Namespace) -> None:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ticket_log WHERE ticket_key = ? ORDER BY timestamp ASC",
        (args.key,),
    ).fetchall()
    conn.close()
    if not rows:
        print(f"No log entries for {args.key}.")
        return
    for r in rows:
        print(json.dumps(dict(r)))


def main() -> None:
    parser = argparse.ArgumentParser(description="quay-sdlc ticket database")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create tables (idempotent)")

    p_add = sub.add_parser("add", help="Add a new ticket (duplicates silently skipped)")
    p_add.add_argument("key", help="Jira ticket key (e.g. PROJQUAY-1234)")
    p_add.add_argument("--summary", required=True)
    p_add.add_argument("--priority", default="Medium")
    p_add.add_argument("--issue-type", default="Bug")
    p_add.add_argument("--url", default="")

    p_update = sub.add_parser("update", help="Atomic status transition (fails if already claimed)")
    p_update.add_argument("key", help="Jira ticket key")
    p_update.add_argument("status", choices=["triaging", "triaged", "invalid", "assigned", "done", "failed"])
    p_update.add_argument("--notes", default="")

    p_list = sub.add_parser("list", help="List tickets by status")
    p_list.add_argument("--status", default="new")
    p_list.add_argument("--limit", type=int, default=0, help="Max tickets to return (0 = all)")
    p_list.add_argument("--sort", choices=["created", "priority"], default="created")

    p_get = sub.add_parser("get", help="Get a single ticket")
    p_get.add_argument("key")

    p_log = sub.add_parser("log", help="Show audit log for a ticket")
    p_log.add_argument("key")

    args = parser.parse_args()
    {
        "init": cmd_init,
        "add": cmd_add,
        "update": cmd_update,
        "list": cmd_list,
        "get": cmd_get,
        "log": cmd_log,
    }[args.command](args)


if __name__ == "__main__":
    main()
