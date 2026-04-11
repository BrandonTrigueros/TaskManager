---
name: taskmanager
description: Use when Brandon mentions tasks, labs, work assignments, deadlines, projects, agenda, to-dos, university coursework, or says something that sounds like a new task. Also use when he sends a photo of a whiteboard or notebook to extract tasks via OCR.
metadata: { "openclaw": { "emoji": "🧠", "os": ["linux"], "requires": { "bins": ["python3"], "env": ["DB_DSN"] } } }
---

# Hartbeat TaskManager — Task Management Skill

## Channel

This skill is the default for the **tasks** Telegram bot.

## Auto-Whiteboard Directive

**Any image received on this channel is a whiteboard or notebook photo.** Process it immediately:
1. Run `python3 -m src.tools.SharedUtilities.ocr whiteboard /tmp/photo.jpg` from the TaskManager project root
2. For each extracted task, run `python3 -m src.tools.TaskManager.classify_task "..."`
3. Insert all with `python3 -m src.tools.TaskManager.tasks add ...`
4. Report all created tasks — no confirmation needed

## What this skill does

Manages Brandon's tasks across university (UCR), work (HPE), and personal life using a PostgreSQL database. The agent uses Python tool scripts to create, list, complete, and categorize tasks.

## Tool Scripts

All tools are Python modules run from the `TaskManager/` project root:

### Create a task
```bash
python3 -m src.tools.TaskManager.tasks add \
  --title "Terminar Lab 2 de Empotrados" \
  --project "Empotrados" \
  --priority 4 \
  --hours 3.0 \
  --due "2026-04-15"
```

### AI-classify a task (returns JSON with project_tag, priority, estimated_hours)
```bash
python3 -m src.tools.TaskManager.classify_task "Corregir el paper de detección de objetos"
```

### List pending tasks
```bash
python3 -m src.tools.TaskManager.tasks list --status pending
python3 -m src.tools.TaskManager.tasks list --status pending --project "HPE"
```

### Complete a task
```bash
python3 -m src.tools.TaskManager.tasks complete --id 42
```

### List overdue tasks
```bash
python3 -m src.tools.TaskManager.tasks overdue
```

### OCR whiteboard/notebook photo
```bash
python3 -m src.tools.SharedUtilities.ocr whiteboard /tmp/photo.jpg
```
Returns a JSON array of extracted task strings. For each extracted task, run `classify_task` and then `tasks add`.

## Classification Workflow

When Brandon sends a new task (text or extracted from OCR):

1. Run `classify_task "<title>"` to get AI classification
2. Create the task with `tasks add` using the AI result
3. Report back: task ID, project tag, priority, estimated hours
4. If Brandon disagrees with the classification, update with `tasks update --id N --project "NewTag"`

## Valid Project Tags

`Empotrados`, `Computer Vision`, `HPE`, `Personal`, `Universidad`, `Finanzas`, `Salud`, `Hogar`

## Priority Scale

1 = Low (can wait weeks), 2 = Normal, 3 = Important (this week), 4 = Urgent (today/tomorrow), 5 = Critical (right now)

## Response Format

When creating a task, always respond with:
```
✅ Tarea #ID — Title
🏷️ Proyecto | 🔥 Prioridad N/5 | ⏱️ ~Xh
```

When listing tasks, use a compact list:
```
📋 Tareas pendientes (N)
🟥 #1 Task title [Project] ~2h 📅 15/04
🟧 #2 Task title [Project] ~1h
🟨 #3 Task title [Project] ~0.5h
```
Priority emoji: 5=🟥 4=🟧 3=🟨 2=🟦 1=⬜

## Quick Task Shortcut

If Brandon sends plain text that looks like a task (imperative verb, deliverable, assignment), create it immediately without asking for confirmation. Classify with AI and report back.
