"""Deterministic SLA Policy Engine for Incident Management.

Strictly uses Python standard library only (zero external dependencies).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.domain.exceptions import InvalidIncidentError
from src.domain.incidents import Incident, IncidentSeverity

SLA_TARGET_MINUTES: dict[IncidentSeverity, int] = {
    IncidentSeverity.SEV1: 15,
    IncidentSeverity.SEV2: 60,
    IncidentSeverity.SEV3: 240,
    IncidentSeverity.SEV4: 1440,
}


@dataclass(frozen=True)
class SlaEvaluation:
    """Immutable value object representing the SLA evaluation of an incident."""

    incident_id: str
    severity: IncidentSeverity
    target_minutes: int
    elapsed_minutes: float
    remaining_minutes: float
    breached: bool


class SlaPolicyEngine:
    """Evaluates an Incident against its severity-based SLA resolution target."""

    @staticmethod
    def evaluate(incident: Incident, elapsed_minutes: float = 0.0) -> SlaEvaluation:
        if not isinstance(incident, Incident):
            raise InvalidIncidentError("SLA evaluation requires a valid Incident aggregate.")
        if (
            not isinstance(elapsed_minutes, (int, float))
            or isinstance(elapsed_minutes, bool)
            or math.isnan(elapsed_minutes)
            or math.isinf(elapsed_minutes)
            or elapsed_minutes < 0.0
        ):
            raise InvalidIncidentError("Field 'elapsed_minutes' must be a finite number >= 0.")

        target_minutes = SLA_TARGET_MINUTES[incident.severity]
        elapsed = round(float(elapsed_minutes), 2)
        remaining = round(float(target_minutes) - float(elapsed_minutes), 2)
        breached = float(elapsed_minutes) > float(target_minutes)

        return SlaEvaluation(
            incident_id=incident.incident_id,
            severity=incident.severity,
            target_minutes=target_minutes,
            elapsed_minutes=elapsed,
            remaining_minutes=remaining,
            breached=breached,
        )
