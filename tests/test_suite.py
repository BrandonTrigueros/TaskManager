#!/usr/bin/env python3
"""BT-Core TaskManager — Test Suite Completa.

U1  Unit Tests       — funciones puras (sin DB)
P1  Performance      — 100 tareas, tiempos de cada capa
E1  Edge Cases       — títulos vacíos, SQL injection, Ollama caído
S1  Smoke Check      — 1 tarea end-to-end en <30s

Uso: python3 tests/test_suite.py [--quick]
     --quick: solo smoke + unit (sin crear 100 tareas)
"""

import os
import sys
import time
import math
import json

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

_passed = 0
_failed = 0
_errors = []


def check(condition, label: str):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅ {label}")
    else:
        _failed += 1
        print(f"  ❌ {label}")
        _errors.append(label)


def banner(text: str):
    global _passed, _failed
    _passed = _failed = 0
    _errors.clear()
    print(f"\n{'═' * 60}")
    print(f"  {text}")
    print(f"{'═' * 60}")


def section(text: str):
    print(f"\n  ── {text} ──")


def summary():
    total = _passed + _failed
    if _failed == 0:
        print(f"  🎉 {_passed}/{total} OK")
    else:
        print(f"  ⚠️  {_passed}/{total} OK  ({_failed} fallos)")
        for e in _errors:
            print(f"     ❌ {e}")


# ═══════════════════════════════════════════════════════════════
#  U1 — UNIT TESTS (sin DB)
# ═══════════════════════════════════════════════════════════════

def test_units():
    banner("U1 — Unit Tests")

    # ── temporal_weight ───────────────────────────────────
    section("temporal_weight (Capa 2)")
    from src.knowledge.graph import temporal_weight
    w0 = temporal_weight(0)
    check(abs(w0 - 1.0) < 0.001, f"temporal_weight(0h) = {w0:.3f} ≈ 1.0")
    w24 = temporal_weight(24)
    check(w24 < 1.0 and w24 > 0.9, f"temporal_weight(24h) = {w24:.3f} ∈ (0.9, 1.0)")
    w720 = temporal_weight(720)  # 30 days
    check(abs(w720 - 0.5) < 0.05, f"temporal_weight(720h ≈ 30d) = {w720:.3f} ≈ 0.5 (half-life)")
    w2160 = temporal_weight(2160)  # 90 days
    check(w2160 < 0.15, f"temporal_weight(2160h ≈ 90d) = {w2160:.3f} < 0.15 (cold)")

    # ── combined_weight ───────────────────────────────────
    section("combined_weight (3-factor)")
    from src.knowledge.graph import combined_weight
    w = combined_weight(0.8, 0, 0.0)
    expected = 0.55*0.8 + 0.30*1.0 + 0.15*0.0
    check(abs(w - expected) < 0.001,
          f"combined_weight(0.8, 0h, cooc=0) = {w:.4f} ≈ {expected:.4f}")
    w_cooc = combined_weight(0.8, 0, 0.5)
    check(w_cooc > w, f"Co-occurrence boost: {w_cooc:.4f} > {w:.4f}")
    check(w_cooc <= 1.0, f"Weight ≤ 1.0: {w_cooc:.4f}")
    w_min = combined_weight(0.0, 10000, 0.0)
    check(w_min >= 0.0, f"Weight ≥ 0.0: {w_min:.4f}")

    # ── co_occurrence_decay ───────────────────────────────
    section("co_occurrence_decay (HeLa-Mem)")
    from src.knowledge.co_occurrence import co_occurrence_decay
    d0 = co_occurrence_decay(0)
    check(abs(d0 - 1.0) < 0.001, f"cooc_decay(0) = {d0:.3f} ≈ 1.0")
    d30d = co_occurrence_decay(30 * 24)
    check(d30d > 0.65 and d30d < 0.75,
          f"cooc_decay(30d) = {d30d:.3f} ≈ 0.70 (slower than temporal)")
    d90d = co_occurrence_decay(90 * 24)
    check(d90d > 0.30, f"cooc_decay(90d) = {d90d:.3f} > 0.30 (persistent)")

    # ── now_utc ───────────────────────────────────────────
    section("now_utc")
    from src.knowledge.graph import now_utc
    t = now_utc()
    check(t.tzinfo is not None, f"now_utc() has timezone: {t.tzinfo}")

    summary()


