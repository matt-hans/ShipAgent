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

CREATE TABLE IF NOT EXISTS hosted_tenants (
    id TEXT PRIMARY KEY,
    provider_host TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CONSTRAINT uq_hosted_tenant_provider_subject UNIQUE (provider_host, provider_subject)
);

CREATE TABLE IF NOT EXISTS connected_accounts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES hosted_tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    account_key TEXT NOT NULL,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    encrypted_token_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT uq_connected_account_tenant_provider_key UNIQUE (tenant_id, provider, account_key)
);

CREATE INDEX IF NOT EXISTS idx_connected_accounts_tenant
    ON connected_accounts(tenant_id);

CREATE TABLE IF NOT EXISTS uploaded_artifacts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES hosted_tenants(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_uploaded_artifacts_tenant
    ON uploaded_artifacts(tenant_id);

CREATE TABLE IF NOT EXISTS confirmation_records (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES hosted_tenants(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    preview_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    token_hash TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    CONSTRAINT uq_confirmation_tenant_idempotency UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_confirmation_records_tenant
    ON confirmation_records(tenant_id);
