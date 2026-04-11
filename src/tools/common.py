#!/usr/bin/env python3
"""Common — Shared infrastructure for all Hartbeat tools.

Provides:
  - Database connection (DSN from env)
  - Gemini REST API client (Zscaler-safe, no gRPC)
  - JSON helpers
"""

import json
import os
import ssl
import sys
import urllib.request
import urllib.error

import psycopg2
import psycopg2.extras

# ─── Database ─────────────────────────────────────────────────

def _build_dsn() -> str:
    """Build PostgreSQL DSN from DB_DSN or individual DB_* vars."""
    dsn = os.environ.get("DB_DSN")
    if dsn:
        return dsn
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "hb_admin")
    pw = os.environ.get("POSTGRES_PASSWORD", "changeme")
    db = os.environ.get("POSTGRES_DB", "heartbeat")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


DSN = _build_dsn()


def get_conn():
    """Get a new psycopg2 connection to the Hartbeat database."""
    return psycopg2.connect(DSN)


def jprint(data):
    """Print JSON to stdout (default serializer handles dates, Decimals)."""
    print(json.dumps(data, default=str, ensure_ascii=False))


# ─── Gemini REST API ─────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

_CA_FILE = "/etc/ssl/certs/ca-certificates.crt"
_SSL_CTX = ssl.create_default_context(cafile=_CA_FILE) if os.path.exists(_CA_FILE) else None


def gemini_generate(prompt: str) -> dict | None:
    """Call Gemini REST API with JSON response mode. Bypasses gRPC/Zscaler issues."""
    if not GEMINI_API_KEY:
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_text(text)
    except Exception as e:
        print(f"Gemini API error: {e}", file=sys.stderr)
        return None


def parse_json_text(text: str) -> dict | list | None:
    """Parse JSON from Gemini response text, handling markdown fences."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
