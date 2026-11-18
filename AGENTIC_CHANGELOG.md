# Agentic Architecture Changelog — pulseflow-collab

## [2026-11-17] - Adopción de Estructura Agéntica (Estándar GNV Manager)

### Added
- **`AGENTS.md`**: Gobernanza del *Lead Orchestrator*, Ley de Ramas (`dev` / `main` / `sdd/agentic-optimization`) y catálogo de 7 subagentes.
- **`.agents/`**: Personas de los 7 subagentes, reglas contextuales (`domain-purity.md`, `ui-strict-types.md`, `gitflow-and-env-isolation.md`), Safety Gate (`hooks.json`, `safety-gate.py`, `safety-gate.js`) y catálogo de skills UI/UX.
- **`.specs/`**: Especificaciones fundacionales en `.specs/00-infrastructure/` y `.specs/01-domain/architecture-baseline.spec.md`.
- **Aislamiento de Entornos**: `.env.development.example`, `.env.production.example` y `docker-compose.dev.yml`.
