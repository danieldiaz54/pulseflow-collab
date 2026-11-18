"""Typed domain exceptions for PulseFlow Collab.

Strictly uses Python standard library only (zero external dependencies).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base exception for all domain-level business rule violations."""


class InvalidIncidentError(DomainError):
    """Raised when an incident or related value object fails invariant validation."""


class IncidentNotFoundError(DomainError):
    """Raised when an incident cannot be found by its identifier."""


class InvalidStateTransitionError(DomainError):
    """Raised when an incident status transition violates the lifecycle state machine."""


class OptimisticConcurrencyError(DomainError):
    """Raised when an update's expected_version does not match the current aggregate version."""

    def __init__(
        self,
        incident_id: str,
        expected_version: int,
        actual_version: int,
        message: str | None = None,
    ) -> None:
        self.incident_id: str = incident_id
        self.expected_version: int = expected_version
        self.actual_version: int = actual_version
        self.code: str = "ERR-409-OPTIMISTIC-LOCK"
        default_message = (
            f"[{self.code}] Optimistic concurrency conflict for incident '{incident_id}': "
            f"expected version {expected_version}, actual version {actual_version}."
        )
        super().__init__(message or default_message)
