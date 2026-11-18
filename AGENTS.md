# pulseflow-collab — Master Orchestration Architecture & Agent Governance

> **Sistema Operativo del Proyecto**: Spec-Driven Development (SDD), Clean Architecture y Domain-Driven Design (DDD).

Este repositorio forma parte del ecosistema **Portafolio**. El agente principal opera como **Lead Orchestrator** y delega la ejecución especializada a los 7 subagentes definidos en `.agents/`.

---

## 0. Ley Inquebrantable de Ambientes y Ramas Git (Grabada en Piedra)

> ⚠️ **REGLA DE ORO OBLIGATORIA PARA TODOS LOS AGENTES Y DESARROLLADORES:**
>
> 1. **`dev` ES EL ÚNICO ORIGEN**: Toda rama de trabajo (`feat/*`, `fix/*`, `sdd/*`, `refactor/*`) nace **OBLIGATORIA Y EXCLUSIVAMENTE de `dev`**. Prohibido crear ramas desde `main` o hacer commits directos sobre `main`.
> 2. **INTEGRACIÓN EXCLUSIVA EN `dev`**: Todo *merge* o *pull request* de desarrollo se integra únicamente en `dev`.
> 3. **`main` RESERVADA PARA RELEASES AUDITADOS**: `main` solo recibe *merges* desde `dev` tras certificación explícita de `qa-verifier` y `security-auditor`.
> 4. **AISLAMIENTO TOTAL DE DATOS Y ENTORNOS**: En `dev` y ramas derivadas se opera exclusivamente con `.env.development` y `docker-compose.dev.yml`, nunca con `.env.production`.

---

## 1. Catálogo de Subagentes Especializados (`.agents/<rol>/persona.md`)

1. **`domain-architect`**: Lógica de dominio pura (`src/domain/`, `src/core/`, `src/types/`) y especificaciones previas en `.specs/`. Respeta `.agents/rules/domain-purity.md`.
2. **`data-architect`**: Persistencia, repositorios, catálogos de datos, esquemas e inmutabilidad. Respeta separación Dev vs Prod.
3. **`integration-architect`**: Contratos DTO tipados, rutas/APIs/eventos y mapeo semántico de errores.
4. **`designer`**: UI/UX en Frontend/Mobile siguiendo `.agents/rules/ui-strict-types.md` y `.agents/skills/`.
5. **`qa-verifier`**: TDD, pruebas automatizadas, lint, typecheck y certificación de releases hacia `main`.
6. **`docs-oracle`**: Consulta material local privado en `docs/` (ignorado en Git salvo `docs/adr/`) y extrae especificaciones sanitizadas hacia `.specs/`. **Cero exposición remota** de material privado.
7. **`security-auditor`**: Seguridad DevSecOps, OWASP, validación de inputs, protección de secretos y mantenimiento de `.agents/hooks.json`.

---

## 2. Flujo SDD y Mejora Continua

1. **Spec antes que código**: Toda nueva capacidad requiere un archivo `.specs/<dominio>/<feature>.spec.md` antes de implementarse.
2. **Rama `sdd/agentic-optimization`**: Se sincroniza post-merge a `dev`, registrando el hash auditado en `.agents/last_dev_commit.txt` y los cambios de gobernanza en `AGENTIC_CHANGELOG.md`.
3. **Safety Gate (`PreToolUse`)**: `.agents/hooks.json` ejecuta `.agents/scripts/safety-gate.py` antes de `run_command` para bloquear comandos destructivos.
