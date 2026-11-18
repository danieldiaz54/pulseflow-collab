"""Repository Port Protocols for the Incident Management Domain.

Inverts persistence dependencies so the domain layer has zero SQL/ORM imports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.incidents import Incident, IncidentAuditRecord, IncidentComment


@runtime_checkable
class IncidentRepositoryProtocol(Protocol):
    """Port interface for atomic Incident persistence, comments, and audit ledger."""

    def create_incident(self, incident: Incident, actor: str = "system") -> Incident:
        """Persist a newly created incident along with its initial version=1 audit entry."""
        ...

    def get_incident(self, incident_id: str) -> Incident:
        """Retrieve an incident by ID or raise IncidentNotFoundError."""
        ...

    def list_incidents(self) -> list[Incident]:
        """List all persisted incidents ordered deterministically."""
        ...

    def save_updated_incident(
        self,
        incident: Incident,
        expected_version: int,
        actor: str,
        diff: dict[str, dict[str, object]],
    ) -> Incident:
        """Atomically persist an updated incident with OCC check (WHERE version = expected_version) and append an audit record."""
        ...

    def add_comment(self, comment: IncidentComment) -> IncidentComment:
        """Append an immutable comment to an incident's timeline."""
        ...

    def list_comments(self, incident_id: str) -> list[IncidentComment]:
        """Return all timeline comments for a given incident."""
        ...

    def list_audit_ledger(self, incident_id: str | None = None) -> list[IncidentAuditRecord]:
        """Return append-only audit records, optionally filtered by incident_id."""
        ...
