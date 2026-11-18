"""Persistence tests for Atomic Compare-And-Swap (CAS) OCC and Append-Only Audit Ledger.

Covers:
1. `SQLitePulseFlowRepository` conformance to `IncidentRepositoryProtocol` and `seed_default_incidents` (5 canonical incidents).
2. Atomic Compare-And-Swap (`save_updated_incident`) succeeding when `expected_version` matches and raising `OptimisticConcurrencyError` (`ERR-409-OPTIMISTIC-LOCK`) when the database row version has already advanced.
3. Database-level `BEFORE UPDATE` and `BEFORE DELETE` immutability triggers on `incident_audit_ledger` raising `AppendOnlyLedgerError` via `execute_raw_mutation_for_test`.
"""

from __future__ import annotations

import unittest

from src.domain.exceptions import IncidentNotFoundError, OptimisticConcurrencyError
from src.domain.incidents import (
    Incident,
    IncidentComment,
    IncidentSeverity,
    IncidentStatus,
)
from src.domain.repositories import IncidentRepositoryProtocol
from src.infrastructure.persistence.seed_incidents import seed_default_incidents
from src.infrastructure.persistence.sqlite_repository import (
    AppendOnlyLedgerError,
    SQLitePulseFlowRepository,
)


class TestSQLiteCasAndAppendOnlyAuditLedger(unittest.TestCase):
    """Verify atomic SQLite CAS concurrency control and immutable audit ledger triggers."""

    def setUp(self) -> None:
        self.repo = SQLitePulseFlowRepository(db_path=":memory:")

    def tearDown(self) -> None:
        self.repo.close()

    def test_repository_protocol_conformance_and_default_seed(self) -> None:
        self.assertIsInstance(self.repo, IncidentRepositoryProtocol)

        seeded_count = seed_default_incidents(self.repo)
        self.assertEqual(seeded_count, 5)

        # Idempotent re-seed returns 0
        self.assertEqual(seed_default_incidents(self.repo), 0)

        incidents = self.repo.list_incidents()
        self.assertEqual(len(incidents), 5)

        inc_101 = self.repo.get_incident("INC-2026-101")
        self.assertEqual(inc_101.version, 1)
        self.assertEqual(inc_101.severity, IncidentSeverity.SEV1)
        self.assertEqual(inc_101.status, IncidentStatus.INVESTIGATING)

        comments_101 = self.repo.list_comments("INC-2026-101")
        self.assertEqual(len(comments_101), 2)

        with self.assertRaises(IncidentNotFoundError):
            self.repo.get_incident("INC-NON-EXISTENT")

    def test_atomic_cas_save_updated_incident_and_stale_version_conflict(self) -> None:
        seed_default_incidents(self.repo)
        original = self.repo.get_incident("INC-2026-101")
        self.assertEqual(original.version, 1)

        # Operator A updates from version 1 -> 2
        updated_v2, diff_v2 = original.apply_update(
            expected_version=1,
            actor="sre.valeria",
            status=IncidentStatus.MITIGATED,
            summary="Pub/Sub shard buffer limits tuned.",
            updated_at="2026-04-12T14:25:00+00:00",
        )
        audit_v2 = self.repo.save_updated_incident(
            updated=updated_v2,
            expected_version=1,
            actor="sre.valeria",
            action="STATUS_TRANSITION",
            diff=diff_v2,
        )
        self.assertEqual(audit_v2.version, 2)
        self.assertEqual(audit_v2.action, "STATUS_TRANSITION")

        persisted = self.repo.get_incident("INC-2026-101")
        self.assertEqual(persisted.version, 2)
        self.assertEqual(persisted.status, IncidentStatus.MITIGATED)

        # Operator B attempts concurrent update with stale expected_version=1 against DB row version=2
        stale_candidate = Incident(
            incident_id=original.incident_id,
            title=original.title,
            service_name=original.service_name,
            severity=original.severity,
            status=IncidentStatus.RESOLVED,
            commander=original.commander,
            summary="Stale operator attempt.",
            version=2,
            created_at=original.created_at,
            updated_at="2026-04-12T14:26:00+00:00",
        )

        with self.assertRaises(OptimisticConcurrencyError) as ctx:
            self.repo.save_updated_incident(
                updated=stale_candidate,
                expected_version=1,
                actor="netops.carlos",
                action="STATUS_TRANSITION",
                diff={"status": {"from": "INVESTIGATING", "to": "RESOLVED"}},
            )

        self.assertEqual(ctx.exception.code, "ERR-409-OPTIMISTIC-LOCK")
        self.assertEqual(ctx.exception.incident_id, "INC-2026-101")
        self.assertEqual(ctx.exception.expected_version, 1)
        self.assertEqual(ctx.exception.actual_version, 2)

        # Confirm database state was not overwritten by stale write
        after_conflict = self.repo.get_incident("INC-2026-101")
        self.assertEqual(after_conflict.version, 2)
        self.assertEqual(after_conflict.status, IncidentStatus.MITIGATED)

    def test_append_only_audit_ledger_triggers_block_update_and_delete(self) -> None:
        seed_default_incidents(self.repo)
        ledger = self.repo.list_audit_ledger(incident_id="INC-2026-101")
        self.assertGreaterEqual(len(ledger), 3)  # 1 creation + 2 comments

        target_audit_id = ledger[0].audit_id

        with self.assertRaises(AppendOnlyLedgerError) as update_ctx:
            self.repo.execute_raw_mutation_for_test(
                "UPDATE incident_audit_ledger SET actor = ? WHERE audit_id = ?",
                ("tampered.actor", target_audit_id),
            )
        self.assertIn("APPEND_ONLY_LEDGER_VIOLATION", str(update_ctx.exception))

        with self.assertRaises(AppendOnlyLedgerError) as delete_ctx:
            self.repo.execute_raw_mutation_for_test(
                "DELETE FROM incident_audit_ledger WHERE audit_id = ?",
                (target_audit_id,),
            )
        self.assertIn("APPEND_ONLY_LEDGER_VIOLATION", str(delete_ctx.exception))

        # Verify audit entry remains intact
        ledger_after = self.repo.list_audit_ledger(incident_id="INC-2026-101")
        self.assertEqual(len(ledger_after), len(ledger))
        self.assertEqual(ledger_after[0].actor, ledger[0].actor)

    def test_add_comment_persists_timeline_and_audit_record(self) -> None:
        seed_default_incidents(self.repo)
        new_comment = IncidentComment(
            comment_id="CMT-2026-101-C",
            incident_id="INC-2026-101",
            author="sre.daniela",
            body="Verified replica convergence across ws-gateway-01 and ws-gateway-02.",
            created_at="2026-04-12T14:30:00+00:00",
        )
        saved_comment, audit_entry = self.repo.add_comment(new_comment)
        self.assertEqual(saved_comment.comment_id, "CMT-2026-101-C")
        self.assertEqual(audit_entry.action, "COMMENT_ADDED")

        comments = self.repo.list_comments("INC-2026-101")
        self.assertEqual(len(comments), 3)


if __name__ == "__main__":
    unittest.main()
