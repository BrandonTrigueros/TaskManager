#!/usr/bin/env python3
"""BT-Core TaskManager — Deterministic Telegram Bot.

UNLIKE the OpenClaw agent, this bot does exactly what you tell it.
No hallucinations, no improvisation, no "I couldn't find that report."

Architecture:
  - Commands route directly to tasks.py functions (100% reliable)
  - classify_task + embeddings run underneath automatically
  - Photos trigger OCR → classify → add (Vision Diff if repeated)
  - Voice notes trigger transcribe → classify → add

Usage:
    python3 scripts/bot.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Project root ─────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Load .env ─────────────────────────────────────────────────
def _load_env(path: Path) -> None:
    import re
    if not path.is_file():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = re.sub(r"\s+#.*$", "", v).strip().strip("\"'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_env(_PROJECT_ROOT / ".env")

TOKEN = os.environ.get("BT_TASKS_BOT_TOKEN", "")
ALLOWED_USER = os.environ.get("BT_ALLOWED_USER_ID", "")

if not TOKEN:
    print("BT_TASKS_BOT_TOKEN not set in .env", file=sys.stderr)
    sys.exit(1)

# ── Telegram bot ──────────────────────────────────────────────
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

PRIORITY_EMOJI = {1: "⬜", 2: "🟦", 3: "🟨", 4: "🟧", 5: "🟥"}



def _p_emoji(priority) -> str:
    """Get priority emoji, handling int or string enum values."""
    try:
        return PRIORITY_EMOJI.get(int(priority), "⬜")
    except (TypeError, ValueError):
        return "⬜"


def _run(cmd: list[str], cwd: str | None = None) -> dict | list | str | None:
    """Run a Python module and return parsed JSON output."""
    python_exe = sys.executable  # Works in venv AND Docker (no hardcoded path)
    try:
        result = subprocess.run(
            [python_exe, "-m", *cmd],
            capture_output=True, text=True, timeout=120,
            cwd=cwd or str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or result.stdout.strip()}
        # Parse JSON output
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return None
    except subprocess.TimeoutExpired:
        return {"error": "timeout after 120s"}
    except json.JSONDecodeError:
        return result.stdout.strip()


# ═══════════════════════════════════════════════════════════════
#  Command handlers
# ═══════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "BT-Core TaskManager\n\n"
        "/add <texto> - Crear tarea\n"
        "/list - Ver pendientes\n"
        "/info <id> - Detalle de tarea\n"
        "/related <id> - Tareas vinculadas\n"
        "/done <id> --hours <N> - Completar\n"
        "/search <texto> - Buscar\n"
        "/overdue - Vencidas\n"
        "/export - Exportar\n\n"
        "Foto -> OCR | Voz -> Transcribe"
    )


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a task: /add <title> [--project X] [--priority N] [--hours N]"""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Uso: /add <título de la tarea>")
        return

    await update.message.reply_text("Clasificando...")

    # Step 1: Classify
    classify_result = _run(["src.processing.classify", text])
    if isinstance(classify_result, dict) and "project_tag" in classify_result:
        project = classify_result.get("project_tag", "Personal")
        priority = classify_result.get("priority", 3)
        hours = classify_result.get("estimated_hours", 1.0)
        linked = classify_result.get("linked_task_ids", [])
    else:
        project, priority, hours, linked = "Personal", 3, 1.0, []

    # Step 2: Create with embed
    add_args = [
        "src.processing.tasks", "add",
        "--title", text,
        "--project", str(project),
        "--priority", str(priority),
        "--hours", str(hours),
        "--embed",
    ]
    result = _run(add_args)

    if isinstance(result, dict) and result.get("ok"):
        tid = result["id"]
        p = _p_emoji(priority)

        # Fetch linked task titles
        linked_lines = ""
        if linked:
            linked_ids = ",".join(str(l) for l in linked)
            tasks_result = _run(["src.processing.tasks", "list", "--limit", "50"])
            if isinstance(tasks_result, list):
                linked_tasks = [t for t in tasks_result if t["id"] in linked]
                if linked_tasks:
                    linked_lines = "\n\n  ~ relacionadas ~\n"
                    for lt in linked_tasks[:4]:
                        linked_lines += f"  {_p_emoji(lt.get('priority',3))} #{lt['id']} {lt['title'][:55]}\n"
                    linked_lines = linked_lines.rstrip()

        # Warn if similar completed task exists
        warn = ""
        if result.get("warn_completed"):
            warn = f"\n  (ya completaste #{result['warn_completed']} — Grafo Vivo conserva los datos)"

        msg = (
            f"═══ #{tid} | {p} P{priority} | {project} | ~{hours}h ═══\n"
            f"\n"
            f"  {text}\n"
            f"{warn}"
            f"{linked_lines}"
        )
    elif isinstance(result, dict) and result.get("deduplicated"):
        tid = result["id"]
        msg = f"Ya existe #{tid}: {text}"
    else:
        msg = f"Error: {str(result)[:200]}"

    await update.message.reply_text(msg)


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List pending tasks."""
    result = _run(["src.processing.tasks", "list", "--status", "pending", "--limit", "15"])
    if isinstance(result, list):
        if not result:
            await update.message.reply_text("Nada pendiente")
            return
        lines = [f"─── Pendientes ({len(result)}) ───"]
        for t in result:
            p = _p_emoji(t.get("priority", 3))
            pid = t["id"]
            title = t["title"][:60]
            proj = t.get("project_tag", "?")
            hours = f" ~{t['estimated_hours']}h" if t.get("estimated_hours") else ""
            lines.append(f"\n{p} #{pid} {title}")
            lines.append(f"   {proj}{hours}")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text(f"Error: {result}")


async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete a task: /done <id> [--hours N]"""
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /done <id> [--hours N]")
        return

    tid = args[0]
    hours = None
    if "--hours" in args:
        idx = args.index("--hours")
        if idx + 1 < len(args):
            hours = args[idx + 1]

    cmd = ["src.processing.tasks", "complete", "--id", str(tid)]
    if hours:
        cmd.extend(["--hours", str(hours)])

    result = _run(cmd)
    if isinstance(result, dict) and result.get("ok"):
        actual = result.get("actual_hours")
        actual_str = f" ({actual}h reales)" if actual else ""
        msg = f"#{tid} completada{actual_str}"
    else:
        msg = f"Error: {result.get('error', 'No se pudo completar')}"

    await update.message.reply_text(msg)


