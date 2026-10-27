-- =============================================================
-- BT-Core: TaskManager — Master Schema
-- PostgreSQL 16 + pgvector
-- Estándar canónico: 768 dimensiones (bge-base-en-v1.5 / nomic-embed-text)
--
-- Run:  psql -U hb_admin -d heartbeat -f db/schema.sql
-- =============================================================

-- ─── Extensions ──────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── ENUM Types (idempotent) ─────────────────────────────────

DO $$ BEGIN
    CREATE TYPE task_status AS ENUM (
        'pending',
        'in_progress',
        'completed',
        'rescheduled',
        'cancelled',
        'archived'
    );
EXCEPTION WHEN duplicate_object THEN
    -- Add 'archived' if missing (PostgreSQL 12+)
    BEGIN
        ALTER TYPE task_status ADD VALUE 'archived';
    EXCEPTION WHEN duplicate_object THEN NULL;
    END;
END $$;

DO $$ BEGIN
    CREATE TYPE source_origin AS ENUM (
        'telegram',
        'google_tasks',
        'apple_reminders',
        'cli',
        'n8n',
        'owntracks',
        'gmail'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE priority_level AS ENUM (
        '1', '2', '3', '4', '5'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE embedding_model AS ENUM (
        'bge-base-en-v1.5',
        'nomic-embed-text'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── Tasks ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,

    -- Clasificación (DeepSeek V4-Flash / R1)
    project_tag     VARCHAR(50),
    priority        priority_level DEFAULT '3',
    estimated_hours DECIMAL(5,2),
    actual_hours    DECIMAL(5,2),          -- Feedback loop: realidad vs estimación (REQ-T7)

    -- Estado
    status          task_status DEFAULT 'pending',

    -- Origen
    source_origin   source_origin,
    external_id     VARCHAR(100),

    -- Temporalidad
    due_date        TIMESTAMPTZ,

    -- Geofencing (Owntracks)
    location_lat    DECIMAL(10,7),
    location_lon    DECIMAL(10,7),
    location_label  VARCHAR(100),
    geofence_radius_m INTEGER DEFAULT 200,

    -- ─── Vector canónico 768d ─────────────────────────────
    --   Spoke (X220/HP):  bge-base-en-v1.5  → 768d
    --   Hub   (LOQ):      nomic-embed-text  → 768d
    --   Ambos generan vectores en el mismo espacio latente.
    --   Distancia: cosine similarity (<=>).
    embedding       VECTOR(768),
    embedding_model embedding_model,

    -- Metadata
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ DEFAULT NOW()  -- Consolidación de Sueño: pruning threshold
);

-- ─── Indexes ─────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project     ON tasks(project_tag);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date    ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_external_id ON tasks(external_id);
CREATE INDEX IF NOT EXISTS idx_tasks_priority    ON tasks(priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_source      ON tasks(source_origin);

-- ─── Vector Index (HNSW, cosine similarity) ──────────────────
--   HNSW elegido sobre IVFFlat porque:
--     1. No requiere datos pre-cargados para construir el índice.
--     2. Mejor relación recall/speed para datasets < 100K vectores.
--     3. Build-time insignificante en schema idempotente.
--   Para producción con >100K tareas, migrar a IVFFlat con lists=1000.

CREATE INDEX IF NOT EXISTS idx_tasks_embedding
    ON tasks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- ─── Task Links (REQ-T5: grafo de similitud) ─────────────────

CREATE TABLE IF NOT EXISTS task_links (
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    linked_task_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    similarity      DECIMAL(5,4) NOT NULL,           -- Cosine similarity [0.0, 1.0]
    weight          DECIMAL(5,4) DEFAULT 0.0,        -- Peso combinado (semántico + temporal + cooc)
    temporal_score  DECIMAL(5,4) DEFAULT 0.0,        -- Decaimiento Hebbiano e^(-λ·Δt)
    co_occurrence_score DECIMAL(5,4) DEFAULT 0.0,    -- HeLa-Mem: score conductual [0, 1]
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (task_id, linked_task_id),
    CHECK (task_id <> linked_task_id)
);

CREATE INDEX IF NOT EXISTS idx_task_links_reverse
    ON task_links(linked_task_id, task_id);

-- ─── Utility: updated_at trigger ─────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;
CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ─── Utility: embedding dimension guard ───────────────────────
--   Garantiza que todo vector insertado tenga exactamente 768 dims.

CREATE OR REPLACE FUNCTION check_embedding_dims()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.embedding IS NOT NULL THEN
        IF vector_dims(NEW.embedding) <> 768 THEN
            RAISE EXCEPTION 'embedding must be exactly 768 dimensions, got %',
                vector_dims(NEW.embedding);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_embedding_dims ON tasks;
CREATE TRIGGER trg_embedding_dims
    BEFORE INSERT OR UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION check_embedding_dims();

-- ─── Co-Occurrence (HeLa-Mem / Salto Asociativo) ──────────────
--   Captura patrones conductuales: tareas completadas juntas,
--   en secuencia, o en la misma franja horaria habitual.

CREATE TABLE IF NOT EXISTS task_co_occurrence (
    task_id_a       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    task_id_b       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    co_count        INTEGER DEFAULT 1,           -- Veces completadas juntas
    sequential_count INTEGER DEFAULT 0,          -- Veces en secuencia A→B
    same_session_count INTEGER DEFAULT 0,        -- Veces en misma sesión (<2h)
    co_score        DECIMAL(5,4) DEFAULT 0.0,    -- Score normalizado [0, 1]
    last_together   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (task_id_a, task_id_b),
    CHECK (task_id_a < task_id_b)   -- Canonical ordering, no duplicates
);

CREATE INDEX IF NOT EXISTS idx_cooc_score ON task_co_occurrence(co_score DESC);
CREATE INDEX IF NOT EXISTS idx_cooc_task_a ON task_co_occurrence(task_id_a);
CREATE INDEX IF NOT EXISTS idx_cooc_task_b ON task_co_occurrence(task_id_b);

-- ─── Structural Debt Log (CogniFold) ──────────────────────────
--   Registra las 4 deudas estructurales en cada ciclo de heartbeat.

CREATE TABLE IF NOT EXISTS structural_debt_log (
    id              SERIAL PRIMARY KEY,
    checked_at      TIMESTAMPTZ DEFAULT NOW(),
    orphan_tasks    INTEGER,          -- Tareas sin ningún link
    dead_links      INTEGER,          -- Links con weight < 0.1
    fragmentation   DECIMAL(5,4),     -- Ratio comunidades / total_tareas
    graph_density   DECIMAL(5,4),     -- Links existentes / links posibles
    total_tasks     INTEGER,
    total_links     INTEGER,
    total_communities INTEGER
);

-- ─── Decisions (M1: "una decisión al día") ────────────────────
--   Registra cada propuesta de next_action.py y su desenlace.
--   Es la materia prima para calibrar la fórmula de score:
--   sin esta tabla, M1 no puede mejorar con el uso.

CREATE TABLE IF NOT EXISTS decisions (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    slot            VARCHAR(8),        -- 'quick' (arranque) | 'deep' (bloque)
    score           DECIMAL(8,4) NOT NULL,
    expectancy      DECIMAL(5,4),      -- [0,1] calibración histórica del cluster
    value_score     DECIMAL(5,4),      -- [0,1] prioridad normalizada
    demora_hours    DECIMAL(10,2),     -- horas hasta el vencimiento (NULL = sin fecha)
    estimate_hours  DECIMAL(5,2),      -- expectativa mostrada al usuario
    alternatives    INTEGER,           -- pendientes consideradas
    rationale       TEXT,              -- por qué se eligió
    chosen_at       TIMESTAMPTZ DEFAULT NOW(),
    executed        BOOLEAN,           -- NULL = sin respuesta todavía
    actual_hours    DECIMAL(5,2),      -- horas reales al cerrar
    closed_at       TIMESTAMPTZ
);

-- Idempotente: instalaciones previas sin la columna `slot`
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS slot VARCHAR(8);

CREATE INDEX IF NOT EXISTS idx_decisions_task
    ON decisions(task_id, chosen_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_recent
    ON decisions(chosen_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_open
    ON decisions(chosen_at DESC) WHERE executed IS NULL;
