# PRODUCT.md — `pulseflow-collab`

## 1. Propósito en una frase
**Tablero colaborativo de tareas en equipo en tiempo real**: mueve tarjetas por columnas y edita detalles junto a tus compañeros viendo quién trabaja en qué tarjeta para evitar sobrescribir cambios ajenos.

## 2. Regla de 2 Capas (Usuario primero, Arquitectura bajo demanda)
- **Capa 1 (`Operate` Dark Workspace):** Tablero Kanban nocturno con 3 columnas (`Por hacer`, `En progreso`, `Resuelto`), avatares en línea (`Valeria`, `Daniel`, `Tú`), modal limpio para crear/editar/comentar tareas y botón de demostración de 1 clic **`"Simular edición simultánea"`** que dispara un conflicto real `HTTP 409` y lo traduce a un aviso claro para el usuario (*"Un compañero acaba de actualizar esta tarjeta"*).
- **Capa 2 (Cajón `"Arquitectura"` opcional):** Muestra eventos WebSocket/SSE multi-nodo en vivo (`/api/v1/events/backplane`), bitácora append-only (`/api/v1/audit/ledger`) y diseño de Monolito Modular + Bloqueo Optimista CAS.
