---
paths:
  - "src/core_banking_mcp/infrastructure/inbound/mcp/**"
  - "tests/contract/**"
---

# Convención de herramientas MCP (servidor `core_banking_mcp`)

1. **Nombres**: `verbo_sustantivo` en snake_case español (`buscar_cliente`, `iniciar_disputa`). Única excepción al inglés (§3.4). Un nombre no cambia sin spec y versión de contrato.
2. **Descripción**: docstring en español con propósito, precondiciones (p. ej. "requiere identidad verificada"), efectos secundarios e idempotencia. El LLM la lee: debe indicar cuándo usar la herramienta y cuándo no.
3. **Esquemas**: entradas y salidas son modelos Pydantic v2 tipados; prohibidos `dict` libre y `Any`. Cada campo con `Field(description=...)`. Campos en snake_case inglés.
4. **Delgadez** (Art. 4): la herramienta valida la entrada, llama a un caso de uso y mapea la salida. Sin lógica de negocio ni SQLAlchemy en `infrastructure/inbound/mcp`.
5. **Identificación** (Art. 7): toda herramienta que lea o modifique datos de cliente exige un identificador de sesión verificado y lo valida en el servidor. Excepciones: `buscar_cliente` y `verificar_identidad`.
6. **Correlación** (Art. 8): `conversation_id` es obligatorio en toda herramienta y se propaga a la auditoría del servidor.
7. **Errores**: nunca excepciones crudas. Se devuelve `{code, message, retryable}` con catálogo cerrado (`IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INVALID_INPUT`, `INTERNAL`, ...). `retryable=false` implica escalar (Art. 10).
8. **Mínima exposición**: devolver solo lo necesario y enmascarar PII (tarjeta `**** 1234`, documento parcial). Ante varias coincidencias de `buscar_cliente`, solo lo mínimo para desambiguar.
9. **Escrituras idempotentes**: `iniciar_disputa`, `bloquear_tarjeta` y `escalar_a_analista` aceptan `idempotency_key` y son seguras ante reintentos.
10. **Límites**: los listados (`consultar_transacciones`) exigen rango de fechas y tienen tope de resultados.
11. **Versionado** (§4.3.3): un cambio de esquema actualiza spec y test de contrato en el mismo cambio. Un cambio incompatible requiere nombre o versión nueva.
12. **stdio**: nada a `stdout` salvo el protocolo MCP; los logs van a `stderr` en JSON.
