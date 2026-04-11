# TaskManager — Extracted Module

Standalone extraction of the TaskManager module from BT-Core for independent testing.

## Structure

```
TaskManager/
├── src/tools/common.py              # Shared infra (DB + Gemini API)
├── src/tools/TaskManager/tasks.py   # CRUD: add, list, complete, update, overdue
├── src/tools/TaskManager/classify_task.py  # AI classification
├── src/tools/SharedUtilities/ocr.py # Whiteboard/notebook OCR
├── db/schema.sql                    # PostgreSQL schema (tasks table + enums)
├── scripts/cli.py                   # CLI entry point
└── openclaw/skills/taskmanager/     # OpenClaw skill definition
```

## Usage

```bash
# Set up env
cp .env.example .env
# Edit .env with your values

# Run DB schema
psql -U hb_admin -d heartbeat -f db/schema.sql

# CLI
python3 scripts/cli.py add --title "Terminar Lab 2" --project Empotrados --priority 4
python3 scripts/cli.py list --status pending
python3 scripts/cli.py complete --id 1
python3 scripts/cli.py overdue
python3 scripts/cli.py classify "Corregir el paper de detección de objetos"
python3 scripts/cli.py ocr-whiteboard /path/to/photo.jpg
```

## Merge Notes

This module uses `src/tools/` package structure. When merging with FinanceSpender and IdeaVault:
1. Combine `src/tools/` trees — each module lives in its own subfolder
2. Keep one shared `src/tools/common.py`
3. `SharedUtilities/` merges naturally (OCR used by both TaskManager and FinanceSpender)