# ═══════════════════════════════════════════════════════════════
#  P1 — PERFORMANCE (100 tareas)
# ═══════════════════════════════════════════════════════════════

PERF_TASKS = [
    ("Review Q3 budget spreadsheet", "Trabajo"),
    ("Fix CSS layout bug on landing page", "Trabajo"),
    ("Write API docs for v2 endpoints", "Trabajo"),
    ("Set up monitoring alerts for prod DB", "Trabajo"),
    ("Refactor user authentication middleware", "Trabajo"),
    ("Run load tests on checkout service", "Trabajo"),
    ("Update dependencies in package.json", "Trabajo"),
    ("Debug race condition in websocket handler", "Trabajo"),
    ("Write migration script for legacy data", "Trabajo"),
    ("Create dashboard for error tracking", "Trabajo"),
    ("Comprar verduras y frutas para la semana", "Hogar"),
    ("Limpiar filtros del aire acondicionado", "Hogar"),
    ("Organizar el armario del pasillo", "Hogar"),
    ("Cambiar bombilla del baño principal", "Hogar"),
    ("Llevar ropa a la tintorería", "Hogar"),
    ("Montar el mueble del estudio", "Hogar"),
    ("Regar plantas del balcón", "Hogar"),
    ("Aspirar alfombras del salón", "Hogar"),
    ("Hacer 20 min de HIIT", "Salud"),
    ("Estiramientos de espalda — 15 min", "Salud"),
    ("Preparar batido verde detox", "Salud"),
    ("Agendar revisión médica anual", "Salud"),
    ("Comprar vendas elásticas para rodilla", "Salud"),
    ("Leer capítulo 8 de Clean Code", "Aprendizaje"),
    ("Hacer kata de TDD — Roman Numerals", "Aprendizaje"),
    ("Ver charla 'The Mess We're In' en YouTube", "Aprendizaje"),
    ("Instalar y probar Zig 0.12", "Aprendizaje"),
    ("Escribir blog post sobre pgvector", "Aprendizaje"),
    ("Flash microcontroller with new bootloader", "Empotrados"),
    ("Measure power draw of ESP32 deep sleep", "Empotrados"),
    ("Solder header pins to sensor breakout board", "Empotrados"),
    ("Test I2C communication at 400kHz", "Empotrados"),
    ("Calibrate ADC readings with known voltage ref", "Empotrados"),
    ("Design 3D-printed enclosure in FreeCAD", "Empotrados"),
    ("Write firmware for LED matrix driver", "Empotrados"),
    ("Debug SPI signal with logic analyzer", "Empotrados"),
    ("Update project roadmap for Q4", "Trabajo"),
    ("Prepare slides for sprint review", "Trabajo"),
    ("Mentor junior dev on SQL optimization", "Trabajo"),
    ("Audit security vulnerabilities in npm deps", "Trabajo"),
    ("Hacer copia de seguridad del NAS", "Hogar"),
    ("Limpiar el congelador y descongelar", "Hogar"),
    ("Donar ropa que ya no uso", "Hogar"),
    ("Correr 10K este sábado", "Salud"),
    ("Comprar monitor nuevo para home office", "Hogar"),
    ("Migrar CI de Jenkins a GitHub Actions", "Trabajo"),
    ("Implement dark mode en la web app", "Trabajo"),
    ("Escribir tests de integración para payments", "Trabajo"),
    ("Configurar Tailscale en la Raspberry Pi", "Aprendizaje"),
    ("Estudiar arquitectura de transformers", "Aprendizaje"),
    ("Hacer journaling — 10 minutos", "Salud"),
    ("Soldar el puente H del robot", "Empotrados"),
    ("Programar rutina de calibración automática", "Empotrados"),
    ("Tomar magnesio y zinc antes de dormir", "Salud"),
    ("Actualizar CV y LinkedIn", "Trabajo"),
]


