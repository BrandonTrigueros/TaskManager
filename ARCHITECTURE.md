# BT-Core: TaskManager — Arquitectura

> **Stack:** Gemini 2.5 Flash Lite (Vision) + DeepSeek V4-Flash (razonamiento)  
> **DB:** PostgreSQL 16 + pgvector (768d canónico)  
> **Grafo Vivo:** 6 capas (Semántica → Temporal → HeLa-Mem → Estructural → Predictiva → CogniFold)

## Arquitectura de Capas

```mermaid
flowchart TB
    %% ═══ CLIENTE ═══
    subgraph CLIENT["📱 CLIENTE"]
        direction LR
        APP["App Android<br/>(Kotlin + Compose)"] --> SRV["api/server.py<br/>:8787 · Bearer"]
    end

    %% ═══ INGESTA ═══
    subgraph INGEST["📥 INGESTA"]
        direction LR
        CLI["💻 CLI"] --> cli["cli.py"]
        IMG["📸 Foto<br/>(cualquier soporte)"] --> ocr["ocr.py<br/>(Gemini Vision)"]
        AUD["🎙️ Audio"] --> trans["transcribe.py<br/>(Faster-Whisper)"]
    end

    %% ═══ PROCESAMIENTO ═══
    subgraph PROC["⚙️ PROCESAMIENTO"]
        direction TB
        vdiff["vision_diff.py<br/>DeepSeek R1<br/>¿nueva o completada?"]
        classify["classify.py<br/>Grafo Vivo + DeepSeek<br/>→ project_tag, priority"]
        tasks["tasks.py<br/>INSERT + embed 768d<br/>UPDATE / complete"]
    end

    %% ═══ PERSISTENCIA ═══
    subgraph PERSIST["💾 PERSISTENCIA"]
        pg[("PostgreSQL + pgvector<br/>tasks · task_links<br/>task_co_occurrence<br/>structural_debt_log")]
    end

    %% ═══ CONOCIMIENTO — Grafo Vivo 6-capas ═══
    subgraph KNOW["🧠 CONOCIMIENTO — Grafo Vivo (6 capas)"]
        direction TB
        l1["CAPA 1 · SEMÁNTICA<br/>cosine similarity<br/>→ linked_task_ids"]
        l2["CAPA 2 · TEMPORAL<br/>Hebbiano e^(-λ·Δt)<br/>λ=0.001"]
        lH["CAPA H · HeLa-Mem<br/>co-occurrencia conductual<br/>→ salto asociativo"]
        l3["CAPA 3 · ESTRUCTURAL<br/>comunidades HCL<br/>+ CI [μ-σ, μ+σ]"]
        l4["CAPA 4 · PREDICTIVA<br/>avg actual_hours<br/>+ planning bias ratio"]
        l5["CAPA 5 · CONSOLIDACIÓN<br/>poda · fusión · archivo<br/>recentrado nocturno"]
        l6["CAPA 6 · COGNIFOLD<br/>deuda estructural<br/>→ health score 0-100"]
        l1 --> l2 --> lH --> l3 --> l4 --> l5 --> l6
    end

    %% ═══ ORQUESTACIÓN ═══
    subgraph ORCH["🔄 ORQUESTACIÓN"]
        hb["heartbeat.py<br/>cada 60 min<br/>+ sleep nocturno"]
    end

    %% ── Flujo de datos ──
    ocr -->|"texto"| vdiff
    trans -->|"texto"| classify
    cli -->|"comando"| classify
    bot -->|"comando"| classify
    vdiff -->|"nueva tarea"| classify
    vdiff -->|"completada"| tasks
    classify -->|"tarea clasificada"| tasks
    tasks -->|"completion hook"| lH

    %% ── Persistencia ──
    tasks -->|"INSERT / UPDATE"| pg

    %% ── Ciclo de conocimiento ──
    pg -->|"datos crudos"| hb
    hb -->|"reconstruye"| KNOW
    KNOW -->|"linked_ids + horas + CI + planning_bias"| classify

    %% ── Estilos ──
    style classify fill:#2a7,stroke:#333,color:#fff
    style vdiff fill:#258,stroke:#333,color:#fff
    style tasks fill:#258,stroke:#333,color:#fff
    style lH fill:#e73,stroke:#333,color:#fff
    style l5 fill:#e73,stroke:#333,color:#fff
    style l6 fill:#e73,stroke:#333,color:#fff
    style KNOW fill:#84b,stroke:#333,color:#fff
    style hb fill:#e73,stroke:#333,color:#fff
    style pg fill:#369,stroke:#333,color:#fff
```

## Ciclo Virtuoso

`tasks → PostgreSQL → heartbeat → Grafo Vivo → classify`. Cada iteración refina
predicciones con datos reales (planning bias) y patrones conductuales (HeLa-Mem).

## Estructura

