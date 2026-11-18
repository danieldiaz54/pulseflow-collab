# SPEC-00-B: Optimización de Arquitectura Agéntica y Seguridad Preventiva

> **Estado**: Aprobado
> **Fecha**: 2026-11-17
> **Alcance**: Gobernanza Multi-Agente, Spec-Driven Development, Safety Gate, Reglas Contextuales y Skills UI

---

## 1. Visión General

Cada repositorio del ecosistema Portafolio replica el modelo agéntico de **GNV Manager**, operado por un **Lead Orchestrator** que coordina 7 subagentes especializados bajo flujo SDD (`.specs/` antes del código).

## 2. Componentes Obligatorios por Repositorio

1. **`AGENTS.md` y `AGENTIC_CHANGELOG.md`**: Constitución operativa del repositorio y registro de cambios agénticos.
2. **Catálogo `.agents/`**:
   - 7 `persona.md`: `domain-architect`, `data-architect`, `integration-architect`, `designer`, `qa-verifier`, `docs-oracle`, `security-auditor`.
   - `rules/`: `domain-purity.md`, `ui-strict-types.md`, `gitflow-and-env-isolation.md`.
   - `hooks.json` + `scripts/safety-gate.py` / `safety-gate.js` (`PreToolUse` sobre `run_command`).
   - `skills/`: catálogo compartido de diseño UI/UX (`minimalist-skill`, `brandkit`, `stitch-skill`, etc.).
   - `last_dev_commit.txt`: hash del último commit de `dev` auditado desde `sdd/agentic-optimization`.
3. **`.specs/00-infrastructure/`**: Especificaciones fundacionales de aislamiento y gobernanza antes de crear módulos de negocio.

## 3. Criterios de Verificación

1. `safety-gate.py` responde `{"decision": "deny"}` ante `DROP DATABASE`, `TRUNCATE TABLE`, `rm -rf /`, `rmdir /s /q c:\`, `format`, o force-push a `main`.
2. `safety-gate.py` responde `{"decision": "allow"}` ante comandos seguros como `git status`.
3. Cada repositorio mantiene la tríada de ramas `main`, `dev` y `sdd/agentic-optimization`.