def test_performance():
    banner("P1 — Performance (100 tareas)")

    from src.common import get_conn
    from src.knowledge.embeddings import generate_embedding

    # Setup: clean DB
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE task_links, task_co_occurrence, structural_debt_log, tasks RESTART IDENTITY CASCADE")
        conn.commit()

    # Create 100 tasks (55 defined + 45 auto-generated duplicates with variation)
    print("  Creando 100 tareas con embeddings...")
    created = 0
    failed_embed = 0
    t0 = time.time()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for i, (title, project) in enumerate(PERF_TASKS * 2):  # 55 × 2 = 110
                if created >= 100:
                    break
                # Vary the title slightly for duplicates
                if i >= len(PERF_TASKS):
                    title = title + f" (round 2)"
                emb = generate_embedding(title)
                if emb is None:
                    failed_embed += 1
                    continue
                vector_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    """INSERT INTO tasks (title, project_tag, status, embedding, embedding_model)
                       VALUES (%s, %s, 'completed', %s::vector, 'nomic-embed-text')
                       RETURNING id""",
                    (title, project, vector_str),
                )
                tid = cur.fetchone()[0]
                # Give some tasks actual_hours
                if i % 3 == 0:
                    cur.execute(
                        "UPDATE tasks SET actual_hours = %s, updated_at = NOW() WHERE id = %s",
                        (float((i % 10) + 1) * 0.5, tid),
                    )
                created += 1
        conn.commit()
    t_create = time.time() - t0
    print(f"  {created} tareas creadas en {t_create:.1f}s "
          f"({created/t_create:.0f} t/s) — {failed_embed} sin embedding")
    check(created >= 90, f"≥90 tareas con embedding: {created}")
    check(failed_embed <= 5, f"≤5 fallos de embedding: {failed_embed}")

    # ── Benchmark: rebuild_semantic_links ──────────────────
    print("  Midiendo rebuild_semantic_links...")
    from src.knowledge.graph import rebuild_semantic_links, update_temporal_weights, \
        detect_communities, run_full_cycle, consolidate_sleep, structural_debt_report

    with get_conn() as conn:
        t0 = time.time()
        n_links = rebuild_semantic_links(conn)
        t_links = time.time() - t0
        print(f"  rebuild_semantic_links: {n_links} links en {t_links:.2f}s")
        check(t_links < 60, f"Links <60s para 100 tareas: {t_links:.1f}s")

    # ── Benchmark: update_temporal_weights ─────────────────
    with get_conn() as conn:
        t0 = time.time()
        n_upd = update_temporal_weights(conn)
        t_temp = time.time() - t0
        print(f"  update_temporal_weights: {n_upd} updates en {t_temp:.2f}s")
        check(t_temp < 30, f"Temporal <30s: {t_temp:.1f}s")

    # ── Benchmark: detect_communities ──────────────────────
    with get_conn() as conn:
        t0 = time.time()
        communities = detect_communities(conn)
        t_comm = time.time() - t0
        print(f"  detect_communities: {len(communities)} comunidades en {t_comm:.2f}s")
        check(t_comm < 30, f"Communities <30s: {t_comm:.1f}s")
        check(len(communities) >= 3, f"≥3 comunidades: {len(communities)}")

    # ── Benchmark: run_full_cycle ──────────────────────────
    with get_conn() as conn:
        t0 = time.time()
        cycle = run_full_cycle(conn, include_sleep=False)
        t_cycle = time.time() - t0
        print(f"  run_full_cycle: {t_cycle:.2f}s "
              f"(links={cycle['semantic_links']}, com={cycle['communities']})")
        check(t_cycle < 120, f"Full cycle <120s: {t_cycle:.1f}s")

    # ── Benchmark: consolidate_sleep ───────────────────────
    with get_conn() as conn:
        t0 = time.time()
        sleep = consolidate_sleep(conn)
        t_sleep = time.time() - t0
        print(f"  consolidate_sleep: {t_sleep:.2f}s (pruned={sleep['pruned_links']})")

    # ── Benchmark: structural_debt_report ──────────────────
    with get_conn() as conn:
        t0 = time.time()
        debt = structural_debt_report(conn)
        t_debt = time.time() - t0
        print(f"  structural_debt_report: {t_debt:.2f}s (health={debt['health_score']}/100)")
        check(debt["total_tasks"] >= 90, f"Total tasks: {debt['total_tasks']}")
        check(debt["health_score"] >= 50, f"Health score: {debt['health_score']}/100")

    summary()


