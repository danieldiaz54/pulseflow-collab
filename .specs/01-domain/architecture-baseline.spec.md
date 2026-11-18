# SPEC-01: Línea Base Arquitectónica de `pulseflow-collab`

> **Estado**: Activo
> **Fecha**: 2026-11-17
> **Alcance**: Dominio, Contratos, UI/API y Criterios de Calidad

---

## 1. Objetivo

Establecer la línea base bajo **Spec-Driven Development (SDD)** y **Clean Architecture** para `pulseflow-collab`, garantizando que toda evolución futura nazca en una rama derivada de `dev` con su especificación `.spec.md` previa.

## 2. Límites de Responsabilidad por Capa

- **Dominio / Tipos (`domain-architect`)**: Contratos puros e invariantes sin dependencias de infraestructura.
- **Datos / Catálogo (`data-architect`)**: Fuente de datos fuertemente tipada o persistencia aislada por entorno.
- **Integración (`integration-architect`)**: Fronteras externas tipadas y manejo explícito de errores.
- **Interfaz (`designer`)**: Componentes tipados sin `any`, siguiendo `.agents/rules/ui-strict-types.md`.
- **Calidad y Seguridad (`qa-verifier` & `security-auditor`)**: Validación de esquema, linting, typecheck, build y revisión de secretos antes de promover `dev` -> `main`.
