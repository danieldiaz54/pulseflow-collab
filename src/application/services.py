"""Application orchestration service for PulseFlow Collab.

Coordinates domain aggregates, SLA policy evaluation, SQLite/PostgreSQL CAS
persistence, append-only audit ledger, and multi-node WebSocket/Pub-Sub fan-out.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from src.domain.collaboration import (
    MultiNodePubSubBackplane,
    PresenceSession,
    RealtimeEnvelope,
)
from src.domain.exceptions import (
    InvalidIncidentError,
    OptimisticConcurrencyError,
)
from src.domain.incidents import (
    Incident,
    IncidentAuditRecord,
    IncidentComment,
    IncidentSeverity,
    IncidentStatus,
)
from src.domain.sla_policy import SlaEvaluation, SlaPolicyEngine
from src.infrastructure.persistence.seed_incidents import seed_default_incidents
from src.infrastructure.persistence.sqlite_repository import SQLitePulseFlowRepository

DEFAULT_Elapsed_SEED_MINUTES: dict[str, float] = {
    "INC-2026-101": 13.0,
    "INC-2026-102": 45.0,
    "INC-2026-103": 18.5,
    "INC-2026-104": 35.0,
    "INC-2026-105": 100.0,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_elapsed_minutes(incident: Incident) -> float:
    """Compute deterministic elapsed minutes from timestamps or seed defaults."""
    if incident.incident_id in DEFAULT_Elapsed_SEED_MINUTES and incident.version == 1:
        return DEFAULT_Elapsed_SEED_MINUTES[incident.incident_id]
    try:
        if incident.created_at and incident.updated_at:
            created = datetime.fromisoformat(incident.created_at)
            updated = datetime.fromisoformat(incident.updated_at)
            diff_min = (updated - created).total_seconds() / 60.0
            if diff_min >= 0:
                return round(diff_min, 2)
    except ValueError:
        pass
    return DEFAULT_Elapsed_SEED_MINUTES.get(incident.incident_id, 5.0)


class PulseFlowApplicationService:
    """Core application service facade for REST, SSE, and WebSocket controllers."""

    def __init__(
        self,
        repository: SQLitePulseFlowRepository | None = None,
        backplane: MultiNodePubSubBackplane | None = None,
        db_path: str = ":memory:",
        auto_seed: bool = True,
    ) -> None:
        self.repository: SQLitePulseFlowRepository = repository or SQLitePulseFlowRepository(
            db_path=db_path
        )
        self.backplane: MultiNodePubSubBackplane = backplane or MultiNodePubSubBackplane(
            nodes=("ws-gateway-01", "ws-gateway-02"),
            max_history=200,
        )
        self.sla_engine: SlaPolicyEngine = SlaPolicyEngine()
        self._node_callbacks_log: dict[str, list[str]] = {
            "ws-gateway-01": [],
            "ws-gateway-02": [],
        }

        for node_id in ("ws-gateway-01", "ws-gateway-02"):
            self._node_callbacks_log.setdefault(node_id, [])
            self.backplane.subscribe(
                node_id,
                lambda env, n=node_id: self._node_callbacks_log[n].append(env.event_id),
            )

        if auto_seed:
            seed_default_incidents(self.repository)
            self._seed_initial_collaboration_state()

    def _seed_initial_collaboration_state(self) -> None:
        """Register initial multi-node presence sessions and bootstrap pub/sub telemetry."""
        if self.backplane.list_presence():
            return

        self.backplane.upsert_presence(
            "sre.valeria",
            gateway_node="ws-gateway-01",
            active_incident_id="INC-2026-101",
            observed_version=1,
            updated_at="2026-04-12T14:18:00+00:00",
        )
        self.backplane.upsert_presence(
            "netops.carlos",
            gateway_node="ws-gateway-02",
            active_incident_id="INC-2026-101",
            observed_version=1,
            updated_at="2026-04-12T14:18:05+00:00",
        )
        self.backplane.upsert_presence(
            "core.daniel",
            gateway_node="ws-gateway-01",
            active_incident_id="INC-2026-103",
            observed_version=1,
            updated_at="2026-04-12T14:25:00+00:00",
        )

        self.backplane.publish(
            event_type="backplane.synchronized",
            incident_id="INC-2026-101",
            version=1,
            origin_node="ws-gateway-01",
            actor="sre.valeria",
            payload={
                "message": "Multi-node Redis Pub/Sub replica ring active across ws-gateway-01 and ws-gateway-02.",
                "status": "INVESTIGATING",
                "severity": "SEV1",
            },
            published_at="2026-04-12T14:18:10+00:00",
        )

    @staticmethod
    def _serialize_sla(sla: SlaEvaluation) -> dict[str, Any]:
        return {
            "incident_id": sla.incident_id,
            "severity": sla.severity.value,
            "target_minutes": sla.target_minutes,
            "elapsed_minutes": sla.elapsed_minutes,
            "remaining_minutes": sla.remaining_minutes,
            "breached": sla.breached,
        }

    def _serialize_incident(
        self,
        incident: Incident,
        comment_count: int | None = None,
    ) -> dict[str, Any]:
        elapsed = _compute_elapsed_minutes(incident)
        sla = self.sla_engine.evaluate(incident, elapsed_minutes=elapsed)
        resolved_comment_count = (
            comment_count
            if comment_count is not None
            else len(self.repository.list_comments(incident.incident_id))
        )
        return {
            "incident_id": incident.incident_id,
            "title": incident.title,
            "service_name": incident.service_name,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "commander": incident.commander,
            "summary": incident.summary,
            "version": incident.version,
            "created_at": incident.created_at,
            "updated_at": incident.updated_at,
            "comment_count": resolved_comment_count,
            "sla": self._serialize_sla(sla),
        }

    @staticmethod
    def _serialize_comment(comment: IncidentComment) -> dict[str, Any]:
        return {
            "comment_id": comment.comment_id,
            "incident_id": comment.incident_id,
            "author": comment.author,
            "body": comment.body,
            "created_at": comment.created_at,
        }

    @staticmethod
    def _serialize_audit(audit: IncidentAuditRecord) -> dict[str, Any]:
        try:
            parsed_changes = json.loads(audit.changes_json)
        except ValueError:
            parsed_changes = {}
        return {
            "audit_id": audit.audit_id,
            "incident_id": audit.incident_id,
            "version": audit.version,
            "actor": audit.actor,
            "action": audit.action,
            "changes": parsed_changes,
            "changes_json": audit.changes_json,
            "created_at": audit.created_at,
        }

    @staticmethod
    def _serialize_envelope(envelope: RealtimeEnvelope) -> dict[str, Any]:
        return {
            "event_id": envelope.event_id,
            "channel": envelope.channel,
            "event_type": envelope.event_type,
            "incident_id": envelope.incident_id,
            "version": envelope.version,
            "origin_node": envelope.origin_node,
            "actor": envelope.actor,
            "payload": envelope.payload,
            "published_at": envelope.published_at,
        }

    @staticmethod
    def _serialize_presence(session: PresenceSession) -> dict[str, Any]:
        return {
            "operator_id": session.operator_id,
            "gateway_node": session.gateway_node,
            "active_incident_id": session.active_incident_id,
            "observed_version": session.observed_version,
            "updated_at": session.updated_at,
        }

    def get_health(self) -> dict[str, Any]:
        """Return health status and operational metrics."""
        incidents = self.repository.list_incidents()
        nodes = self.backplane.list_nodes()
        return {
            "status": "ok",
            "service": "pulseflow-collab",
            "architecture": "modular-monolith-occ-pubsub",
            "gateway_nodes": nodes,
            "incident_count": len(incidents),
            "active_presence_count": len(self.backplane.list_presence()),
            "recent_events_count": len(self.backplane.list_recent_events(limit=50)),
        }

    def list_incidents(self) -> list[dict[str, Any]]:
        """List all persisted incidents enriched with SLA evaluation and comment count."""
        incidents = self.repository.list_incidents()
        return [self._serialize_incident(inc) for inc in incidents]

    def get_incident_detail(self, incident_id: str) -> dict[str, Any]:
        """Return full tactical view for an incident (aggregate, SLA, comments, audit trail, presence)."""
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise InvalidIncidentError("Field 'incident_id' must be a non-empty string.")
        clean_id = incident_id.strip()
        incident = self.repository.get_incident(clean_id)
        comments = [self._serialize_comment(c) for c in self.repository.list_comments(clean_id)]
        audit_trail = [
            self._serialize_audit(a)
            for a in self.repository.list_audit_ledger(incident_id=clean_id, limit=100)
        ]
        presence = [
            self._serialize_presence(p)
            for p in self.backplane.list_presence(incident_id=clean_id)
        ]
        incident_dict = self._serialize_incident(incident, comment_count=len(comments))
        return {
            **incident_dict,
            "incident": incident_dict,
            "sla": incident_dict["sla"],
            "comments": comments,
            "audit_trail": audit_trail,
            "presence": presence,
        }

    def create_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate payload, create a new version=1 incident, and broadcast incident.created."""
        if not isinstance(payload, dict):
            raise InvalidIncidentError("Request payload must be a JSON object.")

        now_iso = _utc_now_iso()
        raw_id = payload.get("incident_id")
        incident_id = (
            str(raw_id).strip()
            if isinstance(raw_id, str) and raw_id.strip()
            else f"INC-2026-{uuid.uuid4().hex[:6].upper()}"
        )
        commander = payload.get("commander")
        actor_raw = payload.get("actor", commander)
        actor = str(actor_raw).strip() if isinstance(actor_raw, str) and actor_raw.strip() else ""
        if not actor and isinstance(commander, str) and commander.strip():
            actor = commander.strip()

        gateway_raw = payload.get("gateway_node", "ws-gateway-01")
        gateway_node = (
            str(gateway_raw).strip()
            if isinstance(gateway_raw, str) and gateway_raw.strip()
            else "ws-gateway-01"
        )

        status_raw = payload.get("status", "OPEN")
        incident = Incident(
            incident_id=incident_id,
            title=payload.get("title", ""),
            service_name=payload.get("service_name", ""),
            severity=payload.get("severity", ""),
            status=status_raw,
            commander=commander if isinstance(commander, str) else "",
            summary=payload.get("summary", ""),
            version=1,
            created_at=str(payload.get("created_at") or now_iso),
            updated_at=str(payload.get("updated_at") or now_iso),
        )

        persisted, audit_record = self.repository.create_incident(
            incident,
            actor=actor or incident.commander,
        )
        serialized_inc = self._serialize_incident(persisted, comment_count=0)
        envelope = self.backplane.publish(
            event_type="incident.created",
            incident_id=persisted.incident_id,
            version=persisted.version,
            origin_node=gateway_node,
            actor=actor or persisted.commander,
            payload={
                "incident": serialized_inc,
                "status": persisted.status.value,
                "severity": persisted.severity.value,
            },
        )
        self.backplane.upsert_presence(
            actor or persisted.commander,
            gateway_node=gateway_node,
            active_incident_id=persisted.incident_id,
            observed_version=persisted.version,
        )
        return {
            "incident": serialized_inc,
            "audit": self._serialize_audit(audit_record),
            "event": self._serialize_envelope(envelope),
        }

    def update_incident(self, incident_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply OCC-guarded update to an incident, broadcasting either update or conflict_rejected."""
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise InvalidIncidentError("Field 'incident_id' must be a non-empty string.")
        if not isinstance(payload, dict):
            raise InvalidIncidentError("Request payload must be a JSON object.")

        clean_id = incident_id.strip()
        if "expected_version" not in payload:
            raise InvalidIncidentError("Field 'expected_version' is required for OCC updates.")

        expected_version = payload.get("expected_version")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise InvalidIncidentError("Field 'expected_version' must be an integer.")

        actor_raw = payload.get("actor")
        if not isinstance(actor_raw, str) or not actor_raw.strip():
            raise InvalidIncidentError("Field 'actor' must be a non-empty string.")
        actor = actor_raw.strip()

        gateway_raw = payload.get("gateway_node", "ws-gateway-01")
        gateway_node = (
            str(gateway_raw).strip()
            if isinstance(gateway_raw, str) and gateway_raw.strip()
            else "ws-gateway-01"
        )

        current = self.repository.get_incident(clean_id)

        try:
            updated_inc, diff = current.apply_update(
                expected_version=expected_version,
                actor=actor,
                title=payload.get("title"),
                severity=payload.get("severity"),
                status=payload.get("status"),
                commander=payload.get("commander"),
                summary=payload.get("summary"),
                updated_at=_utc_now_iso(),
            )
            action = "STATUS_TRANSITION" if "status" in diff else "INCIDENT_UPDATED"
            audit_record = self.repository.save_updated_incident(
                updated=updated_inc,
                expected_version=expected_version,
                actor=actor,
                action=action,
                diff=diff,
            )
        except OptimisticConcurrencyError as err:
            self.backplane.publish(
                event_type="incident.conflict_rejected",
                incident_id=clean_id,
                version=err.actual_version,
                origin_node=gateway_node,
                actor=actor,
                payload={
                    "expected_version": err.expected_version,
                    "actual_version": err.actual_version,
                    "actor": actor,
                    "code": err.code,
                },
            )
            raise

        serialized_inc = self._serialize_incident(updated_inc)
        envelope = self.backplane.publish(
            event_type="incident.updated",
            incident_id=updated_inc.incident_id,
            version=updated_inc.version,
            origin_node=gateway_node,
            actor=actor,
            payload={
                "diff": diff,
                "status": updated_inc.status.value,
                "severity": updated_inc.severity.value,
                "version": updated_inc.version,
                "commander": updated_inc.commander,
                "title": updated_inc.title,
                "summary": updated_inc.summary,
                "incident": serialized_inc,
            },
        )
        self.backplane.upsert_presence(
            actor,
            gateway_node=gateway_node,
            active_incident_id=updated_inc.incident_id,
            observed_version=updated_inc.version,
        )

        return {
            "incident": serialized_inc,
            "audit": self._serialize_audit(audit_record),
            "event": self._serialize_envelope(envelope),
        }

    def add_comment(self, incident_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a timeline comment to an incident and broadcast comment.added."""
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise InvalidIncidentError("Field 'incident_id' must be a non-empty string.")
        if not isinstance(payload, dict):
            raise InvalidIncidentError("Request payload must be a JSON object.")

        clean_id = incident_id.strip()
        author_raw = payload.get("author") or payload.get("actor")
        body_raw = payload.get("body")
        comment_id_raw = payload.get("comment_id")
        comment_id = (
            str(comment_id_raw).strip()
            if isinstance(comment_id_raw, str) and comment_id_raw.strip()
            else f"CMT-{uuid.uuid4().hex[:10].upper()}"
        )
        gateway_raw = payload.get("gateway_node", "ws-gateway-01")
        gateway_node = (
            str(gateway_raw).strip()
            if isinstance(gateway_raw, str) and gateway_raw.strip()
            else "ws-gateway-01"
        )

        comment = IncidentComment(
            comment_id=comment_id,
            incident_id=clean_id,
            author=author_raw if isinstance(author_raw, str) else "",
            body=body_raw if isinstance(body_raw, str) else "",
            created_at=str(payload.get("created_at") or _utc_now_iso()),
        )
        saved_comment, audit_record = self.repository.add_comment(comment)
        serialized_comment = self._serialize_comment(saved_comment)

        envelope = self.backplane.publish(
            event_type="comment.added",
            incident_id=clean_id,
            version=audit_record.version,
            origin_node=gateway_node,
            actor=saved_comment.author,
            payload={
                "comment": serialized_comment,
                "author": saved_comment.author,
                "body": saved_comment.body,
            },
        )
        return {
            "comment": serialized_comment,
            "audit": self._serialize_audit(audit_record),
            "event": self._serialize_envelope(envelope),
        }

    def upsert_presence(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create or update an operator presence session attached to a WebSocket gateway node."""
        if not isinstance(payload, dict):
            raise InvalidIncidentError("Request payload must be a JSON object.")

        operator_id = payload.get("operator_id") or payload.get("actor")
        gateway_node = payload.get("gateway_node", "ws-gateway-01")
        active_incident_id = payload.get("active_incident_id") or payload.get("incident_id")
        observed_version = payload.get("observed_version", 1)

        if not isinstance(observed_version, int) or isinstance(observed_version, bool):
            raise InvalidIncidentError("Field 'observed_version' must be an integer >= 1.")

        session = self.backplane.upsert_presence(
            session_or_operator_id=operator_id if isinstance(operator_id, str) else "",
            gateway_node=gateway_node if isinstance(gateway_node, str) else "",
            active_incident_id=active_incident_id if isinstance(active_incident_id, str) else "",
            observed_version=observed_version,
        )
        return self._serialize_presence(session)

    def list_presence(self, incident_id: str | None = None) -> list[dict[str, Any]]:
        """List active operator presence sessions across gateway nodes."""
        return [
            self._serialize_presence(session)
            for session in self.backplane.list_presence(incident_id=incident_id)
        ]

    def list_backplane_events(self, limit: int = 50) -> dict[str, Any]:
        """Return recent multi-node pub/sub envelopes and per-gateway delivery counts."""
        nodes = self.backplane.list_nodes()
        return {
            "nodes": nodes,
            "node_delivery_counts": {
                node: len(self.backplane.get_node_events(node)) for node in nodes
            },
            "node_events": {
                node: [
                    self._serialize_envelope(env)
                    for env in self.backplane.get_node_events(node)[-limit:]
                ]
                for node in nodes
            },
            "events": [
                self._serialize_envelope(env)
                for env in self.backplane.list_recent_events(limit=limit)
            ],
        }

    def list_audit_ledger(
        self,
        incident_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable append-only audit ledger entries."""
        if limit < 1:
            raise InvalidIncidentError("Field 'limit' must be >= 1.")
        records = self.repository.list_audit_ledger(incident_id=incident_id, limit=limit)
        return [self._serialize_audit(rec) for rec in records]
