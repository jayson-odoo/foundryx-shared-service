-- PLANNER-3D-S1: additive, idempotent. Same DDL as module migration
-- 0002_planner3d_s1_gateway (which also runs on boot via run_module_migrations).
CREATE SCHEMA IF NOT EXISTS app_planner3d;
ALTER TABLE app_planner3d.p3_job ADD COLUMN IF NOT EXISTS api_key_id VARCHAR;
ALTER TABLE app_planner3d.p3_job ADD COLUMN IF NOT EXISTS idempotency_ref VARCHAR(128);
ALTER TABLE app_planner3d.p3_job ADD COLUMN IF NOT EXISTS request_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_p3_job_idempotency ON app_planner3d.p3_job (tenant_id, idempotency_ref);
CREATE TABLE IF NOT EXISTS app_planner3d.p3_api_key (
    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, name VARCHAR(200) NOT NULL,
    key_prefix VARCHAR(16) NOT NULL, key_hash VARCHAR(64) NOT NULL, key_last4 VARCHAR(4) NOT NULL,
    created_by VARCHAR, created_at TIMESTAMPTZ NOT NULL, last_used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_p3_api_key_tenant ON app_planner3d.p3_api_key (tenant_id);
CREATE INDEX IF NOT EXISTS ix_p3_api_key_prefix ON app_planner3d.p3_api_key (key_prefix);
CREATE TABLE IF NOT EXISTS app_planner3d.p3_api_audit (
    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, key_id VARCHAR NOT NULL, method VARCHAR(8) NOT NULL,
    route VARCHAR(200) NOT NULL, status_code INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_p3_api_audit_tenant ON app_planner3d.p3_api_audit (tenant_id);
CREATE INDEX IF NOT EXISTS ix_p3_api_audit_created_at ON app_planner3d.p3_api_audit (created_at);
CREATE TABLE IF NOT EXISTS app_planner3d.p3_upload (
    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, api_key_id VARCHAR, mime VARCHAR(100) NOT NULL,
    size INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, storage_key VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_p3_upload_tenant ON app_planner3d.p3_upload (tenant_id);
CREATE INDEX IF NOT EXISTS ix_p3_upload_expiry ON app_planner3d.p3_upload (used_at, expires_at);
CREATE TABLE IF NOT EXISTS app_planner3d.p3_receiver (
    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, url VARCHAR(2048) NOT NULL, events_json JSON NOT NULL,
    secret_encrypted TEXT NOT NULL, active BOOLEAN NOT NULL, last_success_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_p3_receiver_tenant ON app_planner3d.p3_receiver (tenant_id);
CREATE TABLE IF NOT EXISTS app_planner3d.p3_delivery (
    id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL,
    receiver_id VARCHAR NOT NULL REFERENCES app_planner3d.p3_receiver(id),
    job_id VARCHAR, event_id VARCHAR(64) NOT NULL, event VARCHAR(40) NOT NULL, body_encrypted TEXT NOT NULL,
    attempt INTEGER NOT NULL, next_at TIMESTAMPTZ, status VARCHAR(16) NOT NULL, last_code INTEGER,
    last_error VARCHAR(500), last_attempt_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_p3_delivery_tenant ON app_planner3d.p3_delivery (tenant_id);
CREATE INDEX IF NOT EXISTS ix_p3_delivery_due ON app_planner3d.p3_delivery (status, next_at);
CREATE INDEX IF NOT EXISTS ix_p3_delivery_job ON app_planner3d.p3_delivery (job_id);
