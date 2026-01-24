-- ShipAgent Database Schema
-- Reference SQL for documentation and manual database inspection
-- The actual schema is managed by SQLAlchemy ORM models in models.py

-- Jobs table: Tracks batch shipping jobs
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,  -- UUID
    name TEXT NOT NULL,
    description TEXT,
    original_command TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, paused, completed, failed, cancelled
    mode TEXT NOT NULL DEFAULT 'confirm',  -- confirm, auto

    -- Counts
    total_rows INTEGER NOT NULL DEFAULT 0,
    processed_rows INTEGER NOT NULL DEFAULT 0,
    successful_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows INTEGER NOT NULL DEFAULT 0,

    -- Cost tracking
    total_cost_cents INTEGER,  -- Store as cents to avoid float issues

    -- Timestamps (ISO8601 format)
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,

    -- Error info (if failed)
    error_code TEXT,
    error_message TEXT
);

-- Job rows table: Per-row tracking for retry capability
CREATE TABLE job_rows (
    id TEXT PRIMARY KEY,  -- UUID
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    row_checksum TEXT NOT NULL,  -- SHA-256 of row data
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed, skipped

    -- Result data
    tracking_number TEXT,
    label_path TEXT,
    cost_cents INTEGER,

    -- Error info (if failed)
    error_code TEXT,
    error_message TEXT,

    -- Timestamps
    created_at TEXT NOT NULL,
    processed_at TEXT,

    UNIQUE(job_id, row_number)
);

-- Audit logs table: Full logging for debugging and compliance
CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,  -- UUID
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,  -- ISO8601
    level TEXT NOT NULL,  -- INFO, WARNING, ERROR
    event_type TEXT NOT NULL,  -- state_change, api_call, row_event, error
    message TEXT NOT NULL,

    -- Structured data (JSON blob for request/response payloads)
    details TEXT,

    -- Row context (optional, for row-specific events)
    row_number INTEGER
);

-- Indexes for query performance
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at);
CREATE INDEX idx_job_rows_job_id ON job_rows(job_id);
CREATE INDEX idx_job_rows_status ON job_rows(status);
CREATE INDEX idx_audit_logs_job_id ON audit_logs(job_id);
CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp);
