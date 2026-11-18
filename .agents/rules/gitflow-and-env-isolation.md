# Reglas de GitFlow y Aislamiento de Entornos (Todos los Agentes)

1. **Jerarquía de Ramas Git**:
   - Toda rama nueva (`feat/*`, `fix/*`, `sdd/*`, `refactor/*`) se crea **exclusivamente desde `dev`**.
   - Todo trabajo terminado se integra primero en **`dev`**.
   - **`main`** solo recibe merges desde `dev` tras validación de `qa-verifier` y `security-auditor`.
   - **`sdd/agentic-optimization`** se mantiene sincronizada post-merge a `dev`, registrando el commit auditado en `.agents/last_dev_commit.txt`.

2. **Aislamiento de Entornos y Datos**:
   - Desarrollo local utiliza exclusivamente `.env.development` y `docker-compose.dev.yml`.
   - Queda prohibido conectar el entorno local a credenciales o bases de datos de producción (`.env.production`).
   - La carpeta local `Docs/` debe permanecer siempre en `.gitignore`.
