#!/usr/bin/env python3
"""Markdown Export — Zettelkasten vault for Obsidian (REQ-T8/T9).

Generates a bidirectional-linked knowledge vault:
  1. MASTER_LOG.md        — Dashboard with stats + grouped task list
  2. {PROJECT}.md         — Per-project file with pending/completed
  3. tasks/TASK_{id}.md   — Individual Zettelkasten note with full frontmatter YAML,
                             [[backlinks]] to project and linked tasks, embedding status

Usage (from project root):
    python3 -m src.shared.export_md --output ~/ObsidianVault/TaskManager/

Or via CLI:
    python3 -m src.ingest.cli export [--output /path/to/dir]
"""

import argparse
import json
import os
import sys
from datetime import datetime

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import psycopg2.extras

from src.common import get_conn

PRIORITY_EMOJI = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}
PRIORITY_LABEL = {1: "Low", 2: "Normal", 3: "Important", 4: "Urgent", 5: "Critical"}


def export_master_view(output_dir: str):
    """Export full task vault to Obsidian-compatible Markdown."""
    os.makedirs(output_dir, exist_ok=True)

    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # ── All non-cancelled tasks ──────────────────────────
        cur.execute(
            """SELECT id, title, description, project_tag, priority,
                      estimated_hours, actual_hours, status, source_origin,
                      due_date, location_label, created_at, updated_at,
                      CASE WHEN embedding IS NOT NULL THEN true ELSE false END AS has_embedding
               FROM tasks WHERE status != 'cancelled'
               ORDER BY project_tag NULLS LAST, priority DESC NULLS LAST,
                        due_date ASC NULLS LAST"""
        )
        tasks = cur.fetchall()

        # ── Linked tasks ─────────────────────────────────────
        cur.execute(
            """SELECT task_id, linked_task_id, similarity
               FROM task_links ORDER BY task_id"""
        )
        links = cur.fetchall()

    # Build link index: task_id → [(linked_id, similarity), ...]
    link_index: dict[int, list[dict]] = {}
    for row in links:
        link_index.setdefault(row["task_id"], []).append({
            "id": row["linked_task_id"],
            "sim": float(row["similarity"]),
        })

    # ── Stats ────────────────────────────────────────────────
    total = len(tasks)
    pending_count = sum(1 for t in tasks if t["status"] == "pending")
    in_progress_count = sum(1 for t in tasks if t["status"] == "in_progress")
    completed_count = sum(1 for t in tasks if t["status"] == "completed")
    total_estimated = round(float(sum(t["estimated_hours"] or 0 for t in tasks if t["status"] != "completed")), 1)
    total_actual = round(float(sum(t["actual_hours"] or 0 for t in tasks if t["status"] == "completed")), 1)
    embedded_count = sum(1 for t in tasks if t["has_embedding"])
    overdue_count = sum(
        1 for t in tasks
        if t["status"] in ("pending", "in_progress")
        and t["due_date"] and t["due_date"] < datetime.now().astimezone()
    )

    # Group by project
    projects: dict[str, list] = {}
    for t in tasks:
        tag = t["project_tag"] or "Sin Proyecto"
        projects.setdefault(tag, []).append(t)

    # ═════════════════════════════════════════════════════════
    #  MASTER_LOG.md — Dashboard
    # ═════════════════════════════════════════════════════════
    now = datetime.now()
    master = [
        f"# 📋 TaskManager — Master Log",
        f"",
        f"> Última sincronización: {now.strftime('%d/%m/%Y %H:%M')}",
        f"> Heartbeat: 60 min | Embeddings: {embedded_count}/{total} tareas indexadas",
        f"",
        f"## 📊 Dashboard",
        f"",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Total tareas activas | {total} |",
        f"| Pendientes | {pending_count} |",
        f"| En progreso | {in_progress_count} |",
        f"| Completadas | {completed_count} |",
        f"| ⚠️ Vencidas | {overdue_count} |",
        f"| ⏱️ Horas estimadas (pend.) | {total_estimated:.1f}h |",
        f"| ✅ Horas reales (compl.) | {total_actual:.1f}h |",
        f"| 🧬 Indexación vectorial | {embedded_count}/{total} ({100*embedded_count//max(total,1)}%) |",
        f"",
        f"---",
    ]

    for proj, proj_tasks in sorted(projects.items()):
        safe_proj = proj.replace(" ", "_")
        proj_pending = [t for t in proj_tasks if t["status"] != "completed"]
        proj_done = [t for t in proj_tasks if t["status"] == "completed"]
        master.append(f"## [[{safe_proj}|{proj}]] ({len(proj_pending)} pend., {len(proj_done)} compl.)")
        master.append("")

        if proj_pending:
            for t in proj_pending:
                p_emoji = PRIORITY_EMOJI.get(t["priority"], "⬜")
                hours = f" ~{t['estimated_hours']}h" if t["estimated_hours"] else ""
                due = f" 📅 {t['due_date'].strftime('%d/%m')}" if t["due_date"] else ""
                loc = f" 📍{t['location_label']}" if t.get("location_label") else ""
                status_icon = "🔄" if t["status"] == "in_progress" else " "
                master.append(
                    f"- [{status_icon}] {p_emoji} [[tasks/TASK_{t['id']}|#{t['id']}]] "
                    f"{t['title']}{hours}{due}{loc}"
                )
            master.append("")

        if proj_done:
            master.append("#### ✅ Completadas\n")
            for t in proj_done:
                actual = f" — {t['actual_hours']}h reales" if t["actual_hours"] else ""
                master.append(f"- [x] [[tasks/TASK_{t['id']}|#{t['id']}]] {t['title']}{actual}")
            master.append("")

    with open(os.path.join(output_dir, "MASTER_LOG.md"), "w") as f:
        f.write("\n".join(master))

    # ═════════════════════════════════════════════════════════
    #  Per-project files
    # ═════════════════════════════════════════════════════════
    for proj, proj_tasks in projects.items():
        safe_name = proj.replace(" ", "_").upper()
        pending = [t for t in proj_tasks if t["status"] != "completed"]
        done = [t for t in proj_tasks if t["status"] == "completed"]

        proj_lines = [
            f"# {proj}",
            f"",
            f"> Sincronizado: {now.strftime('%d/%m/%Y %H:%M')}",
            f"> Pendientes: {len(pending)} | Completadas: {len(done)}",
            f"",
            f"↩ [[MASTER_LOG|← Dashboard]]",
            f"",
        ]

        if pending:
            proj_lines.append("## Pendientes\n")
            for t in pending:
                p_emoji = PRIORITY_EMOJI.get(t["priority"], "⬜")
                hours = f" ~{t['estimated_hours']}h" if t["estimated_hours"] else ""
                due = f" 📅 {t['due_date'].strftime('%d/%m')}" if t["due_date"] else ""
                status_icon = "🔄" if t["status"] == "in_progress" else " "
                proj_lines.append(
                    f"- [{status_icon}] {p_emoji} [[tasks/TASK_{t['id']}|#{t['id']}]] "
                    f"{t['title']}{hours}{due}"
                )
            proj_lines.append("")

        if done:
            proj_lines.append("## Completadas\n")
            for t in done:
                actual = f" — {t['actual_hours']}h reales" if t["actual_hours"] else ""
                proj_lines.append(
                    f"- [x] [[tasks/TASK_{t['id']}|#{t['id']}]] {t['title']}{actual}"
                )
            proj_lines.append("")

        with open(os.path.join(output_dir, f"{safe_name}.md"), "w") as f:
            f.write("\n".join(proj_lines))

    # ═════════════════════════════════════════════════════════
    #  Per-task Zettelkasten notes (tasks/TASK_{id}.md)
    # ═════════════════════════════════════════════════════════
    tasks_dir = os.path.join(output_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    for t in tasks:
        tid = t["id"]
        proj = t["project_tag"] or "Sin Proyecto"
        safe_proj = proj.replace(" ", "_")
        linked = link_index.get(tid, [])

        # Build [[backlinks]]
        backlinks = " ".join(f"[[TASK_{l['id']}]]" for l in linked)
        project_link = f"[[../{safe_proj}|{proj}]]"

        frontmatter = [
            "---",
            f"id: {tid}",
            f"title: \"{t['title']}\"",
            f"project: \"{proj}\"",
            f"priority: {t['priority'] or 'null'}",
            f"priority_label: \"{PRIORITY_LABEL.get(t['priority'], 'Unknown')}\"",
            f"estimated_hours: {t['estimated_hours'] or 'null'}",
            f"actual_hours: {t['actual_hours'] or 'null'}",
            f"status: {t['status']}",
            f"source: \"{t['source_origin'] or 'unknown'}\"",
            f"due_date: {t['due_date'].isoformat() if t['due_date'] else 'null'}",
            f"location: \"{t['location_label'] or ''}\"",
            f"has_embedding: {str(t['has_embedding']).lower()}",
            f"linked_tasks: [{', '.join(str(l['id']) for l in linked)}]",
            f"created: {t['created_at'].isoformat() if t['created_at'] else 'null'}",
            f"updated: {t['updated_at'].isoformat() if t['updated_at'] else 'null'}",
            "---",
        ]

        body = [
            f"# {t['title']}",
            "",
            f"**Proyecto:** {project_link}  ",
            f"**Prioridad:** {PRIORITY_EMOJI.get(t['priority'], '⬜')} {t['priority'] or '?'}/5 — {PRIORITY_LABEL.get(t['priority'], 'Unknown')}  ",
            f"**Estado:** {t['status']}  ",
            f"**Origen:** {t['source_origin'] or 'unknown'}  ",
        ]

        if t["estimated_hours"]:
            body.append(f"**Horas estimadas:** {t['estimated_hours']}h  ")
        if t["actual_hours"]:
            delta = ""
            if t["estimated_hours"] and t["estimated_hours"] > 0:
                diff = t["actual_hours"] - t["estimated_hours"]
                sign = "+" if diff > 0 else ""
                delta = f" ({sign}{diff:.1f}h vs estimado)"
            body.append(f"**Horas reales:** {t['actual_hours']}h{delta}  ")
        if t["due_date"]:
            is_overdue = t["due_date"] < datetime.now().astimezone() and t["status"] != "completed"
            overdue_tag = " ⚠️ VENCIDA" if is_overdue else ""
            body.append(f"**Fecha límite:** {t['due_date'].strftime('%d/%m/%Y %H:%M')}{overdue_tag}  ")
        if t["location_label"]:
            body.append(f"**Ubicación:** 📍 {t['location_label']}  ")

        body.extend([
            f"**Embedding:** {'🧬 Indexado (768d)' if t['has_embedding'] else '❌ Sin indexar'}  ",
            f"**Creado:** {t['created_at'].strftime('%d/%m/%Y %H:%M') if t['created_at'] else '?'}  ",
            f"**Actualizado:** {t['updated_at'].strftime('%d/%m/%Y %H:%M') if t['updated_at'] else '?'}  ",
        ])

        if linked:
            body.append("")
            body.append("## 🔗 Tareas vinculadas (REQ-T5)")
            body.append("")
            for l in linked:
                body.append(
                    f"- [[TASK_{l['id']}]] — similitud coseno: {l['sim']:.3f}"
                )
            if backlinks:
                body.append(f"\n{backlinks}")

        if t["description"]:
            body.append("")
            body.append("## 📝 Descripción")
            body.append("")
            body.append(t["description"])

        body.append("")
        body.append(f"↩ [[../{safe_proj}|{proj}]] | [[../MASTER_LOG|Dashboard]]")

        with open(os.path.join(tasks_dir, f"TASK_{tid}.md"), "w") as f:
            f.write("\n".join(frontmatter))
            f.write("\n")
            f.write("\n".join(body))

    # ── Report ───────────────────────────────────────────────
    print(json.dumps({
        "ok": True,
        "output_dir": output_dir,
        "dashboard": "MASTER_LOG.md",
        "project_files": len(projects),
        "projects": list(projects.keys()),
        "task_files": total,
        "stats": {
            "total": total, "pending": pending_count,
            "in_progress": in_progress_count, "completed": completed_count,
            "overdue": overdue_count,
            "estimated_hours_remaining": round(total_estimated, 1),
            "actual_hours_logged": round(total_actual, 1),
            "embedding_coverage": f"{embedded_count}/{total}",
        },
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Zettelkasten Markdown Export for Obsidian")
    parser.add_argument("--output", default=os.path.expanduser("~/Obsidian/TaskManager"))
    args = parser.parse_args()
    export_master_view(args.output)


if __name__ == "__main__":
    main()
