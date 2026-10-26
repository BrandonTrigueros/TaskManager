#!/usr/bin/env python3
"""BT-Core: TaskManager — Single Source of Truth (SSOT).

Infraestructura compartida para todos los nodos federados (LOQ Hub, X220, HP).
Proporciona:
  - Pool de conexiones PostgreSQL (psycopg2 ThreadedConnectionPool)
  - Gemini REST API client (Vision/OCR, Zscaler-safe, sin gRPC)
  - DeepSeek REST API client (clasificación, razonamiento, Vision Diff)
  - Helpers JSON tolerantes a markdown fences

Principio: urllib nativo únicamente — zero-deps más allá de psycopg2.
"""

import json
import os
import ssl
import sys
import threading
import urllib.request
import urllib.error

import psycopg2
import psycopg2.extras
from psycopg2 import pool


# ═══════════════════════════════════════════════════════════════
#  Auto-load .env file (zero-dependency)
# ═══════════════════════════════════════════════════════════════

def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Only sets keys that are NOT already in the environment (env vars
    take precedence over .env). Expands ${VAR} references using values
    already loaded from the same file or from the existing environment.
    """
    import re
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            # Strip inline comments (text after whitespace+# that looks like a comment)
            import re as _re2
            value = _re2.sub(r"\s+#.*$", "", value).strip()
            value = value.strip("\"'")
            # Don't override existing env vars
            if not key or key in os.environ:
                continue
            # Expand ${VAR} references using currently loaded env
            def _expand(m: re.Match) -> str:
                return os.environ.get(m.group(1), m.group(0))
            value = re.sub(r"\$\{(\w+)\}", _expand, value)
            os.environ[key] = value


# Walk up from this file to find project root .env
_current_dir = os.path.dirname(os.path.abspath(__file__))
for _ in range(5):  # max 5 levels up
    _env_path = os.path.join(_current_dir, ".env")
    if os.path.isfile(_env_path):
        _load_dotenv(_env_path)
        break
    _parent = os.path.dirname(_current_dir)
    if _parent == _current_dir:
        break
    _current_dir = _parent

# ═══════════════════════════════════════════════════════════════
#  Database — Threaded Connection Pool
# ═══════════════════════════════════════════════════════════════

def _build_dsn() -> str:
    """Build PostgreSQL DSN from DB_DSN or individual env vars.

    All values come from .env (loaded by _load_dotenv) or Docker environment.
    No hardcoded defaults — fails loud if misconfigured.
    """
    dsn = os.environ.get("DB_DSN")
    if dsn:
        return dsn
    host = os.environ["BT_DB_HOST"]
    port = os.environ["BT_DB_PORT"]
    user = os.environ["POSTGRES_USER"]
    pw = os.environ["POSTGRES_PASSWORD"]
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


DSN = _build_dsn()

# Pool size — dimensionado para el Hub LOQ manejando requests simultáneos
# de X220 + HP + Telegram webhook. Ajustar según carga.
_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "2"))
_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "10"))

_connection_pool: "pool.ThreadedConnectionPool | None" = None
_pool_lock = threading.Lock()


def _init_pool() -> pool.ThreadedConnectionPool:
    """Lazy-init the thread-safe connection pool (double-checked locking)."""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                _connection_pool = pool.ThreadedConnectionPool(
                    _POOL_MIN, _POOL_MAX, DSN
                )
    return _connection_pool


def pool_status() -> dict:
    """Return pool metrics for monitoring. Safe to call before init."""
    p = _connection_pool
    if p is None:
        return {"initialized": False, "min": _POOL_MIN, "max": _POOL_MAX}
    return {
        "initialized": True,
        "min": _POOL_MIN,
        "max": _POOL_MAX,
        "used": len(p._used) if hasattr(p, "_used") else "?",
        "free": len(p._pool) if hasattr(p, "_pool") else "?",
    }


class _PooledConnectionWrapper:
    """Wraps a psycopg2 connection so that .close() returns it to the pool.

    This preserves backward compatibility: all existing code that calls
    get_conn() and later conn.close() will automatically return the
    connection to the pool instead of closing it permanently.

    Context manager support:
        with get_conn() as conn:
            conn.cursor().execute(...)
            conn.commit()
        # Connection is automatically returned to pool on block exit.
    """

    __slots__ = ("_conn", "_closed")

    def __init__(self, conn):
        self._conn = conn
        self._closed = False

    def __getattr__(self, name):
        if self._closed:
            raise psycopg2.InterfaceError("connection already closed (returned to pool)")
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit on success, rollback on error, always return to pool."""
        if self._closed:
            return
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self.close()

    def close(self):
        """Return connection to pool instead of permanently closing it.

        Idempotent: safe to call multiple times (double-close protection).
        """
        if self._closed:
            return
        self._closed = True
        p = _connection_pool
        if p is not None and self._conn is not None:
            try:
                p.putconn(self._conn)
                self._conn = None
                return
            except Exception:
                pass
        # Fallback: real close if pool is gone or putconn failed
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self):
        if not self._closed:
            try:
                self.close()
            except Exception:
                pass

    def __repr__(self) -> str:
        try:
            dsn = self._conn.dsn if hasattr(self._conn, "dsn") else "?"
            closed = self._conn.closed if hasattr(self._conn, "closed") else "?"
            return f"<PooledConnection dsn={dsn} closed={closed}>"
        except Exception:
            return "<PooledConnection ?>"