```
TaskManager/
├── db/schema.sql              # PostgreSQL + pgvector + decisions + debt_log
│
├── src/
│   ├── common.py              # SSOT: pool DB + Gemini + DeepSeek REST
│   ├── ingest/                # INGESTA
│   │   ├── bot.py             #   Telegram bot determinista
│   │   ├── cli.py             #   CLI router
│   │   └── heartbeat.py       #   Orquestador 60min + sleep nocturno
│   ├── processing/            # PROCESAMIENTO
│   │   ├── classify.py        #   Grafo Vivo + DeepSeek
│   │   ├── vision_diff.py     #   DeepSeek R1 diff lógico
│   │   └── tasks.py           #   CRUD + embed + dedup
│   ├── knowledge/             # CONOCIMIENTO — Grafo Vivo 6-capas
│   │   ├── graph.py           #   Motor: 6 capas + run_full_cycle
│   │   ├── co_occurrence.py   #   HeLa-Mem: co-ocurrencia conductual
│   │   └── embeddings.py      #   Ollama → 768d → pgvector
│   └── shared/                # UTILIDADES
│       ├── ocr.py             #   Gemini VLM
│       ├── transcribe.py      #   Faster-Whisper
│       └── export_md.py       #   Markdown dashboard
│
├── tests/
│   └── stress_test_grafo_vivo.py  # 11 fases de validación
└── scripts/setup_loq.sh
```

## Stack de IA

| Capa | Motor | Rol |
|---|---|---|
| Vision | Gemini 2.5 Flash Lite | OCR pizarras, recibos |
| Razonamiento | DeepSeek V4-Flash | project_tag + priority |
| Diff Lógico | DeepSeek R1 | Vision Diff |
| Audio | Faster-Whisper | Transcripción local |
| Embeddings | nomic-embed-text (Ollama) | Vectores 768d |
| Grafo Vivo | Python + pgvector + scipy | 6 capas de conocimiento |

## Las 6 capas del Grafo Vivo

| # | Capa | ¿Qué hace? | Output |
|---|---|---|---|
| **1** | Semántica | Cosine similarity pgvector | `linked_task_ids` (top-5 vecinos) |
| **2** | Temporal | Decaimiento Hebbiano `e^(-λ·Δt)` | Peso temporal por antigüedad |
| **H** | **HeLa-Mem** | Co-ocurrencia conductual | Peso por hábitos (misma sesión, secuencia) |
| **3** | Estructural | HCL average-linkage | Comunidades + intervalos de confianza `[μ-σ, μ+σ]` |
| **4** | Predictiva | `avg actual_hours` por cluster | `estimated_hours` + ratio planificación |
| **5** | **Consolidación** | Poda (w<0.1), fusión (Jaccard>0.5), archivado (>90d) | Grafo limpio y eficiente |
| **6** | **CogniFold** | 4 deudas estructurales | Health Score 0–100 |

### Peso combinado (3 factores)

```
w = 0.55 × cosine_sim + 0.30 × e^(-λ·Δt) + 0.15 × cooc_score
```

| Símbolo | Peso | Significado |
|---|---|---|
| `β_sem` | 0.55 | Similitud semántica (embedding) |
| `β_temp` | 0.30 | Relevancia temporal (decaimiento) |
| `β_cooc` | 0.15 | Patrón conductual (HeLa-Mem) |

## ¿Cómo funciona el feedback?

1. **Creás tarea** → `classify.py` consulta Grafo Vivo → recibe `linked_ids` (Capa 1) + `estimated_hours` con `[CI_lower, CI_upper]` (Capa 4) + `planning_bias` del proyecto → DeepSeek solo decide `project_tag` + `priority` → `tasks.py` INSERT.

2. **Completás tarea** → `tasks.py complete --hours X` → `actual_hours` + `last_activity_at` se persisten → hook dispara `record_completion()` para HeLa-Mem.

3. **Heartbeat (60 min)** → `graph.py` actualiza co-ocurrencia (Capa H), links semánticos (Capa 1), pesos temporales (Capa 2), comunidades con CI (Capa 3), planning ratios (Capa 4).

4. **Sleep (nocturno)** → `consolidate_sleep()` poda links muertos, fusiona comunidades solapadas, archiva tareas inactivas >90 días, recentra pesos. Corre `structural_debt_report()` para el dashboard CogniFold.

5. **Próxima tarea** → `classify.py` recibe datos MÁS precisos + patrón conductual → el ciclo se refuerza.

## Hiperparámetros

| Parámetro | Valor | Significado |
|---|---|---|
| λ (lambda) | 0.001 | Decaimiento temporal (vida media ~29 días) |
| β_sem | 0.55 | Peso semántico en combined_weight |
| β_temp | 0.30 | Peso temporal en combined_weight |
| β_cooc | 0.15 | Peso co-ocurrencia (HeLa-Mem) |
| TOP_K | 5 | Vecinos máximos por tarea |
| Cohesión mínima | 0.6 | Para promover cluster a subproyecto |
| Tamaño mínimo | 5 | Tareas mínimas para subproyecto |
| PRUNE_THRESHOLD | 0.1 | Peso mínimo para mantener un link |
| MERGE_JACCARD | 0.5 | Solapamiento para fusionar comunidades |
| ARCHIVE_DAYS | 90 | Inactividad para archivado automático |

## Deuda Estructural (CogniFold)

| Métrica | Significado | Alerta |
|---|---|---|
| **Huérfanas** | % tareas sin links | >20% → problema de embeddings |
| **Dead links** | % links con weight < 0.1 | >30% → λ muy agresivo |
| **Fragmentación** | ratio comunidades/tareas | >50% → umbral de clustering muy estricto |
| **Densidad** | links existentes / posibles | <10% → grafo muy disperso |
| **Health Score** | 0–100 combinado | <60 → requiere intervención |
