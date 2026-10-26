#!/usr/bin/env python3
"""Grafo Vivo — 4-layer + HeLa-Mem + CogniFold + Consolidación.

Layer 1 — SEMÁNTICA:     cosine similarity via pgvector
Layer 2 — TEMPORAL:       Hebbian decay e^(-λ·Δt)
Layer H — HeLa-Mem:       Co-occurrence conductual (salto asociativo)
Layer 3 — ESTRUCTURAL:    hierarchical clustering → communities
Layer 4 — PREDICTIVA:     cluster actual_hours + confidence intervals
Layer 5 — CONSOLIDACIÓN:  prune, merge, archive, recenter (sueño)
Layer 6 — COGNIFOLD:      structural debt dashboard

Combined weight = β_sem·cos + β_temp·e^(-λ·Δt) + β_cooc·cooc_score
"""

import math
import sys
import numpy as np
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import psycopg2.extras

# ── Hyperparameters ───────────────────────────────────────────
LAMBDA = 0.001              # Temporal decay rate (half-life ~29 days)
BETA_SEM = 0.55             # Semantic weight in combined score
BETA_TEMP = 0.30            # Temporal weight in combined score
BETA_COOC = 0.15            # Co-occurrence weight (HeLa-Mem)
MIN_SIMILARITY = 0.3        # Minimum cosine sim to create a link
TOP_K = 5                   # Max neighbors per task
PRUNE_WEIGHT_THRESHOLD = 0.1     # Links below this get pruned
MERGE_JACCARD_THRESHOLD = 0.5    # Communities with Jaccard > this get merged
ARCHIVE_DAYS = 90                # Tasks inactive > this get archived


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(dt: datetime) -> float:
    if dt is None:
        return 0.0
    delta = now_utc() - dt
    return delta.total_seconds() / 3600.0


def temporal_weight(hours_elapsed: float) -> float:
    """Hebbian decay: e^(-λ·Δt). Half-life ~29 days."""
    return math.exp(-LAMBDA * hours_elapsed)


def _get_cooc_score(conn, task_a: int, task_b: int) -> float:
    """Lookup co-occurrence score from task_co_occurrence table."""
    a, b = (task_a, task_b) if task_a < task_b else (task_b, task_a)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT co_score FROM task_co_occurrence WHERE task_id_a = %s AND task_id_b = %s",
            (a, b),
        )
        row = cur.fetchone()
    return float(row[0]) if row else 0.0


def combined_weight(cosine_sim: float, hours_elapsed: float,
                    cooc_score: float = 0.0) -> float:
    """3-factor edge weight: semantic + temporal + co-occurrence."""
    tw = temporal_weight(hours_elapsed)
    return BETA_SEM * cosine_sim + BETA_TEMP * tw + BETA_COOC * cooc_score


# ═══════════════════════════════════════════════════════════════
#  Capa 1+2+H — Reconstruir links (3-factor weight)
# ═══════════════════════════════════════════════════════════════

def rebuild_semantic_links(conn) -> int:
    """Rebuild task_links with 3-factor weight (semantic+temp+cooc)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, embedding, created_at FROM tasks "
            "WHERE embedding IS NOT NULL AND status NOT IN ('cancelled', 'archived')"
        )
        tasks = [(r[0], r[1], r[2]) for r in cur.fetchall()]

    link_count = 0
    for task_id, emb, created in tasks:
        hours = _hours_since(created)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO task_links (task_id, linked_task_id, similarity, weight, temporal_score)
                   SELECT %s, id,
                          1 - (embedding <=> %s::vector) AS sim,
                          0.0 AS weight,
                          %s AS temporal_score
                   FROM tasks
                   WHERE id != %s
                     AND embedding IS NOT NULL
                     AND status NOT IN ('cancelled', 'archived')
                     AND 1 - (embedding <=> %s::vector) > %s
                   ORDER BY embedding <=> %s::vector
                   LIMIT %s
                   ON CONFLICT (task_id, linked_task_id)
                   DO UPDATE SET similarity = EXCLUDED.similarity,
                                 temporal_score = EXCLUDED.temporal_score""",
                (task_id, emb, temporal_weight(hours),
                 task_id, emb, MIN_SIMILARITY, emb, TOP_K),
            )
            link_count += cur.rowcount
    conn.commit()

    # Apply 3-factor weights (needs cooc lookup)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT tl.task_id, tl.linked_task_id, tl.similarity,
                      t.created_at
               FROM task_links tl
               JOIN tasks t ON t.id = tl.linked_task_id"""
        )
        rows = cur.fetchall()

    for task_id, linked_id, sim, linked_created in rows:
        sim = float(sim)
        hours = _hours_since(linked_created)
        cooc = _get_cooc_score(conn, task_id, linked_id)
        cw = combined_weight(sim, hours, cooc)
        tw = temporal_weight(hours)
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE task_links
                   SET weight = %s, temporal_score = %s
                   WHERE task_id = %s AND linked_task_id = %s""",
                (cw, tw, task_id, linked_id),
            )
    conn.commit()
    return link_count


