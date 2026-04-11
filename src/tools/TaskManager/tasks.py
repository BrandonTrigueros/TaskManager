#!/usr/bin/env python3
"""Tasks — CRUD operations for TaskManager tasks.

Usage (from project root):
    python3 -m src.tools.TaskManager.tasks add --title "..." [--project X] [--priority N] [--hours N] [--due DATE]
    python3 -m src.tools.TaskManager.tasks list [--status pending] [--project X] [--limit N]
    python3 -m src.tools.TaskManager.tasks complete --id N
    python3 -m src.tools.TaskManager.tasks update --id N [--project X] [--priority N] [--status X]
    python3 -m src.tools.TaskManager.tasks overdue

Or via CLI:
    python3 scripts/cli.py add --title "..."
"""

import argparse
import json
import os
import sys

# Ensure project root is in sys.path for `from src.tools.common import ...`
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import psycopg2.extras

from src.tools.common import get_conn, jprint


def add_task(args):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tasks (title, description, project_tag, priority, estimated_hours,
                                  source_origin, due_date)
               VALUES (%s, %s, %s, %s, %s, %s::source_origin, %s::timestamptz)
               RETURNING id""",
            (args.title, args.description, args.project, args.priority,
             args.hours, args.source or "cli", args.due),
        )
        task_id = cur.fetchone()[0]
        conn.commit()
        jprint({"ok": True, "id": task_id, "title": args.title,
                "project": args.project, "priority": args.priority})


def list_tasks(args):
    clauses, params = [], []
    if args.status:
        clauses.append("status = %s::task_status")
        params.append(args.status)
    if args.project:
        clauses.append("project_tag = %s")
        params.append(args.project)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = args.limit or 20
    params.append(limit)

    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""SELECT id, title, project_tag, priority, estimated_hours,
                       status, due_date, created_at
                FROM tasks {where}
                ORDER BY priority DESC NULLS LAST, due_date ASC NULLS LAST
                LIMIT %s""",
            params,
        )
        jprint(cur.fetchall())


def complete_task(args):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET status = 'completed' WHERE id = %s AND status != 'completed' RETURNING id",
            (args.id,),
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            jprint({"ok": True, "id": row[0], "status": "completed"})
        else:
            jprint({"ok": False, "error": f"Task {args.id} not found or already completed"})


def update_task(args):
    sets, params = [], []
    if args.project:
        sets.append("project_tag = %s")
        params.append(args.project)
    if args.priority:
        sets.append("priority = %s")
        params.append(args.priority)
    if args.status:
        sets.append("status = %s::task_status")
        params.append(args.status)
    if not sets:
        jprint({"ok": False, "error": "Nothing to update"})
        return

    params.append(args.id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = %s RETURNING id",
            params,
        )
        row = cur.fetchone()
        conn.commit()
        jprint({"ok": bool(row), "id": args.id})


def overdue_tasks(_args):
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT id, title, project_tag, priority, due_date
               FROM tasks
               WHERE status = 'pending' AND due_date < NOW()
               ORDER BY due_date ASC"""
        )
        jprint(cur.fetchall())


def main():
    parser = argparse.ArgumentParser(description="Tasks — TaskManager CRUD")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--project")
    p.add_argument("--priority", type=int)
    p.add_argument("--hours", type=float)
    p.add_argument("--due")
    p.add_argument("--source", default="cli")

    p = sub.add_parser("list")
    p.add_argument("--status", default="pending")
    p.add_argument("--project")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("complete")
    p.add_argument("--id", type=int, required=True)

    p = sub.add_parser("update")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--project")
    p.add_argument("--priority", type=int)
    p.add_argument("--status")

    sub.add_parser("overdue")

    args = parser.parse_args()

    commands = {
        "add": add_task,
        "list": list_tasks,
        "complete": complete_task,
        "update": update_task,
        "overdue": overdue_tasks,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
