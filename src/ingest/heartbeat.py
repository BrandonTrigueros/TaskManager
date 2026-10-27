#!/usr/bin/env python3
"""BT-Core Heartbeat — 60-minute semantic coherence cycle (REQ-T12).

Acciones (--action):
  backfill    Embeddings para tareas con embedding NULL
  reminders   Tareas por vencer en las próximas 24 h
  graph       Ciclo completo del Grafo Vivo: co-ocurrencia (Capa H),
              pesos temporales (2), comunidades (3), deuda estructural (6)
  sleep       Lo anterior + consolidación (5): poda, fusión, archivado >90 d
  export      Sincroniza el vault de Obsidian
  all         Todo lo anterior; la consolidación entra sola una vez al día a
              la hora de HEARTBEAT_SLEEP_HOUR (default 3)

Pensado para cron, systemd o el loop de docker-compose.
stdout = JSON; avisos legibles por stderr.

Usage:
    python3 -m src.ingest.heartbeat
    python3 -m src.ingest.heartbeat --action reminders
    python3 -m src.ingest.heartbeat --action sleep
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


# ─── Consolidación de sueño (Capa 5) ─────────────────────────
# Con un ciclo de 60 min, comparar la hora local dispara una sola vez al día.
# Si el ciclo tardara más de una hora podría saltarse el día; el loop de
# docker-compose está dimensionado para ciclos de segundos.
SLEEP_HOUR = int(os.environ.get("HEARTBEAT_SLEEP_HOUR", "3"))


def sleep_is_due(action: str, now: datetime | None = None) -> bool:
    """¿Entra la consolidación en este ciclo?

    - `--action sleep` consolida siempre (para cron explícito).
    - `--action all` consolida solo en SLEEP_HOUR, una vez al día.
    - `backfill` / `reminders` / `graph` / `export` nunca consolidan.
    """
    if action == "sleep":
        return True
    if action != "all":
        return False
    return (now or datetime.now()).hour == SLEEP_HOUR


def run_heartbeat(action: str = "all") -> dict:
    """Ejecuta el ciclo y devuelve un dict serializable con el resultado
    de cada acción."""
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

        if action in ("graph", "all", "sleep"):
            # Import perezoso: `backfill` y `reminders` deben funcionar aunque
            # scipy no esté instalado (solo lo requiere la Capa 3).
            from src.knowledge.graph import run_full_cycle

            include_sleep = sleep_is_due(action)
            cycle = run_full_cycle(conn, include_sleep=include_sleep)
            result["graph_cycle"] = cycle
            result["graph_links"] = cycle.get("semantic_links", 0)
            result["sleep_ran"] = include_sleep

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
        choices=["all", "backfill", "reminders", "graph", "sleep", "export"],
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

    # stdout = JSON legible por máquina (cron, bot, jq)
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
