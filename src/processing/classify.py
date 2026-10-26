#!/usr/bin/env python3
"""Classify Task — Grafo Vivo-powered classification.

Architecture:
  - Capa 1 (Semántica): linked_task_ids via pgvector cosine similarity
  - Capa 4 (Predictiva): estimated_hours via cluster avg actual_hours
  - DeepSeek: project_tag + priority only (what requires intelligence)

The Grafo Vivo provides data. DeepSeek provides reasoning.
Together: el Círculo Virtuoso completo.

Usage:
    python3 -m src.processing.classify "Terminar Lab 2 de Empotrados"
"""

import argparse
import json
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common import get_conn, deepseek_generate
from src.knowledge.embeddings import classify_context
from src.knowledge.graph import cluster_stats_for_task

SYSTEM_PROMPT = (
    "Eres un clasificador de tareas técnicas. "
    "Dada una tarea nueva y su contexto, determina ÚNICAMENTE el project_tag "
    "y la prioridad. Las horas estimadas y los linked_task_ids ya fueron "
    "calculados por el sistema. "
    "Responde SIEMPRE con un JSON: "
    '{"project_tag": "...", "priority": <int>}'
)

VALID_PROJECTS = [
    "Empotrados", "Computer Vision", "HPE", "Personal",
    "Universidad", "Finanzas", "Salud", "Hogar",
]


def classify_task(text: str):
    """Classify a task using Grafo Vivo + DeepSeek.

    Returns:
        {project_tag, priority, estimated_hours, linked_task_ids}
    """
    conn = None
    similar = []
    cluster_stats = {}
    linked_ids = []

    try:
        conn = get_conn()
        # ── Capa 1: Semantic neighbors ──────────────────────
        similar = classify_context(conn, text, limit=5)
        linked_ids = [t["id"] for t in similar if t.get("id")]

        # ── Capa 4: Cluster-based estimated_hours ───────────
        if linked_ids:
            # Use the first similar task's cluster as anchor
            cluster_stats = cluster_stats_for_task(conn, linked_ids[0])
    except Exception as e:
        print(f"Grafo Vivo lookup failed: {e}", file=sys.stderr)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # ── Grafo Vivo provides estimated_hours ──────────────────
    if cluster_stats and cluster_stats.get("avg_actual_hours"):
        estimated_hours = round(cluster_stats["avg_actual_hours"], 1)
        hours_source = "grafo_vivo"
    else:
        estimated_hours = 1.0
        hours_source = "default"

    # ── DeepSeek provides project_tag + priority ─────────────
    context_lines = []
    if similar:
        context_lines.append("Tareas similares encontradas:")
        for t in similar[:3]:
            actual = f" ({t.get('actual_hours', '?')}h reales)" if t.get("actual_hours") else ""
            context_lines.append(f"  - {t['title'][:60]} → {t.get('project_tag', '?')}{actual}")

    prompt = (
        f"Tarea: {text}\n\n"
        + ("\n".join(context_lines) if context_lines else "Sin contexto adicional.") +
        f"\n\nClasifica project_tag de esta lista: {', '.join(VALID_PROJECTS)}.\n"
        f"Asigna prioridad (1=baja, 5=urgente).\n"
        f"Las horas YA fueron calculadas por el sistema como {estimated_hours}h "
        f"(basado en {hours_source}).\n"
        f"Responde SOLO el JSON con project_tag y priority."
    )

    project_tag = "Personal"
    priority = 3

    try:
        result = deepseek_generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.2)
        if result and isinstance(result, dict):
            project_tag = result.get("project_tag", "Personal")
            priority = int(result.get("priority", 3))
    except Exception as e:
        print(f"DeepSeek classify error: {e}", file=sys.stderr)

    return {
        "project_tag": project_tag,
        "priority": priority,
        "estimated_hours": estimated_hours,
        "linked_task_ids": linked_ids,
        "hours_source": hours_source,
        "cluster_size": cluster_stats.get("cluster_size", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Task Classification (Grafo Vivo + DeepSeek)")
    parser.add_argument("text", nargs="+")
    args = parser.parse_args()
    result = classify_task(" ".join(args.text))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