async def overdue_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List overdue tasks."""
    result = _run(["src.processing.tasks", "overdue"])
    if isinstance(result, list):
        if not result:
            await update.message.reply_text("Nada vencido.")
            return
        lines = ["⚠️ *Tareas vencidas:*", ""]
        for t in result:
            p = _p_emoji(t.get("priority", 3))
            lines.append(f"{p} *#{t['id']}* — {t['title'][:60]} [{t.get('project_tag','?')}]")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text(f"Error: {result}")


async def update_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update a task: /update <id> --priority N [--project X] [--status S] [--due YYYY-MM-DD]"""
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Uso: /update <id> --priority N [--project X] [--due YYYY-MM-DD]")
        return

    cmd = ["src.processing.tasks", "update", "--id", args[0]]
    cmd.extend(args[1:])

    result = _run(cmd)
    if isinstance(result, dict) and result.get("ok"):
        msg = f"#{result['id']} actualizada"
    else:
        msg = f"Error: {result.get('error', 'No se pudo actualizar')}"

    await update.message.reply_text(msg)


async def search_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Semantic search: /search <query>"""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Uso: /search <consulta>")
        return

    await update.message.reply_text("Buscando...")
    result = _run(["src.processing.classify", text])

    if isinstance(result, dict) and "linked_task_ids" in result:
        linked = result.get("linked_task_ids", [])
        if linked:
            all_tasks = _run(["src.processing.tasks", "list", "--limit", "50"])
            if isinstance(all_tasks, list):
                matches = [t for t in all_tasks if t["id"] in linked]
                if matches:
                    lines = [f"Similares a '{text}':"]
                    for t in matches[:8]:
                        p = _p_emoji(t.get("priority", 3))
                        lines.append(f"{p} #{t['id']} {t['title'][:60]} [{t.get('project_tag','?')}]")
                    await update.message.reply_text("\n".join(lines))
                    return

    # Fallback: plain text search
    all_tasks = _run(["src.processing.tasks", "list", "--limit", "50"])
    if isinstance(all_tasks, list):
        matches = [t for t in all_tasks if text.lower() in t.get("title","").lower()]
        if matches:
            lines = [f"Coincidencias textuales '{text}':"]
            for t in matches[:8]:
                p = _p_emoji(t.get("priority", 3))
                lines.append(f"{p} #{t['id']} {t['title'][:60]} [{t.get('project_tag','?')}]")
            await update.message.reply_text("\n".join(lines))
            return

    await update.message.reply_text("Nada encontrado")


async def export_vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export to Obsidian vault."""
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", os.path.expanduser("~/Obsidian/TaskManager"))
    await update.message.reply_text("Exportando...")
    result = _run(["src.shared.export_md", "--output", vault_path])
    if isinstance(result, dict) and result.get("ok"):
        stats = result.get("stats", {})
        msg = (
            f"Exportado a `{vault_path}`\n"
            f"{stats.get('total','?')} tareas, {stats.get('pending','?')} pendientes"
            f"{stats.get('embedding_coverage','?')} embeddings"
        )
    else:
        msg = f"Error en export: {result}"
    await update.message.reply_text(msg)


