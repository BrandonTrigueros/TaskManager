#!/usr/bin/env python3
"""TaskManager CLI — Quick entry point for task management.

Usage:
    python3 -m src.ingest.cli add --title "comprar leche"
    python3 -m src.ingest.cli "comprar leche"             → shortcut: add-task
    python3 -m src.ingest.cli list [--status pending] [--project X]
    python3 -m src.ingest.cli complete --id 42
    python3 -m src.ingest.cli update --id 42 --priority 5
    python3 -m src.ingest.cli overdue
    python3 -m src.ingest.cli classify "Terminar Lab 2 de Empotrados"
    python3 -m src.ingest.cli ocr-whiteboard /path/to/photo.jpg

Designed to run from the TaskManager/ project root.
All DB/AI calls go to localhost.
"""

import os
import subprocess
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PYTHON = sys.executable


def tool(module: str, *args: str):
    """Run a TaskManager tool module, forwarding stdout/stderr."""
    result = subprocess.run(
        [PYTHON, "-m", module, *args],
        capture_output=False,
        cwd=_PROJECT_ROOT,
    )
    sys.exit(result.returncode)


def main():
    if len(sys.argv) < 2:
        print("Uso: cli.py <comando|texto>")
        print()
        print("  cli.py \"tarea nueva\"                          → agregar tarea (clasifica + --embed)")
        print("  cli.py add --title \"...\" [--project X]        → agregar tarea")
        print("        [--priority N] [--hours N] [--due DATE]")
        print("        [--embed] [--location-lat X] [--location-lon Y]")
        print("        [--location-label \"...\"] [--description \"...\"]")
        print("  cli.py list [--status S] [--project P]        → listar tareas")
        print("  cli.py complete --id N [--hours N]             → completar tarea (REQ-T7)")
        print("  cli.py update --id N [--priority N] [--status S] [--project P]")
        print("  cli.py overdue                                → tareas vencidas")
        print("  cli.py classify \"texto\"                        → clasificar con DeepSeek")
        print("  cli.py vision-diff --pending FILE --ocr FILE   → diff lógico (REQ-T4)")
        print("  cli.py ocr-whiteboard /path/to/img             → OCR de pizarra")
        print("  cli.py ocr-receipt /path/to/img                → OCR de recibo")
        print("  cli.py ocr-describe /path/to/img               → describir imagen")
        print("  cli.py transcribe /path/to/audio.ogg           → transcribir audio (REQ-T3)")
        print("  cli.py export [--output /path/to/dir]          → exportar a Obsidian")
        print("  cli.py heartbeat [--action all|backfill|reminders]  → ciclo de coherencia")
        sys.exit(1)

    cmd = sys.argv[1]

    # ─── Task CRUD commands (forward to tasks.py) ───────────
    if cmd in ("add", "list", "complete", "update", "overdue"):
        tool("src.processing.tasks", cmd, *sys.argv[2:])

    # ─── AI classification ──────────────────────────────────
    elif cmd == "classify":
        if len(sys.argv) < 3:
            print("Uso: cli.py classify \"texto de la tarea\"")
            sys.exit(1)
        tool("src.processing.classify", *sys.argv[2:])

    # ─── Vision Diff (REQ-T4) ───────────────────────────────
    elif cmd == "vision-diff":
        tool("src.processing.vision_diff", *sys.argv[2:])

    # ─── OCR whiteboard ────────────────────────────────────
    elif cmd == "ocr-whiteboard":
        if len(sys.argv) < 3:
            print("Uso: cli.py ocr-whiteboard /path/to/photo.jpg")
            sys.exit(1)
        tool("src.shared.ocr", "whiteboard", sys.argv[2])

    # ─── OCR receipt ────────────────────────────────────────
    elif cmd == "ocr-receipt":
        if len(sys.argv) < 3:
            print("Uso: cli.py ocr-receipt /path/to/photo.jpg")
            sys.exit(1)
        tool("src.shared.ocr", "receipt", sys.argv[2])

    # ─── OCR describe ───────────────────────────────────────
    elif cmd == "ocr-describe":
        if len(sys.argv) < 3:
            print("Uso: cli.py ocr-describe /path/to/image.jpg")
            sys.exit(1)
        tool("src.shared.ocr", "describe", sys.argv[2])

    # ─── Transcribe audio (REQ-T3) ───────────────────────────
    elif cmd == "transcribe":
        if len(sys.argv) < 3:
            print("Uso: cli.py transcribe /path/to/audio.ogg")
            sys.exit(1)
        tool("src.shared.transcribe", *sys.argv[2:])

    # ─── Markdown export ────────────────────────────────────
    elif cmd == "export":
        tool("src.shared.export_md", *sys.argv[2:])

    # ─── Heartbeat (REQ-T12) ─────────────────────────────────
    elif cmd == "heartbeat":
        tool("src.ingest.heartbeat", *sys.argv[2:])

    # ─── Default: treat entire input as a new task ──────────
    else:
        title = " ".join(sys.argv[1:])
        tool("src.processing.tasks", "add", "--title", title, "--source", "cli", "--embed")


if __name__ == "__main__":
    main()
