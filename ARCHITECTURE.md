# TaskManager — Arquitectura

> **Tipo:** Módulo standalone extraído de BT-Core  
> **Runtime:** OpenClaw Gateway (producción) / Flask harness (dev/test)  
> **DB:** PostgreSQL 16 (Docker)  
> **IA:** Gemini 2.5 Flash Lite (REST, sin gRPC)

## Origen

Este repositorio es un port del módulo TaskManager de [BT-Core](../BT-Core). Se extrajo para desarrollo y testing independiente, sin depender de FinanceSpender, IdeaVault ni la infraestructura completa de Hartbeat.

### Decisiones del port

- **Estructura `src/tools/`**: BT-Core usa `tools/` directo con `sys.path.insert` manual. El port usa paquetes Python (`src.tools.TaskManager.tasks`) para imports limpios y ejecución con `python3 -m`.
- **Import bug corregido**: En BT-Core, `classify_task.py` y `tasks.py` hacen `from src.tools.common import ...` pero la estructura de directorios es `tools/common.py` (sin `src/`). Funciona solo porque el `sys.path.insert` apunta al directorio padre. El port corrige esto al crear la estructura `src/tools/` real.
- **Schema idempotente**: `db/schema.sql` usa `CREATE TABLE IF NOT EXISTS` y `DO $$ BEGIN...EXCEPTION` para los ENUMs, a diferencia del `init.sql` de BT-Core que asume una DB limpia.
- **Docker simplificado**: Bind a `127.0.0.1` en vez de `${HUB_IP}`, volumen nombrado, sin extensión `vector` (no se necesita sin IdeaVault).

## Estructura

```
TaskManager/
├── ARCHITECTURE.md                       ← este archivo
├── README.md
├── TaskManager.md                        # Spec de requerimientos (REQ-T1..T12)
├── docker-compose.yml                    # PostgreSQL 16 local (dev)
├── requirements.txt
├── .env                                  # Variables de entorno (gitignored)
│
├── db/
│   └── schema.sql                        # Schema: tasks + enums (idempotente)
│
├── src/
│   └── tools/
│       ├── common.py                     # DB connection (psycopg2) + Gemini REST API
│       ├── TaskManager/
│       │   ├── tasks.py                  # CRUD: add, list, complete, update, overdue
│       │   └── classify_task.py          # Clasificación IA (Gemini Flash)
│       └── SharedUtilities/
│           ├── ocr.py                    # OCR: whiteboard, receipt, describe (Gemini Vision)
│           └── export_md.py              # Export a Markdown/Obsidian (REQ-T8/T9)
│
├── scripts/
│   └── cli.py                            # CLI router: add, list, classify, export, ocr-*
│
├── tests/
│   └── telegram_harness.py              # Flask webhook harness (simula Telegram → tools)
│
└── openclaw/
    └── skills/
        └── taskmanager/
            └── SKILL.md                  # Skill definition para OpenClaw Gateway
```

## Flujo de Datos

```
                    ┌──────────────────────┐
                    │   Fuentes de entrada  │
                    └──────┬───────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
     ┌───────────┐  ┌───────────┐  ┌───────────┐
     │ Telegram  │  │   CLI     │  │ OpenClaw  │
     │ (harness) │  │ cli.py    │  │ Gateway   │
     └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
           │               │              │
           ▼               ▼              ▼
     ┌─────────────────────────────────────────┐
     │         Tipo de input                    │
     ├──────────┬──────────┬───────────────────┤
     │  Texto   │  Foto    │  Audio (futuro)   │
     └────┬─────┘────┬─────┘───────┬───────────┘
          │          │             │
          │    ┌─────▼──────┐     │
          │    │  ocr.py    │     │ REQ-T3
          │    │ whiteboard │     │ (pendiente)
          │    └─────┬──────┘     │
          │          │            │
          ▼          ▼            ▼
     ┌────────────────────────────────┐
     │   classify_task.py             │
     │   Gemini Flash → JSON          │
     │   {project_tag, priority,      │
     │    estimated_hours}            │
     └──────────────┬─────────────────┘
                    │
                    ▼
     ┌────────────────────────────────┐
     │   tasks.py add                 │
     │   INSERT INTO tasks (...)      │
     └──────────────┬─────────────────┘
                    │
                    ▼
     ┌────────────────────────────────┐
     │   PostgreSQL                   │
     │   tasks table                  │
     └──────────────┬─────────────────┘
                    │
                    ▼
     ┌────────────────────────────────┐
     │   export_md.py                 │
     │   MASTER_LOG.md + por proyecto │
     │   + por tarea (Obsidian vault) │
     └────────────────────────────────┘
```

## Componentes

### `common.py` — Infraestructura compartida

| Función | Propósito |
|---|---|
| `get_conn()` | Conexión psycopg2 (DSN desde `DB_DSN` o vars `DB_*` individuales) |
| `gemini_generate(prompt)` | Gemini REST API con response mode JSON |
| `parse_json_text(text)` | Parser tolerante a markdown fences en respuestas de Gemini |
| `jprint(data)` | JSON a stdout con serialización de dates/Decimals |

**¿Por qué `urllib` en vez de `requests`?** Para minimizar dependencias. `requests` solo se usa en el test harness (Flask). Los tools de producción usan solo stdlib + psycopg2.

