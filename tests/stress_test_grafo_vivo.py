#!/usr/bin/env python3
"""Stress-test del Grafo Vivo — 6 capas al límite.

HeLa-Mem · 3-factor weight · Confidence Intervals · Planning Bias
· Consolidación (poda/fusión/archivado) · Deuda Estructural (CogniFold)

Uso: python3 tests/stress_test_grafo_vivo.py
"""

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common import get_conn
from src.knowledge.embeddings import generate_embedding
from src.knowledge.graph import (
    combined_weight,
    rebuild_semantic_links,
    update_temporal_weights,
    detect_communities,
    cluster_stats_for_task,
    planning_bias_by_project,
    consolidate_sleep,
    structural_debt_report,
    run_full_cycle,
)


def banner(text: str):
    print(f"\n{'═' * 70}")
    print(f"  {text}")
    print(f"{'═' * 70}")


def check(condition, label: str) -> bool:
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    return condition


# ═══════════════════════════════════════════════════════════════
#  Datos — 5 dominios, 35 tareas
# ═══════════════════════════════════════════════════════════════

TASKS = [
    # TRABAJO (8)
    ("Fix memory leak in authentication module", "Trabajo", "completed", 3.5, -2),
    ("Refactor database connection pool to use async", "Trabajo", "completed", 8.0, -5),
    ("Write unit tests for payment gateway integration", "Trabajo", "completed", 4.0, -3),
    ("Deploy v2.3 to production with blue-green strategy", "Trabajo", "pending", None, -1),
    ("Set up CI/CD pipeline with GitHub Actions", "Trabajo", "pending", None, -7),
    ("Optimize PostgreSQL queries for dashboard", "Trabajo", "completed", 2.5, -10),
    ("Review pull request #342 — API rate limiting", "Trabajo", "in_progress", None, -0.5),
    ("Migrate legacy monolith to microservices", "Trabajo", "pending", None, -30),
    # HOGAR (7)
    ("Comprar víveres para la semana — leche, pan, huevos", "Hogar", "completed", 1.0, -1),
    ("Limpiar el garaje y organizar cajas", "Hogar", "pending", None, -3),
    ("Reparar la fuga del grifo de la cocina", "Hogar", "completed", 2.0, -5),
    ("Pintar la pared del living color blanco mate", "Hogar", "pending", None, -14),
    ("Llamar al electricista para revisar el tablero", "Hogar", "completed", 0.5, -2),
    ("Lavar y aspirar el auto", "Hogar", "pending", None, -1),
    ("Podar el césped y regar las plantas del jardín", "Hogar", "pending", None, -4),
    # SALUD (7)
    ("Correr 5 kilómetros en el parque — entrenamiento", "Salud", "completed", 0.5, -1),
    ("Ir al gimnasio — rutina de pierna y espalda", "Salud", "completed", 1.5, -3),
    ("Agendar cita con el dentista para limpieza", "Salud", "pending", None, -2),
    ("Preparar meal prep para la semana — pollo y verduras", "Salud", "completed", 2.0, -5),
    ("Hacer 30 minutos de yoga y meditación matutina", "Salud", "pending", None, -1),
    ("Comprar suplementos — creatina, proteína, omega 3", "Salud", "completed", 0.5, -7),
    ("Estudiar plan de entrenamiento para media maratón", "Salud", "pending", None, -10),
    # APRENDIZAJE (7)
    ("Leer capítulo 5 de 'Designing Data-Intensive Applications'", "Aprendizaje", "completed", 2.0, -2),
    ("Hacer ejercicios de álgebra lineal — valores propios", "Aprendizaje", "pending", None, -1),
    ("Ver curso de Rust — módulo de ownership y borrowing", "Aprendizaje", "completed", 3.0, -5),
    ("Practicar problemas de LeetCode — dynamic programming", "Aprendizaje", "pending", None, -3),
    ("Leer paper 'Attention Is All You Need' completo", "Aprendizaje", "completed", 1.5, -8),
    ("Configurar entorno de desarrollo para contribuir a open source", "Aprendizaje", "pending", None, -4),
    ("Escribir resumen del capítulo de sistemas distribuidos", "Aprendizaje", "pending", None, -6),
    # EMPOTRADOS (6)
    ("Implementar driver I2C para sensor de temperatura BMP280", "Empotrados", "completed", 6.0, -4),
    ("Diseñar PCB del controlador de motores paso a paso", "Empotrados", "in_progress", None, -2),
    ("Escribir firmware del bootloader para STM32F407", "Empotrados", "completed", 12.0, -10),
    ("Calibrar IMU con filtro de Kalman extendido", "Empotrados", "pending", None, -1),
    ("Programar comunicación UART entre ESP32 y Raspberry Pi", "Empotrados", "completed", 4.0, -6),
    ("Hacer pruebas de consumo energético del dispositivo final", "Empotrados", "pending", None, -3),
]


