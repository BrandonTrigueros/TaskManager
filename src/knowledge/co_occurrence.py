#!/usr/bin/env python3
"""HeLa-Mem — Salto Asociativo conductual.

Captura patrones que la similitud semántica (Capa 1) no puede ver:
  - Tareas completadas en la misma sesión (ventana de 2 horas)
  - Tareas completadas secuencialmente (A → B → C)
  - Tareas en misma franja horaria recurrente (sábados 9am)

Estos patrones alimentan un score de co-ocurrencia que se integra
en el peso combinado del Grafo Vivo como tercer factor.

Reference: HeLa-Mem (2024) — hippocampal-like associative memory
           for task graphs. Co-occurrence as Hebbian reinforcement.
"""

import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict


# ── Hyperparameters ───────────────────────────────────────────
COOC_WINDOW_HOURS = 2        # Ventana para considerar "misma sesión"
COOC_DECAY_LAMBDA = 0.0005   # Decaimiento de co-ocurrencia (más lento que temporal)
COOC_MAX_SCORE = 1.0         # Score máximo normalizado
SEQUENTIAL_BONUS = 1.5       # Bonus multiplicativo para secuencias A→B


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def co_occurrence_decay(hours_elapsed: float) -> float:
    """Decaimiento de co-ocurrencia: e^(-λ_cooc · Δt).

    Más lento que el decaimiento temporal porque los hábitos
    cambian más despacio que la relevancia operativa.

    30 días:  ~0.70
    90 días:  ~0.34
    180 días: ~0.12
    """
    import math
    return math.exp(-COOC_DECAY_LAMBDA * hours_elapsed)


# ═══════════════════════════════════════════════════════════════
#  Registro de actividad
# ═══════════════════════════════════════════════════════════════

def record_completion(conn, task_id: int):
    """Mark task as completed and update last_activity_at.

    Call this from tasks.py complete() — hooks into the feedback loop.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tasks SET last_activity_at = NOW() WHERE id = %s",
            (task_id,),
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
#  Co-occurrence computation
# ═══════════════════════════════════════════════════════════════

def update_co_occurrence(conn) -> int:
    """Rebuild co-occurrence scores from completion timestamps.

    Strategy:
      1. Find all completed tasks with actual_hours set
      2. For each pair completed within COOC_WINDOW_HOURS, increment co_count
      3. For sequential pairs (A completed, then B within window), increment sequential_count
      4. Apply decay to old co-occurrence scores
      5. Normalize scores to [0, 1]

    Returns number of co-occurrence pairs updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, updated_at
               FROM tasks
               WHERE status = 'completed'
                 AND actual_hours IS NOT NULL
               ORDER BY updated_at"""
        )
        completed = [(r[0], r[1]) for r in cur.fetchall()]

    if len(completed) < 2:
        return 0

    # Build co-occurrence pairs within time window
    new_pairs = defaultdict(lambda: {"co": 0, "seq": 0, "session": 0})

    for i, (id_a, ts_a) in enumerate(completed):
        for j, (id_b, ts_b) in enumerate(completed):
            if j <= i:
                continue
            if id_a == id_b:
                continue

            delta = abs((ts_b - ts_a).total_seconds()) / 3600.0
            if delta > COOC_WINDOW_HOURS:
                continue

            # Canonical ordering (a < b)
            a, b = (id_a, id_b) if id_a < id_b else (id_b, id_a)
            new_pairs[(a, b)]["co"] += 1
            new_pairs[(a, b)]["session"] += 1

            # Sequential: j == i+1 means consecutive completions
            if j == i + 1:
                new_pairs[(a, b)]["seq"] += 1

    # Upsert into task_co_occurrence with decay
    updated = 0
    now = now_utc()
    with conn.cursor() as cur:
        for (a, b), counts in new_pairs.items():
            # Get existing record
            cur.execute(
                """SELECT co_count, sequential_count, same_session_count, last_together
                   FROM task_co_occurrence
                   WHERE task_id_a = %s AND task_id_b = %s""",
                (a, b),
            )
            existing = cur.fetchone()

            if existing:
                old_co, old_seq, old_sess, last = existing
                hours = (now - last).total_seconds() / 3600.0
                decay = co_occurrence_decay(hours)

                new_co = int(old_co * decay) + counts["co"]
                new_seq = int(old_seq * decay) + counts["seq"]
                new_sess = int(old_sess * decay) + counts["session"]
                # Score: weighted sum normalized
                score = min(COOC_MAX_SCORE,
                           (new_co * 0.5 + new_seq * SEQUENTIAL_BONUS * 0.3 + new_sess * 0.2) / 10.0)

                cur.execute(
                    """UPDATE task_co_occurrence
                       SET co_count = %s, sequential_count = %s,
                           same_session_count = %s, co_score = %s,
                           last_together = %s
                       WHERE task_id_a = %s AND task_id_b = %s""",
                    (new_co, new_seq, new_sess, score, now, a, b),
                )
            else:
                score = min(COOC_MAX_SCORE,
                           (counts["co"] * 0.5 +
                            counts["seq"] * SEQUENTIAL_BONUS * 0.3 +
                            counts["session"] * 0.2) / 10.0)

                cur.execute(
                    """INSERT INTO task_co_occurrence
                       (task_id_a, task_id_b, co_count, sequential_count,
                        same_session_count, co_score, last_together)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (a, b, counts["co"], counts["seq"],
                     counts["session"], score, now),
                )
            updated += 1
    conn.commit()
    return updated


# ═══════════════════════════════════════════════════════════════
#  Score lookup
# ═══════════════════════════════════════════════════════════════

def get_co_occurrence_score(conn, task_id_a: int, task_id_b: int) -> float:
    """Get normalized co-occurrence score [0, 1] for a task pair.

    Returns 0.0 if no co-occurrence record exists.
    """
    a, b = (task_id_a, task_id_b) if task_id_a < task_id_b else (task_id_b, task_id_a)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT co_score FROM task_co_occurrence WHERE task_id_a = %s AND task_id_b = %s",
            (a, b),
        )
        row = cur.fetchone()
    return float(row[0]) if row else 0.0


def get_top_co_occurring(conn, task_id: int, limit: int = 5) -> list[dict]:
    """Get tasks that most frequently co-occur with the given task.

    Returns list of {task_id, title, co_score, co_count}.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT
                   CASE WHEN tco.task_id_a = %s THEN tco.task_id_b ELSE tco.task_id_a END AS other_id,
                   tco.co_score, tco.co_count, tco.sequential_count,
                   t.title
               FROM task_co_occurrence tco
               JOIN tasks t ON t.id = CASE WHEN tco.task_id_a = %s THEN tco.task_id_b ELSE tco.task_id_a END
               WHERE (tco.task_id_a = %s OR tco.task_id_b = %s)
                 AND tco.co_score > 0
               ORDER BY tco.co_score DESC
               LIMIT %s""",
            (task_id, task_id, task_id, task_id, limit),
        )
        rows = cur.fetchall()
    return [
        {"task_id": r[0], "co_score": float(r[1]), "co_count": r[2],
         "sequential_count": r[3], "title": r[4]}
        for r in rows
    ]