**¿Por qué REST en vez de gRPC?** El SDK oficial de Gemini (`google-generativeai`) usa gRPC, que es bloqueado por el proxy Zscaler en la red de HPE. REST con `urllib` bypasea ese problema.

### `tasks.py` — CRUD

5 operaciones: `add`, `list`, `complete`, `update`, `overdue`. Todas usan queries parametrizados (sin SQL injection). Output siempre JSON a stdout para composability con OpenClaw.

### `classify_task.py` — Clasificación IA

Prompt en español → Gemini Flash → JSON con `project_tag`, `priority`, `estimated_hours`. Fallback hardcoded (`Personal`, prioridad 3, 1h) si la API falla.

### `ocr.py` — Visión

3 modos: `whiteboard` (→ array de strings), `receipt` (→ JSON estructurado), `describe` (→ descripción + tags). Usa Gemini Vision con imágenes en base64.

### `export_md.py` — Obsidian Export

Genera 3 niveles de archivos Markdown con linking de Obsidian (`[[...]]`):
1. `MASTER_LOG.md` — Vista global agrupada por proyecto
2. `{PROYECTO}.md` — Un archivo por project_tag con pendientes y completadas
3. `tasks/TASK_{id}.md` — Un archivo por tarea con frontmatter YAML completo

### `telegram_harness.py` — Test Harness

Flask webhook que simula el flujo Telegram sin OpenClaw. Soporta:
- Texto → classify + add
- Foto → OCR whiteboard → classify + add (batch)
- Comandos: `/list`, `/done <id>`, `/overdue`
- Validación de `ALLOWED_USER_ID` para seguridad

**No es el bot de producción.** En producción, OpenClaw Gateway maneja el webhook de Telegram y despacha a los skills.

## Estado de Requerimientos vs Implementación

| REQ | Descripción | Estado | Notas |
|-----|-------------|--------|-------|
| T1 | Multi-source (Telegram texto + foto + CLI) | ✅ Parcial | Texto y foto OK. Audio pendiente (T3) |
| T2 | OCR de pizarras/cuadernos | ✅ | `ocr.py whiteboard` |
| T3 | Transcripción de audio | ❌ | Placeholder en harness. Necesita Gemini audio o Whisper |
| T4 | Diferenciación de cambios entre envíos | ❌ | Requiere embeddings + diff semántico entre fotos sucesivas |
| T5 | Linking de tareas relacionadas | ❌ | Requiere embeddings + similarity search (pgvector) |
| T6 | Categorización latente (proyecto automático) | ✅ | `classify_task.py` con Gemini Flash |
| T7 | Estimación usando contexto histórico | ❌ | Classify estima sin contexto. Necesita query de tareas similares previas |
| T8 | Vista Maestra (MASTER_LOG.md + por proyecto) | ✅ | `export_md.py` |
| T9 | Markdown Sync a Obsidian | ✅ | `export_md.py --output ~/vault/` |
| T10 | Telegram answering (consultas + recordatorios) | ✅ Parcial | Harness soporta `/list`, `/overdue`. Sin recordatorios proactivos |
| T11 | Telegram task update | ✅ Parcial | `/done <id>` en harness. Sin update de otros campos |
| T12 | Telegram reminders automáticos | ❌ | Requiere cron/heartbeat que consulte `due_date` y envíe alerts |

### Próximas prioridades sugeridas

1. **REQ-T3 (Audio)** — Agregar transcripción con `gemini-2.5-flash` en modo audio o Whisper local
2. **REQ-T12 (Reminders)** — Cron job o heartbeat que envíe Telegram alerts para tareas con `due_date < NOW() + interval '24h'`
3. **REQ-T5 (Linking)** — Requiere pgvector + embeddings. Se puede traer de IdeaVault cuando se haga el merge con BT-Core
4. **REQ-T7 (Estimación contextual)** — Query de tareas completadas con `project_tag` similar + promedio de `estimated_hours` como input al prompt de classify

## Variables de Entorno

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `DB_DSN` | No | (construido de DB_*) | DSN completo de PostgreSQL |
| `DB_HOST` | No | `localhost` | Host de PostgreSQL |
| `DB_PORT` | No | `5432` | Puerto de PostgreSQL |
| `POSTGRES_USER` | No | `hb_admin` | Usuario de PostgreSQL |
| `POSTGRES_PASSWORD` | No | `changeme` | Password de PostgreSQL |
| `POSTGRES_DB` | No | `heartbeat` | Nombre de la base de datos |
| `GEMINI_API_KEY` | Sí | — | API key de Google AI Studio |
| `GEMINI_MODEL` | No | `gemini-2.5-flash-lite` | Modelo de Gemini a usar |
| `TASKS_BOT_TOKEN` | Solo harness | — | Token del bot de Telegram |
| `ALLOWED_USER_ID` | Solo harness | — | Telegram user ID autorizado |

## Merge con BT-Core

Cuando se reintegre a BT-Core:

1. Copiar `src/tools/TaskManager/` → `tools/TaskManager/` (o mantener `src/tools/` como estructura unificada)
2. `common.py` ya es idéntico — usar uno solo
3. `SharedUtilities/` se fusiona naturalmente (`ocr.py` lo usan TaskManager y FinanceSpender)
4. `export_md.py` — Agregar la sección de expenses del original de BT-Core
5. `db/schema.sql` → Deduplicar ENUMs con `init.sql` de BT-Core
6. `cli.py` → Integrar en `cli_task.py` de BT-Core (o reemplazarlo)