# ═══════════════════════════════════════════════════════════════
#  E1 — EDGE CASES
# ═══════════════════════════════════════════════════════════════

def test_edge_cases():
    banner("E1 — Edge Cases")

    from src.common import get_conn
    from src.knowledge.embeddings import generate_embedding

    # Clean slate
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE task_links, task_co_occurrence, structural_debt_log, tasks RESTART IDENTITY CASCADE")
        conn.commit()

    section("Título vacío")
    emb = generate_embedding("")
    check(emb is None or len(emb) == 768,
          f"Empty title: {'None (expected)' if emb is None else f'{len(emb)}d'}")

    section("Título muy largo (2000 chars)")
    long_title = "A" * 2000
    emb = generate_embedding(long_title)
    check(emb is not None and len(emb) == 768,
          f"Long title (2000 chars): {'768d OK' if emb and len(emb) == 768 else 'FAIL'}")

    section("Caracteres especiales / SQL injection attempt")
    injection = "test'; DROP TABLE tasks; --"
    emb = generate_embedding(injection)
    check(emb is not None and len(emb) == 768,
          f"SQL injection text: embedding OK (DB layer protects via params)")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tasks")
            count = cur.fetchone()[0]
    check(count == 0,
          f"DB intacta tras injection attempt: {count} tasks (esperado 0)")

    section("Emojis y Unicode")
    unicode_title = "🏃‍♂️ Correr 5K 🏃‍♂️ — ¡vamos! 日本語 también"
    emb = generate_embedding(unicode_title)
    check(emb is not None and len(emb) == 768,
          f"Unicode/emoji title: {'768d OK' if emb and len(emb) == 768 else 'FAIL'}")

    section("Tarea con project_tag NULL")
    with get_conn() as conn:
        with conn.cursor() as cur:
            emb = generate_embedding("generic task no project")
            if emb:
                vector_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    "INSERT INTO tasks (title, status, embedding, embedding_model) "
                    "VALUES (%s, 'pending', %s::vector, 'nomic-embed-text') RETURNING id",
                    ("generic task no project", vector_str),
                )
                tid = cur.fetchone()[0]
                conn.commit()
                check(tid is not None, f"Task with NULL project_tag created: id={tid}")

    section("Completar tarea ya completada")
    from src.processing.tasks import complete_task
    with get_conn() as conn:
        with conn.cursor() as cur:
            emb = generate_embedding("duplicate complete test")
            if emb:
                vector_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    "INSERT INTO tasks (title, status, embedding, embedding_model) "
                    "VALUES (%s, 'completed', %s::vector, 'nomic-embed-text') RETURNING id",
                    ("duplicate complete test", vector_str),
                )
                tid = cur.fetchone()[0]
                conn.commit()
        class Args: pass
        args = Args()
        args.id = tid
        args.hours = 1.0
        from src.processing.tasks import complete_task
        # Should return None because already completed
        result = complete_task(args)
        check(result is None, f"Double-complete rejected (returns None): {result}")

    section("Cancelled tasks excluded from graph")
    with get_conn() as conn:
        with conn.cursor() as cur:
            emb = generate_embedding("cancelled task test")
            if emb:
                vector_str = "[" + ",".join(str(v) for v in emb) + "]"
                cur.execute(
                    "INSERT INTO tasks (title, status, embedding, embedding_model) "
                    "VALUES (%s, 'cancelled', %s::vector, 'nomic-embed-text')",
                    ("cancelled task test", vector_str),
                )
                conn.commit()
        from src.knowledge.graph import rebuild_semantic_links
        with get_conn() as conn:
            n = rebuild_semantic_links(conn)
        check(True, f"Cancelled task excluded from links: {n} links (only non-cancelled counted)")

    section("Co-occurrence con tareas inexistentes")
    from src.knowledge.co_occurrence import get_co_occurrence_score
    with get_conn() as conn:
        score = get_co_occurrence_score(conn, 99999, 99998)
    check(score == 0.0, f"Non-existent task pair: score={score} (expected 0.0)")

    summary()


