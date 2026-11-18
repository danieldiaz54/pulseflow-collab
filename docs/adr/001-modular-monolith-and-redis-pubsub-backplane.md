# ADR 001: Modular Monolith Architecture & Multi-Node Redis Pub/Sub Backplane

- **Status**: Accepted
- **Date**: 2026-04-12
- **Deciders**: Lead Orchestrator, Domain Architect, Integration Architect

---

## Context

Real-time collaborative incident response platforms require low-latency state coordination across multiple Incident Commanders, Site Reliability Engineers (SREs), and network operators connected simultaneously. While premature microservice fragmentation introduces distributed transaction overhead and operational complexity during high-severity outages, horizontal scaling of real-time WebSocket and Server-Sent Events (SSE) connections requires multiple stateless gateway instances (`ws-gateway-01`, `ws-gateway-02`) synchronized via a shared pub/sub backplane.

## Decision

1. **Modular Monolith with Pure Domain Kernel (`src/domain/`)**:
   - The core business logic (`incidents`, `sla_policy`, `collaboration`, `exceptions`, `repositories`) is encapsulated in a zero-dependency Python 3.12 domain kernel with strict module boundaries and inverted repository ports (`IncidentRepositoryProtocol`).
   - Application orchestration (`src/application/services.py`) coordinates domain aggregates, persistence adapters, and pub/sub broadcasts inside a single deployable unit.

2. **Multi-Node Pub/Sub Backplane (`MultiNodePubSubBackplane`)**:
   - Every incident mutation (`incident.created`, `incident.updated`, `comment.added`, `incident.conflict_rejected`) is wrapped in an immutable `RealtimeEnvelope` and published to the `incidents.realtime` channel.
   - The backplane fans out each `RealtimeEnvelope` across all registered gateway nodes (`ws-gateway-01`, `ws-gateway-02`) and tracks operator presence sessions (`PresenceSession`) per gateway node, ensuring deterministic multi-node synchronization whether running in-memory for local/CI verification or backed by Redis Pub/Sub in clustered deployments.

## Consequences

- **Positive**: Zero network hop latency between incident command state validation, SLA evaluation, and audit logging; deterministic in-memory multi-node fan-out verification in CI without external broker flakiness.
- **Negative**: Requires strict enforcement of architectural import rules so infrastructure concerns (`sqlite3`, HTTP headers, WebSocket sockets) never leak into `src/domain/`.
