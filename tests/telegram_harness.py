#!/usr/bin/env python3
"""Telegram Webhook Harness — Dev/test entry point for REQ-T1.

This is NOT the production bot handler (OpenClaw handles that).
This is a lightweight test harness that mimics the Telegram → tools flow
so we can validate the TaskManager pipeline independently.

Usage:
    1. Start ngrok:   ngrok http 5001
    2. Run harness:   python3 tests/telegram_harness.py --webhook-url https://xxxx.ngrok-free.app
    3. Send messages to the bot in Telegram

The harness will:
    - Text  → classify_task + tasks.py add      (REQ-T1, REQ-T6)
    - Photo → ocr.py whiteboard → for each task, classify + add  (REQ-T1, REQ-T2)
    - Voice → placeholder for REQ-T3 (transcription)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

from flask import Flask, request, jsonify

# ─── Config ────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TASKS_BOT_TOKEN", "")
ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON = sys.executable

app = Flask(__name__)


# ─── Telegram API helpers ──────────────────────────────────────

def tg_send(chat_id: int, text: str):
    """Send a message back to the user via Telegram API."""
    url = f"{TELEGRAM_API}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[tg_send error] {e}", file=sys.stderr)


def tg_download_file(file_id: str, dest_path: str) -> bool:
    """Download a file from Telegram servers."""
    # Get file path
    url = f"{TELEGRAM_API}/getFile?file_id={file_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        file_path = data["result"]["file_path"]
    except Exception as e:
        print(f"[getFile error] {e}", file=sys.stderr)
        return False

    # Download
    dl_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    try:
        urllib.request.urlretrieve(dl_url, dest_path)
        return True
    except Exception as e:
        print(f"[download error] {e}", file=sys.stderr)
        return False


# ─── Tool runners ─────────────────────────────────────────────

def run_tool(module: str, *args: str) -> tuple[int, str, str]:
    """Run a TaskManager tool module. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        [PYTHON, "-m", module, *args],
        capture_output=True, text=True,
        cwd=_PROJECT_ROOT,
        env={**os.environ},
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def classify_and_add(text: str) -> dict:
    """Classify a task with AI, then add it to the DB."""
    # Step 1: AI classification
    rc, out, err = run_tool("src.tools.TaskManager.classify_task", text)
    classification = {}
    if rc == 0 and out:
        try:
            classification = json.loads(out)
        except json.JSONDecodeError:
            pass

    project = classification.get("project_tag")
    priority = classification.get("priority")
    hours = classification.get("estimated_hours")

    # Step 2: Add task
    add_args = ["add", "--title", text, "--source", "telegram"]
    if project:
        add_args += ["--project", str(project)]
    if priority:
        add_args += ["--priority", str(int(priority))]
    if hours:
        add_args += ["--hours", str(float(hours))]

    rc, out, err = run_tool("src.tools.TaskManager.tasks", *add_args)
    result = {}
    if rc == 0 and out:
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            pass

    return {
        "task": result,
        "classification": classification,
        "ai_error": classification.get("ai_error"),
    }


# ─── Message handlers ─────────────────────────────────────────

def handle_text(chat_id: int, text: str):
    """Handle a plain text message → classify + add task."""
    print(f"[TEXT] {text}")
    tg_send(chat_id, f"⏳ Procesando: _{text}_")

    result = classify_and_add(text)
    task = result.get("task", {})
    cls = result.get("classification", {})

    if task.get("ok"):
        response = (
            f"✅ Tarea #{task['id']} — {task.get('title', text)}\n"
            f"🏷️ {cls.get('project_tag', '?')} | "
            f"🔥 Prioridad {cls.get('priority', '?')}/5 | "
            f"⏱️ ~{cls.get('estimated_hours', '?')}h"
        )
    else:
        response = f"❌ Error creando tarea: {task.get('error', 'unknown')}"

    if result.get("ai_error"):
        response += f"\n⚠️ AI fallback: {result['ai_error']}"

    tg_send(chat_id, response)


def handle_photo(chat_id: int, photo_file_id: str):
    """Handle a photo message → OCR whiteboard → classify + add each task."""
    print(f"[PHOTO] file_id={photo_file_id}")
    tg_send(chat_id, "📸 Procesando imagen de pizarra/libreta...")

    # Download photo to temp file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        tmp_path = f.name

    try:
        if not tg_download_file(photo_file_id, tmp_path):
            tg_send(chat_id, "❌ No pude descargar la foto")
            return

        # OCR
        rc, out, err = run_tool("src.tools.SharedUtilities.ocr", "whiteboard", tmp_path)
        if rc != 0 or not out:
            tg_send(chat_id, f"❌ OCR falló: {err or 'sin output'}")
            return

        try:
            tasks_text = json.loads(out)
        except json.JSONDecodeError:
            tg_send(chat_id, f"❌ OCR retornó formato inválido: {out[:200]}")
            return

        if not isinstance(tasks_text, list) or len(tasks_text) == 0:
            tg_send(chat_id, "🤷 No se detectaron tareas en la imagen")
            return

        tg_send(chat_id, f"📋 Detectadas {len(tasks_text)} tareas. Clasificando...")

        # Classify and add each task
        results = []
        for task_str in tasks_text:
            if not isinstance(task_str, str) or not task_str.strip():
                continue
            r = classify_and_add(task_str.strip())
            results.append(r)

        # Report
        lines = [f"✅ {len(results)} tareas creadas desde la pizarra:\n"]
        for r in results:
            task = r.get("task", {})
            cls = r.get("classification", {})
            tid = task.get("id", "?")
            title = task.get("title", "?")
            proj = cls.get("project_tag", "?")
            pri = cls.get("priority", "?")
            lines.append(f"  #{tid} — {title} [{proj}] P{pri}")

        tg_send(chat_id, "\n".join(lines))

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def handle_voice(chat_id: int, voice_file_id: str):
    """Handle a voice message → placeholder for REQ-T3 transcription."""
    print(f"[VOICE] file_id={voice_file_id}")
    tg_send(chat_id, "🎤 Transcripción de audio aún no implementada (REQ-T3). Enviá texto o foto por ahora.")


