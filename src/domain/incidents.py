"""Core Incident domain aggregate, value objects, and lifecycle state machine.

Strictly uses Python standard library only (zero external dependencies).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.exceptions import (
    InvalidIncidentError,
    InvalidStateTransitionError,
    OptimisticConcurrencyError,
)


class IncidentSeverity(str, Enum):
    """Standardized incident severity tiers."""

    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentStatus(str, Enum):
    """Incident lifecycle states."""

    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"


VALID_STATUS_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.MITIGATED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.MITIGATED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.MITIGATED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.RESOLVED: {
        IncidentStatus.INVESTIGATING,
    },
}


def _require_non_empty_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIncidentError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _parse_severity(value: object) -> IncidentSeverity:
    if isinstance(value, IncidentSeverity):
        return value
    if isinstance(value, str):
        try:
            return IncidentSeverity(value.strip().upper())
        except ValueError as exc:
            raise InvalidIncidentError(f"Invalid incident severity: '{value}'.") from exc
    raise InvalidIncidentError(f"Invalid incident severity type: {type(value).__name__}.")


def _parse_status(value: object) -> IncidentStatus:
    if isinstance(value, IncidentStatus):
        return value
    if isinstance(value, str):
        try:
            return IncidentStatus(value.strip().upper())
        except ValueError as exc:
            raise InvalidIncidentError(f"Invalid incident status: '{value}'.") from exc
    raise InvalidIncidentError(f"Invalid incident status type: {type(value).__name__}.")


@dataclass(frozen=True)
class IncidentComment:
    """Immutable value object representing a timeline comment on an incident."""

    comment_id: str
    incident_id: str
    author: str
    body: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "comment_id", _require_non_empty_str(self.comment_id, "comment_id"))
        object.__setattr__(self, "incident_id", _require_non_empty_str(self.incident_id, "incident_id"))
        object.__setattr__(self, "author", _require_non_empty_str(self.author, "author"))
        object.__setattr__(self, "body", _require_non_empty_str(self.body, "body"))
        object.__setattr__(self, "created_at", _require_non_empty_str(self.created_at, "created_at"))


@dataclass(frozen=True)
class IncidentAuditRecord:
    """Immutable append-only audit entry recording a state change on an incident."""

    audit_id: str
    incident_id: str
    version: int
    actor: str
    action: str
    changes_json: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_id", _require_non_empty_str(self.audit_id, "audit_id"))
        object.__setattr__(self, "incident_id", _require_non_empty_str(self.incident_id, "incident_id"))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidIncidentError("Field 'version' on IncidentAuditRecord must be an integer >= 1.")
        object.__setattr__(self, "actor", _require_non_empty_str(self.actor, "actor"))
        object.__setattr__(self, "action", _require_non_empty_str(self.action, "action"))
        object.__setattr__(self, "changes_json", _require_non_empty_str(self.changes_json, "changes_json"))
        object.__setattr__(self, "created_at", _require_non_empty_str(self.created_at, "created_at"))


@dataclass(frozen=True)
class Incident:
    """Immutable Incident aggregate root with Optimistic Concurrency Control (OCC)."""

    incident_id: str
    title: str
    service_name: str
    severity: IncidentSeverity
    status: IncidentStatus
    commander: str
    summary: str
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "incident_id", _require_non_empty_str(self.incident_id, "incident_id"))
        object.__setattr__(self, "title", _require_non_empty_str(self.title, "title"))
        object.__setattr__(self, "service_name", _require_non_empty_str(self.service_name, "service_name"))
        object.__setattr__(self, "severity", _parse_severity(self.severity))
        object.__setattr__(self, "status", _parse_status(self.status))
        object.__setattr__(self, "commander", _require_non_empty_str(self.commander, "commander"))
        object.__setattr__(self, "summary", _require_non_empty_str(self.summary, "summary"))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidIncidentError("Field 'version' must be an integer >= 1.")
        if not isinstance(self.created_at, str):
            raise InvalidIncidentError("Field 'created_at' must be a string.")
        if not isinstance(self.updated_at, str):
            raise InvalidIncidentError("Field 'updated_at' must be a string.")

    def apply_update(
        self,
        *,
        expected_version: int,
        actor: str,
        title: str | None = None,
        severity: IncidentSeverity | str | None = None,
        status: IncidentStatus | str | None = None,
        commander: str | None = None,
        summary: str | None = None,
        updated_at: str | None = None,
    ) -> tuple[Incident, dict[str, dict[str, object]]]:
        """Validate OCC version and state transitions, returning (new_incident, diff)."""
        _require_non_empty_str(actor, "actor")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise InvalidIncidentError("Field 'expected_version' must be an integer.")

        if expected_version != self.version:
            raise OptimisticConcurrencyError(
                incident_id=self.incident_id,
                expected_version=expected_version,
                actual_version=self.version,
            )

        diff: dict[str, dict[str, object]] = {}

        next_title = self.title
        if title is not None:
            validated_title = _require_non_empty_str(title, "title")
            if validated_title != self.title:
                diff["title"] = {"from": self.title, "to": validated_title}
                next_title = validated_title

        next_severity = self.severity
        if severity is not None:
            validated_severity = _parse_severity(severity)
            if validated_severity != self.severity:
                diff["severity"] = {"from": self.severity.value, "to": validated_severity.value}
                next_severity = validated_severity

        next_status = self.status
        if status is not None:
            validated_status = _parse_status(status)
            if validated_status != self.status:
                allowed = VALID_STATUS_TRANSITIONS.get(self.status, set())
                if validated_status not in allowed:
                    raise InvalidStateTransitionError(
                        f"Cannot transition incident '{self.incident_id}' from "
                        f"'{self.status.value}' to '{validated_status.value}'."
                    )
                diff["status"] = {"from": self.status.value, "to": validated_status.value}
                next_status = validated_status

        next_commander = self.commander
        if commander is not None:
            validated_commander = _require_non_empty_str(commander, "commander")
            if validated_commander != self.commander:
                diff["commander"] = {"from": self.commander, "to": validated_commander}
                next_commander = validated_commander

        next_summary = self.summary
        if summary is not None:
            validated_summary = _require_non_empty_str(summary, "summary")
            if validated_summary != self.summary:
                diff["summary"] = {"from": self.summary, "to": validated_summary}
                next_summary = validated_summary

        next_updated_at = self.updated_at if updated_at is None else updated_at

        updated_incident = Incident(
            incident_id=self.incident_id,
            title=next_title,
            service_name=self.service_name,
            severity=next_severity,
            status=next_status,
            commander=next_commander,
            summary=next_summary,
            version=self.version + 1,
            created_at=self.created_at,
            updated_at=next_updated_at,
        )
        return updated_incident, diff
