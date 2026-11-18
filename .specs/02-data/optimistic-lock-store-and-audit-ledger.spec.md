# Specification 02-Data: Optimistic Lock Store & Append-Only Audit Ledger

> **Repository**: `pulseflow-collab`
> **Layer**: Infrastructure / Persistence (`src/infrastructure/persistence/`, `migrations/`)
> **Author**: `data-architect`
> **Status**: Approved

---

## 1. Purpose & Scope

This specification defines the relational data model, atomic concurrency control mechanics, database-enforced append-only audit ledger triggers, and environment isolation policies for **PulseFlow Collab** (Real-Time Collaborative Incident Command & Operational Sync Engine).

---

## 2. Relational Schema & Constraints

### 2.1 `incidents` (Versioned Incident Command Aggregates)
Stores the current state of operational incidents with a monotonically increasing `version` integer (`>= 1`) enforcing Optimistic Concurrency Control (OCC).

| Column | SQL Type (PostgreSQL / SQLite) | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `incident_id` | `VARCHAR(64)` / `TEXT` | `PRIMARY KEY` | Deterministic or UUID incident identifier (e.g., `INC-2026-101`). |
| `title` | `VARCHAR(180)` / `TEXT` | `NOT NULL` | Concise incident summary title (`3..180` chars). |
| `service_name` | `VARCHAR(128)` / `TEXT` | `NOT NULL` | Affected microservice or subsystem identifier. |
| `severity` | `VARCHAR(16)` / `TEXT` | `NOT NULL CHECK (severity IN ('SEV1','SEV2','SEV3','SEV4'))` | Operational impact tier. |
| `status` | `VARCHAR(32)` / `TEXT` | `NOT NULL CHECK (status IN ('OPEN','INVESTIGATING','MITIGATED','RESOLVED'))` | Finite-State Machine lifecycle phase. |
| `commander` | `VARCHAR(128)` / `TEXT` | `NOT NULL` | Assigned Incident Commander handle. |
| `summary` | `TEXT` | `NOT NULL` | Live tactical situational summary. |
| `version` | `INTEGER` | `NOT NULL DEFAULT 1 CHECK (version >= 1)` | Monotonic OCC version counter. |
| `created_at` | `TIMESTAMPTZ` / `TEXT` | `NOT NULL` | ISO-8601 UTC creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` / `TEXT` | `NOT NULL` | ISO-8601 UTC last mutation timestamp. |

### 2.2 `incident_comments` (Chronological Tactical Timeline Notes)
Stores collaborative timeline notes attached to an incident.

| Column | SQL Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `comment_id` | `VARCHAR(64)` / `TEXT` | `PRIMARY KEY` | Unique comment identifier. |
| `incident_id` | `VARCHAR(64)` / `TEXT` | `NOT NULL REFERENCES incidents(incident_id)` | Parent incident reference. |
| `author` | `VARCHAR(128)` / `TEXT` | `NOT NULL` | Responder handle who posted the note. |
| `body` | `TEXT` | `NOT NULL` | Tactical timeline entry text. |
| `created_at` | `TIMESTAMPTZ` / `TEXT` | `NOT NULL` | ISO-8601 UTC timestamp. |

### 2.3 `incident_audit_ledger` (Immutable Append-Only Operational Audit Trail)
Stores every state transition, creation event, and comment publication with cryptographic/forensic immutability enforced at the database engine layer.

| Column | SQL Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `audit_id` | `VARCHAR(64)` / `TEXT` | `PRIMARY KEY` | Unique audit entry identifier. |
| `incident_id` | `VARCHAR(64)` / `TEXT` | `NOT NULL REFERENCES incidents(incident_id)` | Target incident identifier. |
| `version` | `INTEGER` | `NOT NULL CHECK (version >= 1)` | Incident aggregate version associated with the event. |
| `actor` | `VARCHAR(128)` / `TEXT` | `NOT NULL` | Responder or system actor performing the mutation. |
| `action` | `VARCHAR(64)` / `TEXT` | `NOT NULL` | Semantic event code (`INCIDENT_CREATED`, `STATUS_TRANSITION`, `INCIDENT_UPDATED`, `COMMENT_ADDED`, etc.). |
| `changes_json` | `JSONB` / `TEXT` | `NOT NULL` | Structured JSON diff of before/after fields. |
| `created_at` | `TIMESTAMPTZ` / `TEXT` | `NOT NULL` | ISO-8601 UTC event timestamp. |

---

## 3. Atomic Compare-And-Swap (CAS) for Optimistic Concurrency Control

To prevent lost updates when multiple responders concurrently edit an incident or transition its status, `save_updated_incident` executes an atomic Compare-And-Swap SQL `UPDATE` inside a database transaction:

```sql
UPDATE incidents
SET title = ?,
    service_name = ?,
    severity = ?,
    status = ?,
    commander = ?,
    summary = ?,
    version = ?,
    updated_at = ?
WHERE incident_id = ? AND version = ?;
```

### CAS Resolution Flow
1. **`cursor.rowcount == 1`**:
   - The caller's `expected_version` matched the database row's `version`, and the row has been atomically advanced to `expected_version + 1`.
   - Within the **same ACID transaction**, the repository inserts the corresponding `IncidentAuditRecord` into `incident_audit_ledger` and commits.
2. **`cursor.rowcount == 0`**:
   - The repository queries `SELECT version FROM incidents WHERE incident_id = ?`:
     - If no row is returned: raises `IncidentNotFoundError(updated.incident_id)`.
     - If a row exists with `actual_version`: rolls back and raises `OptimisticConcurrencyError(updated.incident_id, expected_version, actual_version)` (`ERR-409-OPTIMISTIC-LOCK`).

---

## 4. Database-Level Append-Only Audit Ledger Enforcement

Historical incident command audit records must never be altered or deleted. Both PostgreSQL and SQLite enforce this invariant via `BEFORE UPDATE` and `BEFORE DELETE` triggers on `incident_audit_ledger`:

- **Trigger Error Signature**: `APPEND_ONLY_LEDGER_VIOLATION: Incident audit ledger is immutable`
- **Repository Exception Mapping**: Any attempt to execute an `UPDATE` or `DELETE` against `incident_audit_ledger` raises `AppendOnlyLedgerError(RuntimeError)`.

### Rollback / Migration Discipline
- Schema initialization is tracked in `migrations/001_init_pulseflow_schema.sql`.
- Downward rollback is explicitly forbidden in production for `incident_audit_ledger` without a signed compliance snapshot export.

---

## 5. Environment Isolation (`.env.development` vs `.env.production`)

- **Development (`.env.development.example` & `docker-compose.dev.yml`)**:
  - `PULSEFLOW_ENV=development`
  - `PULSEFLOW_PORT=8095`
  - Local isolated PostgreSQL (`postgres:16-alpine` on port `5439`) and Redis Pub/Sub backplane (`redis:7-alpine` on port `6385`), or local SQLite persistence for zero-dependency test suites.
- **Production (`.env.production.example`)**:
  - `PULSEFLOW_ENV=production`
  - Requires external TLS-enforced PostgreSQL (`sslmode=require`) and authenticated Redis cluster (`rediss://`).
  - Development containers and test suites must never reference `.env.production`.
