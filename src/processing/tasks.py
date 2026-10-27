#!/usr/bin/env python3
"""Tasks — CRUD operations for TaskManager tasks.

Features (BT-Core Wizard-grade):
  - Deduplication: same title + project + pending → returns existing ID.
  - Embeddings (REQ-T5): --embed flag triggers Ollama → pgvector 768d.
  - Feedback loop (REQ-T7): complete --hours writes actual_hours.
  - Geofencing-ready: --location-lat, --location-lon, --location-label.
  - Single Source of Truth: all DB access via get_conn() from common.py.

Usage (from project root):
    python3 -m src.processing.tasks add --title "..." [--project X] [--priority N]
                [--hours N] [--due DATE] [--embed] [--location-lat X --location-lon Y]
    python3 -m src.processing.tasks list [--status pending] [--project X] [--limit N]
    python3 -m src.processing.tasks complete --id N [--hours N]
    python3 -m src.processing.tasks update --id N [--project X] [--priority N] [--status X]
    python3 -m src.processing.tasks overdue

Or via CLI:
    python3 -m src.ingest.cli add --title "..."
"""

import argparse
import json
import os
import sys

# Ensure project root is in sys.path for `from src.task_manager / src.shared / src.common import ...`
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import psycopg2.extras

from src.common import get_conn, jprint
from src.knowledge.embeddings import generate_embedding


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _format_vector(embedding: list[float]) -> str:
    """Convert a 768d list to pgvector literal: [0.1,0.2,...]."""
    return "[" + ",".join(str(v) for v in embedding) + "]"


def _cast_priority(value) -> str | None:
    """Normalize priority to string for priority_level ENUM ('1'–'5')."""
    if value is None:
        return None
    return str(int(value))


# ═══════════════════════════════════════════════════════════════
#  CRUD Operations
# ═══════════════════════════════════════════════════════════════

