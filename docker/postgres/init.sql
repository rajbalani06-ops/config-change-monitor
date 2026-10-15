CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO tenants (id, name) VALUES ('default', 'Default tenant')
ON CONFLICT (id) DO NOTHING;
INSERT INTO tenants (id, name) VALUES ('tenant-a', 'Tenant A')
ON CONFLICT (id) DO NOTHING;
INSERT INTO tenants (id, name) VALUES ('tenant-b', 'Tenant B')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS monitored_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_scan_at TIMESTAMPTZ,
    last_error TEXT,
    last_operation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, path)
);

CREATE TABLE IF NOT EXISTS file_snapshots (
    file_id UUID PRIMARY KEY REFERENCES monitored_files(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    content_hash TEXT NOT NULL,
    structure JSONB,
    valid BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS change_events (
    id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    file_id UUID NOT NULL REFERENCES monitored_files(id) ON DELETE CASCADE,
    correlation_id UUID NOT NULL,
    schema_version TEXT NOT NULL,
    operation TEXT NOT NULL,
    parse_status TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    content_hash TEXT,
    previous_hash TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outbox (
    id UUID PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES change_events(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ
);

ALTER TABLE outbox ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS notification_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    url TEXT NOT NULL,
    auth_header_name TEXT,
    auth_header_value TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL,
    tenant_id TEXT NOT NULL,
    destination_id UUID,
    status TEXT NOT NULL,
    http_status INTEGER,
    error TEXT,
    attempt INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dead_letter_events (
    event_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watcher_leases (
    directory TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_tenant_created ON change_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_file ON change_events (file_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_operation ON change_events (operation);
CREATE INDEX IF NOT EXISTS idx_events_delivery ON change_events (delivery_status);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox (status, available_at);
CREATE INDEX IF NOT EXISTS idx_delivery_event ON delivery_attempts (event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_tenant ON monitored_files (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log (tenant_id, created_at DESC);
