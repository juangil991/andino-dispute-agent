# Plan: Bloquear una tarjeta de un cliente verificado por sospecha de fraude

| Campo | Valor |
|---|---|
| Feature | `005-card-block` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-17 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 |

---

## 1. Resumen técnico

Quinta feature de `core_banking_mcp` y segunda que escribe en el core. Añade la herramienta `bloquear_tarjeta` y el registro de bloqueos. Reutiliza el esqueleto, el sobre de errores, la auditoría, el reloj, el almacén de verificación, `mask_card` y `redact_card_numbers` de 001–004, y copia el patrón de `iniciar_disputa` (004). No toca `dispute_agent`.

- **Dominio puro** (stdlib), en `domain/models/card_block.py`:
  - `BlockReason`: enum de `FRAUD_SUSPECTED` y `LOST_OR_STOLEN` (RN-005-02).
  - `CardBlockRequest.create(conversation_id, card_id, reason, idempotency_key)`: aplica RN-005-08 y lanza `InvalidInputError`.
  - `OwnedCard(card_id, last4, status: CardStatus)`: tarjeta del cliente verificado con su estado.
  - `CardBlock`: bloqueo registrado; `same_request(card_id, reason)` aplica RN-005-07.
- **Caso de uso `BlockCard`**, en el orden de RN-005-09:
  1. Valida la entrada.
  2. Lee la verificación (`ConversationVerificationStore.get`).
  3. Busca un bloqueo por `(conversation_id, idempotency_key)`. Si existe con la misma tarjeta y el mismo motivo, devuelve ese bloqueo como repetición (`replayed`); si existe con otros datos, `InvalidInputError`.
  4. Busca la tarjeta del cliente verificado; si no está, `CardNotFoundError`.
  5. Según el estado de la tarjeta: `CANCELLED` → `CardNotBlockableError`; `BLOCKED` → devuelve el bloqueo registrado de la tarjeta, o `None`, con `already_blocked`; `ACTIVE` → bloquea.
  6. Audita.

  Cualquier excepción inesperada tras la validación se convierte en `CoreUnavailableError` (RN-005-13), como en 003 y 004.
- **Puerto nuevo `CardRepository`** (decisión del usuario), separado de `TransactionRepository`, con cuatro operaciones:
  - `find_customer_card(customer_id, card_id) -> OwnedCard | None`: filtra por el cliente verificado, así que una tarjeta ajena y una inexistente salen por la misma rama (RN-005-04).
  - `find_block_by_key(conversation_id, key) -> CardBlock | None`
  - `find_block_by_card(card_id) -> CardBlock | None`
  - `block(conversation_id, idempotency_key, card_id, reason, blocked_at) -> CardBlock`: atómico.
- **Tabla nueva `card_blocks`** (decisión del usuario), con el mismo patrón que `disputes`:
  - Guarda `conversation_id` e `idempotency_key`, con un índice único sobre ambos, y otro índice único sobre `card_id` (sin desbloqueo, una tarjeta tiene a lo sumo un bloqueo registrado).
  - `block` hace en un solo `commit` el `UPDATE cards SET status = 'BLOCKED' WHERE card_ref = ? AND status = 'ACTIVE'`, que debe afectar exactamente 1 fila, y el `INSERT` en `card_blocks`.
  - Ante cualquier excepción hace `rollback` y la relanza: la tarjeta queda como estaba (RN-005-13).
  - Si dos solicitudes compiten, el índice único o el `UPDATE` sin filas afectadas terminan en `INTERNAL` (Art. 10).
- **Instantes:** `blocked_at` es `clock.now()` (UTC). Se guarda en UTC sin zona, como `opened_at`, y la herramienta lo serializa en ISO 8601 con el offset de Bogotá; `null` si no hay bloqueo registrado (RN-005-06).
- **Herramienta delgada `bloquear_tarjeta`** en un módulo propio (`card_tools.py`):
  - Firma permisiva de 001–004 (`str | None` en todos los campos), para que toda violación salga como `INVALID_INPUT` auditado.
  - `ErrorCode` gana `CARD_NOT_BLOCKABLE`.
  - `masked_card` se calcula con `mask_card(last4)`.