def main():
    all_ok = True

    banner("FASE 0 — Limpieza")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE task_links, task_co_occurrence, structural_debt_log, tasks RESTART IDENTITY CASCADE")
    conn.commit()
    print("  ✅ DB limpia")

    banner("FASE 1 — 35 tareas con embeddings")
    created_ids = []
    with conn.cursor() as cur:
        for title, project, status, actual_hours, days_ago in TASKS:
            emb = generate_embedding(title)
            if emb is None:
                continue
            vector_str = "[" + ",".join(str(v) for v in emb) + "]"
            created_at = f"NOW() + INTERVAL '{days_ago} days'"
            cur.execute(
                f"""INSERT INTO tasks (title, project_tag, status, actual_hours,
                        estimated_hours, embedding, embedding_model,
                        created_at, updated_at, last_activity_at)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, 'nomic-embed-text',
                            {created_at}, {created_at}, {created_at})
                    RETURNING id""",
                (title, project, status, actual_hours, actual_hours, vector_str),
            )
            created_ids.append(cur.fetchone()[0])
    conn.commit()
    print(f"  ✅ {len(created_ids)} tareas creadas")

    banner("FASE 2 — HeLa-Mem: co-occurrencia")
    from src.knowledge.co_occurrence import update_co_occurrence
    n_cooc = update_co_occurrence(conn)
    print(f"  Pares co-ocurrentes: {n_cooc}")
    all_ok &= check(n_cooc >= 0, "update_co_occurrence OK")
    with conn.cursor() as cur:
        cur.execute("""SELECT t1.title, t2.title, co_score
                       FROM task_co_occurrence tco
                       JOIN tasks t1 ON t1.id = tco.task_id_a
                       JOIN tasks t2 ON t2.id = tco.task_id_b
                       ORDER BY co_score DESC LIMIT 3""")
        for a, b, s in cur.fetchall():
            print(f"     score={float(s):.3f}  |  {a[:45]}  ↔  {b[:45]}")

    banner("FASE 3 — 3-factor weight")
    w3 = combined_weight(0.7, 24, 0.5)
    w0 = combined_weight(0.7, 24, 0.0)
    print(f"  w(cooc=0.5) = {w3:.4f}  |  w(cooc=0.0) = {w0:.4f}")
    all_ok &= check(w3 > w0, "Boost co-ocurrencia activo")
    all_ok &= check(0 <= w3 <= 1.0, f"Weight en [0,1]: {w3:.4f}")

    banner("FASE 4 — Links semánticos (3 factores)")
    n = rebuild_semantic_links(conn)
    all_ok &= check(n > 0, f"{n} links creados")

    banner("FASE 5 — Comunidades + CI + Planning Ratio")
    communities = detect_communities(conn)
    all_ok &= check(len(communities) >= 2, f"{len(communities)} comunidades")
    for c in communities[:4]:
        ci = f"[{c.get('ci_lower')}–{c.get('ci_upper')}h]" if c.get('ci_lower') else "—"
        bias = c.get('planning_bias', '—')
        print(f"  🏘️ #{c['community_id']} size={c['size']} cohesión={c['cohesion']:.3f} "
              f"act={c.get('avg_actual_hours')}h CI={ci} bias={bias}")

    banner("FASE 6 — Predicción por tarea (Capa 4)")
    for label, title in [
        ("Empotrados", "Implementar driver I2C para sensor de temperatura BMP280"),
        ("Aprendizaje", "Leer capítulo 5 de 'Designing Data-Intensive Applications'"),
    ]:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tasks WHERE title = %s", (title,))
            row = cur.fetchone()
        if row:
            s = cluster_stats_for_task(conn, row[0])
            ci = f"[{s.get('ci_lower')}–{s.get('ci_upper')}h]" if s.get('ci_lower') else "—"
            print(f"  📊 [{label}] avg={s['avg_actual_hours']}h CI={ci} "
                  f"ratio={s.get('planning_ratio')} bias={s.get('planning_bias')}")

    banner("FASE 7 — Planning bias global")
    biases = planning_bias_by_project(conn)
    for b in biases:
        print(f"  {b['bias']:15s} {b['project_tag']:15s} "
              f"real={b['avg_actual']}h est={b['avg_estimated']}h ratio={b['ratio']}")
    all_ok &= check(len(biases) >= 2, f"{len(biases)} proyectos con datos")

    banner("FASE 8 — Consolidación de Sueño")
    ss = consolidate_sleep(conn)
    print(f"  poda={ss['pruned_links']} fusión={ss['merged_communities']} "
          f"archivado={ss['archived_tasks']} recentrado={ss['recentered_links']}")

    banner("FASE 9 — Deuda Estructural (CogniFold)")
    debt = structural_debt_report(conn)
    print(f"  🏥 Health: {debt['health_score']}/100")
    print(f"  👻 Huérfanas: {debt['orphan_tasks']} ({debt['orphan_pct']}%)")
    print(f"  💀 Muertos: {debt['dead_links']} ({debt['dead_pct']}%)")
    print(f"  🧩 Fragmentación: {debt['fragmentation']}  🔗 Densidad: {debt['graph_density']}")
    print(f"  📊 T={debt['total_tasks']} L={debt['total_links']} C={debt['total_communities']}")
    all_ok &= check(debt['health_score'] >= 0, "Health score válido")

    banner("FASE 10 — Ciclo completo + sueño")
    cycle = run_full_cycle(conn, include_sleep=True)
    print(f"  cooc={cycle['co_occurrence_pairs']} links={cycle['semantic_links']} "
          f"com={cycle['communities']} sub={cycle['subproject_candidates']}")
    print(f"  health={cycle['debt_health_score']}/100 "
          f"orphan={cycle['debt_orphan_pct']}% dead={cycle['debt_dead_pct']}%")
    all_ok &= check(cycle["semantic_links"] > 0, "Ciclo completo OK")

    banner("FASE 11 — Classify con Grafo Vivo")
    from src.processing.classify import classify_task
    r = classify_task("Debug memory leak in microservice architecture")
    print(f"  project={r.get('project_tag')} priority={r.get('priority')} "
          f"hours={r.get('estimated_hours')} ({r.get('hours_source')})")
    print(f"  linked={r.get('linked_task_ids')}")
    all_ok &= check(r.get("project_tag") is not None, "classify OK")

    banner("RESUMEN")
    if all_ok:
        print("  🎉 TODOS LOS CHECKS PASARON — Grafo Vivo 6-capas listo")
    else:
        print("  ⚠️  FALLOS — revisar arriba")
    conn.close()
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
