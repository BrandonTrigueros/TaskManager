# TaskManager

Módulo standalone de gestión de tareas, extraído de [BT-Core](https://github.com/BrandonTrigueros/BT-Core). Recibe tareas por Telegram (texto + fotos de pizarra) y CLI, las clasifica con IA, y las persiste en PostgreSQL.

## Estructura

```
TaskManager/
├── ARCHITECTURE.md                       # Arquitectura, decisiones, estado de REQs
├── docker-compose.yml                    # PostgreSQL 16 (dev)
├── .env.example                          # Template de variables de entorno
│
├── db/
│   └── schema.sql                        # Schema: tasks + enums (idempotente)
│
├── src/tools/
│   ├── common.py                         # DB connection + Gemini REST API
│   ├── TaskManager/
│   │   ├── tasks.py                      # CRUD: add, list, complete, update, overdue
│   │   └── classify_task.py              # Clasificación IA (Gemini Flash)
│   └── SharedUtilities/
│       ├── ocr.py                        # OCR: whiteboard, receipt, describe
│       └── export_md.py                  # Export a Markdown/Obsidian
│
├── scripts/
│   ├── cli.py                            # CLI router
│   └── setup_loq.sh                      # Setup automatizado para LOQ Hub
│
└── openclaw/
    ├── openclaw.json                     # Config de OpenClaw Gateway
    ├── workspace/
    │   ├── AGENTS.md                     # Identidad del agente
    │   └── SOUL.md                       # Personalidad
    └── skills/
        └── taskmanager/
            └── SKILL.md                  # Skill definition
```

## Setup (LOQ Hub)

```bash
git clone https://github.com/BrandonTrigueros/TaskManager.git ~/TaskManager
cd ~/TaskManager
bash scripts/setup_loq.sh
# Editar .env y ~/.openclaw/openclaw.json con valores reales
openclaw gateway restart
```

Prerequisitos: Node.js 22+, Docker, Python 3.11+, Tailscale.

## CLI

```bash
cd ~/TaskManager && source .venv/bin/activate

# Tareas
python3 scripts/cli.py add --title "Terminar Lab 2" --project Empotrados --priority 4
python3 scripts/cli.py "comprar leche"              # shortcut: add-task
python3 scripts/cli.py list --status pending
python3 scripts/cli.py complete --id 1
python3 scripts/cli.py update --id 1 --priority 5
python3 scripts/cli.py overdue

# IA
python3 scripts/cli.py classify "Corregir el paper de detección de objetos"

# OCR
python3 scripts/cli.py ocr-whiteboard /path/to/photo.jpg

# Export a Obsidian
python3 scripts/cli.py export --output ~/Obsidian/TaskManager/
```

## Requerimientos (spec completo)

### Ingesta (Input Layer)

| REQ | Descripción | Estado |
|-----|-------------|--------|
| T1 | Multi-source: Telegram (texto, audio, fotos) + CLI | ✅ Parcial (audio pendiente) |
| T2 | OCR de pizarras/cuadernos | ✅ |
| T3 | Transcripción de audio | ❌ Pendiente |

### Procesamiento (Logic Layer)

| REQ | Descripción | Estado |
|-----|-------------|--------|
| T4 | Diferenciación de cambios entre envíos sucesivos de la misma hoja | ❌ |
| T5 | Linking de tareas relacionadas (grafo de similitud) | ❌ |
| T6 | Categorización latente por proyecto (IA) | ✅ |
| T7 | Estimación de horas usando contexto de tareas similares | ❌ |

### Almacenamiento y Sincronización (Storage Layer)

| REQ | Descripción | Estado |
|-----|-------------|--------|
| T8 | Vista Maestra: MASTER_LOG.md + por proyecto + por tarea (Obsidian linking) | ✅ |
| T9 | Markdown Sync a Obsidian vault | ✅ |
| T10 | Telegram: responder consultas + recordatorios | ✅ Parcial |
| T11 | Telegram: actualizar estado de tareas | ✅ Parcial |
| T12 | Telegram: recordatorios automáticos (cron) | ❌ |

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para detalles de diseño, flujo de datos, y plan de implementación.

## Merge con BT-Core

1. Copiar `src/tools/TaskManager/` y `SharedUtilities/` al tree de BT-Core
2. Usar un solo `common.py` compartido
3. Deduplicar ENUMs en `db/schema.sql` con `init.sql`
4. Integrar `cli.py` en `cli_task.py` de BT-Core
