"""SQLite repository implementing Atomic Compare-And-Swap (CAS) OCC and Append-Only Audit Ledger.

Strictly uses Python 3.12 standard library (`sqlite3`, `json`, `threading`, `uuid`, `datetime`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any

from src.domain.exceptions import IncidentNotFoundError, OptimisticConcurrencyError
from src.domain.incidents import (
    Incident,
    IncidentAuditRecord,
    IncidentComment,
    IncidentSeverity,
    IncidentStatus,
)


class AppendOnlyLedgerError(RuntimeError):
    """Raised when an operation attempts to UPDATE or DELETE an immutable audit ledger row."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLitePulseFlowRepository:
    """Thread-safe SQLite repository with Atomic CAS OCC and Append-Only Audit Ledger triggers."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent) and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    commander TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_comments (
                    comment_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_audit_ledger (
                    audit_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS trg_audit_ledger_no_update
                BEFORE UPDATE ON incident_audit_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER_VIOLATION: Incident audit ledger is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_audit_ledger_no_delete
                BEFORE DELETE ON incident_audit_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER_VIOLATION: Incident audit ledger is immutable');
                END;
                """
            )

    @staticmethod
    def _row_to_incident(row: sqlite3.Row) -> Incident:
        return Incident(
            incident_id=str(row["incident_id"]),
            title=str(row["title"]),
            service_name=str(row["service_name"]),
            severity=IncidentSeverity(str(row["severity"])),
            status=IncidentStatus(str(row["status"])),
            commander=str(row["commander"]),
            summary=str(row["summary"]),
            version=int(row["version"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_comment(row: sqlite3.Row) -> IncidentComment:
        return IncidentComment(
            comment_id=str(row["comment_id"]),
            incident_id=str(row["incident_id"]),
            author=str(row["author"]),
            body=str(row["body"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> IncidentAuditRecord:
        return IncidentAuditRecord(
            audit_id=str(row["audit_id"]),
            incident_id=str(row["incident_id"]),
            version=int(row["version"]),
            actor=str(row["actor"]),
            action=str(row["action"]),
            changes_json=str(row["changes_json"]),
            created_at=str(row["created_at"]),
        )

    def create_incident(
        self,
        incident: Incident,
        actor: str = "system",
    ) -> tuple[Incident, IncidentAuditRecord]:
        """Insert a new incident and append INCIDENT_CREATED to incident_audit_ledger atomically."""
        now_iso = _utc_now_iso()
        created_at = incident.created_at.strip() or now_iso
        updated_at = incident.updated_at.strip() or created_at

        persisted_incident = Incident(
            incident_id=incident.incident_id,
            title=incident.title,
            service_name=incident.service_name,
            severity=incident.severity,
            status=incident.status,
            commander=incident.commander,
            summary=incident.summary,
            version=incident.version,
            created_at=created_at,
            updated_at=updated_at,
        )

        snapshot = {
            "incident_id": persisted_incident.incident_id,
            "title": persisted_incident.title,
            "service_name": persisted_incident.service_name,
            "severity": persisted_incident.severity.value,
            "status": persisted_incident.status.value,
            "commander": persisted_incident.commander,
            "summary": persisted_incident.summary,
            "version": persisted_incident.version,
        }
        audit_record = IncidentAuditRecord(
            audit_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            incident_id=persisted_incident.incident_id,
            version=persisted_incident.version,
            actor=actor.strip() or "system",
            action="INCIDENT_CREATED",
            changes_json=json.dumps(snapshot, sort_keys=True),
            created_at=created_at,
        )

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, title, service_name, severity, status,
                    commander, summary, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted_incident.incident_id,
                    persisted_incident.title,
                    persisted_incident.service_name,
                    persisted_incident.severity.value,
                    persisted_incident.status.value,
                    persisted_incident.commander,
                    persisted_incident.summary,
                    persisted_incident.version,
                    persisted_incident.created_at,
                    persisted_incident.updated_at,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO incident_audit_ledger (
                    audit_id, incident_id, version, actor, action, changes_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.audit_id,
                    audit_record.incident_id,
                    audit_record.version,
                    audit_record.actor,
                    audit_record.action,
                    audit_record.changes_json,
                    audit_record.created_at,
                ),
            )

        return persisted_incident, audit_record

    def get_incident(self, incident_id: str) -> Incident:
        """Retrieve an incident by ID or raise IncidentNotFoundError."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        if row is None:
            raise IncidentNotFoundError(f"Incident '{incident_id}' was not found.")
        return self._row_to_incident(row)

    def list_incidents(self) -> list[Incident]:
        """Return all incidents ordered by severity and most recently updated."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM incidents ORDER BY severity ASC, updated_at DESC, incident_id ASC"
            ).fetchall()
        return [self._row_to_incident(r) for r in rows]

    def save_updated_incident(
        self,
        updated: Incident,
        expected_version: int,
        actor: str,
        action: str,
        diff: dict[str, Any],
    ) -> IncidentAuditRecord:
        """Persist an updated incident via Atomic Compare-And-Swap (CAS) and record audit ledger entry."""
        now_iso = updated.updated_at.strip() or _utc_now_iso()
        audit_record = IncidentAuditRecord(
            audit_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            incident_id=updated.incident_id,
            version=updated.version,
            actor=actor.strip() or "system",
            action=action.strip() or "INCIDENT_UPDATED",
            changes_json=json.dumps(diff, sort_keys=True),
            created_at=now_iso,
        )

        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE incidents
                SET title=?,
                    service_name=?,
                    severity=?,
                    status=?,
                    commander=?,
                    summary=?,
                    version=?,
                    updated_at=?
                WHERE incident_id=? AND version=?
                """,
                (
                    updated.title,
                    updated.service_name,
                    updated.severity.value,
                    updated.status.value,
                    updated.commander,
                    updated.summary,
                    updated.version,
                    now_iso,
                    updated.incident_id,
                    expected_version,
                ),
            )
            if cursor.rowcount == 0:
                existing = self._conn.execute(
                    "SELECT version FROM incidents WHERE incident_id = ?",
                    (updated.incident_id,),
                ).fetchone()
                if existing is None:
                    raise IncidentNotFoundError(
                        f"Incident '{updated.incident_id}' was not found."
                    )
                actual_version = int(existing["version"])
                raise OptimisticConcurrencyError(
                    updated.incident_id,
                    expected_version,
                    actual_version,
                )

            self._conn.execute(
                """
                INSERT INTO incident_audit_ledger (
                    audit_id, incident_id, version, actor, action, changes_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.audit_id,
                    audit_record.incident_id,
                    audit_record.version,
                    audit_record.actor,
                    audit_record.action,
                    audit_record.changes_json,
                    audit_record.created_at,
                ),
            )

        return audit_record

    def add_comment(
        self,
        comment: IncidentComment,
    ) -> tuple[IncidentComment, IncidentAuditRecord]:
        """Verify incident exists, persist comment, and append COMMENT_ADDED to audit ledger."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT version FROM incidents WHERE incident_id = ?",
                (comment.incident_id,),
            ).fetchone()
            if row is None:
                raise IncidentNotFoundError(
                    f"Incident '{comment.incident_id}' was not found."
                )
            current_version = int(row["version"])

            audit_record = IncidentAuditRecord(
                audit_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
                incident_id=comment.incident_id,
                version=current_version,
                actor=comment.author,
                action="COMMENT_ADDED",
                changes_json=json.dumps(
                    {
                        "comment_id": comment.comment_id,
                        "author": comment.author,
                        "body": comment.body,
                    },
                    sort_keys=True,
                ),
                created_at=comment.created_at,
            )

            self._conn.execute(
                """
                INSERT INTO incident_comments (
                    comment_id, incident_id, author, body, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    comment.comment_id,
                    comment.incident_id,
                    comment.author,
                    comment.body,
                    comment.created_at,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO incident_audit_ledger (
                    audit_id, incident_id, version, actor, action, changes_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.audit_id,
                    audit_record.incident_id,
                    audit_record.version,
                    audit_record.actor,
                    audit_record.action,
                    audit_record.changes_json,
                    audit_record.created_at,
                ),
            )

        return comment, audit_record

    def list_comments(self, incident_id: str) -> list[IncidentComment]:
        """Return all timeline comments for a given incident in chronological order."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM incident_comments
                WHERE incident_id = ?
                ORDER BY created_at ASC, comment_id ASC
                """,
                (incident_id,),
            ).fetchall()
        return [self._row_to_comment(r) for r in rows]

    def list_audit_ledger(
        self,
        incident_id: str | None = None,
        limit: int = 100,
    ) -> list[IncidentAuditRecord]:
        """Return audit ledger entries filtered optionally by incident_id."""
        with self._lock:
            if incident_id is not None:
                rows = self._conn.execute(
                    """
                    SELECT * FROM incident_audit_ledger
                    WHERE incident_id = ?
                    ORDER BY created_at ASC, version ASC, audit_id ASC
                    LIMIT ?
                    """,
                    (incident_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM incident_audit_ledger
                    ORDER BY created_at DESC, version DESC, audit_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._row_to_audit(r) for r in rows]

    def execute_raw_mutation_for_test(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> None:
        """Execute a raw SQL statement in test suites to verify database trigger enforcement."""
        try:
            with self._lock, self._conn:
                self._conn.execute(sql, params)
        except sqlite3.DatabaseError as exc:
            if "APPEND_ONLY_LEDGER_VIOLATION" in str(exc):
                raise AppendOnlyLedgerError(str(exc)) from exc
            raise

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()
