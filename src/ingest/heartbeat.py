#!/usr/bin/env python3
"""BT-Core Heartbeat — 60-minute semantic coherence cycle (REQ-T12).

Actions:
  1. Backfill embeddings for tasks with embedding=NULL
  2. Check for due reminders (due_date < NOW() + 24h)
  3. Rebuild task_links graph
  4. Sync Obsidian vault export

Designed to be called by OpenClaw Gateway heartbeat or cron.
Output is JSON for composability with OpenClaw.

Usage:
    python3 scripts/heartbeat.py
    python3 scripts/heartbeat.py --action backfill    # only backfill
    python3 scripts/heartbeat.py --action reminders   # only reminders
    python3 scripts/heartbeat.py --action all         # full cycle (default)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common import get_conn
from src.knowledge.embeddings import generate_embedding


def backfill_embeddings(conn, limit: int = 20) -> int:
    """Generate and store embeddings for tasks missing them.

    Returns number of tasks backfilled.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, COALESCE(description, '')
               FROM tasks
               WHERE embedding IS NULL
                 AND status != 'cancelled'
               LIMIT %s""",
            (limit,),
        )
        orphans = cur.fetchall()

    count = 0
    for task_id, title, description in orphans:
        text = f"{title} — {description}" if description else title
        emb = generate_embedding(text)
        if emb and len(emb) == 768:
            vector_str = "[" + ",".join(str(v) for v in emb) + "]"
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE tasks
                       SET embedding = %s::vector,
                           embedding_model = 'nomic-embed-text'
                       WHERE id = %s""",
                    (vector_str, task_id),
                )
            count += 1

    conn.commit()
    return count


def check_due_reminders(conn) -> list[dict]:
    """Find tasks due in the next 24 hours.

    Returns list of dicts with id, title, project, priority, due_date.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, title, project_tag, priority, due_date
               FROM tasks
               WHERE status = 'pending'
                 AND due_date IS NOT NULL
                 AND due_date <= NOW() + INTERVAL '24 hours'
                 AND due_date > NOW() - INTERVAL '1 hour'
               ORDER BY due_date ASC"""
        )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "title": r[1],
            "project": r[2],
            "priority": r[3],
            "due_date": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def rebuild_task_graph(conn) -> int:
    """Rebuild task_links for tasks updated in the last 2 hours.

    Returns number of links created/updated.
    """
    with conn.cursor() as cur:
        # Clear stale links for recently modified tasks
        cur.execute(
            """DELETE FROM task_links
               WHERE task_id IN (
                   SELECT id FROM tasks
                   WHERE updated_at > NOW() - INTERVAL '2 hours'
               )
               OR linked_task_id IN (
                   SELECT id FROM tasks
                   WHERE updated_at > NOW() - INTERVAL '2 hours'
               )"""
        )
        cleared = cur.rowcount

        # Get all tasks with embeddings
        cur.execute(
            "SELECT id, embedding FROM tasks WHERE embedding IS NOT NULL"
        )
        tasks = [(r[0], r[1]) for r in cur.fetchall()]

        # Rebuild: for each task, find top-3 similar by cosine distance
        link_count = 0
        for task_id, emb in tasks:
            # emb from psycopg2 is a string already in pgvector format: [0.1, -0.2, ...]
            cur.execute(
                """INSERT INTO task_links (task_id, linked_task_id, similarity)
                   SELECT %s, id, 1 - (embedding <=> %s::vector)
                   FROM tasks
                   WHERE id != %s
                     AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector
                   LIMIT 3
                   ON CONFLICT (task_id, linked_task_id)
                   DO UPDATE SET similarity = EXCLUDED.similarity""",
                (task_id, emb, task_id, emb),
            )
            link_count += cur.rowcount

        conn.commit()

    return link_count


def run_heartbeat(action: str = "all") -> dict:
    """Execute the heartbeat cycle.

    Returns a dict with results for OpenClaw to parse and dispatch.
    """
    conn = get_conn()
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
    }

    try:
        if action in ("backfill", "all"):
            n = backfill_embeddings(conn)
            result["backfill"] = n

        if action in ("reminders", "all"):
            due = check_due_reminders(conn)
            result["due_reminders"] = due
            result["due_count"] = len(due)

        if action in ("graph", "all"):
            n = rebuild_task_graph(conn)
            result["graph_links"] = n

        if action in ("export", "all"):
            import io, contextlib
            from src.shared.export_md import export_master_view
            output_dir = os.environ.get(
                "TASKMANAGER_EXPORT_DIR",
                os.path.expanduser("~/taskmanager_export"),
            )
            # Suppress export's stdout (it prints JSON), capture to parse
            f = io.StringIO()
            with contextlib.redirect_stdout(f):
                export_master_view(output_dir)
            export_result = json.loads(f.getvalue())
            result["obsidian_export"] = output_dir
            result["obsidian_stats"] = export_result.get("stats", {})
    finally:
        conn.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="BT-Core Heartbeat (60min cycle)")
    parser.add_argument(
        "--action",
        choices=["all", "backfill", "reminders", "graph", "export"],
        default="all",
    )
    args = parser.parse_args()

    result = run_heartbeat(args.action)

    # Print reminders in human-readable format to stderr (agent reads this)
    reminders = result.get("due_reminders", [])
    if reminders:
        print("\n⚠️  Tareas por vencer en las próximas 24 horas:", file=sys.stderr)
        for t in reminders:
            priority_emoji = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}
            p = priority_emoji.get(t["priority"], "⬜")
            print(f"  {p} #{t['id']} — {t['title']} [{t['project']}]", file=sys.stderr)

    # Print JSON result for OpenClaw (stdout = machine-readable)
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
