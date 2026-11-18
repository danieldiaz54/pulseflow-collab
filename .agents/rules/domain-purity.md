# Reglas de Pureza de Dominio (`domain-architect`)

1. **Cero Dependencias de Infraestructura**:
   - El núcleo de dominio (`src/domain/`, `src/core/`, `domain/`) no debe importar frameworks web (Express, Fastify, NestJS, Next.js, FastAPI, Spring Web), clientes de base de datos ni ORMs (Prisma, SQLAlchemy, Hibernate, Redis).
   - Toda dependencia externa debe invertirse mediante interfaces o puertos definidos en el dominio.

2. **Excepciones e Invariantes Explícitos**:
   - Los errores de negocio, conflictos de concurrencia, violaciones de invariantes o fallos de convergencia deben lanzar excepciones tipadas de dominio.
   - Queda prohibido silenciar errores, devolver valores mágicos o truncar datos inconsistentes.
