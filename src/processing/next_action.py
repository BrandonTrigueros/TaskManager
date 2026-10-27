#!/usr/bin/env python3
"""Next Action — M1: una decisión al día.

Elige **una** tarea pendiente usando la teoría de motivación temporal de Steel:

    M = (Expectativa × Valor) / (1 + Impulsividad × Demora)

- **Expectativa**: qué tan probable es que la termines, estimada con tu propia
  calibración histórica en el cluster (`planning_ratio` de la Capa 4).
- **Valor**: prioridad normalizada a [0, 1].
- **Demora**: días hasta el vencimiento, normalizados a [0, 30]. Sin `due_date`
  se asume un horizonte neutro.

No decide qué tareas existen: decide **cuál ahora**. Es el único output del
producto (ver PRODUCT.md, M1). Cada decisión queda registrada en `decisions`
para poder calibrar la fórmula más adelante.

Usage:
    python3 -m src.processing.next_action
    python3 -m src.processing.next_action --dry-run
    python3 -m src.processing.next_action --limit 100 --no-llm
    python3 -m src.processing.next_action --demo       # sin base de datos
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import psycopg2.extras

from src.common import get_conn, deepseek_generate

# ═══════════════════════════════════════════════════════════════
#  Hiperparámetros — v1 (dos slots + vencimiento que decae)
# ═══════════════════════════════════════════════════════════════

IMPULSIVITY = float(os.environ.get("NEXT_ACTION_IMPULSIVITY", "1.0"))
NEUTRAL_HORIZON_DAYS = 15.0   # demora asumida cuando no hay vencimiento
MAX_HORIZON_DAYS = 30.0       # techo de la demora considerada
NEUTRAL_EXPECTANCY = 0.6      # prior sin historial del cluster
NEUTRAL_PRIORITY = 3          # prioridad asumida si viene NULL

# v1 · Dos slots. Sin esto, lo trivial de 20 min le gana siempre al deep work
# de 6 h, porque la fórmula no tenía término de esfuerzo.
QUICK_MAX_HOURS = 0.75        # techo del arranque corto
DEEP_MIN_HOURS = 1.5          # piso del bloque protegido
DEEP_BLOCK_HOURS = 2.0        # tamaño del bloque propuesto (no de la tarea)

# v1 · El bonus por vencimiento decae. Con un bonus fijo, lo atrasado
# secuestra el ranking para siempre y `/hoy` se vuelve una máquina de culpa.
OVERDUE_BOOST = 1.5
OVERDUE_HALFLIFE_DAYS = 10.0
STALE_AFTER_DAYS = 30.0       # más viejo que esto: sale de la propuesta

PENDING_SQL = """
    SELECT id, title, project_tag, priority, estimated_hours, due_date
    FROM tasks
    WHERE status = 'pending'
    ORDER BY priority DESC NULLS LAST, due_date ASC NULLS LAST
    LIMIT %s