- **Auditoría sin PAN por construcción:**
  - `AuditEvent` gana `card_id` y `block_reason`, opcionales y al final. `masked_card` e `idempotency_key` ya existen.
  - `card_id` e `idempotency_key` se registran solo si son válidos según RN-005-08 y siempre pasan por `redact_card_numbers`; `block_reason` solo si es un código del catálogo.
  - `masked_card` solo se registra cuando la tarjeta del cliente verificado ya se resolvió (RN-005-14).
  - La entrada no se serializa (`input=None`).

Decisiones triviales tomadas:

- **`NOT_FOUND` idéntico:** el mensaje es una constante del módulo de la herramienta y las dos situaciones pasan por la misma rama (`find_customer_card` devuelve `None`).
- **`CARD_NOT_BLOCKABLE`:** mensaje fijo, p. ej. `"Una tarjeta cancelada no se puede bloquear."`.
- **Enum en el esquema de entrada:** `reason` se declara `str | None` para validar en el dominio, pero su `Field` publica `json_schema_extra={"enum": ["FRAUD_SUSPECTED", "LOST_OR_STOLEN"]}` (spec §7: `string (enum)`).
- **Esquema de salida:** `BloquearTarjetaOut` con `extra="forbid"`; `status: Literal["BLOCKED"]`, `blocked_at: str | None`, `reason: Literal["FRAUD_SUSPECTED", "LOST_OR_STOLEN"] | None` y `already_blocked: bool`.
- **Resultado del caso de uso:** `BlockCardResult(card: OwnedCard, block: CardBlock | None, outcome: Literal["blocked", "replayed", "already_blocked"])`. La herramienta deriva `already_blocked = outcome == "already_blocked"` y responde siempre `status = "BLOCKED"`.
- **Repetición:** vuelve a leer la tarjeta con `find_customer_card` para obtener `last4`. Si la tarjeta pasó a `CANCELLED` después, la respuesta es igual la del bloqueo original (spec AC-005-11, última fila).
- **`MAX_ID_LENGTH`:** se reutiliza la constante de `domain/models/dispute.py` (64).
- **Regla y motivo auditados:**
  - Resultados: `blocked` → RN-005-06; `replayed` → RN-005-07; `already_blocked` → RN-005-05.
  - Errores: `INVALID_INPUT` → RN-005-08 (RN-005-07 si es por clave reutilizada); `IDENTITY_NOT_VERIFIED` → RN-005-03; `NOT_FOUND` → RN-005-04; `CARD_NOT_BLOCKABLE` → RN-005-05; `INTERNAL` → RN-005-13.
- **`customer_id` en la auditoría:** se registra el verificado cuando ya se conoce, como en 003 y 004.
- **Misma sesión y mismo almacén:** `server.py` pasa al nuevo caso de uso la misma `Session` y la misma instancia de `InMemoryConversationVerificationStore`.

