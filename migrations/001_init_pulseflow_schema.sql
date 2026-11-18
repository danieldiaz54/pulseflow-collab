-- =============================================================================
-- Migration 001: PulseFlow Collab Core Schema & Append-Only Audit Ledger
-- Database: PostgreSQL 16+
-- Author: data-architect
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS incidents (
    incident_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(180) NOT NULL,
    service_name VARCHAR(128) NOT NULL,
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('SEV1', 'SEV2', 'SEV3', 'SEV4')),
    status VARCHAR(32) NOT NULL CHECK (status IN ('OPEN', 'TRIAGE', 'INVESTIGATING', 'MITIGATED', 'RESOLVED')),
    commander VARCHAR(128) NOT NULL,
    summary TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_status_severity
    ON incidents (status, severity, updated_at DESC);

CREATE TABLE IF NOT EXISTS incident_comments (
    comment_id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(incident_id) ON DELETE RESTRICT,
    author VARCHAR(128) NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_comments_incident_created
    ON incident_comments (incident_id, created_at ASC);

CREATE TABLE IF NOT EXISTS incident_audit_ledger (
    audit_id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(incident_id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version >= 1),
    actor VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    changes_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incident_audit_ledger_incident_version
    ON incident_audit_ledger (incident_id, version DESC, created_at DESC);

-- =============================================================================
-- Append-Only Ledger Enforcement Trigger (Immutability Invariant)
-- =============================================================================

CREATE OR REPLACE FUNCTION prevent_incident_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'APPEND_ONLY_LEDGER_VIOLATION: Incident audit ledger is immutable (% disallowed on audit_id=%)',
        TG_OP, OLD.audit_id
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_ledger_no_update ON incident_audit_ledger;
CREATE TRIGGER trg_audit_ledger_no_update
BEFORE UPDATE ON incident_audit_ledger
FOR EACH ROW
EXECUTE FUNCTION prevent_incident_audit_mutation();

DROP TRIGGER IF EXISTS trg_audit_ledger_no_delete ON incident_audit_ledger;
CREATE TRIGGER trg_audit_ledger_no_delete
BEFORE DELETE ON incident_audit_ledger
FOR EACH ROW
EXECUTE FUNCTION prevent_incident_audit_mutation();

COMMIT;