# ═══════════════════════════════════════════════════════════════
#  Capa 2 — Actualización de pesos temporales
# ═══════════════════════════════════════════════════════════════

def update_temporal_weights(conn) -> int:
    """Recalculate 3-factor weights for all links."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT tl.task_id, tl.linked_task_id, tl.similarity,
                      t.created_at
               FROM task_links tl
               JOIN tasks t ON t.id = tl.linked_task_id
               WHERE t.status NOT IN ('cancelled', 'archived')"""
        )
        rows = cur.fetchall()

    updated = 0
    for task_id, linked_id, sim, created in rows:
        sim = float(sim)
        hours = _hours_since(created)
        tw = temporal_weight(hours)
        cooc = _get_cooc_score(conn, task_id, linked_id)
        cw = combined_weight(sim, hours, cooc)
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE task_links
                   SET temporal_score = %s, weight = %s
                   WHERE task_id = %s AND linked_task_id = %s""",
                (tw, cw, task_id, linked_id),
            )
            updated += cur.rowcount
    conn.commit()
    return updated


# ═══════════════════════════════════════════════════════════════
#  Capa 3 — Estructural (community detection)
# ═══════════════════════════════════════════════════════════════

def _build_adjacency(conn) -> dict[int, dict[int, float]]:
    adj = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT task_id, linked_task_id, weight FROM task_links WHERE weight > 0.1"
        )
        for tid, lid, w in cur.fetchall():
            adj[tid][lid] = float(w)
            adj[lid][tid] = float(w)
    return dict(adj)


def detect_communities(conn) -> list[dict]:
    """Detect communities with cohesion, confidence intervals, planning ratio."""
    adj = _build_adjacency(conn)
    if len(adj) < 3:
        return []

    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform

    node_ids = sorted(adj.keys())
    n = len(node_ids)

    dist = np.zeros((n, n))
    for i, a in enumerate(node_ids):
        for j, b in enumerate(node_ids):
            if i == j:
                dist[i][j] = 0.0
            elif b in adj.get(a, {}):
                dist[i][j] = 1.0 - adj[a][b]
            else:
                dist[i][j] = 1.0

    condensed = squareform(dist)
    Z = linkage(condensed, method="average")
    clusters = fcluster(Z, t=0.4, criterion="distance")
    cluster_map = defaultdict(list)
    for node_idx, cluster_id in enumerate(clusters):
        cluster_map[int(cluster_id)].append(node_ids[node_idx])

    result = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for cid, members in cluster_map.items():
            if len(members) < 2:
                continue
            cur.execute(
                "SELECT id, title, project_tag, estimated_hours, actual_hours "
                "FROM tasks WHERE id = ANY(%s)",
                (members,),
            )
            tasks = cur.fetchall()

            tags = list(set(t.get("project_tag") for t in tasks if t.get("project_tag")))
            est_vals = [t.get("estimated_hours") or 0 for t in tasks]
            act_vals = [t.get("actual_hours") for t in tasks if t.get("actual_hours")]

            avg_est = float(np.mean(est_vals)) if est_vals else 0.0
            avg_act = float(np.mean(act_vals)) if act_vals else None
            std_act = float(np.std(act_vals)) if act_vals and len(act_vals) >= 2 else None

            # Confidence interval
            ci_lower = round(avg_act - std_act, 1) if avg_act is not None and std_act is not None else None
            ci_upper = round(avg_act + std_act, 1) if avg_act is not None and std_act is not None else None

            # Planning ratio
            planning_ratio = round(avg_act / avg_est, 2) if avg_act and avg_est > 0 else None
            planning_bias = None
            if planning_ratio is not None:
                if planning_ratio > 1.3:
                    planning_bias = "underestimate"
                elif planning_ratio < 0.7:
                    planning_bias = "overestimate"
                else:
                    planning_bias = "accurate"

            # Cohesion
            internal_edges = sum(
                adj[a].get(b, 0) for a in members for b in members if a < b
            )
            max_edges = len(members) * (len(members) - 1) / 2
            cohesion = internal_edges / max_edges if max_edges > 0 else 0.0

            result.append({
                "community_id": int(cid),
                "size": len(members),
                "task_ids": members,
                "project_tags": tags,
                "avg_estimated_hours": round(avg_est, 1),
                "avg_actual_hours": round(avg_act, 1) if avg_act is not None else None,
                "std_actual_hours": round(std_act, 1) if std_act is not None else None,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "planning_ratio": planning_ratio,
                "planning_bias": planning_bias,
                "cohesion": round(cohesion, 3),
                "suggested_subproject": cohesion > 0.6 and len(members) >= 5,
            })

    return sorted(result, key=lambda c: c["cohesion"], reverse=True)


# ═══════════════════════════════════════════════════════════════
#  Capa 4 — Predictiva (CI + planning ratio)
# ═══════════════════════════════════════════════════════════════

def cluster_stats_for_task(conn, task_id: int) -> dict:
    """Predictive stats with confidence intervals and planning ratio."""
    communities = detect_communities(conn)
    my_community = None
    for c in communities:
        if task_id in c["task_ids"]:
            my_community = c
            break

    if my_community is None:
        return {
            "avg_actual_hours": None, "cluster_size": 0, "projects": [],
            "cohesion": 0.0, "community_id": None,
            "ci_lower": None, "ci_upper": None,
            "planning_ratio": None, "planning_bias": None,
        }

    return {
        "avg_actual_hours": my_community["avg_actual_hours"],
        "std_actual_hours": my_community.get("std_actual_hours"),
        "ci_lower": my_community.get("ci_lower"),
        "ci_upper": my_community.get("ci_upper"),
        "planning_ratio": my_community.get("planning_ratio"),
        "planning_bias": my_community.get("planning_bias"),
        "cluster_size": my_community["size"],
        "projects": my_community["project_tags"],
        "cohesion": my_community["cohesion"],
        "community_id": my_community["community_id"],
        "avg_estimated_hours": my_community["avg_estimated_hours"],
    }


def planning_bias_by_project(conn) -> list[dict]:
    """Global planning bias report: ratio per project_tag."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT project_tag,
                   COUNT(*) AS task_count,
                   COALESCE(AVG(actual_hours), 0) AS avg_actual,
                   COALESCE(AVG(estimated_hours), 0) AS avg_estimated,
                   CASE WHEN AVG(estimated_hours) > 0
                        THEN AVG(actual_hours) / AVG(estimated_hours)
                        ELSE NULL END AS ratio
            FROM tasks
            WHERE actual_hours IS NOT NULL
              AND estimated_hours IS NOT NULL
              AND project_tag IS NOT NULL
            GROUP BY project_tag
            HAVING COUNT(*) >= 2
            ORDER BY ratio DESC
        """)
        rows = cur.fetchall()
    result = []
    for r in rows:
        ratio = float(r["ratio"]) if r["ratio"] else None
        bias = None
        if ratio is not None:
            if ratio > 1.3:
                bias = "⏱️ subestimás"
            elif ratio < 0.7:
                bias = "🐢 sobreestimás"
            else:
                bias = "✅ preciso"
        result.append({
            "project_tag": r["project_tag"],
            "task_count": r["task_count"],
            "avg_actual": round(float(r["avg_actual"]), 1),
            "avg_estimated": round(float(r["avg_estimated"]), 1),
            "ratio": round(ratio, 2) if ratio else None,
            "bias": bias,
        })
    return result


# ═══════════════════════════════════════════════════════════════
#  Capa 5 — Consolidación de Sueño
# ═══════════════════════════════════════════════════════════════

def consolidate_sleep(conn) -> dict:
    """Nightly consolidation: prune dead links, merge overlapping communities,
    archive inactive tasks, recenter weights."""
    stats = {}

    # PODA
    with conn.cursor() as cur:
        cur.execute("DELETE FROM task_links WHERE weight < %s",
                    (PRUNE_WEIGHT_THRESHOLD,))
        stats["pruned_links"] = cur.rowcount

    # FUSIÓN de comunidades solapadas (Jaccard > 0.5)
    communities = detect_communities(conn)
    merged = 0
    merged_ids = set()
    for i, c1 in enumerate(communities):
        if c1["community_id"] in merged_ids:
            continue
        set1 = set(c1["task_ids"])
        for j, c2 in enumerate(communities):
            if j <= i or c2["community_id"] in merged_ids:
                continue
            set2 = set(c2["task_ids"])
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            jaccard = intersection / union if union > 0 else 0
            if jaccard > MERGE_JACCARD_THRESHOLD:
                merged += 1
                merged_ids.add(c2["community_id"])
                for a in c1["task_ids"]:
                    for b in c2["task_ids"]:
                        if a == b:
                            continue
                        with conn.cursor() as cur:
                            cur.execute(
                                """INSERT INTO task_links (task_id, linked_task_id,
                                   similarity, weight, temporal_score)
                                   VALUES (%s, %s, 0.5, 0.5, 1.0)
                                   ON CONFLICT (task_id, linked_task_id)
                                   DO UPDATE SET weight = GREATEST(task_links.weight, 0.5)""",
                                (a, b),
                            )
    conn.commit()
    stats["merged_communities"] = merged

    # ARCHIVADO
    cutoff = now_utc() - timedelta(days=ARCHIVE_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE tasks SET status = 'archived'
               WHERE status IN ('pending', 'in_progress')
                 AND last_activity_at < %s""",
            (cutoff,),
        )
        stats["archived_tasks"] = cur.rowcount

    # RECENTER
    stats["recentered_links"] = update_temporal_weights(conn)
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════════
#  Capa 6 — Deuda Estructural (CogniFold)
# ═══════════════════════════════════════════════════════════════