def add_task(args):
    """Insert a task. Deduplicates on title + project_tag + status='pending'.

    If --embed is set, generates a 768d embedding via Ollama and persists it.

    Returns:
        task_id (int) on success, or existing_id on dedup, or None on error.
    """
    title = args.title
    project = args.project
    priority = _cast_priority(args.priority)
    source = args.source or "cli"

    with get_conn() as conn, conn.cursor() as cur:
        # ── Deduplication check (case-insensitive) ────────────
        # 1. Block if same title + project + pending
        cur.execute(
            """SELECT id FROM tasks
               WHERE title ILIKE %s
                 AND (project_tag = %s OR (project_tag IS NULL AND %s IS NULL))
                 AND status = 'pending'
               LIMIT 1""",
            (title, project, project),
        )
        existing = cur.fetchone()
        if existing:
            existing_id = existing[0]
            conn.commit()
            jprint({
                "ok": True, "id": existing_id, "title": title,
                "project": project, "priority": priority,
                "deduplicated": True,
                "note": "Task with same title+project already pending, returning existing ID",
            })
            return existing_id

        # 2. Warn if same title + project + completed (Grafo Vivo training data)
        cur.execute(
            """SELECT id FROM tasks
               WHERE title ILIKE %s
                 AND (project_tag = %s OR (project_tag IS NULL AND %s IS NULL))
                 AND status = 'completed'
               LIMIT 1""",
            (title, project, project),
        )
        already_done = cur.fetchone()
        if already_done:
            # No se deduplica contra una completada: recrear la tarea preserva
            # el dato del Grafo Vivo (horas reales del ciclo anterior).
            # Antes se intentaba devolver `existing_id`, variable que en esta
            # rama no existe (venimos de `existing is None`) → UnboundLocalError.
            print(f"⚠️  Task similar to completed #{already_done[0]} — "
                  f"creating new one (Grafo Vivo data preserved)", file=sys.stderr)

        # ── Embedding (REQ-T5, optional) ─────────────────────
        embedding_vector = None
        embedding_model_name = None
        if getattr(args, "embed", False):
            text_to_embed = f"{title}"
            if args.description:
                text_to_embed += f" — {args.description}"
            emb = generate_embedding(text_to_embed)
            if emb and len(emb) == 768:
                embedding_vector = _format_vector(emb)
                embedding_model_name = "nomic-embed-text"

        # ── Build dynamic INSERT ─────────────────────────────
        columns = ["title", "description", "project_tag", "priority",
                   "estimated_hours", "source_origin", "due_date"]
        values = [title, args.description, project, priority,
                  args.hours, source, args.due]
        type_hints = ["", "", "", "::priority_level", "",
                      "::source_origin", "::timestamptz"]

        # Geofencing (Owntracks-ready)
        loc_lat = getattr(args, "location_lat", None)
        loc_lon = getattr(args, "location_lon", None)
        loc_label = getattr(args, "location_label", None)
        if loc_lat is not None:
            columns.append("location_lat"); values.append(loc_lat); type_hints.append("")
        if loc_lon is not None:
            columns.append("location_lon"); values.append(loc_lon); type_hints.append("")
        if loc_label is not None:
            columns.append("location_label"); values.append(loc_label); type_hints.append("")

        # Embedding
        if embedding_vector is not None:
            columns.append("embedding"); values.append(embedding_vector)
            type_hints.append("::vector")
            columns.append("embedding_model"); values.append(embedding_model_name)
            type_hints.append("::embedding_model")

        placeholders = ", ".join(
            f"%s{th}" if th else "%s" for th in type_hints
        )
        col_list = ", ".join(columns)

        cur.execute(
            f"INSERT INTO tasks ({col_list}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        task_id = cur.fetchone()[0]
        conn.commit()

        result = {"ok": True, "id": task_id, "title": title,
                   "project": project, "priority": priority}
        if already_done:
            result["warn_completed"] = already_done[0]
        if embedding_vector is not None:
            result["embedding_stored"] = True
            result["embedding_model"] = embedding_model_name
        jprint(result)
        return task_id


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
                       actual_hours, status, due_date, location_label,
                       created_at, updated_at,
                       CASE WHEN embedding IS NOT NULL THEN true ELSE false END AS has_embedding
                FROM tasks {where}
                ORDER BY priority DESC NULLS LAST, due_date ASC NULLS LAST
                LIMIT %s""",
            params,
        )
        jprint(cur.fetchall())


def complete_task(args):
    """Mark a task as completed, optionally recording actual hours (REQ-T7)."""
    sets = ["status = 'completed'"]
    params = []

    actual_hours = getattr(args, "hours", None)
    if actual_hours is not None:
        sets.append("actual_hours = %s")
        params.append(float(actual_hours))

    params.append(args.id)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE tasks SET {', '.join(sets)} "
            f"WHERE id = %s AND status != 'completed' RETURNING id",
            params,
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            result = {"ok": True, "id": row[0], "status": "completed"}
            if actual_hours is not None:
                result["actual_hours"] = float(actual_hours)
            jprint(result)
            return row[0]
        else:
            jprint({"ok": False, "error": f"Task {args.id} not found or already completed"})
            return None


def update_task(args):
    sets, params = [], []
    if args.project:
        sets.append("project_tag = %s")
        params.append(args.project)
    if args.priority is not None:
        sets.append("priority = %s::priority_level")
        params.append(_cast_priority(args.priority))
    if args.status:
        sets.append("status = %s::task_status")
        params.append(args.status)
    if args.due:
        sets.append("due_date = %s::timestamptz")
        params.append(args.due)
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
            """SELECT id, title, project_tag, priority, due_date, location_label
               FROM tasks
               WHERE status = 'pending' AND due_date < NOW()
               ORDER BY due_date ASC"""
        )
        jprint(cur.fetchall())


# ═══════════════════════════════════════════════════════════════
#  CLI Entry Point
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Tasks — TaskManager CRUD (Wizard-grade)")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── add ──────────────────────────────────────────────────
    p = sub.add_parser("add")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--project")
    p.add_argument("--priority", type=int, help="1 (baja) a 5 (urgente)")
    p.add_argument("--hours", type=float, help="Horas estimadas (decimal)")
    p.add_argument("--due", help="Fecha límite (YYYY-MM-DD o ISO 8601)")
    p.add_argument("--source", default="cli")
    p.add_argument("--embed", action="store_true",
                   help="Generar y persistir embedding 768d vía Ollama (REQ-T5)")
    p.add_argument("--location-lat", type=float, help="Latitud (geofencing)")
    p.add_argument("--location-lon", type=float, help="Longitud (geofencing)")
    p.add_argument("--location-label", help="Etiqueta de ubicación (ej. 'Casa', 'U')")

    # ── list ─────────────────────────────────────────────────
    p = sub.add_parser("list")
    p.add_argument("--status", default="pending")
    p.add_argument("--project")
    p.add_argument("--limit", type=int, default=20)

    # ── complete ─────────────────────────────────────────────
    p = sub.add_parser("complete")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--hours", type=float,
                   help="Horas REALES que tomó la tarea (REQ-T7, feedback loop)")

    # ── update ───────────────────────────────────────────────
    p = sub.add_parser("update")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--project")
    p.add_argument("--priority", type=int, help="1 (baja) a 5 (urgente)")
    p.add_argument("--status")
    p.add_argument("--due", help="Nueva fecha límite (YYYY-MM-DD o ISO 8601)")

    # ── overdue ──────────────────────────────────────────────
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