## 2. Componentes por capa

Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/models/card_block.py` — `BlockReason`, `CardBlockRequest`, `OwnedCard`, `CardBlock` | Nuevo | Value objects inmutables. `CardBlockRequest.create(...)` aplica RN-005-08 (campos recortados; `reason` exacto y sensible a mayúsculas). `OwnedCard` y `CardBlock` con las invariantes de §4. |
| `core_banking_mcp` | `application` | `application/errors.py` | Modificado | Se añaden `CardNotFoundError` (RN-005-04) y `CardNotBlockableError` (RN-005-05). |
| `core_banking_mcp` | `application` | `application/ports/card_repository.py` — `CardRepository` | Nuevo | Las 4 operaciones de §1. `block` es atómico: cambia el estado y registra bloqueo y clave, o no hace nada. |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditEvent` | Modificado | Campos opcionales al final: `card_id` y `block_reason` (`str \| None = None`). Los eventos de 001–004 no cambian. |
| `core_banking_mcp` | `application` | `application/use_cases/block_card.py` — `BlockCard`, `BlockCardCommand`, `BlockCardResult` | Nuevo | Orquesta el orden de RN-005-09 con un único evento de auditoría por invocación (RN-005-14). No escribe en el almacén de verificación ni toca otras tarjetas, transacciones o disputas (RN-005-12). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Modificado | `ErrorCode` gana `CARD_NOT_BLOCKABLE`. Se añade `BloquearTarjetaOut` (`extra="forbid"`). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/card_tools.py` — `register_card_tools(mcp, block_card)` | Nuevo | Herramienta delgada `bloquear_tarjeta` con docstring en español (spec §7). Todos los errores salen con `retryable=false`; serializa `blocked_at` en Bogotá. Mapeo de errores: <ul><li>`InvalidInputError` → `INVALID_INPUT`</li><li>`IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED`</li><li>`CardNotFoundError` → `NOT_FOUND` (mensaje constante)</li><li>`CardNotBlockableError` → `CARD_NOT_BLOCKABLE`</li><li>`CoreUnavailableError` y el *catch-all* → `INTERNAL`</li></ul> |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/tables.py` | Modificado | Tabla nueva `CardBlockRow` (§4). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_card_repository.py` — `SqlAlchemyCardRepository` | Nuevo | Implementa el puerto. Mapea `card_ref` ↔ `card_id` de dominio y las filas a `OwnedCard` y `CardBlock` (`blocked_at` con `tzinfo=UTC`). `block` hace el `UPDATE` condicionado y el `INSERT` en un solo `commit`, y `rollback` ante cualquier excepción. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` | Modificado | Añade `card_id` y `block_reason` a `_OPTIONAL_KEYS` para omitirlos si son `None`; el JSON de 001–004 no cambia. |
| `core_banking_mcp` | arranque | `server.py` — `build_server` | Modificado | Crea `SqlAlchemyCardRepository` con la misma sesión, construye `BlockCard` con el **mismo** almacén de verificación y llama a `register_card_tools`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `CardRepository` | Nuevo | `SqlAlchemyCardRepository` | Fakes en `tests/fakes/`: uno en memoria y otro que falla en `block`. La pertenencia se comprueba con una consulta filtrada por el `customer_id` verificado, nunca con un dato de la solicitud. |
| `ConversationVerificationStore` | Sin cambios | `InMemoryConversationVerificationStore` | Solo `get(...)` (RN-002-13). |
| `AuditLogPort` (core) | Modificado | `JsonAuditLog` | `AuditEvent` gana campos opcionales; el puerto no cambia. |
| `Clock` | Sin cambios | `SystemClock` | `blocked_at` = `clock.now()`. |
| `TransactionRepository`, `DisputeRepository`, `CustomerRepository` | Sin cambios | — | — |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `BlockReason` | `FRAUD_SUSPECTED`, `LOST_OR_STOLEN` | Enum cerrado (RN-005-02). |
| `CardBlockRequest` | `conversation_id: str`, `card_id: str`, `reason: BlockReason`, `idempotency_key: str` | Se crea solo con `create(...)`: `conversation_id` no vacío tras recortar; `card_id` e `idempotency_key` de 1 a 64 caracteres tras recortar; `reason` igual a un valor del enum, sin normalizar mayúsculas. Cualquier campo ausente o inválido → `InvalidInputError(field, ...)`. Los valores se guardan recortados. |
| `OwnedCard` | `card_id: str`, `last4: str`, `status: CardStatus` | `card_id` no vacío; `last4` de 4 dígitos (`validate_last4`). Reutiliza `CardStatus` de `domain/models/customer.py`. |
| `CardBlock` | `card_id: str`, `conversation_id: str`, `idempotency_key: str`, `reason: BlockReason`, `blocked_at: datetime` | Textos no vacíos; `blocked_at` con zona horaria. `same_request(card_id, reason) -> bool` (RN-005-07). |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `card_blocks` | `block_id` (`Integer`, PK autoincremental, interno), `card_id` (FK → `cards.card_id`), `conversation_id` (`String`), `idempotency_key` (`String`), `reason` (`String`), `blocked_at` (`DateTime`, UTC sin zona) | Tabla nueva. Índice único `ux_card_blocks_conversation_key` sobre `(conversation_id, idempotency_key)` y único `ux_card_blocks_card` sobre `card_id`. |
| `cards` | `status` | Sin cambio de esquema; `block` actualiza `status` de `ACTIVE` a `BLOCKED`. |

### Semillas

No hay semillas nuevas. Las tarjetas ficticias de 001–004 ya cubren los casos para la demo y el smoke (Art. 1); los tests usan builders (§5.3.7):

