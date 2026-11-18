# ADR 002: Optimistic Concurrency Control (OCC) & Database-Enforced Append-Only Audit Ledger

- **Status**: Accepted
- **Date**: 2026-04-12
- **Deciders**: Lead Orchestrator, Domain Architect, Data Architect, Integration Architect

---

## Context

During a `SEV1` production incident, multiple responders frequently attempt to update the incident status, reassign the Incident Commander, or edit the tactical summary simultaneously from different terminals or gateway nodes. Last-Write-Wins (LWW) silently overwrites concurrent updates ("Lost Update" anomaly), while post-incident forensic reviews require an untamperable, chronological record of every mutation.

## Decision

1. **Monotonic Version Counter & Atomic Compare-And-Swap (CAS)**:
   - Every `Incident` aggregate maintains an integer `version >= 1`.
   - Every mutation (`PATCH /api/v1/incidents/{incident_id}`) requires an explicit `expected_version` in the request payload.
   - Both the domain aggregate (`Incident.apply_update`) and the SQL repository (`UPDATE incidents SET ..., version = ? WHERE incident_id = ? AND version = ?`) enforce `expected_version == actual_version`.
   - When `cursor.rowcount == 0` or versions diverge, the service raises `OptimisticConcurrencyError` (`ERR-409-OPTIMISTIC-LOCK`), broadcasts an `incident.conflict_rejected` event over the pub/sub backplane, and maps the error to HTTP `409 Conflict` containing both `expected_version` and `actual_version`.

2. **Database-Enforced Append-Only Audit Ledger (`incident_audit_ledger`)**:
   - Every state change (`INCIDENT_CREATED`, `STATUS_TRANSITION`, `INCIDENT_UPDATED`, `COMMENT_ADDED`) is written atomically within the same database transaction as the aggregate mutation.
   - Database triggers (`trg_audit_ledger_no_update` and `trg_audit_ledger_no_delete` in SQLite and PostgreSQL) abort any `UPDATE` or `DELETE` statement on `incident_audit_ledger` with `APPEND_ONLY_LEDGER_VIOLATION`.

## Consequences

- **Positive**: Complete elimination of silent lost updates across concurrent operators; cryptographic/forensic confidence that historical incident audit entries cannot be altered or deleted even by privileged application queries.
- **Negative**: Clients must handle HTTP `409 Conflict` responses by refreshing or merging their local view against the latest aggregate `version`.