"""

FIRST_STEP_SYSTEM = (
    "Sos un asistente que descompone tareas en un primer paso de 2 minutos. "
    "Respondés siempre JSON válido, en español, sin explicaciones."
)


# ═══════════════════════════════════════════════════════════════
#  Núcleo: función pura (testeable sin base de datos)
# ═══════════════════════════════════════════════════════════════

def overdue_factor(days_to_due: float) -> float:
    """Bonus por estar vencida, decreciente con la edad.

    A 0 días de atraso vale OVERDUE_BOOST; decae a la mitad cada
    OVERDUE_HALFLIFE_DAYS y tiende a 1.0 (nunca penaliza por vieja: para eso
    está el corte de STALE_AFTER_DAYS).
    """
    if days_to_due >= 0:
        return 1.0
    age = abs(float(days_to_due))
    return round(1.0 + (OVERDUE_BOOST - 1.0) * math.exp(-age / OVERDUE_HALFLIFE_DAYS), 4)


def score(expectancy: float, value: float, days_to_due: float | None,
          impulsivity: float = IMPULSIVITY) -> float:
    """Motivación según TMT de Steel, normalizada.

    Args:
        expectancy: [0, 1] probabilidad subjetiva de completarla.
        value: [0, 1] cuánto importa.
        days_to_due: días hasta el vencimiento. Negativo = vencida.
            None = sin fecha (se usa NEUTRAL_HORIZON_DAYS).
        impulsivity: sensibilidad al retraso. 0 = indiferente a las fechas.

    Returns:
        Score en [0, ~1.5]. Mayor = mejor candidata para ahora.
    """
    expectancy = min(max(float(expectancy), 0.0), 1.0)
    value = min(max(float(value), 0.0), 1.0)

    if days_to_due is None:
        delay = NEUTRAL_HORIZON_DAYS
        bonus = 1.0
    elif days_to_due < 0:
        delay = 0.0
        bonus = overdue_factor(days_to_due)
    else:
        delay = min(float(days_to_due), MAX_HORIZON_DAYS)
        bonus = 1.0

    denominator = 1.0 + impulsivity * (delay / MAX_HORIZON_DAYS)
    return round((expectancy * value * bonus) / denominator, 4)


def deep_score(expectancy: float, value: float, days_to_due: float | None,
               impulsivity: float = IMPULSIVITY) -> float:
    """Score para el bloque profundo: el valor pesa más que la expectativa.

    El trabajo que mueve la aguja suele ser justo el que evitás, y por eso su
    `expectancy` es baja (mala calibración histórica, tarea grande). Si pesara
    igual que en `quick`, el bloque se llenaría de tareas administrativas y el
    deep work nunca aparecería. La expectativa entra como modulador al 50 %,
    no como multiplicador pleno: una tarea importante y evitada sigue siendo
    propuesta.
    """
    expectancy = min(max(float(expectancy), 0.0), 1.0)
    base = score(1.0, value, days_to_due, impulsivity)
    return round(base * (0.5 + 0.5 * expectancy), 4)


def expectancy_from_stats(stats: dict | None) -> float:
    """Proxy de autoeficacia a partir de la calibración histórica.

    `planning_ratio` = horas reales / horas estimadas del cluster.
    Ratio 1.0 (estimás bien) → expectativa máxima; desviarse la baja.
    """
    if not stats:
        return NEUTRAL_EXPECTANCY
    ratio = stats.get("planning_ratio")
    if ratio is None:
        return NEUTRAL_EXPECTANCY
    try:
        return round(1.0 / (1.0 + abs(float(ratio) - 1.0)), 4)
    except (TypeError, ValueError):
        return NEUTRAL_EXPECTANCY


def slot_for(estimate_hours: float | None) -> str:
    """Asigna la tarea a un slot según su duración real esperada.

    - `quick`: arranque corto, cabe en un hueco del día.
    - `deep`:  bloque protegido; se propone un bloque, no la tarea completa.

    Sin estimación → `quick`: mejor empezar y ver, que bloquear 2 h a ciegas.
    El tramo 0.75–1.5 h queda en `quick`: no cabe en un hueco chico ni
    justifica proteger un bloque.
    """
    if estimate_hours is None or estimate_hours <= QUICK_MAX_HOURS:
        return "quick"
    if estimate_hours >= DEEP_MIN_HOURS:
        return "deep"
    return "quick"


def quick_weight(estimate_hours: float | None) -> float:
    """Densidad de valor para el slot `quick`: premia lo que se resuelve rápido.

    Acotado a [1.0, 1.5] para no aplastar el resto del ranking: el piso de
    0.25 h evita que una tarea de 3 minutos explote el score.
    """
    hours = 0.25 if estimate_hours is None else max(float(estimate_hours), 0.25)
    return round(0.5 + 0.5 / (0.25 + hours), 4)


# ═══════════════════════════════════════════════════════════════
#  Acceso a datos
# ═══════════════════════════════════════════════════════════════

def _priority_int(raw) -> int:
    """Prioridad como int (el ENUM llega como string por psycopg2)."""
    try:
        return int(raw) if raw is not None else NEUTRAL_PRIORITY
    except (TypeError, ValueError):
        return NEUTRAL_PRIORITY


def _priority_value(raw) -> float:
    """Normaliza la prioridad a [0, 1].

    `tasks.priority` es el ENUM `priority_level`, así que psycopg2 lo entrega
    como string ('4'), no como int.
    """
    try:
        priority = int(raw) if raw is not None else NEUTRAL_PRIORITY
    except (TypeError, ValueError):
        priority = NEUTRAL_PRIORITY
    return min(max(priority, 0), 5) / 5.0


def _days_to_due(due) -> float | None:
    if not due:
        return None
    now = datetime.now(timezone.utc)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return (due - now).total_seconds() / 86400.0


def _communities_index(conn) -> dict[int, dict]:
    """task_id → stats de su comunidad, en una sola pasada de clustering.

    Se evita `cluster_stats_for_task()` por tarea: cada llamada recalcularía
    el clustering completo (average-linkage con scipy).
    """
    from src.knowledge.graph import detect_communities

    try:
        communities = detect_communities(conn)
    except Exception as e:  # grafo vacío, scipy ausente, etc.
        print(f"Grafo Vivo no disponible: {e}", file=sys.stderr)
        return {}

    index: dict[int, dict] = {}
    for community in communities:
        for task_id in community.get("task_ids", []):
            index[task_id] = community
    return index


# ═══════════════════════════════════════════════════════════════
#  Primer paso de 2 minutos
# ═══════════════════════════════════════════════════════════════

def first_step(title: str, project: str | None, use_llm: bool = True) -> str:
    """Primer paso accionable. Cae a plantilla fija si el LLM falla."""
    fallback = (
        f"Abrí el contexto de «{title}» y anotá en una línea "
        f"cuál es el criterio de hecho."
    )
    if not use_llm:
        return fallback

    prompt = (
        f"Tarea: {title}\n"
        f"Proyecto: {project or 'sin proyecto'}\n\n"
        "Escribí el PRIMER paso concreto para arrancarla: 2 minutos o menos. "
        "Una sola frase imperativa en español, sin explicaciones. "
        'Respondé SOLO JSON: {"first_step": "..."}'
    )
    try:
        result = deepseek_generate(
            prompt, system_prompt=FIRST_STEP_SYSTEM, temperature=0.4
        )
        if isinstance(result, dict) and result.get("first_step"):
            return str(result["first_step"]).strip()[:200]
    except Exception as e:
        print(f"first_step: LLM no disponible ({e})", file=sys.stderr)
    return fallback


# ═══════════════════════════════════════════════════════════════
#  Selección
# ═══════════════════════════════════════════════════════════════

def _rationale(best: dict) -> str:
    """Por qué se eligió esta y no otra. Sin esto el usuario no confía."""
    parts = []
    stats = best["_stats"]
    if stats and stats.get("avg_actual_hours"):
        txt = (
            f"cluster {best['project'] or 'sin proyecto'}: "
            f"{stats.get('size', 0)} cierres, "
            f"{round(float(stats['avg_actual_hours']), 1)}h"
        )
        if stats.get("std_actual_hours"):
            txt += f" ±{round(float(stats['std_actual_hours']), 1)}"
        if stats.get("planning_ratio"):
            txt += f", calibración ×{round(float(stats['planning_ratio']), 1)}"
        parts.append(txt)
    else:
        parts.append("sin historial en el cluster (expectativa neutra)")

    dtd = best["_days_to_due"]
    if dtd is None:
        parts.append("sin vencimiento")
    elif dtd < 0:
        parts.append(f"vencida hace {abs(round(dtd))} d")
    else:
        parts.append(f"vence en {round(dtd, 1)} d")

    parts.append(f"elegida entre {best['_alternatives']} pendientes")
    return " · ".join(parts)


def _persist(conn, best: dict, slot: str) -> int | None:
    demora_hours = (
        None if best["_days_to_due"] is None
        else round(best["_days_to_due"] * 24, 2)
    )
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO decisions
               (task_id, slot, score, expectancy, value_score, demora_hours,
                estimate_hours, alternatives, rationale)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                best["task_id"], slot, best["score"], best["_expectancy"],
                best["_value"], demora_hours, best["estimate_hours"],
                best["_alternatives"], best["why"],
            ),
        )
        decision_id = cur.fetchone()["id"]
    conn.commit()
    return decision_id


def close_decision(conn, decision_id: int, executed: bool,
                   hours: float | None = None) -> dict:
    """Registra el desenlace de una decisión propuesta.

    No completa la tarea: de eso se encarga `src.processing.tasks complete`,
    que es quien mantiene el ciclo de vida y el hook de HeLa-Mem.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """UPDATE decisions
               SET executed = %s, actual_hours = %s, closed_at = NOW()
               WHERE id = %s
               RETURNING task_id, executed, actual_hours""",
            (executed, hours, decision_id),
        )
        row = cur.fetchone()

    if not row:
        return {"ok": False, "error": f"decisión {decision_id} no existe"}

    conn.commit()
    return {
        "ok": True,
        "decision_id": decision_id,
        "task_id": row["task_id"],
        "executed": row["executed"],
        "actual_hours": float(row["actual_hours"]) if row["actual_hours"] else None,
    }