def get_conn():
    """Get a database connection from the pool.

    Returns a wrapped connection — calling .close() returns it to the pool.
    Thread-safe for concurrent access from LOQ Hub.
    """
    return _PooledConnectionWrapper(_init_pool().getconn())


def jprint(data):
    """Print JSON to stdout with default serializer (handles dates, Decimals)."""
    print(json.dumps(data, default=str, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════
#  Gemini REST API — Vision / OCR (Zscaler-safe, urllib nativo)
# ═══════════════════════════════════════════════════════════════

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

_CA_FILE = "/etc/ssl/certs/ca-certificates.crt"
_SSL_CTX = ssl.create_default_context(cafile=_CA_FILE) if os.path.exists(_CA_FILE) else None


def gemini_generate(prompt: str, image_base64: str | None = None) -> dict | None:
    """Call Gemini REST API with JSON response mode.

    Args:
        prompt: Text prompt (español).
        image_base64: Optional inline image for Vision/OCR.

    Returns:
        Parsed JSON dict, or None on failure.

    Bypasses gRPC/Zscaler issues by using urllib + REST.
    """
    if not GEMINI_API_KEY:
        print("Gemini: GEMINI_API_KEY not set", file=sys.stderr)
        return None

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    parts: list[dict] = [{"text": prompt}]
    if image_base64:
        parts.append({
            "inlineData": {
                "mimeType": "image/jpeg",
                "data": image_base64,
            }
        })

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_text(text)
    except Exception as e:
        print(f"Gemini API error: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
#  DeepSeek REST API — Clasificación / Razonamiento / Vision Diff
# ═══════════════════════════════════════════════════════════════

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_CLASSIFY_MODEL = os.environ.get("DEEPSEEK_CLASSIFY_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = os.environ.get("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")


def deepseek_generate(
    prompt: str,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.3,
) -> dict | None:
    """Call DeepSeek REST API.

    Args:
        prompt: User message (español).
        model: Model to use. Defaults to DEEPSEEK_CLASSIFY_MODEL (deepseek-chat).
               Use DEEPSEEK_REASONER_MODEL (deepseek-reasoner) for Vision Diff.
        system_prompt: Optional system-level instruction.
        temperature: 0.0–1.0. Lower = más determinístico para clasificación.

    Returns:
        Parsed JSON dict, or None on failure.
    """
    if not DEEPSEEK_API_KEY:
        print("DeepSeek: DEEPSEEK_API_KEY not set", file=sys.stderr)
        return None

    if model is None:
        model = DEEPSEEK_CLASSIFY_MODEL

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=payload,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=120) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        return parse_json_text(text)
    except Exception as e:
        print(f"DeepSeek API error: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
#  JSON Helpers
# ═══════════════════════════════════════════════════════════════

def parse_json_text(text: str) -> dict | list | None:
    """Parse JSON from LLM response, handling markdown fences and noise.

    Tolera todas estas variantes que los LLMs sueltan en producción:
      ```json
      { ... }
      ```
      ```json{ ... }```           (inline fence, sin newline)
      ```{ ... }```              (sin language tag)
      Sure! Here's the JSON:   (texto antes del JSON)
      { ... }
      ```
      { ... }                     (JSON desnudo, sin fences)

    Estrategia: intentar parsear el texto completo primero. Si falla,
    buscar el primer { o [ y el último } o ], y parsear ese slice.
    Si aún falla, intentar después de strippear fences markdown.
    """
    if not text or not text.strip():
        return None

    # Attempt 1: parse the whole thing as-is
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: strip markdown code fences, then try the whole block
    cleaned = text.strip()
    # Remove opening ``` (with or without language tag)
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
    # Remove closing ```
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    if cleaned:
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

    # Attempt 3: find the outermost { } or [ ] and parse just that
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            candidate = cleaned[start:end + 1]
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                pass

    # Attempt 4: same as 3 but on the original text (in case cleaning broke it)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                pass

    print(f"JSON parse failed for text: {text[:200]}...", file=sys.stderr)
    return None
