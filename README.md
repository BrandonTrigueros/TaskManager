# BT-Core: TaskManager

**Compañero silencioso de productividad.** Soltás una idea — por voz, foto de
cuaderno, captura de pantalla o texto — y el sistema clasifica, vincula, estima
y decide qué hacer ahora. Sin mover un dedo en organizar.

> **Norte del producto:** decidir en 30 segundos qué hacer ahora, con evidencia
> de tu propia historia. No un gestor de tareas: un motor de decisión que
> **olvida a propósito**. Roadmap, criterios de aceptación y regla de kill en
> [PRODUCT.md](PRODUCT.md).

> **Cliente:** app Android nativa (Kotlin + Compose) en `android/`, hablando
> con la API local `src/api/server.py`. Ver [ANDROID.md](ANDROID.md).

> **Diseño:** [ARCHITECTURE.md](ARCHITECTURE.md) (mecanismo del Grafo Vivo) ·
> [DESIGN.md](DESIGN.md) (decisiones: por qué determinista y no agéntico)

## El problema que resuelve

Tus tareas están dispersas: libreta del trabajo, pizarra de la U, notas en el
celular, chats de WhatsApp. Se pierden. TaskManager las centraliza en un solo
lugar **y luego decide por vos**: no te devuelve una lista, te devuelve dos
propuestas — un arranque corto y un bloque profundo.

## Cómo usarlo

### App Android (principal)

| Pantalla | Qué hace |
|---|---|
| **Hoy** | Dos tarjetas: ⚡ arranque (≤45 min) y 🧠 bloque profundo. Cada una con duración esperada, la razón de la elección y un primer paso de 2 minutos |
| **Hoy → ✅ Hecho** | Cierra en un tap; elegís horas reales (±50 % de la estimación) |
| **Hoy → ⏭ Hoy no** | Descarta la propuesta sin perderla |
| **Ajustes** | URL del backend + token del dispositivo |

### Terminal

```bash
cd ~/Dev/FigureThisOut/TaskManager && source .venv/bin/activate

python3 -m src.processing.next_action --demo        # sin DB, corpus de 30 tareas
python3 -m src.ingest.cli add --title "Lab 5 Empotrados" --embed
python3 -m src.ingest.cli list
python3 -m src.ingest.cli complete --id 3 --hours 6
python3 -m src.ingest.cli heartbeat --action graph
```

Cada módulo también es ejecutable por separado (`python3 -m src.processing.tasks list`)
y siempre imprime JSON a stdout.

### API local

```bash
python3 -m src.api.server     # :8787, Bearer API_TOKEN
```

## ¿Qué pasa por debajo?

1. **Captura** → texto, OCR de cualquier soporte, transcripción local
2. **Clasificación** (DeepSeek) → proyecto y prioridad; **las horas las pone el
   Grafo Vivo**, no el LLM
3. **Embedding** (Ollama, 768d) → vector semántico en pgvector
4. **Linking** → 5 vecinos por similitud coseno, peso combinado con decaimiento
   temporal y co-ocurrencia
5. **Selección** (`next_action`) → dos propuestas con duración esperada y razón
6. **Cierre** → tus horas reales recalibran el cluster

## Setup

Sin contenedores: PostgreSQL corre como proceso nativo.

```bash
sudo apt install postgresql-16 postgresql-16-pgvector
git clone https://github.com/BrandonTrigueros/TaskManager.git ~/Dev/TaskManager
cd ~/Dev/TaskManager && bash scripts/setup_loq.sh
```

El script crea rol, base, aplica `db/schema.sql`, arma el `.venv` y baja el
modelo de embeddings. Después editá `.env` con `GEMINI_API_KEY` y
`DEEPSEEK_API_KEY`.

Prerrequisitos: PostgreSQL 16 + pgvector, Python 3.11+, Ollama.

## Proyectos

`Empotrados` `Computer Vision` `HPE` `Personal` `Universidad` `Finanzas` `Salud` `Hogar`

## Prioridades

🟥 Crítico · 🟧 Urgente · 🟨 Importante · 🟦 Normal · ⬜ Bajo
