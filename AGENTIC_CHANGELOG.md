# Agentic Architecture Changelog — pulseflow-collab

## [2026-11-18] - Release v0.1.0: Modular Monolith, Optimistic Concurrency Control & Multi-Node Pub/Sub

### Added
- **SDD Specifications (`.specs/`)**:
  - `.specs/01-domain/modular-monolith-incidents-and-collab.spec.md` (`domain-architect`)
  - `.specs/02-data/optimistic-lock-store-and-audit-ledger.spec.md` (`data-architect`)
  - `.specs/03-integration/realtime-ws-rest-contracts.spec.md` (`integration-architect`)
  - `.specs/04-security/security-audit-report.spec.md` (`security-auditor`)
- **Modular Monolith Domain (`src/domain/`)**:
  - Módulos `incidents` (con control de concurrencia optimista `ERR-409-OPTIMISTIC-LOCK` y máquina de estados `VALID_STATUS_TRANSITIONS`), `sla_policy` (`SlaPolicyEngine`) y `collaboration` (`MultiNodePubSubBackplane` con fan-out hacia `ws-gateway-01` y `ws-gateway-02`).
- **Atomic CAS & Append-Only Audit Ledger (`src/infrastructure/persistence/` & `migrations/`)**:
  - `SQLitePulseFlowRepository` con actualización atómica *Compare-And-Swap* (`WHERE incident_id=? AND version=?`) y triggers `BEFORE UPDATE` / `BEFORE DELETE` en `incident_audit_ledger`, `seed_incidents.py` (5 incidentes canónicos) y `001_init_pulseflow_schema.sql`.
- **Realtime HTTP/SSE/WebSocket Gateway & Minimalist UI (`src/application/`, `src/interfaces/http/`, `ui/`)**:
  - `PulseFlowApplicationService`, `server.py` (REST + SSE + mapeo semántico `409 Conflict` / `422 Unprocessable Entity`), `ws_gateway.py` (`aiohttp` RFC 6455 WebSocket) y Centro de Comando Multi-Operador en `ui/index.html`.
- **QA & Security Certification (`tests/`)**:
  - 17/17 pruebas unitarias, AST domain purity, CAS optimista, triggers append-only e integración HTTP/SSE certificadas por `qa-verifier` y `security-auditor`.

## [2026-11-18] - Adopción de Estructura Agéntica (Estándar GNV Manager)

### Added
- **`AGENTS.md`**: Gobernanza del *Lead Orchestrator*, Ley de Ramas (`dev` / `main` / `sdd/agentic-optimization`) y catálogo de 7 subagentes.
- **`.agents/`**: Personas de los 7 subagentes, reglas contextuales (`domain-purity.md`, `ui-strict-types.md`, `gitflow-and-env-isolation.md`), Safety Gate (`hooks.json`, `safety-gate.py`, `safety-gate.js`) y catálogo de skills UI/UX.
- **`.specs/`**: Especificaciones fundacionales en `.specs/00-infrastructure/` y `.specs/01-domain/architecture-baseline.spec.md`.
- **Aislamiento de Entornos**: `.env.development.example`, `.env.production.example` y `docker-compose.dev.yml`.
