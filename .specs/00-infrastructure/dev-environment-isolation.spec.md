# SPEC-00: Aislamiento de Entornos (Dev vs. Prod) y Estrategia de Ramas Git

> **Estado**: Aprobado
> **Fecha**: 2026-11-17
> **Alcance**: Git Workflow, Aislamiento de Variables `.env`, Docker Compose de Desarrollo, Repositorios Públicos

---

## 1. Contexto y Problema

Al gestionar un ecosistema de 6 repositorios públicos independientes (`portfolio-web`, `pulseflow-collab`, `ledgercore-distributed`, `cortex-rag-agent`, `fieldnotes-mobile`, `cloudops-gitops-platform`), trabajar directamente sobre `main` o mezclar variables de desarrollo y producción introduce dos riesgos graves:
1. Regresiones directas en la rama pública estable (`main`).
2. Fuga accidental de credenciales o alteración de entornos remotos desde pruebas locales.

---

## 2. Estrategia de Ramas Git (GitFlow Simplificado)

```mermaid
gitGraph
   commit id: "Initial Main"
   branch dev
   checkout dev
   commit id: "Setup Agentic & Dev Env"
   branch sdd/agentic-optimization
   checkout dev
   branch feat/new-capability
   commit id: "Spec + Tests + Impl"
   checkout dev
   merge feat/new-capability id: "Merge to Dev"
   checkout sdd/agentic-optimization
   merge dev id: "Audit & Update last_dev_commit"
   checkout main
   merge dev id: "Certified Release"
```

1. **`main` (Producción / Release Público Estable)**:
   - Protegida contra commits directos. Solo recibe merges desde `dev` tras validación explícita de `qa-verifier` y `security-auditor`.
2. **`dev` (Integración / Desarrollo Activo)**:
   - Único origen permitido para ramas `feat/*`, `fix/*`, `sdd/*`, `refactor/*`.
   - Toda nueva funcionalidad se integra en `dev`.
3. **`sdd/agentic-optimization` (Auditoría Agéntica Continua)**:
   - Rama persistente sincronizada post-merge a `dev` para auditar prompts, reglas y `.specs/`.

---

## 3. Aislamiento de Configuración y Contenedores

| Entorno | Archivo de Variables | Plantilla Versionada | Orquestación Local |
| :--- | :--- | :--- | :--- |
| **Desarrollo (Local/Dev)** | `.env.development` (gitignored) | `.env.development.example` | `docker-compose.dev.yml` |
| **Producción (Prod)** | `.env.production` (gitignored) | `.env.production.example` | `docker-compose.yml` / IaC |
| **Referencia Privada** | `Docs/` (gitignored) | N/A (solo lectura local) | Custodiado por `docs-oracle` |