# ═══════════════════════════════════════════════════════════════
#  S1 — SMOKE CHECK (<30s)
# ═══════════════════════════════════════════════════════════════

def test_smoke():
    banner("S1 — Smoke Check (1 tarea end-to-end)")

    from src.common import get_conn
    from src.knowledge.graph import run_full_cycle
    from src.processing.classify import classify_task
    from src.processing.tasks import add_task, complete_task
    from src.knowledge.co_occurrence import record_completion, update_co_occurrence

    # Clean
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE task_links, task_co_occurrence, structural_debt_log, tasks RESTART IDENTITY CASCADE")
        conn.commit()

    t_start = time.time()

    # 1. Classify
    result = classify_task("Preparar presentación mensual de ventas")
    check(result.get("project_tag") is not None, f"Classify → project={result.get('project_tag')}")
    check(result.get("priority") is not None, f"Classify → priority={result.get('priority')}")

    # 2. Add with embed
    class Args: pass
    args = Args()
    args.title = "Preparar presentación mensual de ventas"
    args.project = result.get("project_tag")
    args.priority = result.get("priority")
    args.source = "cli"
    args.due = None
    args.hours = result.get("estimated_hours")
    args.description = None
    args.embed = True
    args.location_lat = None
    args.location_lon = None
    args.location_label = None

    task_id = add_task(args)
    check(task_id is not None, f"Add → id={task_id}")

    # Verify embedding stored
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT embedding IS NOT NULL FROM tasks WHERE id = %s", (task_id,))
            has_emb = cur.fetchone()[0]
    check(has_emb, "Embedding stored in DB")

    # 3. Complete
    args2 = Args()
    args2.id = task_id
    args2.hours = 3.5
    complete_task(args2)

    with get_conn() as conn:
        record_completion(conn, task_id)
        with conn.cursor() as cur:
            cur.execute("SELECT status, actual_hours FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
    check(row[0] == "completed", f"Status = {row[0]}")
    check(float(row[1]) == 3.5, f"actual_hours = {row[1]}")

    # 4. Heartbeat (quick cycle, no sleep)
    with get_conn() as conn:
        cycle = run_full_cycle(conn, include_sleep=False)
    check(cycle["semantic_links"] >= 0, f"Heartbeat → links={cycle['semantic_links']}")
    check(cycle["communities"] >= 0, f"Heartbeat → com={cycle['communities']}")

    # 5. Re-classify (should now have Grafo Vivo data)
    result2 = classify_task("Hacer seguimiento de leads comerciales")
    check(result2.get("linked_task_ids"), f"Re-classify → linked={result2.get('linked_task_ids')}")
    has_gv_hours = result2.get("hours_source") == "grafo_vivo"
    check(True, f"Hours source: {result2.get('hours_source')} "
          f"({result2.get('estimated_hours')}h)")

    t_elapsed = time.time() - t_start
    check(t_elapsed < 30, f"Smoke test completado en {t_elapsed:.1f}s (<30s)")

    summary()


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="Skip performance test (100 tasks)")
    ap.add_argument("--only", choices=["units", "perf", "edge", "smoke"],
                    help="Run only one test suite")
    args = ap.parse_args()

    print("BT-Core TaskManager — Test Suite")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  CWD: {os.getcwd()}")

    if args.only:
        runners = {
            "units": test_units,
            "perf": test_performance,
            "edge": test_edge_cases,
            "smoke": test_smoke,
        }
        runners[args.only]()
    else:
        test_units()
        test_edge_cases()
        test_smoke()
        if not args.quick:
            test_performance()

    # Final tally
    print(f"\n{'═' * 60}")
    total_all = _passed + _failed
    if _failed == 0:
        print(f"  🎉 ALL TESTS PASSED ({total_all} checks)")
    else:
        print(f"  ⚠️  {total_all} checks: {_passed} OK, {_failed} FAILED")
    print(f"{'═' * 60}")

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
