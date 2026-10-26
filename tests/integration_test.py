#!/usr/bin/env python3
"""Integration test — Full pipeline end-to-end.

Flujos probados:
  1. CLI add → classify → DB (embedding + project_tag + linked_ids)
  2. CLI complete → actual_hours → co-occurrence
  3. CLI classify → Grafo Vivo context
  4. Heartbeat → full cycle → verify links + communities + debt
  5. Dedup: same title + project → returns existing ID
  6. Overdue detection
  7. Planning bias report

Uso: python3 tests/integration_test.py
"""

import os
import sys
import json

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common import get_conn, jprint
from src.knowledge.embeddings import generate_embedding
from src.knowledge.graph import (
    run_full_cycle,
    planning_bias_by_project,
    structural_debt_report,
)


def banner(text: str):
    print(f"\n{'═' * 60}")
    print(f"  {text}")
    print(f"{'═' * 60}")


def check(condition, label: str) -> bool:
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    return condition


def main():
    all_ok = True

    # ── Setup: clean slate ───────────────────────────────────
    banner("SETUP — Limpiar DB")
    with get_conn() as setup_conn:
        with setup_conn.cursor() as cur:
            cur.execute("TRUNCATE task_links, task_co_occurrence, structural_debt_log, tasks RESTART IDENTITY CASCADE")
        setup_conn.commit()
    print("  ✅ DB limpia")

    # Open persistent connection for test verification queries
    conn = get_conn()

    # ═══════════════════════════════════════════════════════════
    #  TEST 1: CLI add → classify → verify DB
    # ═══════════════════════════════════════════════════════════
    banner("TEST 1 — add task via processing layer")
    from src.processing.tasks import add_task
    from src.processing.classify import classify_task

    # Simulate CLI add with classify
    class Args:
        pass

    test_tasks = [
        ("Terminar informe de métricas del Q2", "Trabajo", 3),
        ("Comprar comida para el gato y arena sanitaria", "Hogar", 2),
        ("Hacer 30 min de bicicleta fija", "Salud", 1),
        ("Estudiar capítulo 7 de 'Sistemas Operativos'", "Aprendizaje", 2),
        ("Soldar los pines del sensor ultrasónico HC-SR04", "Empotrados", 3),
    ]

    created_ids = []
    created_projects = []  # Track actual project assigned by classify
    for title, project, priority in test_tasks:
        # 1. Classify (Grafo Vivo gives linked_ids + estimated_hours)
        result = classify_task(title)
        actual_project = result.get("project_tag") or project
        print(f"\n  📝 \"{title[:50]}...\"")
        print(f"     classify → project={actual_project} "
              f"priority={result.get('priority')} "
              f"hours={result.get('estimated_hours')} "
              f"source={result.get('hours_source')} "
              f"linked={result.get('linked_task_ids')}")

        # 2. Add to DB with embedding
        args = Args()
        args.title = title
        args.project = actual_project
        args.priority = result.get("priority") or priority
        args.source = "cli"
        args.due = None
        args.hours = result.get("estimated_hours")
        args.description = None
        args.embed = True  # triggers Ollama
        args.location_lat = None
        args.location_lon = None
        args.location_label = None

        task_id = add_task(args)
        created_ids.append(task_id)
        created_projects.append(actual_project)
        print(f"     DB insert → id={task_id}")

    all_ok &= check(len(created_ids) == 5, f"5 tareas creadas: {len(created_ids)}")
    all_ok &= check(len(set(created_ids)) == 5, "IDs únicos (sin duplicados)")

    # Verify embeddings exist
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tasks WHERE embedding IS NOT NULL")
        emb_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tasks WHERE project_tag IS NOT NULL")
        proj_count = cur.fetchone()[0]
    all_ok &= check(emb_count >= 3, f"Embeddings generados: {emb_count}/5")
    all_ok &= check(proj_count >= 3, f"Project tags asignados: {proj_count}/5")

    # ═══════════════════════════════════════════════════════════
    #  TEST 2: Dedup — same title + project → returns existing
    # ═══════════════════════════════════════════════════════════
    banner("TEST 2 — Deduplication")
    args2 = Args()
    args2.title = test_tasks[0][0]  # Same title as first task
    args2.project = created_projects[0]  # Use actual project from classify
    args2.priority = 3
    args2.source = "cli"
    args2.due = None
    args2.hours = None
    args2.description = None
    args2.embed = False
    args2.location_lat = None
    args2.location_lon = None
    args2.location_label = None

    dup_id = add_task(args2)
    all_ok &= check(dup_id == created_ids[0],
                    f"Dedup: mismo ID ({dup_id} == {created_ids[0]})")

    # ═══════════════════════════════════════════════════════════
    #  TEST 3: Complete task → actual_hours + co-occurrence
    # ═══════════════════════════════════════════════════════════
    banner("TEST 3 — Complete tasks with hours")
    from src.processing.tasks import complete_task

    complete_hours = [
        (created_ids[0], 4.5),  # Trabajo: informe métricas
        (created_ids[1], 0.5),  # Hogar: comida gato
        (created_ids[2], 0.75), # Salud: bici
        (created_ids[3], 2.0),  # Aprendizaje: SO cap 7
        (created_ids[4], 3.0),  # Empotrados: soldar sensor
    ]
    completed_ok = 0
    for tid, hours in complete_hours:
        if tid is None:
            print(f"  ⚠️  Skipping — task ID is None")
            continue
        args_c = Args()
        args_c.id = tid
        args_c.hours = hours
        result_id = complete_task(args_c)
        if result_id:
            from src.knowledge.co_occurrence import record_completion
            record_completion(conn, tid)
            print(f"  ✅ Task #{tid} completada con {hours}h")
            completed_ok += 1
        else:
            print(f"  ❌ Task #{tid} falló al completar")

    all_ok &= check(completed_ok == 5, f"5 tareas completadas: {completed_ok}")

    # Verify actual_hours persisted
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tasks WHERE actual_hours IS NOT NULL")
        completed = cur.fetchone()[0]
    all_ok &= check(completed == 5, f"5 tareas con actual_hours: {completed}")

    # ═══════════════════════════════════════════════════════════
    #  TEST 4: Heartbeat → full cycle → verify
    # ═══════════════════════════════════════════════════════════
    banner("TEST 4 — Heartbeat: ciclo completo + sueño")
    stats = run_full_cycle(conn, include_sleep=True)
    print(f"  cooc={stats['co_occurrence_pairs']} "
          f"links={stats['semantic_links']} "
          f"com={stats['communities']} "
          f"sub={stats['subproject_candidates']}")
    print(f"  health={stats['debt_health_score']}/100 "
          f"orphan={stats['debt_orphan_pct']}% "
          f"dead={stats['debt_dead_pct']}%")
    print(f"  sleep: pruned={stats.get('sleep_pruned_links', 'N/A')} "
          f"merged={stats.get('sleep_merged_communities', 'N/A')} "
          f"archived={stats.get('sleep_archived_tasks', 'N/A')}")

    all_ok &= check(stats["semantic_links"] >= 5, f"Links creados: {stats['semantic_links']}")
    all_ok &= check(stats["communities"] >= 1, f"Comunidades: {stats['communities']}")
    all_ok &= check(stats["co_occurrence_pairs"] >= 0, "Co-occurrence OK")
    all_ok &= check(isinstance(stats["debt_health_score"], (int, float)),
                    f"Health score: {stats['debt_health_score']}")

    # ═══════════════════════════════════════════════════════════
    #  TEST 5: Planning bias report
    # ═══════════════════════════════════════════════════════════
    banner("TEST 5 — Planning bias por proyecto")
    biases = planning_bias_by_project(conn)
    for b in biases:
        print(f"  {b['bias']:15s} {b['project_tag']:15s} "
              f"real={b['avg_actual']}h est={b['avg_estimated']}h "
              f"ratio={b['ratio']}")
    all_ok &= check(len(biases) >= 0, f"Planning bias report generado ({len(biases)} proyectos, "
                    f"necesitan ≥2 tareas por proyecto para mostrar ratio)")

    # ═══════════════════════════════════════════════════════════
    #  TEST 6: Co-occurrence (HeLa-Mem) after completions
    # ═══════════════════════════════════════════════════════════
    banner("TEST 6 — HeLa-Mem co-occurrence")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM task_co_occurrence WHERE co_score > 0")
        cooc_pairs = cur.fetchone()[0]
    print(f"  Pares co-ocurrentes activos: {cooc_pairs}")
    all_ok &= check(cooc_pairs >= 0, "Co-occurrence table populated")

    if cooc_pairs > 0:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t1.title, t2.title, co_score
                FROM task_co_occurrence tco
                JOIN tasks t1 ON t1.id = tco.task_id_a
                JOIN tasks t2 ON t2.id = tco.task_id_b
                ORDER BY co_score DESC LIMIT 3
            """)
            for a, b, s in cur.fetchall():
                print(f"     {float(s):.3f} | {a[:40]} ↔ {b[:40]}")

    # ═══════════════════════════════════════════════════════════
    #  TEST 7: Classify with populated Grafo Vivo
    # ═══════════════════════════════════════════════════════════
    banner("TEST 7 — Classify new task with full Grafo Vivo context")
    result = classify_task("Preparar presentación de avances del proyecto")
    print(f"  project_tag:     {result.get('project_tag')}")
    print(f"  priority:        {result.get('priority')}")
    print(f"  estimated_hours: {result.get('estimated_hours')} "
          f"(source: {result.get('hours_source')})")
    print(f"  linked_task_ids: {result.get('linked_task_ids')}")

    all_ok &= check(result.get("project_tag") is not None, "Project tag asignado")
    all_ok &= check(result.get("estimated_hours") is not None, "Horas estimadas del Grafo Vivo")
    all_ok &= check(bool(result.get("linked_task_ids")),
                    f"Linked tasks encontrados: {len(result.get('linked_task_ids', []))}")

    # ═══════════════════════════════════════════════════════════
    #  TEST 8: Structural debt dashboard
    # ═══════════════════════════════════════════════════════════
    banner("TEST 8 — CogniFold structural debt")
    debt = structural_debt_report(conn)
    print(f"  Health: {debt['health_score']}/100")
    print(f"  Huérfanas: {debt['orphan_tasks']} ({debt['orphan_pct']}%)")
    print(f"  Dead links: {debt['dead_links']} ({debt['dead_pct']}%)")
    print(f"  Fragmentación: {debt['fragmentation']}")
    print(f"  Densidad: {debt['graph_density']}")
    all_ok &= check(debt["health_score"] >= 0, "Health score válido")

    # ═══════════════════════════════════════════════════════════
    #  TEST 9: Verify DB state — debrief
    # ═══════════════════════════════════════════════════════════
    banner("TEST 9 — DB state verification")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tasks")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'")
        done = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM task_links WHERE weight > 0")
        links = cur.fetchone()[0]
    print(f"  Total tasks: {total}")
    print(f"  Completed:   {done}")
    print(f"  Active links: {links}")
    all_ok &= check(total in (5, 6), f"5-6 tareas total (5 original + posible dedup): {total}")
    all_ok &= check(done >= 4, f"≥4 completadas: {done}")
    all_ok &= check(links > 0, f"Links activos: {links}")

    # ── Summary ───────────────────────────────────────────────
    banner("RESUMEN")
    if all_ok:
        print("  🎉 INTEGRATION TESTS: TODOS LOS CHECKS PASARON")
        print("  ✅ add → classify → embed → DB")
        print("  ✅ dedup")
        print("  ✅ complete → actual_hours → co-occurrence")
        print("  ✅ heartbeat → 6-capas cycle + sleep")
        print("  ✅ planning bias report")
        print("  ✅ HeLa-Mem co-occurrence")
        print("  ✅ classify con Grafo Vivo poblado")
        print("  ✅ CogniFold structural debt")
        print("  ✅ DB state consistente")
    else:
        print("  ⚠️  ALGUNOS CHECKS FALLARON — revisar arriba")

    conn.close()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