def pick_next(conn, limit: int = 200, use_llm: bool = True,
              dry_run: bool = False) -> dict:
    """Devuelve hasta dos propuestas: un arranque corto y un bloque profundo.

    Lo vencido hace más de STALE_AFTER_DAYS no se propone: queda contado en
    `stale_count` para que se re-triage a mano.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(PENDING_SQL, (limit,))
        rows = cur.fetchall()

    if not rows:
        return {"ok": False, "reason": "no hay tareas pendientes"}

    clusters = _communities_index(conn)

    candidates = []
    stale = 0
    for row in rows:
        stats = clusters.get(row["id"])
        dtd = _days_to_due(row["due_date"])

        if dtd is not None and dtd < -STALE_AFTER_DAYS:
            stale += 1
            continue

        expectancy = expectancy_from_stats(stats)
        value = _priority_value(row["priority"])

        estimate = None
        estimate_range = None
        if stats and stats.get("avg_actual_hours"):
            estimate = round(float(stats["avg_actual_hours"]), 1)
            lo, hi = stats.get("ci_lower"), stats.get("ci_upper")
            if lo is not None and hi is not None:
                estimate_range = [round(float(lo), 1), round(float(hi), 1)]
        elif row["estimated_hours"] is not None:
            estimate = round(float(row["estimated_hours"]), 1)

        slot = slot_for(estimate)
        if slot == "quick":
            final = round(score(expectancy, value, dtd) * quick_weight(estimate), 4)
        else:
            final = deep_score(expectancy, value, dtd)

        candidates.append({
            "task_id": row["id"],
            "title": row["title"],
            "project": row["project_tag"],
            "priority": _priority_int(row["priority"]),
            "slot": slot,
            "score": final,
            "estimate_hours": estimate,
            "estimate_range": estimate_range,
            "_expectancy": expectancy,
            "_value": round(value, 4),
            "_days_to_due": dtd,
            "_stats": stats,
        })

    if not candidates:
        return {
            "ok": False,
            "reason": (
                "todo lo pendiente venció hace más de "
                f"{int(STALE_AFTER_DAYS)} días"
            ),
            "stale_count": stale,
        }

    result = {
        "ok": True,
        "quick": None,
        "deep": None,
        "stale_count": stale,
        "alternatives_considered": len(candidates),
    }

    for slot in ("quick", "deep"):
        pool = [c for c in candidates if c["slot"] == slot]
        if not pool:
            continue

        pool.sort(key=lambda c: c["score"], reverse=True)
        best = pool[0]
        best["_alternatives"] = len(pool)
        best["why"] = _rationale(best)
        if slot == "deep" and best["estimate_hours"]:
            best["why"] += f" · bloque de {DEEP_BLOCK_HOURS}h"

        result[slot] = {
            "decision_id": None if dry_run else _persist(conn, best, slot),
            "task_id": best["task_id"],
            "title": best["title"],
            "project": best["project"],
            "priority": best["priority"],
            "slot": slot,
            "score": best["score"],
            "why": best["why"],
            "estimate_hours": best["estimate_hours"],
            "estimate_range": best["estimate_range"],
            "block_hours": DEEP_BLOCK_HOURS if slot == "deep" else None,
            "first_step": first_step(best["title"], best["project"], use_llm),
            "alternatives_considered": len(pool),
        }

    return result


# ═══════════════════════════════════════════════════════════════
#  Demo — el formato de `/hoy` sin base de datos
# ═══════════════════════════════════════════════════════════════

PRIORITY_EMOJI = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}
DEMO_FIXTURE = os.path.join(_PROJECT_ROOT, "tests", "fixtures", "demo_tasks.json")


def run_demo(fixture_path: str = DEMO_FIXTURE) -> dict:
    """Corre la fórmula sobre el corpus de demostración.

    Los stats de cluster vienen del propio fixture: son simulados y existen
    solo para que el campo `why` muestre una calibración plausible.
    """
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", {})
    candidates = []
    stale = 0

    for index, row in enumerate(data.get("tasks", []), start=1):
        stats = projects.get(row.get("project") or "")
        dtd = row.get("due_in_days")
        dtd = None if dtd is None else float(dtd)

        if dtd is not None and dtd < -STALE_AFTER_DAYS:
            stale += 1
            continue

        expectancy = expectancy_from_stats(stats)
        value = _priority_value(row.get("priority"))

        estimate = None
        estimate_range = None
        if stats and stats.get("avg_actual_hours"):
            estimate = round(float(stats["avg_actual_hours"]), 1)
            lo, hi = stats.get("ci_lower"), stats.get("ci_upper")
            if lo is not None and hi is not None:
                estimate_range = [round(float(lo), 1), round(float(hi), 1)]
        elif row.get("estimated_hours") is not None:
            estimate = round(float(row["estimated_hours"]), 1)

        slot = slot_for(estimate)
        if slot == "quick":
            final = round(score(expectancy, value, dtd) * quick_weight(estimate), 4)
        else:
            final = deep_score(expectancy, value, dtd)

        candidates.append({
            "task_id": index,
            "title": row["title"],
            "project": row.get("project"),
            "priority": _priority_int(row.get("priority")),
            "slot": slot,
            "score": final,
            "estimate_hours": estimate,
            "estimate_range": estimate_range,
            "_expectancy": expectancy,
            "_value": round(value, 4),
            "_days_to_due": dtd,
            "_stats": stats,
        })

    slots = {}
    for slot in ("quick", "deep"):
        pool = sorted(
            (c for c in candidates if c["slot"] == slot),
            key=lambda c: c["score"], reverse=True,
        )
        if not pool:
            continue
        best = pool[0]
        best["_alternatives"] = len(pool)
        best["why"] = _rationale(best)
        if slot == "deep" and best["estimate_hours"]:
            best["why"] += f" · bloque de {DEEP_BLOCK_HOURS}h"
        best["first_step"] = first_step(best["title"], best["project"], use_llm=False)
        best["alternatives_considered"] = len(pool)
        slots[slot] = best

    ranking = sorted(candidates, key=lambda c: c["score"], reverse=True)
    return {
        "quick": slots.get("quick"),
        "deep": slots.get("deep"),
        "ranking": ranking,
        "stale_count": stale,
    }


def _format_card(label: str, card: dict) -> str:
    """El mensaje tal como lo vería el usuario en `/hoy`."""
    emoji = PRIORITY_EMOJI.get(card.get("priority") or NEUTRAL_PRIORITY, "⬜")
    lines = [
        f"{label} · #{card['task_id']}",
        card["title"],
        f"{emoji} {card['project'] or 'sin proyecto'}",
    ]
    if card["estimate_hours"] is not None:
        estimate = f"~{card['estimate_hours']}h"
        if card["estimate_range"]:
            estimate += f" ({card['estimate_range'][0]}–{card['estimate_range'][1]})"
        if card.get("block_hours"):
            estimate += f" · bloque de {card['block_hours']}h"
        lines.append(estimate)
    lines += [
        card["why"],
        "",
        f"▶ {card['first_step']}",
        "",
        "[ ✅ Hecho ]   [ ⏭ Hoy no ]",
    ]
    return "\n".join(lines)


def _format_ranking(ranking: list[dict], n: int = 8) -> str:
    lines = ["── ranking (stats de cluster simulados) ──"]
    for position, candidate in enumerate(ranking[:n], start=1):
        emoji = PRIORITY_EMOJI.get(
            candidate.get("priority") or NEUTRAL_PRIORITY, "⬜"
        )
        mark = "⚡" if candidate["slot"] == "quick" else "🧠"
        lines.append(
            f"{position}. {candidate['score']:.3f} {mark} {emoji} "
            f"{candidate['title'][:48]}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Next Action — una decisión al día (M1)"
    )
    parser.add_argument("--limit", type=int, default=200,
                        help="tareas pendientes a considerar (default 200)")
    parser.add_argument("--dry-run", action="store_true",
                        help="no persiste en la tabla decisions")
    parser.add_argument("--no-llm", action="store_true",
                        help="primer paso con plantilla fija, sin DeepSeek")
    parser.add_argument("--demo", action="store_true",
                        help="corre el corpus de demo, sin base de datos")
    parser.add_argument("--close", type=int, metavar="DECISION_ID",
                        help="registra el desenlace de una decisión")
    parser.add_argument("--executed", choices=["true", "false"], default="true",
                        help="¿se ejecutó? (con --close)")
    parser.add_argument("--hours", type=float,
                        help="horas reales al cerrar (con --close)")
    args = parser.parse_args()

    if args.demo:
        demo = run_demo()
        for label, slot in (("⚡ ARRANQUE", "quick"), ("🧠 BLOQUE PROFUNDO", "deep")):
            if demo.get(slot):
                print(_format_card(label, demo[slot]))
                print()
        print(_format_ranking(demo["ranking"]))
        if demo["stale_count"]:
            print(
                f"\n{demo['stale_count']} tareas vencidas hace más de "
                f"{int(STALE_AFTER_DAYS)} d quedaron fuera de la propuesta."
            )
        return

    if args.close is not None:
        conn = get_conn()
        try:
            result = close_decision(
                conn,
                args.close,
                executed=(args.executed == "true"),
                hours=args.hours,
            )
        finally:
            conn.close()
        print(json.dumps(result, default=str, ensure_ascii=False))
        return

    conn = get_conn()
    try:
        result = pick_next(
            conn,
            limit=args.limit,
            use_llm=not args.no_llm,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
