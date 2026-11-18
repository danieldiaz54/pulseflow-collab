"""Unit tests for the PulseFlow Collab Pure Domain Kernel (Modular Monolith).

Covers:
1. Incident aggregate self-validation & immutability.
2. Optimistic Concurrency Control (OCC) in `Incident.apply_update()` (`expected_version == version` vs `ERR-409-OPTIMISTIC-LOCK`).
3. Incident lifecycle state machine (`VALID_STATUS_TRANSITIONS`) & `InvalidStateTransitionError`.
4. `SlaPolicyEngine.evaluate()` across severities (`SEV1`..`SEV4`) and breach conditions.
5. `MultiNodePubSubBackplane` fan-out delivery across `ws-gateway-01` and `ws-gateway-02` and presence management.
6. AST-level Domain Purity verification (`.agents/rules/domain-purity.md`).
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from src.domain.collaboration import (
    MultiNodePubSubBackplane,
    PresenceSession,
    RealtimeEnvelope,
)
from src.domain.exceptions import (
    DomainError,
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
from src.domain.sla_policy import SLA_TARGET_MINUTES, SlaPolicyEngine


class TestIncidentDomainAggregate(unittest.TestCase):
    """Verify Incident aggregate root invariants, OCC, and state machine."""

    def _make_incident(
        self,
        status: IncidentStatus = IncidentStatus.OPEN,
        severity: IncidentSeverity = IncidentSeverity.SEV1,
        version: int = 1,
    ) -> Incident:
        return Incident(
            incident_id="INC-2026-900",
            title="Redis Pub/Sub Backplane Latency Spike",
            service_name="pulseflow-sync-backplane",
            severity=severity,
            status=status,
            commander="sre.valeria",
            summary="Initial investigation into p99 broadcast latency.",
            version=version,
            created_at="2026-04-12T14:00:00+00:00",
            updated_at="2026-04-12T14:00:00+00:00",
        )

    def test_incident_self_validation_and_immutability(self) -> None:
        inc = self._make_incident()
        self.assertEqual(inc.incident_id, "INC-2026-900")
        self.assertEqual(inc.severity, IncidentSeverity.SEV1)
        self.assertEqual(inc.status, IncidentStatus.OPEN)
        self.assertEqual(inc.version, 1)

        with self.assertRaises(FrozenInstanceError):
            inc.version = 2  # type: ignore[misc]

        for empty_field in ("incident_id", "title", "service_name", "commander", "summary"):
            kwargs = {
                "incident_id": "INC-2026-900",
                "title": "Valid Title",
                "service_name": "valid-service",
                "severity": IncidentSeverity.SEV2,
                "status": IncidentStatus.OPEN,
                "commander": "sre.valeria",
                "summary": "Valid summary",
                "version": 1,
            }
            kwargs[empty_field] = "   "
            with self.assertRaises(InvalidIncidentError):
                Incident(**kwargs)  # type: ignore[arg-type]

        with self.assertRaises(InvalidIncidentError):
            self._make_incident(version=0)

        with self.assertRaises(InvalidIncidentError):
            self._make_incident(version=True)  # type: ignore[arg-type]

        with self.assertRaises(InvalidIncidentError):
            Incident(
                incident_id="INC-2026-901",
                title="Invalid Severity",
                service_name="svc",
                severity="SEV99",  # type: ignore[arg-type]
                status=IncidentStatus.OPEN,
                commander="sre.valeria",
                summary="Summary",
            )

    def test_comment_and_audit_record_self_validation(self) -> None:
        comment = IncidentComment(
            comment_id="CMT-1",
            incident_id="INC-2026-900",
            author="sre.valeria",
            body="Mitigation applied.",
            created_at="2026-04-12T14:05:00+00:00",
        )
        self.assertEqual(comment.comment_id, "CMT-1")

        with self.assertRaises(InvalidIncidentError):
            IncidentComment(
                comment_id="",
                incident_id="INC-2026-900",
                author="sre.valeria",
                body="Mitigation applied.",
                created_at="2026-04-12T14:05:00+00:00",
            )

        audit = IncidentAuditRecord(
            audit_id="AUD-1",
            incident_id="INC-2026-900",
            version=1,
            actor="sre.valeria",
            action="INCIDENT_CREATED",
            changes_json='{"status": "OPEN"}',
            created_at="2026-04-12T14:00:00+00:00",
        )
        self.assertEqual(audit.version, 1)

        with self.assertRaises(InvalidIncidentError):
            IncidentAuditRecord(
                audit_id="AUD-1",
                incident_id="INC-2026-900",
                version=0,
                actor="sre.valeria",
                action="INCIDENT_CREATED",
                changes_json="{}",
                created_at="2026-04-12T14:00:00+00:00",
            )

    def test_apply_update_optimistic_concurrency_control_success_and_diff(self) -> None:
        inc = self._make_incident(status=IncidentStatus.OPEN, version=1)
        updated, diff = inc.apply_update(
            expected_version=1,
            actor="sre.valeria",
            status=IncidentStatus.INVESTIGATING,
            commander="netops.carlos",
            summary="Investigating shard buffer saturation.",
            updated_at="2026-04-12T14:10:00+00:00",
        )

        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.status, IncidentStatus.INVESTIGATING)
        self.assertEqual(updated.commander, "netops.carlos")
        self.assertEqual(
            diff,
            {
                "status": {"from": "OPEN", "to": "INVESTIGATING"},
                "commander": {"from": "sre.valeria", "to": "netops.carlos"},
                "summary": {
                    "from": "Initial investigation into p99 broadcast latency.",
                    "to": "Investigating shard buffer saturation.",
                },
            },
        )

    def test_apply_update_optimistic_concurrency_conflict_raises_409_domain_error(self) -> None:
        inc = self._make_incident(status=IncidentStatus.INVESTIGATING, version=3)

        with self.assertRaises(OptimisticConcurrencyError) as ctx:
            inc.apply_update(
                expected_version=1,
                actor="sre.daniela",
                status=IncidentStatus.MITIGATED,
            )

        err = ctx.exception
        self.assertIsInstance(err, DomainError)
        self.assertEqual(err.code, "ERR-409-OPTIMISTIC-LOCK")
        self.assertEqual(err.incident_id, "INC-2026-900")
        self.assertEqual(err.expected_version, 1)
        self.assertEqual(err.actual_version, 3)
        self.assertIn("ERR-409-OPTIMISTIC-LOCK", str(err))

    def test_lifecycle_state_machine_valid_and_invalid_transitions(self) -> None:
        self.assertIn(IncidentStatus.INVESTIGATING, VALID_STATUS_TRANSITIONS[IncidentStatus.OPEN])
        self.assertIn(IncidentStatus.MITIGATED, VALID_STATUS_TRANSITIONS[IncidentStatus.INVESTIGATING])
        self.assertIn(IncidentStatus.RESOLVED, VALID_STATUS_TRANSITIONS[IncidentStatus.MITIGATED])
        self.assertEqual(
            VALID_STATUS_TRANSITIONS[IncidentStatus.RESOLVED],
            {IncidentStatus.INVESTIGATING},
        )

        # Valid chain: OPEN -> INVESTIGATING -> MITIGATED -> RESOLVED -> INVESTIGATING
        inc1 = self._make_incident(status=IncidentStatus.OPEN, version=1)
        inc2, _ = inc1.apply_update(
            expected_version=1,
            actor="sre.valeria",
            status=IncidentStatus.INVESTIGATING,
        )
        inc3, _ = inc2.apply_update(
            expected_version=2,
            actor="sre.valeria",
            status=IncidentStatus.MITIGATED,
        )
        inc4, _ = inc3.apply_update(
            expected_version=3,
            actor="sre.valeria",
            status=IncidentStatus.RESOLVED,
        )
        inc5, _ = inc4.apply_update(
            expected_version=4,
            actor="sre.valeria",
            status=IncidentStatus.INVESTIGATING,
        )
        self.assertEqual(inc5.status, IncidentStatus.INVESTIGATING)
        self.assertEqual(inc5.version, 5)

        # Disallowed transitions: RESOLVED -> MITIGATED, RESOLVED -> OPEN, INVESTIGATING -> OPEN
        invalid_pairs = [
            (IncidentStatus.RESOLVED, IncidentStatus.MITIGATED),
            (IncidentStatus.RESOLVED, IncidentStatus.OPEN),
            (IncidentStatus.INVESTIGATING, IncidentStatus.OPEN),
            (IncidentStatus.MITIGATED, IncidentStatus.OPEN),
        ]
        for current_status, illegal_target in invalid_pairs:
            with self.subTest(current=current_status, target=illegal_target):
                incident = self._make_incident(status=current_status, version=1)
                with self.assertRaises(InvalidStateTransitionError):
                    incident.apply_update(
                        expected_version=1,
                        actor="sre.valeria",
                        status=illegal_target,
                    )


class TestSlaPolicyEngine(unittest.TestCase):
    """Verify deterministic SLA evaluation across SEV1..SEV4 and breach thresholds."""

    def _make_incident(self, severity: IncidentSeverity) -> Incident:
        return Incident(
            incident_id=f"INC-{severity.value}",
            title="SLA Test Incident",
            service_name="core-service",
            severity=severity,
            status=IncidentStatus.INVESTIGATING,
            commander="sre.valeria",
            summary="Evaluating SLA window.",
            version=1,
        )

    def test_sla_targets_and_breach_evaluation_across_all_severities(self) -> None:
        expected_targets = {
            IncidentSeverity.SEV1: 15,
            IncidentSeverity.SEV2: 60,
            IncidentSeverity.SEV3: 240,
            IncidentSeverity.SEV4: 1440,
        }
        self.assertEqual(SLA_TARGET_MINUTES, expected_targets)

        for sev, target in expected_targets.items():
            inc = self._make_incident(sev)

            within_sla = SlaPolicyEngine.evaluate(inc, elapsed_minutes=target - 2.5)
            self.assertEqual(within_sla.target_minutes, target)
            self.assertAlmostEqual(within_sla.remaining_minutes, 2.5)
            self.assertFalse(within_sla.breached)

            exact_boundary = SlaPolicyEngine.evaluate(inc, elapsed_minutes=float(target))
            self.assertEqual(exact_boundary.remaining_minutes, 0.0)
            self.assertFalse(exact_boundary.breached)

            breached_sla = SlaPolicyEngine.evaluate(inc, elapsed_minutes=target + 5.25)
            self.assertAlmostEqual(breached_sla.remaining_minutes, -5.25)
            self.assertTrue(breached_sla.breached)

    def test_sla_rejects_negative_or_invalid_elapsed_minutes(self) -> None:
        inc = self._make_incident(IncidentSeverity.SEV1)
        with self.assertRaises(InvalidIncidentError):
            SlaPolicyEngine.evaluate(inc, elapsed_minutes=-0.1)
        with self.assertRaises(InvalidIncidentError):
            SlaPolicyEngine.evaluate(inc, elapsed_minutes=float("nan"))
        with self.assertRaises(InvalidIncidentError):
            SlaPolicyEngine.evaluate("not-an-incident", elapsed_minutes=5.0)  # type: ignore[arg-type]


class TestMultiNodePubSubBackplane(unittest.TestCase):
    """Verify multi-node fan-out across ws-gateway-01 and ws-gateway-02 and presence tracking."""

    def test_fanout_delivery_across_gateway_nodes_and_presence(self) -> None:
        backplane = MultiNodePubSubBackplane(nodes=("ws-gateway-01", "ws-gateway-02"))
        self.assertEqual(backplane.list_nodes(), ["ws-gateway-01", "ws-gateway-02"])

        received_node_1: list[RealtimeEnvelope] = []
        received_node_2: list[RealtimeEnvelope] = []

        backplane.subscribe("ws-gateway-01", received_node_1.append)
        backplane.subscribe("ws-gateway-02", received_node_2.append)

        envelope = backplane.publish(
            event_type="incident.updated",
            incident_id="INC-2026-101",
            version=2,
            origin_node="ws-gateway-01",
            actor="sre.valeria",
            payload={"status": "MITIGATED", "version": 2},
        )

        self.assertEqual(len(received_node_1), 1)
        self.assertEqual(len(received_node_2), 1)
        self.assertEqual(received_node_1[0], envelope)
        self.assertEqual(received_node_2[0], envelope)
        self.assertEqual(len(backplane.get_node_events("ws-gateway-01")), 1)
        self.assertEqual(len(backplane.get_node_events("ws-gateway-02")), 1)
        self.assertEqual(len(backplane.list_recent_events(limit=10)), 1)

        # Presence tracking per gateway node
        s1 = backplane.upsert_presence(
            "sre.valeria",
            gateway_node="ws-gateway-01",
            active_incident_id="INC-2026-101",
            observed_version=2,
        )
        s2 = backplane.upsert_presence(
            PresenceSession(
                operator_id="netops.carlos",
                gateway_node="ws-gateway-02",
                active_incident_id="INC-2026-101",
                observed_version=2,
                updated_at="2026-04-12T14:20:00+00:00",
            )
        )
        self.assertEqual(s1.gateway_node, "ws-gateway-01")
        self.assertEqual(s2.gateway_node, "ws-gateway-02")
        self.assertEqual(len(backplane.list_presence(incident_id="INC-2026-101")), 2)
        self.assertEqual(len(backplane.list_presence(incident_id="INC-OTHER")), 0)


class TestAstDomainPurity(unittest.TestCase):
    """Enforce .agents/rules/domain-purity.md via AST inspection of src/domain/*.py."""

    FORBIDDEN_ROOT_MODULES: set[str] = {
        "sqlite3",
        "http",
        "aiohttp",
        "fastapi",
        "urllib",
        "redis",
        "sqlalchemy",
    }
    FORBIDDEN_PREFIXES: tuple[str, ...] = (
        "src.infrastructure",
        "src.interfaces",
        "src.application",
    )

    def test_domain_layer_has_zero_infrastructure_or_framework_imports(self) -> None:
        domain_dir = Path(__file__).resolve().parents[1] / "src" / "domain"
        py_files = sorted(domain_dir.glob("*.py"))
        self.assertGreaterEqual(len(py_files), 5)

        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".")[0]
                        self.assertNotIn(
                            root_mod,
                            self.FORBIDDEN_ROOT_MODULES,
                            f"Forbidden import '{alias.name}' found in {py_file.name}",
                        )
                        self.assertFalse(
                            alias.name.startswith(self.FORBIDDEN_PREFIXES),
                            f"Forbidden outer-layer import '{alias.name}' found in {py_file.name}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".")[0]
                    self.assertNotIn(
                        root_mod,
                        self.FORBIDDEN_ROOT_MODULES,
                        f"Forbidden from-import '{node.module}' found in {py_file.name}",
                    )
                    self.assertFalse(
                        node.module.startswith(self.FORBIDDEN_PREFIXES),
                        f"Forbidden outer-layer from-import '{node.module}' found in {py_file.name}",
                    )


if __name__ == "__main__":
    unittest.main()