# ─── Webhook endpoint ─────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming Telegram update."""
    update = request.get_json(silent=True)
    if not update:
        return jsonify({"ok": False}), 400

    message = update.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    user_id = str(message.get("from", {}).get("id", ""))

    # Security: only allow configured user
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        print(f"[BLOCKED] user_id={user_id} not in allowed list")
        return jsonify({"ok": True})

    # Route by message type
    if "photo" in message:
        # Telegram sends multiple sizes, take the largest
        photo = message["photo"][-1]
        handle_photo(chat_id, photo["file_id"])

    elif "voice" in message:
        handle_voice(chat_id, message["voice"]["file_id"])

    elif "text" in message:
        text = message["text"].strip()
        # Ignore commands for now
        if text.startswith("/start"):
            tg_send(chat_id, "🧠 TaskManager activo. Enviá texto, fotos de pizarra o audio.")
        elif text.startswith("/list"):
            rc, out, _ = run_tool("src.tools.TaskManager.tasks", "list")
            if rc == 0 and out:
                try:
                    tasks = json.loads(out)
                    if tasks:
                        priority_emoji = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}
                        lines = [f"📋 Tareas pendientes ({len(tasks)})\n"]
                        for t in tasks:
                            p = priority_emoji.get(t.get("priority"), "⬜")
                            proj = t.get("project_tag") or "?"
                            hours = f" ~{t['estimated_hours']}h" if t.get("estimated_hours") else ""
                            lines.append(f"{p} #{t['id']} {t['title']} [{proj}]{hours}")
                        tg_send(chat_id, "\n".join(lines))
                    else:
                        tg_send(chat_id, "📋 No hay tareas pendientes")
                except json.JSONDecodeError:
                    tg_send(chat_id, out)
            else:
                tg_send(chat_id, "❌ Error listando tareas")
        elif text.startswith("/done"):
            parts = text.split()
            if len(parts) >= 2:
                try:
                    task_id = int(parts[1])
                    rc, out, _ = run_tool("src.tools.TaskManager.tasks", "complete", "--id", str(task_id))
                    if rc == 0:
                        result = json.loads(out)
                        if result.get("ok"):
                            tg_send(chat_id, f"✅ Tarea #{task_id} completada")
                        else:
                            tg_send(chat_id, f"❌ {result.get('error', 'Error')}")
                    else:
                        tg_send(chat_id, "❌ Error completando tarea")
                except (ValueError, json.JSONDecodeError):
                    tg_send(chat_id, "Uso: /done <id>")
            else:
                tg_send(chat_id, "Uso: /done <id>")
        elif text.startswith("/overdue"):
            rc, out, _ = run_tool("src.tools.TaskManager.tasks", "overdue")
            if rc == 0 and out:
                try:
                    tasks = json.loads(out)
                    if tasks:
                        lines = [f"⏰ Tareas vencidas ({len(tasks)})\n"]
                        for t in tasks:
                            lines.append(f"🟥 #{t['id']} {t['title']} 📅 {t.get('due_date', '?')}")
                        tg_send(chat_id, "\n".join(lines))
                    else:
                        tg_send(chat_id, "✅ No hay tareas vencidas")
                except json.JSONDecodeError:
                    tg_send(chat_id, out)
        elif text.startswith("/"):
            tg_send(chat_id, "Comandos: /list /done <id> /overdue\nO simplemente enviá texto para agregar una tarea")
        else:
            handle_text(chat_id, text)

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "taskmanager-harness"})


# ─── Setup ─────────────────────────────────────────────────────

def set_webhook(webhook_url: str):
    """Register webhook URL with Telegram."""
    url = f"{TELEGRAM_API}/setWebhook"
    payload = json.dumps({
        "url": f"{webhook_url}/webhook",
        "allowed_updates": ["message"],
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    print(f"[setWebhook] {result}")
    return result


def delete_webhook():
    """Remove webhook so we can use long-polling or switch URLs."""
    url = f"{TELEGRAM_API}/deleteWebhook"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    print(f"[deleteWebhook] {result}")


def main():
    parser = argparse.ArgumentParser(description="Telegram Webhook Harness (dev/test)")
    parser.add_argument("--webhook-url", required=True,
                        help="Public URL from ngrok (e.g. https://xxxx.ngrok-free.app)")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not BOT_TOKEN:
        print("ERROR: Set TASKS_BOT_TOKEN in .env or environment", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Setting webhook to {args.webhook_url}/webhook")
    set_webhook(args.webhook_url)

    print(f"[*] Starting Flask on {args.host}:{args.port}")
    print(f"[*] Bot commands: /start /list /done <id> /overdue")
    print(f"[*] Or just send text → auto-create task")
    print(f"[*] Send photo → OCR whiteboard → create tasks")
    print(f"[*] Press Ctrl+C to stop")

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[*] Cleaning up webhook...")
        delete_webhook()


if __name__ == "__main__":
    main()
