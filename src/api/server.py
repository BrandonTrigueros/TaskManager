#!/usr/bin/env python3
"""API HTTP local — puente entre el cliente Android y el backend existente.

La app Kotlin no reimplementa el Grafo Vivo: habla con este proceso, que
reutiliza `next_action`, `tasks` y la base de datos tal como están.

Seguridad:
  - Auth por `Authorization: Bearer <API_TOKEN>`.
  - Las claves de Gemini/DeepSeek viven en el `.env` de ESTE proceso.
    La app nunca las recibe ni las guarda.
  - Pensado para LAN local (o un teléfono en la misma red), no para
exponerse a internet.

Endpoints:
    GET  /health
    GET  /hoy
    POST /decisions/{id}/close    {"executed": true, "hours": 3.2}
    GET  /tasks?status=pending&limit=50
    POST /tasks                   {"title": "...", "project": "...", ...}

Uso:
    python3 -m src.api.server
    API_PORT=9000 API_TOKEN=secreto python3 -m src.api.server
"""

import json
import os
import sys
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src._bootstrap  # noqa: F401  (UTF-8 + CA en Windows)

import psycopg2.extras

from src.common import get_conn

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8787"))
API_TOKEN = os.environ.get("API_TOKEN", "")


def _json_default(value):
    return str(value)


def _result(payload: dict, status: int = 200):
    return status, payload


# ═══════════════════════════════════════════════════════════════
#  Handlers de dominio
# ═══════════════════════════════════════════════════════════════

def _health() -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"ok": True, "service": "taskmanager-api", "db": "up"}
    finally:
        conn.close()


def _hoy() -> dict:
    from src.processing.next_action import pick_next

    conn = get_conn()
    try:
        return pick_next(conn, limit=200, use_llm=True)
    finally:
        conn.close()


def _close_decision(decision_id: int, body: dict) -> dict:
    from src.processing.next_action import close_decision

    conn = get_conn()
    try:
        return close_decision(
            conn,
            decision_id,
            executed=bool(body.get("executed", True)),
            hours=body.get("hours"),
        )
    finally:
        conn.close()


def _list_tasks(status: str, limit: int) -> list:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status == "all":
                cur.execute(
                    """SELECT id, title, project_tag, priority, estimated_hours,
                              actual_hours, status, due_date
                       FROM tasks
                       ORDER BY priority DESC NULLS LAST, due_date ASC NULLS LAST
                       LIMIT %s""",
                    (limit,),
                )
            else:
                cur.execute(
                    """SELECT id, title, project_tag, priority, estimated_hours,
                              actual_hours, status, due_date
                       FROM tasks
                       WHERE status = %s
                       ORDER BY priority DESC NULLS LAST, due_date ASC NULLS LAST
                       LIMIT %s""",
                    (status, limit),
                )
            return list(cur.fetchall())
    finally:
        conn.close()


def _create_task(body: dict) -> dict:
    """Reusa el CLI de tasks: mantiene dedup y generación de embedding."""
    cmd = [sys.executable, "-m", "src.processing.tasks", "add",
           "--title", str(body.get("title", "")).strip()]
    if body.get("project"):
        cmd += ["--project", str(body["project"])]
    if body.get("priority") is not None:
        cmd += ["--priority", str(body["priority"])]
    if body.get("hours") is not None:
        cmd += ["--hours", str(body["hours"])]
    if body.get("due"):
        cmd += ["--due", str(body["due"])]
    if body.get("embed", True):
        cmd += ["--embed"]

    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=_PROJECT_ROOT, timeout=120
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "respuesta no-JSON de tasks"}


def _complete_task(task_id: int, hours: float | None) -> dict:
    cmd = [sys.executable, "-m", "src.processing.tasks", "complete",
           "--id", str(task_id)]
    if hours is not None:
        cmd += ["--hours", str(hours)]

    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=_PROJECT_ROOT, timeout=120
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": True, "raw": proc.stdout.strip()}


# ═══════════════════════════════════════════════════════════════
#  Router HTTP
# ═══════════════════════════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):
    server_version = "TaskManagerAPI/1.0"

    def log_message(self, fmt, *args):  # log compacto a stderr
        print(f"[api] {self.address_string()} {fmt % args}", file=sys.stderr)

    # ── utilidades ──
    def _send(self, status: int, payload):
        body = json.dumps(payload, default=_json_default,
                          ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not API_TOKEN:
            return True  # sin token configurado: solo LAN de confianza
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {API_TOKEN}"

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    # ── verbos ──
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/health":
            try:
                self._send(200, _health())
            except Exception as e:
                self._send(503, {"ok": False, "error": str(e)})
            return

        if not self._authorized():
            self._send(401, {"ok": False, "error": "no autorizado"})
            return

        try:
            if path == "/hoy":
                self._send(200, _hoy())
                return

            if path == "/tasks":
                query = parse_qs(parsed.query)
                status = (query.get("status") or ["pending"])[0]
                limit = int((query.get("limit") or ["50"])[0])
                self._send(200, {"ok": True, "tasks": _list_tasks(status, limit)})
                return

            self._send(404, {"ok": False, "error": f"ruta desconocida: {path}"})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        if not self._authorized():
            self._send(401, {"ok": False, "error": "no autorizado"})
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        body = self._body()

        try:
            if path.startswith("/decisions/") and path.endswith("/close"):
                parts = path.split("/")
                decision_id = int(parts[2])
                result = _close_decision(decision_id, body)

                hours = body.get("hours")
                if result.get("ok") and body.get("executed", True):
                    completed = _complete_task(result["task_id"], hours)
                    result["task"] = completed
                self._send(200, result)
                return

            if path == "/tasks":
                if not str(body.get("title", "")).strip():
                    self._send(400, {"ok": False, "error": "title requerido"})
                    return
                self._send(201, _create_task(body))
                return

            self._send(404, {"ok": False, "error": f"ruta desconocida: {path}"})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})


def main():
    server = ThreadingHTTPServer((API_HOST, API_PORT), Handler)
    print(
        f"[api] escuchando en http://{API_HOST}:{API_PORT} "
        f"(auth: {'token' if API_TOKEN else 'sin token — solo LAN'})",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api] cerrado", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
