"""Pure domain package for PulseFlow Collab.

Exports core entities, value objects, domain exceptions, SLA policy engine,
multi-node realtime collaboration backplane, and repository protocols.
"""

from src.domain.collaboration import (
    MultiNodePubSubBackplane,
    PresenceSession,
    RealtimeEnvelope,
)
from src.domain.exceptions import (
    DomainError,
    IncidentNotFoundError,
    InvalidIncidentError,
    InvalidStateTransitionError,
    OptimisticConcurrencyError,
)
from src.domain.incidents import (
    VALID_STATUS_TRANSITIONS,
    Incident,
    IncidentAuditRecord,
    IncidentComment,
    IncidentSeverity,
    IncidentStatus,
)
from src.domain.repositories import IncidentRepositoryProtocol
from src.domain.sla_policy import (
    SLA_TARGET_MINUTES,
    SlaEvaluation,
    SlaPolicyEngine,
)

__all__ = [
    "DomainError",
    "Incident",
    "IncidentAuditRecord",
    "IncidentComment",
    "IncidentNotFoundError",
    "IncidentRepositoryProtocol",
    "IncidentSeverity",
    "IncidentStatus",
    "InvalidIncidentError",
    "InvalidStateTransitionError",
    "MultiNodePubSubBackplane",
    "OptimisticConcurrencyError",
    "PresenceSession",
    "RealtimeEnvelope",
    "SLA_TARGET_MINUTES",
    "SlaEvaluation",
    "SlaPolicyEngine",
    "VALID_STATUS_TRANSITIONS",
]
