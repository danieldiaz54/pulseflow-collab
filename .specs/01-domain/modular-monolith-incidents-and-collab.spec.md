# Specification: Modular Monolith Incident Management & Multi-Node Realtime Collaboration

> **Domain**: `01-domain` (`pulseflow-collab`)  
> **Architecture**: Modular Monolith, Clean Architecture, Domain-Driven Design (DDD)  
> **Status**: Approved for Implementation  

---

## 1. Domain Boundaries & Modular Monolith Structure

`pulseflow-collab` is designed as a **Modular Monolith** with strict separation of concerns inside the pure domain kernel (`src/domain/`). Every module inside `src/domain/` uses **only the Python 3.12 standard library** with zero external or infrastructure dependencies:

1. **`exceptions` (`src/domain/exceptions.py`)**:
   - Defines explicit, typed domain exceptions (`DomainError`, `InvalidIncidentError`, `IncidentNotFoundError`, `InvalidStateTransitionError`, `OptimisticConcurrencyError`).
2. **`incidents` (`src/domain/incidents.py`)**:
   - Models the core `Incident` aggregate root, `IncidentSeverity`, `IncidentStatus`, `VALID_STATUS_TRANSITIONS`, `IncidentComment`, and `IncidentAuditRecord`.
   - Enforces immutable value semantics (`@dataclass(frozen=True)`), self-validation on instantiation, state machine transitions, and Optimistic Concurrency Control (OCC).
3. **`sla_policy` (`src/domain/sla_policy.py`)**:
   - Encapsulates deterministic Service Level Agreement (SLA) target budgets per severity tier (`SEV1` through `SEV4`) and evaluates remaining/breached SLA windows via `SlaPolicyEngine` and `SlaEvaluation`.
4. **`collaboration` (`src/domain/collaboration.py`)**:
   - Models the multi-node realtime collaboration domain: `RealtimeEnvelope`, `PresenceSession`, and `MultiNodePubSubBackplane` facilitating deterministic pub/sub fan-out across distributed WebSocket gateway nodes (`ws-gateway-01`, `ws-gateway-02`).
5. **`repositories` (`src/domain/repositories.py`)**:
   - Declares the inverted persistence port `IncidentRepositoryProtocol` (`@runtime_checkable Protocol`) so the domain remains decoupled from SQLite/PostgreSQL storage adapters.

---

## 2. Optimistic Concurrency Control (OCC) Invariant

Concurrent edits by multiple Incident Commanders or SRE operators across WebSocket/REST nodes must never overwrite each other ("Lost Update" problem).

### Invariant Rules
- Every `Incident` aggregate carries a monotonically increasing integer `version >= 1` (initialized to `1` upon creation).
- Every state mutation request via `Incident.apply_update(..., expected_version=...)` MUST validate:
  $$\text{expected\_version} == \text{incident.version}$$
- **On Match**: The mutation produces a new immutable `Incident` instance with:
  $$\text{new\_version} = \text{incident.version} + 1$$
  along with a structured field-level change dictionary `diff: dict[str, dict[str, object]]` (`{"field": {"from": old_val, "to": new_val}}`) to be persisted atomically with an `IncidentAuditRecord`.
- **On Mismatch**: The aggregate immediately raises `OptimisticConcurrencyError(incident_id, expected_version, actual_version)` carrying:
  - `code = "ERR-409-OPTIMISTIC-LOCK"`
  - `incident_id: str`
  - `expected_version: int`
  - `actual_version: int`

---

## 3. Incident Lifecycle State Machine

An `Incident` progresses through a deterministic lifecycle governed by `IncidentStatus` and `VALID_STATUS_TRANSITIONS`:

| Current Status | Allowed Next Statuses | Disallowed Transitions |
| :--- | :--- | :--- |
| `OPEN` | `INVESTIGATING`, `MITIGATED`, `RESOLVED` | — |
| `INVESTIGATING` | `MITIGATED`, `RESOLVED` | `OPEN` |
| `MITIGATED` | `INVESTIGATING`, `RESOLVED` | `OPEN` |
| `RESOLVED` | `INVESTIGATING` | `OPEN`, `MITIGATED` |

### State Transition Rules
- Reopening a `RESOLVED` incident MUST transition directly to `INVESTIGATING`.
- Any attempt to transition to an unlisted target status (such as `RESOLVED -> MITIGATED` or `INVESTIGATING -> OPEN`) raises `InvalidStateTransitionError`.
- Assigning the same status (`new_status == current_status`) is treated as a no-op for status transition validation.

---

## 4. SLA Policy Engine

| Severity | Target Resolution Window (`SLA_TARGET_MINUTES`) |
| :--- | :--- |
| `SEV1` | `15` minutes |
| `SEV2` | `60` minutes |
| `SEV3` | `240` minutes (4 hours) |
| `SEV4` | `1440` minutes (24 hours) |

- `SlaPolicyEngine.evaluate(incident: Incident, elapsed_minutes: float = 0.0) -> SlaEvaluation`:
  - Validates `elapsed_minutes >= 0` (raises `InvalidIncidentError` if negative).
  - Computes `remaining_minutes = round(target_minutes - elapsed_minutes, 2)`.
  - Computes `breached = elapsed_minutes > target_minutes`.

---

## 5. Multi-Node WebSocket / Pub-Sub Backplane Model

To support horizontal scaling of realtime collaboration across multiple gateway instances (`ws-gateway-01`, `ws-gateway-02`):

1. **`RealtimeEnvelope`**:
   - Immutable event packet (`event_id`, `channel`, `event_type`, `incident_id`, `version`, `origin_node`, `actor`, `payload`, `published_at`).
2. **`PresenceSession`**:
   - Tracks operator presence per gateway node (`operator_id`, `gateway_node`, `active_incident_id`, `observed_version`, `updated_at`).
3. **`MultiNodePubSubBackplane`**:
   - Maintains node subscriptions (`subscribe(node_id, callback)`), presence sessions (`upsert_presence`, `list_presence`), and a bounded history of published envelopes (`publish(...) -> RealtimeEnvelope`, `list_recent_events(limit=50)`).
   - Publishing an event on `origin_node` fans out the `RealtimeEnvelope` to all registered gateway node callbacks (`ws-gateway-01`, `ws-gateway-02`, etc.) so clients connected to any node receive synchronized incident updates and OCC version broadcasts.
