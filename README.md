# BT-Core: TaskManager

**Compañero silencioso de productividad.** Soltás una idea — por voz, foto de pizarra, texto en Telegram, o terminal — y el sistema clasifica, vincula, estima y ordena. Sin mover un dedo en organizar.

> **Norte del producto:** decidir en 30 segundos qué hacer ahora, con evidencia
> de tu propia historia. No un gestor de tareas: un motor de decisión que
> **olvida a propósito**. Roadmap, criterios de aceptación y regla de kill en
> [PRODUCT.md](PRODUCT.md).

> **Diseño:** [ARCHITECTURE.md](ARCHITECTURE.md) (mecanismo del Grafo Vivo) ·
> [DESIGN.md](DESIGN.md) (decisiones: por qué determinista y no agéntico)

## El problema que resuelve

Tus tareas están dispersas: libreta del trabajo, pizarra de la U, notas en el celular, chats de WhatsApp. Se pierden. TaskManager las centraliza en **una sola terminal** — da igual si entrás por Telegram o por CLI.

## Cómo usarlo

### Telegram (`@bt_task_bot`)

| Comando | Qué hace |
|---|---|
| `/add Comprar materiales para el lab` | Crea tarea. La IA clasifica proyecto, prioridad, horas. |
| `/list` | Lista pendientes con prioridades |
| `/done 3 --hours 5.5` | Completa tarea #3, registra horas reales |
| `/update 5 --priority 4 --due 2026-07-25` | Modifica prioridad, fecha |
| `/overdue` | Tareas vencidas |
| `/search presentación` | Busca tareas similares semánticamente |
| `/tablero` | Vista compacta del dashboard |
| `/export` | Genera archivos Markdown del estado actual |
| 📸 Enviar foto | OCR automático → Vision Diff → tareas nuevas y completadas |
| 🎙️ Enviar audio | Transcripción → clasificación → tarea creada |

### Terminal (CLI)

```bash
cd ~/Dev/FigureThisOut/TaskManager && source .venv/bin/activate

python3 -m src.ingest.cli add --title "Lab 5 Empotrados" --embed
python3 -m src.ingest.cli list
python3 -m src.ingest.cli complete --id 3 --hours 6
python3 -m src.ingest.cli overdue
python3 -m src.ingest.cli classify "Terminar paper de CV"
python3 -m src.ingest.cli ocr-whiteboard /tmp/pizarra.jpg
python3 -m src.ingest.cli export
python3 -m src.ingest.cli heartbeat --action all
```

Cada módulo también es ejecutable por separado (`python3 -m src.processing.tasks list`)
y siempre imprime JSON a stdout.

## ¿Qué pasa por debajo?

Cada tarea que creás dispara una cadena silenciosa:

1. **Clasificación** (DeepSeek) → proyecto, prioridad, horas estimadas
2. **Embedding** (Ollama, 768d) → vector semántico en pgvector
3. **Linking** → se buscan las 5 tareas más similares por similitud coseno
4. **Sesgo de realidad** → las horas estimadas se anclan en horas reales de tareas similares
5. **Grafo** → `task_links` mantiene el mapa de relaciones actualizado

## Setup rápido

```bash
git clone https://github.com/BrandonTrigueros/TaskManager.git ~/Dev/TaskManager
cd ~/Dev/TaskManager
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
docker exec -i taskmanager_pg psql -U hb_admin -d heartbeat -h localhost < db/schema.sql
# Editar .env con GEMINI_API_KEY y DEEPSEEK_API_KEY
ollama pull nomic-embed-text
python3 -m src.ingest.bot &
```

Prerrequisitos: Docker, Python 3.11+, Ollama.

## Proyectos

`Empotrados` `Computer Vision` `HPE` `Personal` `Universidad` `Finanzas` `Salud` `Hogar`

## Prioridades

🟥 Crítico · 🟧 Urgente · 🟨 Importante · 🟦 Normal · ⬜ Bajo
