#!/usr/bin/env python3
"""Markdown Export — Export tasks to Markdown for Obsidian.

Usage (from project root):
    python3 -m src.tools.SharedUtilities.export_md --output ~/ObsidianVault/TaskManager/

Or via CLI:
    python3 scripts/cli.py export [--output /path/to/dir]
"""

import argparse
import json
import os
import sys
from datetime import datetime

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import psycopg2.extras

from src.tools.common import get_conn


PRIORITY_EMOJI = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}


def export_master_view(output_dir: str):
    """Export tasks grouped by project to markdown files."""
    os.makedirs(output_dir, exist_ok=True)

    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT project_tag, id, title, priority, estimated_hours, status, due_date
               FROM tasks WHERE status != 'cancelled'
               ORDER BY project_tag, priority DESC NULLS LAST, due_date ASC NULLS LAST"""
        )
        tasks = cur.fetchall()

    # Group by project
    projects = {}
    for t in tasks:
        tag = t["project_tag"] or "Sin Proyecto"
        projects.setdefault(tag, []).append(t)

    # ─── MASTER_LOG.md ────────────────────────────────────
    lines = [f"# 📋 Tareas — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"]

    for proj, proj_tasks in sorted(projects.items()):
        lines.append(f"\n## [[{proj}]]\n")
        for t in proj_tasks:
            check = "x" if t["status"] == "completed" else " "
            p = PRIORITY_EMOJI.get(t["priority"], "⬜")
            hours = f" ~{t['estimated_hours']}h" if t["estimated_hours"] else ""
            due = f" 📅 {t['due_date'].strftime('%d/%m')}" if t["due_date"] else ""
            lines.append(f"- [{check}] {p} [[TASK_{t['id']}|#{t['id']}]] {t['title']}{hours}{due}")

    with open(os.path.join(output_dir, "MASTER_LOG.md"), "w") as f:
        f.write("\n".join(lines))

    # ─── Per-project files ────────────────────────────────
    for proj, proj_tasks in projects.items():
        safe_name = proj.upper().replace(" ", "_")
        proj_lines = [
            f"# {proj}\n",
            f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n",
        ]
        pending = [t for t in proj_tasks if t["status"] != "completed"]
        done = [t for t in proj_tasks if t["status"] == "completed"]

        if pending:
            proj_lines.append("\n## Pendientes\n")
            for t in pending:
                p = PRIORITY_EMOJI.get(t["priority"], "⬜")
                hours = f" ~{t['estimated_hours']}h" if t["estimated_hours"] else ""
                due = f" 📅 {t['due_date'].strftime('%d/%m')}" if t["due_date"] else ""
                proj_lines.append(f"- [ ] {p} [[TASK_{t['id']}|#{t['id']}]] {t['title']}{hours}{due}")

        if done:
            proj_lines.append("\n## Completadas\n")
            for t in done:
                proj_lines.append(f"- [x] [[TASK_{t['id']}|#{t['id']}]] {t['title']}")

        with open(os.path.join(output_dir, f"{safe_name}.md"), "w") as f:
            f.write("\n".join(proj_lines))

    # ─── Per-task files ───────────────────────────────────
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT id, title, description, project_tag, priority,
                      estimated_hours, status, source_origin, due_date,
                      created_at, updated_at
               FROM tasks WHERE status != 'cancelled'"""
        )
        all_tasks = cur.fetchall()

    tasks_dir = os.path.join(output_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    for t in all_tasks:
        proj = t["project_tag"] or "Sin Proyecto"
        task_lines = [
            "---",
            f"id: {t['id']}",
            f"title: \"{t['title']}\"",
            f"project: \"{proj}\"",
            f"priority: {t['priority'] or 'null'}",
            f"estimated_hours: {t['estimated_hours'] or 'null'}",
            f"status: {t['status']}",
            f"source: {t['source_origin'] or 'unknown'}",
            f"due_date: {t['due_date'].isoformat() if t['due_date'] else 'null'}",
            f"created: {t['created_at'].isoformat() if t['created_at'] else 'null'}",
            f"updated: {t['updated_at'].isoformat() if t['updated_at'] else 'null'}",
            "---",
            "",
            f"# {t['title']}",
            "",
            f"**Proyecto:** [[{proj}]]  ",
            f"**Prioridad:** {PRIORITY_EMOJI.get(t['priority'], '⬜')} {t['priority'] or '?'}/5  ",
            f"**Horas estimadas:** {t['estimated_hours'] or '?'}  ",
            f"**Estado:** {t['status']}  ",
        ]
        if t["due_date"]:
            task_lines.append(f"**Fecha límite:** {t['due_date'].strftime('%d/%m/%Y')}")
        if t["description"]:
            task_lines.extend(["", "## Descripción", "", t["description"]])

        with open(os.path.join(tasks_dir, f"TASK_{t['id']}.md"), "w") as f:
            f.write("\n".join(task_lines))

    exported_files = ["MASTER_LOG.md"] + [f"{p.upper().replace(' ', '_')}.md" for p in projects]
    print(json.dumps({
        "ok": True,
        "output_dir": output_dir,
        "files": exported_files,
        "task_files": len(all_tasks),
    }))


def main():
    parser = argparse.ArgumentParser(description="Markdown Export for Obsidian")
    parser.add_argument("--output", default=os.path.expanduser("~/Hartbeat/exports/tasks"))
    args = parser.parse_args()
    export_master_view(args.output)


if __name__ == "__main__":
    main()
