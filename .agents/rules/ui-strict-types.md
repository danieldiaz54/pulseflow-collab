# Reglas de Calidad y Tipado Estricto para UI (`designer`)

1. **Tipado Estricto Sin Excepciones**:
   - Queda prohibido el uso de `any` en componentes, hooks, props, respuestas de API y estado en TypeScript (Web y React Native).
   - Toda métrica numérica, latencia, contador o lectura técnica debe tiparse explícitamente (`number`) y validarse contra `NaN` o valores fuera de rango.

2. **Ergonomía e Integridad de Inputs**:
   - Evitar conversiones automáticas que rompan la edición decimal o antepongan ceros al borrar valores numéricos.
   - Validar límites en formularios antes de enviar comandos al backend.

3. **Consistencia Visual y Tipográfica**:
   - Todo identificador técnico, badge de fase, código ADR, latencia o métrica numérica debe usar fuente monoespaciada (`font-mono`).
   - Respetar las variables CSS y tokens de tema definidos en `tailwind.config.ts` / `globals.css` y las directrices de `.agents/skills/`.