- `CARD-0001` (Laura, `4321`, `ACTIVE`): bloqueo nuevo.
- `CARD-0002` (Laura, `8765`, `BLOCKED` sin bloqueo registrado): `already_blocked = true` con `blocked_at = null`.
- `CARD-0004` (Marta, `5555`, `CANCELLED`): `CARD_NOT_BLOCKABLE`.

Al arrancar sobre una base existente, `create_all` crea la tabla `card_blocks` vacía.

## 5. Dependencias nuevas

Ninguna. `enum`, `dataclasses` y `datetime` son de la biblioteca estándar; SQLAlchemy, Pydantic y `mcp` ya están en el stack.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes y builders nuevos en `tests/fakes/`:

- `OwnedCardBuilder` y `CardBlockBuilder`: valores por defecto válidos; estado, tarjeta, conversación, clave, motivo y fecha configurables.
- `FakeCardRepository`: tarjetas por cliente y bloqueos en memoria, con la misma unicidad que el puerto exige; `block` cambia el estado de la tarjeta.
- `FailingCardRepository`: falla en `block` con una excepción que no es de dominio, sin cambiar nada. Se puede "reparar" para AC-005-14.
- Se reutilizan `FakeVerificationStore`, `FakeAuditLog` y `FixedClock`.

Los tests de herramienta usan una sesión MCP en memoria contra el servidor real con SQLite `:memory:`, como en 001–004. La verificación se prepara con `verificar_identidad` o con el almacén del servidor, y las tarjetas se crean con el repositorio de clientes.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-005-01 | `BlockCard` con fakes: resultado `blocked` con `blocked_at` = reloj y `reason`; el fake deja la tarjeta `BLOCKED` con 1 bloqueo; el almacén no cambia | `bloquear_tarjeta` vía sesión MCP con SQLite: los 6 campos de la spec, con `blocked_at = "2026-10-17T10:00:00-05:00"`, `masked_card = "**** 4321"` y `already_blocked = false`; `cards.status = 'BLOCKED'` y 1 fila en `card_blocks` | La salida cumple `BloquearTarjetaOut` | — |
| AC-005-02 | `CardBlockRequest.create` acepta los 2 códigos (parametrizado) | La herramienta bloquea con cada código y devuelve el mismo `reason` (2 filas) | `reason` de salida es un enum de los 2 códigos o `null` | — |
| AC-005-03 | `CardBlockRequest.create` rechaza `"STOLEN"`, minúsculas, texto en español, `""` y `None` → `InvalidInputError`; el caso de uso no toca el repositorio | La herramienta devuelve `INVALID_INPUT` con `retryable=false`; la tarjeta sigue `ACTIVE` y no hay filas en `card_blocks` (5 filas) | El esquema de entrada publica el `enum` de `reason` | — |
| AC-005-04 | El caso de uso con la tarjeta en las 4 situaciones (parametrizado): `blocked`; `already_blocked` con el bloqueo original; `already_blocked` con `block = None`; `CardNotBlockableError`. En las tres últimas no se llama a `block` | La herramienta con las 4 filas. La de `LOST_OR_STOLEN` se prepara con una primera llamada en otra conversación y con el reloj del 15 de octubre; la de semilla, insertando la tarjeta `BLOCKED` sin fila en `card_blocks`. Se comprueba el nº de filas de `card_blocks` y el estado final | El catálogo de códigos incluye `CARD_NOT_BLOCKABLE`; `blocked_at` y `reason` admiten `null` | — |
| AC-005-05 | Dos ejecuciones con la misma clave, tarjeta y motivo, con el reloj una hora después: mismo `CardBlock`, `outcome = "replayed"` y 1 solo bloqueo | La herramienta: las dos respuestas son idénticas (`already_blocked = false` y el mismo `blocked_at`) y hay 1 fila en `card_blocks` | — | — |
| AC-005-06 | La misma clave con otra tarjeta y con otro motivo → `InvalidInputError` sin llamar a `block` (2 filas) | La herramienta con las 2 filas: `INVALID_INPUT`; `CARD-L2` sigue `ACTIVE` y no hay filas adicionales | — | — |
| AC-005-07 | Con `K-1` usada en `A`, una solicitud en `B`, verificada para el mismo cliente → `already_blocked` con el bloqueo de `A` | La herramienta en `A` y `B`, verificadas con `verificar_identidad`: `B` recibe `already_blocked = true` con el `blocked_at` de `A`; hay 1 fila | — | — |
| AC-005-08 | `find_customer_card` del fake devuelve `None` para la tarjeta ajena y para la inexistente → `CardNotFoundError` en ambos casos | La herramienta con `CARD-P1` (de Pedro) y con `CARD-9999`: los dos sobres son iguales campo a campo y no tienen datos de Pedro; su tarjeta sigue `ACTIVE`. El repositorio SQL no devuelve tarjetas de otro cliente | El catálogo de códigos incluye `NOT_FOUND` | — |
| AC-005-09 | El caso de uso con el almacén en las 4 situaciones → `IdentityNotVerifiedError`, sin llamar al repositorio; el almacén no cambia | La herramienta en las 4 situaciones (incluida `B` con `A` verificada vía `verificar_identidad`) → `IDENTITY_NOT_VERIFIED` con `retryable=false`; la tarjeta sigue `ACTIVE` y el almacén igual | — | — |
| AC-005-10 | `CardBlockRequest.create` parametrizado con las 7 filas, incluidos los bordes de 64 y 65 caracteres | La herramienta devuelve `INVALID_INPUT` con `retryable=false` en cada fila, sin cambios en `cards` ni en `card_blocks` | El sobre de error cumple `ToolErrorOut` | — |
| AC-005-11 | El caso de uso parametrizado con las 5 filas: el primer resultado según RN-005-09 | La herramienta con las 5 filas; en la última, la tarjeta se cancela directamente en la base tras el primer bloqueo | — | — |
| AC-005-12 | El fake con `CARD-L1` y `CARD-L2`: tras bloquear `CARD-L1`, `CARD-L2` sigue `ACTIVE` | `SqlAlchemyCardRepository.block` solo cambia la fila de `CARD-L1`; la herramienta deja `CARD-L2` `ACTIVE` y sin bloqueo | — | — |
| AC-005-13 | — | La respuesta serializada solo tiene los 6 campos de RN-005-10, con `masked_card = "**** 4321"`, y no contiene `4111111111114321`, `D-1001` ni `Laura Méndez` | `BloquearTarjetaOut` tiene `additionalProperties: false` y exactamente los campos de la spec §7 | — |
| AC-005-14 | `FailingCardRepository` → `CoreUnavailableError` auditado como `INTERNAL`; la tarjeta sigue `ACTIVE` y sin bloqueo. Tras repararlo, la misma solicitud con `K-1` da `blocked` | `SqlAlchemyCardRepository.block` hace `rollback` ante un fallo forzado (p. ej. índice único violado): `cards.status` no cambia y la sesión sigue usable. La herramienta con un repositorio que falla devuelve `INTERNAL` con `retryable=false`, sin el texto de la excepción, trazas ni SQL | El sobre cumple `ToolErrorOut` | — |
| AC-005-15 | `FakeAuditLog` + `FixedClock`: exactamente un evento en cada uno de los 10 casos (parametrizado), con `conversation_id`, timestamp, `tool`, `card_id`, `block_reason`, `idempotency_key`, `masked_card` y resultado. `block_reason` vacío con `"STOLEN"`; `[REDACTED]` con el PAN en `card_id` y en `idempotency_key`; `masked_card` vacío en `NOT_FOUND` y sin verificación. Ni el evento ni su JSON contienen `4111111111114321` ni `D-1001` | `JsonAuditLog` escribe `card_id` y `block_reason` y omite los vacíos; los eventos de 001–004 no cambian de claves; nada en `stdout` | — | — |

