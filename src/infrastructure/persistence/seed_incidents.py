"""Deterministic production-grade incident seeds for PulseFlow Collab."""

from __future__ import annotations

from typing import Any

from src.domain.incidents import (
    Incident,
    IncidentComment,
    IncidentSeverity,
    IncidentStatus,
)
from src.infrastructure.persistence.sqlite_repository import SQLitePulseFlowRepository

DEFAULT_INCIDENTS: list[dict[str, Any]] = [
    {
        "incident_id": "INC-2026-101",
        "title": "Redis Pub/Sub Backplane Latency Spike",
        "service_name": "pulseflow-sync-backplane",
        "severity": "SEV1",
        "status": "INVESTIGATING",
        "commander": "sre.valeria",
        "summary": (
            "P99 fan-out broadcast latency across WebSocket replica nodes exceeded 420ms "
            "due to client output buffer saturation on primary Redis Pub/Sub shard."
        ),
        "created_at": "2026-04-12T14:05:00+00:00",
        "updated_at": "2026-04-12T14:18:00+00:00",
        "comments": [
            {
                "comment_id": "CMT-2026-101-A",
                "author": "sre.valeria",
                "body": "Identified slow consumer on ws-gateway-03; draining active SSE/WS channels and scaling pubsub shard replicas.",
                "created_at": "2026-04-12T14:12:00+00:00",
            },
            {
                "comment_id": "CMT-2026-101-B",
                "author": "netops.carlos",
                "body": "Applied client-output-buffer-limit pubsub 256mb 64mb 15s; p99 fan-out dropping toward 38ms.",
                "created_at": "2026-04-12T14:18:00+00:00",
            },
        ],
    },
    {
        "incident_id": "INC-2026-102",
        "title": "pgvector HNSW Index Memory Saturation",
        "service_name": "cortex-rag-retriever",
        "severity": "SEV2",
        "status": "MITIGATED",
        "commander": "mlops.elena",
        "summary": (
            "HNSW ef_search=128 concurrent hybrid queries triggered shared_buffers eviction "
            "and increased disk IOPS by 3.4x on read replica pg-vector-02."
        ),
        "created_at": "2026-04-12T12:30:00+00:00",
        "updated_at": "2026-04-12T13:15:00+00:00",
        "comments": [
            {
                "comment_id": "CMT-2026-102-A",
                "author": "mlops.elena",
                "body": "Tuned hnsw.ef_search to 64 via session pooler and routed bulk ingestion jobs to maintenance window.",
                "created_at": "2026-04-12T13:15:00+00:00",
            }
        ],
    },
    {
        "incident_id": "INC-2026-103",
        "title": "Kafka Outbox Relay Partition Stall",
        "service_name": "ledgercore-outbox-relay",
        "severity": "SEV1",
        "status": "OPEN",
        "commander": "core.daniel",
        "summary": (
            "Transactional Outbox CDC worker stalled on partition 7 after schema registry "
            "timeout; 1,420 settlement events queued in PostgreSQL outbox_events table."
        ),
        "created_at": "2026-04-12T14:22:00+00:00",
        "updated_at": "2026-04-12T14:25:00+00:00",
        "comments": [
            {
                "comment_id": "CMT-2026-103-A",
                "author": "core.daniel",
                "body": "Verifying double-entry ledger idempotency locks before restarting outbox consumer group.",
                "created_at": "2026-04-12T14:25:00+00:00",
            }
        ],
    },
    {
        "incident_id": "INC-2026-104",
        "title": "OTel Collector Trace Export Backpressure",
        "service_name": "cloudops-otel-gateway",
        "severity": "SEV3",
        "status": "INVESTIGATING",
        "commander": "platform.marco",
        "summary": (
            "OpenTelemetry collector batch processor queue reached 88% capacity during "
            "canary rollout telemetry burst in cluster us-east-prod-01."
        ),
        "created_at": "2026-04-12T11:10:00+00:00",
        "updated_at": "2026-04-12T11:45:00+00:00",
        "comments": [
            {
                "comment_id": "CMT-2026-104-A",
                "author": "platform.marco",
                "body": "Enabled tail-based sampling at 15% for healthy HTTP 200 spans while retaining 100% error/latency traces.",
                "created_at": "2026-04-12T11:45:00+00:00",
            }
        ],
    },
    {
        "incident_id": "INC-2026-105",
        "title": "Mobile SQLite Offline Sync Conflict",
        "service_name": "fieldnotes-sync-gateway",
        "severity": "SEV4",
        "status": "RESOLVED",
        "commander": "mobile.sofia",
        "summary": (
            "Field inspection devices reconnecting after 18h offline window encountered "
            "vector clock divergence on shared attachment manifests."
        ),
        "created_at": "2026-04-12T08:00:00+00:00",
        "updated_at": "2026-04-12T09:40:00+00:00",
        "comments": [
            {
                "comment_id": "CMT-2026-105-A",
                "author": "mobile.sofia",
                "body": "Deterministic LWW-Element-Set merge resolver deployed and verified against 420 queued field mutation logs.",
                "created_at": "2026-04-12T09:40:00+00:00",
            }
        ],
    },
]


def seed_default_incidents(repo: SQLitePulseFlowRepository) -> int:
    """Seed the 5 canonical production incidents if they are not already present."""
    existing_ids = {inc.incident_id for inc in repo.list_incidents()}
    seeded_count = 0

    for item in DEFAULT_INCIDENTS:
        incident_id = str(item["incident_id"])
        if incident_id in existing_ids:
            continue

        initial_status = IncidentStatus(str(item["status"]))
        incident = Incident(
            incident_id=incident_id,
            title=str(item["title"]),
            service_name=str(item["service_name"]),
            severity=IncidentSeverity(str(item["severity"])),
            status=initial_status,
            commander=str(item["commander"]),
            summary=str(item["summary"]),
            version=1,
            created_at=str(item["created_at"]),
            updated_at=str(item["updated_at"]),
        )
        repo.create_incident(incident, actor=incident.commander)

        for comment_data in item.get("comments", []):
            comment = IncidentComment(
                comment_id=str(comment_data["comment_id"]),
                incident_id=incident_id,
                author=str(comment_data["author"]),
                body=str(comment_data["body"]),
                created_at=str(comment_data["created_at"]),
            )
            repo.add_comment(comment)

        seeded_count += 1

    return seeded_count
