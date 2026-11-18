"""Multi-Node WebSocket / Redis Pub-Sub Backplane domain model.

Simulates and enforces deterministic multi-node fan-out across distributed
WebSocket gateway nodes (ws-gateway-01, ws-gateway-02) using only the Python
standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from src.domain.exceptions import InvalidIncidentError


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidIncidentError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class RealtimeEnvelope:
    """Immutable pub/sub event packet broadcast across all WebSocket gateway nodes."""

    event_id: str
    channel: str
    event_type: str
    incident_id: str
    version: int
    origin_node: str
    actor: str
    payload: dict[str, object]
    published_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_text(self.event_id, "event_id"))
        object.__setattr__(self, "channel", _require_text(self.channel, "channel"))
        object.__setattr__(self, "event_type", _require_text(self.event_type, "event_type"))
        object.__setattr__(self, "incident_id", _require_text(self.incident_id, "incident_id"))
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidIncidentError("Field 'version' on RealtimeEnvelope must be an integer >= 1.")
        object.__setattr__(self, "origin_node", _require_text(self.origin_node, "origin_node"))
        object.__setattr__(self, "actor", _require_text(self.actor, "actor"))
        if not isinstance(self.payload, dict):
            raise InvalidIncidentError("Field 'payload' on RealtimeEnvelope must be a dict.")
        object.__setattr__(self, "published_at", _require_text(self.published_at, "published_at"))


@dataclass(frozen=True)
class PresenceSession:
    """Immutable operator presence state attached to a specific WebSocket gateway node."""

    operator_id: str
    gateway_node: str
    active_incident_id: str
    observed_version: int
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_id", _require_text(self.operator_id, "operator_id"))
        object.__setattr__(self, "gateway_node", _require_text(self.gateway_node, "gateway_node"))
        object.__setattr__(
            self, "active_incident_id", _require_text(self.active_incident_id, "active_incident_id")
        )
        if (
            not isinstance(self.observed_version, int)
            or isinstance(self.observed_version, bool)
            or self.observed_version < 1
        ):
            raise InvalidIncidentError("Field 'observed_version' must be an integer >= 1.")
        object.__setattr__(self, "updated_at", _require_text(self.updated_at, "updated_at"))


class MultiNodePubSubBackplane:
    """In-memory multi-node Pub/Sub backplane supporting fan-out across gateway nodes."""

    DEFAULT_NODES: tuple[str, ...] = ("ws-gateway-01", "ws-gateway-02")

    def __init__(
        self,
        nodes: tuple[str, ...] = DEFAULT_NODES,
        max_history: int = 200,
    ) -> None:
        if max_history < 1:
            raise InvalidIncidentError("max_history must be >= 1.")
        self._max_history: int = max_history
        self._history: list[RealtimeEnvelope] = []
        self._presence: dict[str, PresenceSession] = {}
        self._subscribers: dict[str, list[Callable[[RealtimeEnvelope], None]]] = {}
        self._node_mailboxes: dict[str, list[RealtimeEnvelope]] = {}
        for node in nodes:
            clean_node = _require_text(node, "node_id")
            self._subscribers.setdefault(clean_node, [])
            self._node_mailboxes.setdefault(clean_node, [])

    def list_nodes(self) -> list[str]:
        """Return all registered WebSocket gateway node identifiers."""
        return list(self._node_mailboxes.keys())

    def subscribe(
        self,
        node_id: str,
        callback: Callable[[RealtimeEnvelope], None],
    ) -> None:
        """Register a subscriber callback for a specific WebSocket gateway node."""
        clean_node = _require_text(node_id, "node_id")
        if not callable(callback):
            raise InvalidIncidentError("Subscriber callback must be callable.")
        self._subscribers.setdefault(clean_node, []).append(callback)
        self._node_mailboxes.setdefault(clean_node, [])

    def publish(
        self,
        envelope_or_event_type: RealtimeEnvelope | str | None = None,
        *,
        event_id: str | None = None,
        channel: str = "incidents.realtime",
        event_type: str | None = None,
        incident_id: str | None = None,
        version: int = 1,
        origin_node: str = "ws-gateway-01",
        actor: str = "system",
        payload: dict[str, object] | None = None,
        published_at: str | None = None,
    ) -> RealtimeEnvelope:
        """Publish a RealtimeEnvelope and fan it out to all subscribed gateway nodes."""
        if isinstance(envelope_or_event_type, RealtimeEnvelope):
            envelope = envelope_or_event_type
        else:
            resolved_event_type = (
                envelope_or_event_type if isinstance(envelope_or_event_type, str) else event_type
            )
            if resolved_event_type is None or incident_id is None:
                raise InvalidIncidentError(
                    "publish() requires either a RealtimeEnvelope or 'event_type' and 'incident_id'."
                )
            envelope = RealtimeEnvelope(
                event_id=event_id or f"evt-{uuid4().hex[:12]}",
                channel=channel,
                event_type=resolved_event_type,
                incident_id=incident_id,
                version=version,
                origin_node=origin_node,
                actor=actor,
                payload=dict(payload or {}),
                published_at=published_at or _utc_now_iso(),
            )

        self._subscribers.setdefault(envelope.origin_node, [])
        self._node_mailboxes.setdefault(envelope.origin_node, [])

        self._history.append(envelope)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        for node_id, mailbox in self._node_mailboxes.items():
            mailbox.append(envelope)
            if len(mailbox) > self._max_history:
                self._node_mailboxes[node_id] = mailbox[-self._max_history :]
            for callback in self._subscribers.get(node_id, []):
                callback(envelope)

        return envelope

    def upsert_presence(
        self,
        session_or_operator_id: PresenceSession | str,
        gateway_node: str | None = None,
        active_incident_id: str | None = None,
        observed_version: int = 1,
        updated_at: str | None = None,
    ) -> PresenceSession:
        """Create or update an operator's presence session on a gateway node."""
        if isinstance(session_or_operator_id, PresenceSession):
            session = session_or_operator_id
        else:
            if gateway_node is None or active_incident_id is None:
                raise InvalidIncidentError(
                    "upsert_presence() requires 'gateway_node' and 'active_incident_id'."
                )
            session = PresenceSession(
                operator_id=session_or_operator_id,
                gateway_node=gateway_node,
                active_incident_id=active_incident_id,
                observed_version=observed_version,
                updated_at=updated_at or _utc_now_iso(),
            )

        self._subscribers.setdefault(session.gateway_node, [])
        self._node_mailboxes.setdefault(session.gateway_node, [])
        self._presence[session.operator_id] = session
        return session

    def list_presence(self, incident_id: str | None = None) -> list[PresenceSession]:
        """List active operator presence sessions, optionally filtered by incident_id."""
        sessions = list(self._presence.values())
        if incident_id is not None:
            return [s for s in sessions if s.active_incident_id == incident_id]
        return sessions

    def list_recent_events(self, limit: int = 50) -> list[RealtimeEnvelope]:
        """Return up to `limit` most recent published envelopes."""
        if limit < 1:
            raise InvalidIncidentError("limit must be >= 1.")
        return list(self._history[-limit:])

    def get_node_events(self, node_id: str) -> list[RealtimeEnvelope]:
        """Return all envelopes received by a specific gateway node via fan-out."""
        clean_node = _require_text(node_id, "node_id")
        return list(self._node_mailboxes.get(clean_node, []))
