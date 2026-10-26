#!/usr/bin/env python3
"""Embeddings — Semantic indexing for the federated BT-Core network.

Provides:
  - Ollama REST API client for nomic-embed-text (768d, LOQ Hub)
  - pgvector cosine similarity search against the tasks table
  - Graceful fallback to text-based search when Ollama is unreachable

Standard: 768-dimensional vectors. Mathematically interchangeable between
bge-base-en-v1.5 (spoke CPU) and nomic-embed-text (hub GPU).
"""

import json
import os
import sys
import urllib.request
import urllib.error

# ═══════════════════════════════════════════════════════════════
#  Ollama Embedding API (LOQ Hub, port 11434)
# ═══════════════════════════════════════════════════════════════

OLLAMA_URL = os.environ.get("BT_OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("BT_OLLAMA_EMBED_MODEL", "nomic-embed-text")


def generate_embedding(text: str) -> list[float] | None:
    """Generate a 768d embedding via Ollama REST API.

    Returns None if Ollama is unreachable — caller should fall back to
    text-based similarity (pg_trgm / ILIKE).
    """
    url = f"{OLLAMA_URL}/api/embeddings"
    payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        embedding = data.get("embedding")
        if embedding and len(embedding) == 768:
            return embedding
        print(f"Embedding: unexpected dims {len(embedding) if embedding else 0}, expected 768",
              file=sys.stderr)
        return None
    except Exception as e:
        print(f"Ollama embedding unavailable ({e}), falling back to text search",
              file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
#  Similarity Search
# ═══════════════════════════════════════════════════════════════

def find_similar_vector(conn, embedding: list[float], limit: int = 5) -> list[dict]:
    """Find top-N similar tasks by cosine similarity (pgvector <=>).

    Args:
        conn: psycopg2 connection (or _PooledConnectionWrapper).
        embedding: 768d vector from generate_embedding().
        limit: max results.

    Returns list of dicts with id, title, project_tag, estimated_hours,
    actual_hours, similarity.
    """
    vector_str = "[" + ",".join(str(v) for v in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, project_tag, priority, estimated_hours, actual_hours,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM tasks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vector_str, vector_str, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "title": r[1], "project_tag": r[2],
            "priority": r[3], "estimated_hours": float(r[4]) if r[4] else None,
            "actual_hours": float(r[5]) if r[5] else None,
            "similarity": round(float(r[6]), 4),
        }
        for r in rows
    ]


def find_similar_text(conn, text: str, limit: int = 5) -> list[dict]:
    """Fallback: find similar tasks by pg_trgm text similarity.

    Used when Ollama is unreachable and no vector search is possible.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, project_tag, priority, estimated_hours, actual_hours,
                   similarity(title, %s) AS sim
            FROM tasks
            WHERE title IS NOT NULL
            ORDER BY sim DESC
            LIMIT %s
            """,
            (text, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "title": r[1], "project_tag": r[2],
            "priority": r[3], "estimated_hours": float(r[4]) if r[4] else None,
            "actual_hours": float(r[5]) if r[5] else None,
            "similarity": round(float(r[6]), 4),
        }
        for r in rows if r[6] > 0.05  # filter noise
    ]


def classify_context(conn, text: str, limit: int = 5) -> list[dict]:
    """Retrieve top-N similar tasks for classification context (REQ-T7).

    Tries vector search first (Ollama → pgvector), falls back to
    pg_trgm text similarity if embedding generation fails.

    Returns list of dicts, may be empty if no similar tasks exist.
    """
    embedding = generate_embedding(text)
    if embedding:
        results = find_similar_vector(conn, embedding, limit)
        if results:
            return results
    # Fallback: pg_trgm text search
    return find_similar_text(conn, text, limit)
