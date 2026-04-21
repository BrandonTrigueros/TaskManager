#!/usr/bin/env python3
"""TaskManager CLI — Quick entry point for task management.

Usage:
    python3 scripts/cli.py add --title "comprar leche"
    python3 scripts/cli.py "comprar leche"                → shortcut: add-task
    python3 scripts/cli.py list [--status pending] [--project X]
    python3 scripts/cli.py complete --id 42
    python3 scripts/cli.py update --id 42 --priority 5
    python3 scripts/cli.py overdue
    python3 scripts/cli.py classify "Terminar Lab 2 de Empotrados"
    python3 scripts/cli.py ocr-whiteboard /path/to/photo.jpg

Designed to run from the TaskManager/ project root.
All DB/AI calls go to the LOQ hub transparently via Tailscale.
"""

import os
import subprocess
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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
        print("  cli.py \"tarea nueva\"                    → agregar tarea")
        print("  cli.py add --title \"...\" [--project X]  → agregar tarea")
        print("  cli.py list [--status S] [--project P]  → listar tareas")
        print("  cli.py complete --id N                  → completar tarea")
        print("  cli.py update --id N [--priority N]     → actualizar tarea")
        print("  cli.py overdue                          → tareas vencidas")
        print("  cli.py classify \"texto\"                  → clasificar con IA")
        print("  cli.py ocr-whiteboard /path/to/img      → OCR de pizarra")
        print("  cli.py export [--output /path/to/dir]   → exportar a Markdown")
        sys.exit(1)

    cmd = sys.argv[1]

    # ─── Task CRUD commands (forward to tasks.py) ───────────
    if cmd in ("add", "list", "complete", "update", "overdue"):
        tool("src.tools.TaskManager.tasks", cmd, *sys.argv[2:])

    # ─── AI classification ──────────────────────────────────
    elif cmd == "classify":
        if len(sys.argv) < 3:
            print("Uso: cli.py classify \"texto de la tarea\"")
            sys.exit(1)
        tool("src.tools.TaskManager.classify_task", *sys.argv[2:])

    # ─── OCR whiteboard ────────────────────────────────────
    elif cmd == "ocr-whiteboard":
        if len(sys.argv) < 3:
            print("Uso: cli.py ocr-whiteboard /path/to/photo.jpg")
            sys.exit(1)
        tool("src.tools.SharedUtilities.ocr", "whiteboard", sys.argv[2])

    # ─── OCR receipt ────────────────────────────────────────
    elif cmd == "ocr-receipt":
        if len(sys.argv) < 3:
            print("Uso: cli.py ocr-receipt /path/to/photo.jpg")
            sys.exit(1)
        tool("src.tools.SharedUtilities.ocr", "receipt", sys.argv[2])

    # ─── Markdown export ────────────────────────────────────
    elif cmd == "export":
        extra = sys.argv[2:]
        tool("src.tools.SharedUtilities.export_md", *extra)

    # ─── Default: treat entire input as a new task ──────────
    else:
        title = " ".join(sys.argv[1:])
        tool("src.tools.TaskManager.tasks", "add", "--title", title, "--source", "cli")


if __name__ == "__main__":
    main()