async def tablero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /list — compact dashboard."""
    await list_tasks(update, context)


async def info_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full details of a task: /info <id>"""
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /info <id>")
        return

    tid = args[0]
    result = _run(["src.processing.tasks", "list", "--limit", "100"])
    if isinstance(result, list):
        task = next((t for t in result if str(t["id"]) == str(tid)), None)
        if not task:
            await update.message.reply_text(f"Tarea #{tid} no encontrada")
            return

        p = _p_emoji(task.get("priority", 3))
        status = task.get("status", "?")
        proj = task.get("project_tag", "-")
        est = task.get("estimated_hours", "-")
        act = task.get("actual_hours")
        act_str = f" | real: {act}h" if act else ""
        emb = "embed" if task.get("has_embedding") else "sin embed"
        due = task.get("due_date", "")[:10] if task.get("due_date") else "-"

        msg = (
            f"═══ #{tid} | {p} P{task.get('priority','?')} | {proj} ═══\n"
            f"\n"
            f"  {task['title']}\n"
            f"\n"
            f"  estado: {status} | est: ~{est}h{act_str}\n"
            f"  vence: {due} | {emb}\n"
        )

        # Fetch linked tasks from Grafo Vivo
        classify_result = _run(["src.processing.classify", task["title"]])
        if isinstance(classify_result, dict):
            linked = classify_result.get("linked_task_ids", [])
            linked = [l for l in linked if l != int(tid)]
            if linked:
                all_tasks = _run(["src.processing.tasks", "list", "--limit", "100"])
                if isinstance(all_tasks, list):
                    related = [t for t in all_tasks if t["id"] in linked]
                    if related:
                        msg += "\n  ~ relacionadas ~\n"
                        for rt in related[:5]:
                            rp = _p_emoji(rt.get("priority", 3))
                            msg += f"  {rp} #{rt['id']} {rt['title'][:50]}\n"

        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Error al buscar tarea")