Adicionales (`mcp-testing.md` §7, §2):

- **Snapshot del catálogo:** `test_tool_catalog.py` pasa a esperar también `bloquear_tarjeta`, compara sus esquemas de entrada y salida con la spec §7 y falla ante herramientas no declaradas.
- **Art. 7 (§5.3.5):** la llamada sin identificación previa la cubre AC-005-09. También se prueba que la herramienta nunca escribe en el almacén (RN-005-12).
- **Escalamiento (§5.3.4):** el caso de la spec §8 (`INTERNAL` con `retryable = false`) lo cubre AC-005-14.
- **Smoke por stdio:** se amplía el test existente: `list_tools` muestra las cinco herramientas. Tras `verificar_identidad` con `C-0001`, `bloquear_tarjeta` sobre `CARD-0001` devuelve `BLOCKED` con `already_blocked = false`, y sobre `CARD-0002` devuelve `already_blocked = true`. La salida por `stdout` es solo protocolo.
- **`server.mcp`:** el test existente pasa a esperar las cinco herramientas.
- **Regresión de 001–004:** `ErrorCode` y `AuditEvent` se amplían. Las suites existentes deben seguir en verde sin cambios de comportamiento.
- El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global. En la verificación final, además, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Un fallo entre el `UPDATE` de `cards` y el `INSERT` en `card_blocks` deja la tarjeta bloqueada sin registro, o con la sesión compartida en estado inválido (`PendingRollbackError`) | Alto | Ambas sentencias van en un solo `commit`; `block` hace `rollback` ante cualquier excepción antes de relanzarla. Un test de integración fuerza un `IntegrityError` y comprueba que `cards.status` no cambió y que la siguiente operación funciona. |
| La herramienta comprueba la verificación contra un almacén distinto del de `verificar_identidad` | Alto | `server.py` crea una sola instancia y la comparte. El smoke por stdio y los tests de herramienta verifican primero con `verificar_identidad` y luego bloquean en el mismo servidor. |
| Se bloquea una tarjeta de otro cliente | Alto | `find_customer_card` filtra por el `customer_id` del almacén, y `block` solo se invoca con el `card_id` ya resuelto para ese cliente. AC-005-08 lo prueba en el fake y en SQLite con dos clientes. |
| Dos solicitudes simultáneas sobre la misma tarjeta | Medio | El `UPDATE ... WHERE status = 'ACTIVE'` exige 1 fila afectada y `ux_card_blocks_card` impide un segundo registro; el choque sale como `INTERNAL` (Art. 10). Hay un test de integración del índice y del `UPDATE` sin filas. |
| Un PAN escrito en un campo de texto libre llega a la auditoría | Medio | `redact_card_numbers` se aplica siempre a `card_id` e `idempotency_key` antes de crear el evento; AC-005-15 lo prueba en el evento y en el JSON. |
| Una base SQLite local de 001–004 ya tiene bloqueos de prueba o tarjetas modificadas | Bajo | `create_all` crea la tabla vacía. Para volver al estado de las semillas, borrar `data/core_banking.db` (ignorado por git), como en 003 y 004. |
| Ampliar `ErrorCode` y `AuditEvent` cambia esquemas usados por 001–004 | Bajo | Son cambios compatibles (catálogo ampliado y campos opcionales al final). Los tests de contrato del sobre se actualizan en el mismo cambio; `server.py`, `schemas.py` y `tests/fakes/*` se tratan como archivos compartidos al calcular las oleadas. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | No hay semillas nuevas; se reutilizan las tarjetas ficticias de 001 y los tests usan builders. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento; los 15 AC están trazados en §6. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); el dominio puro, el caso de uso y los fakes permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio usa solo stdlib; SQLAlchemy y Pydantic se quedan en infraestructura y se mapean en los adaptadores; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La herramienta solo ejecuta el bloqueo; no decide si hay fraude ni toca `DisputePolicy` (spec §5). |
| Art. 6 — Acciones vía MCP | Cumple | Las tarjetas solo se bloquean mediante la herramienta MCP `bloquear_tarjeta`. |
| Art. 7 — Identificación antes que información | Cumple | El caso de uso consulta el almacén de 002 antes de tocar datos y resuelve la tarjeta con el `customer_id` verificado (AC-005-08, AC-005-09). La respuesta solo muestra la tarjeta enmascarada (AC-005-13). |
| Art. 8 — Auditoría | Cumple | Cada invocación genera un único registro con `conversation_id`, marca de tiempo del reloj inyectado, herramienta, tarjeta, motivo, clave, tarjeta enmascarada, resultado, regla y motivo de auditoría, sin PAN ni documento (AC-005-15). |
| Art. 9 — Secretos | Cumple | No hay secretos ni configuración nueva. |
| Art. 10 — Ante la duda, escalar | Cumple | Una falla inesperada, incluida una colisión del índice único o un `UPDATE` sin filas, devuelve `INTERNAL` con `retryable = false` sin cambiar la tarjeta (AC-005-14); el escalamiento lo ejecutará el consumidor (spec §8). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