def structural_debt_report(conn) -> dict:
    """Compute CogniFold's 4 structural debts and health score."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('cancelled', 'archived')"
        )
        total_tasks = cur.fetchone()[0] or 1
        cur.execute("SELECT COUNT(*) FROM task_links WHERE weight > 0")
        total_links = cur.fetchone()[0] or 1

        # 1. ACUMULACIÓN — orphan tasks
        cur.execute("""
            SELECT COUNT(*) FROM tasks t
            WHERE t.status NOT IN ('cancelled', 'archived')
              AND NOT EXISTS (
                  SELECT 1 FROM task_links tl
                  WHERE tl.task_id = t.id OR tl.linked_task_id = t.id
              )
        """)
        orphan_tasks = cur.fetchone()[0]

        # 2. DECAIMIENTO — dead links
        cur.execute(
            "SELECT COUNT(*) FROM task_links WHERE weight < %s",
            (PRUNE_WEIGHT_THRESHOLD,),
        )
        dead_links = cur.fetchone()[0]

    # 3. COMPRESIÓN — fragmentation
    communities = detect_communities(conn)
    total_communities = len(communities)
    fragmentation = round(total_communities / total_tasks, 4)

    # 4. COMPLETITUD — graph density
    max_possible = total_tasks * (total_tasks - 1) / 2
    graph_density = round(total_links / max_possible, 4) if max_possible > 0 else 0.0

    # Log
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO structural_debt_log
               (orphan_tasks, dead_links, fragmentation, graph_density,
                total_tasks, total_links, total_communities)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (orphan_tasks, dead_links, fragmentation, graph_density,
             total_tasks, total_links, total_communities),
        )
    conn.commit()

    # Health score 0–100
    orphan_pct = orphan_tasks / total_tasks
    dead_pct = dead_links / total_links
    frag_penalty = max(0, fragmentation - 0.3) * 100
    health = max(0, 100 - orphan_pct * 40 - dead_pct * 30 - frag_penalty)
    health = min(100, round(health, 1))

    return {
        "orphan_tasks": orphan_tasks, "orphan_pct": round(orphan_pct * 100, 1),
        "dead_links": dead_links, "dead_pct": round(dead_pct * 100, 1),
        "fragmentation": fragmentation, "graph_density": graph_density,
        "total_tasks": total_tasks, "total_links": total_links,
        "total_communities": total_communities,
        "health_score": health,
    }


# ═══════════════════════════════════════════════════════════════
#  Full cycle
# ═══════════════════════════════════════════════════════════════

def run_full_cycle(conn, include_sleep: bool = False) -> dict:
    """Execute all layers of the Grafo Vivo cycle.

    Args:
        conn: DB connection
        include_sleep: if True, also run consolidation (prune/merge/archive)
    """
    from src.knowledge.co_occurrence import update_co_occurrence

    stats = {}

    # Capa H: HeLa-Mem co-occurrence
    n_cooc = update_co_occurrence(conn)
    stats["co_occurrence_pairs"] = n_cooc

    # Capa 1+2+H: Semantic links with 3-factor weight
    stats["semantic_links"] = rebuild_semantic_links(conn)

    # Capa 2: Temporal weight update
    stats["temporal_updates"] = update_temporal_weights(conn)

    # Capa 3: Community detection
    communities = detect_communities(conn)
    stats["communities"] = len(communities)
    stats["subproject_candidates"] = sum(
        1 for c in communities if c.get("suggested_subproject")
    )

    # Capa 5: Consolidation (nightly)
    if include_sleep:
        sleep_stats = consolidate_sleep(conn)
        stats.update({f"sleep_{k}": v for k, v in sleep_stats.items()})

    # Capa 6: Structural debt
    debt = structural_debt_report(conn)
    stats["debt_health_score"] = debt["health_score"]
    stats["debt_orphan_pct"] = debt["orphan_pct"]
    stats["debt_dead_pct"] = debt["dead_pct"]

    return stats