async def related_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Grafo Vivo neighbors: /related <id>"""
    args = context.args or []
    if not args:
        await update.message.reply_text("Uso: /related <id>")
        return

    tid = args[0]
    result = _run(["src.processing.tasks", "list", "--limit", "100"])
    if isinstance(result, list):
        task = next((t for t in result if str(t["id"]) == str(tid)), None)
        if not task:
            await update.message.reply_text(f"Tarea #{tid} no encontrada")
            return

        classify_result = _run(["src.processing.classify", task["title"]])
        if isinstance(classify_result, dict):
            linked = classify_result.get("linked_task_ids", [])
            linked = [l for l in linked if l != int(tid)]
            if linked:
                all_tasks = _run(["src.processing.tasks", "list", "--limit", "100"])
                if isinstance(all_tasks, list):
                    related = [t for t in all_tasks if t["id"] in linked]
                    if related:
                        lines = [f"═══ Relacionadas con #{tid} ═══", ""]
                        for rt in related[:8]:
                            rp = _p_emoji(rt.get("priority", 3))
                            lines.append(f"{rp} #{rt['id']} {rt['title'][:55]}")
                            lines.append(f"   {rt.get('project_tag','?')} | ~{rt.get('estimated_hours','?')}h")
                            if rt.get("actual_hours"):
                                lines[-1] += f" | real: {rt['actual_hours']}h"
                        await update.message.reply_text("\n".join(lines))
                        return

        await update.message.reply_text(f"#{tid}: sin relaciones en el Grafo Vivo")
    else:
        await update.message.reply_text("Error")


# ═══════════════════════════════════════════════════════════════
#  Photo handler — OCR → classify → add (Vision Diff ready)
# ═══════════════════════════════════════════════════════════════

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process a whiteboard/notebook photo."""
    await update.message.reply_text("Procesando imagen...")

    # Download photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        await file.download_to_drive(f.name)
        photo_path = f.name

    try:
        # Step 1: OCR
        ocr_result = _run(["src.shared.ocr", "whiteboard", photo_path])
        tasks = ocr_result if isinstance(ocr_result, list) else []

        if not tasks:
            await update.message.reply_text("No se detectaron tareas en la imagen.")
            return

        # Step 2: Get pending tasks for Vision Diff
        pending = _run(["src.processing.tasks", "list", "--status", "pending", "--limit", "50"])
        pending_list = pending if isinstance(pending, list) else []

        # Step 3: Vision Diff via DeepSeek R1
        from src.processing.vision_diff import diff_whiteboard
        diff_result = diff_whiteboard(pending_list, tasks)

        # If vision_diff fails, treat all OCR tasks as new
        if isinstance(diff_result, dict):
            new_tasks = diff_result.get("new", tasks if not diff_result else [])
            completed_ids = diff_result.get("completed_ids", [])
        else:
            new_tasks = tasks
            completed_ids = []

        # Step 4: Create new tasks
        created = []
        for task_text in new_tasks:
            classify = _run(["src.processing.classify", task_text])
            proj = classify.get("project_tag", "Personal") if isinstance(classify, dict) else "Personal"
            pri = classify.get("priority", 3) if isinstance(classify, dict) else 3
            hrs = classify.get("estimated_hours", 1.0) if isinstance(classify, dict) else 1.0

            add_result = _run([
                "src.processing.tasks", "add",
                "--title", task_text,
                "--project", str(proj),
                "--priority", str(pri),
                "--hours", str(hrs),
                "--embed",
            ])
            if isinstance(add_result, dict) and add_result.get("ok") and not add_result.get("deduplicated"):
                created.append(f"  ✅ #{add_result['id']} — {task_text[:50]} [{proj}]")

        # Step 5: Complete tasks that disappeared
        completed = []
        for tid in completed_ids:
            _run(["src.processing.tasks", "complete", "--id", str(tid)])
            completed.append(f"  ✓ #{tid} marcada completada")

        # Step 6: Report
        lines = ["Diff completado:"]
        if created:
            lines.append(f"➕ *{len(created)} nuevas:*")
            lines.extend(created)
        if completed:
            lines.append(f"\n✅ *{len(completed)} completadas:*")
            lines.extend(completed)
        if not created and not completed:
            lines.append("Sin cambios detectados.")

        await update.message.reply_text("\n".join(lines))

    finally:
        os.unlink(photo_path)


# ═══════════════════════════════════════════════════════════════
#  Voice handler — transcribe → classify → add
# ═══════════════════════════════════════════════════════════════

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe voice note and create task."""
    await update.message.reply_text("Transcribiendo...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        await file.download_to_drive(f.name)
        audio_path = f.name

    try:
        result = _run(["src.shared.transcribe", audio_path])
        if isinstance(result, dict) and "text" in result:
            text = result["text"]
            await update.message.reply_text(f"🎙️ \"{text[:200]}\"\n\n⏳ Creando tarea...")
            # Now create the task
            context.args = [text]
            await add_task(update, context)
        else:
            await update.message.reply_text("No se pudo transcribir el audio.")
    finally:
        os.unlink(audio_path)


# ═══════════════════════════════════════════════════════════════
#  Security: only respond to allowed user
# ═══════════════════════════════════════════════════════════════

async def security_filter(update: Update) -> bool:
    """Block messages from non-authorized users."""
    if ALLOWED_USER and str(update.effective_user.id) != ALLOWED_USER:
        await update.message.reply_text("⛔ No autorizado.")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", complete_task))
    app.add_handler(CommandHandler("update", update_task))
    app.add_handler(CommandHandler("overdue", overdue_tasks))
    app.add_handler(CommandHandler("search", search_tasks))
    app.add_handler(CommandHandler("info", info_task))
    app.add_handler(CommandHandler("related", related_tasks))
    app.add_handler(CommandHandler("export", export_vault))
    app.add_handler(CommandHandler("tablero", tablero))

    # Media handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 BT-Core TaskManager bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
