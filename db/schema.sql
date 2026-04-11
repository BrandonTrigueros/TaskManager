-- =============================================================
-- TaskManager — Database Schema (extracted from BT-Core)
-- PostgreSQL 16
--
-- Run:  psql -U hb_admin -d heartbeat -f db/schema.sql
--
-- NOTE: Extensions and shared enums (source_origin) are created
-- here for standalone testing. During merge, deduplicate with
-- the full BT-Core schema.
-- =============================================================

-- ─── Extensions ──────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── ENUM Types ──────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE task_status AS ENUM ('pending', 'in_progress', 'completed', 'rescheduled', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE source_origin AS ENUM ('telegram', 'google_tasks', 'apple_reminders', 'cli', 'n8n', 'owntracks', 'gmail');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── Tasks ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    project_tag VARCHAR(50),
    priority INTEGER CHECK (priority BETWEEN 1 AND 5),
    estimated_hours DECIMAL(5,2),
    status task_status DEFAULT 'pending',
    source_origin source_origin,
    external_id VARCHAR(100),
    due_date TIMESTAMPTZ,
    location_lat DECIMAL(10,7),
    location_lon DECIMAL(10,7),
    location_label VARCHAR(100),
    geofence_radius_m INTEGER DEFAULT 200,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_tag);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_external_id ON tasks(external_id);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC);

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
    BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION update_updated_at();
