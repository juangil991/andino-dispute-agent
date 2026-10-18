# Plan: Derivar un caso a un analista humano con un resumen estructurado

| Campo | Valor |
|---|---|
| Feature | `006-analyst-escalation` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-17 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 |

---

## 1. Resumen técnico

Sexta feature de `core_banking_mcp` y tercera que escribe en el core. Añade la herramienta `escalar_a_analista` y el registro de derivaciones. Reutiliza de 001–005 el esqueleto, el sobre de errores, la auditoría, el reloj, el almacén de verificación, `mask_card` y `redact_card_numbers`, y copia el patrón de `iniciar_disputa` y `bloquear_tarjeta`. No toca `dispute_agent`.

- **Dominio puro** (stdlib), en `domain/models/escalation.py`:
  - `EscalationReason`: enum de los 7 códigos de RN-006-02.
  - `PriorAction`: enum de `DISPUTE_OPENED` y `CARD_BLOCKED` (RN-006-05).
  - `EscalationStatus`: enum con `PENDING`.
  - `EscalationRequest.create(conversation_id, reason, idempotency_key, transaction_id, card_id, prior_actions, dispute_id, note)`: aplica RN-006-10, la coherencia de RN-006-05 y la normalización de la nota de RN-006-07 (recorte, vacía → `None`, máximo 300 caracteres, `redact_card_numbers`). Lanza `InvalidInputError`. Expone `has_customer_data` (RN-006-03).
  - `Escalation`: derivación registrada, con todos los datos de la solicitud, `customer_id`, `identity_verified`, `status` y `escalated_at`. `same_request(request)` compara `reason`, `transaction_id`, `card_id`, `prior_actions` (como conjunto), `dispute_id` y `note` ya normalizados (RN-006-09).
- **Caso de uso `EscalateToAnalyst`**, en el orden de RN-006-11:
  1. Valida la entrada.
  2. Lee la verificación (`ConversationVerificationStore.get`). Si la solicitud trae datos del cliente y la conversación no está verificada, lanza `IdentityNotVerifiedError`. Sin datos del cliente sigue adelante en cualquier caso y anota `identity_verified` y `customer_id` (o `None`).
  3. Busca una derivación por `(conversation_id, idempotency_key)`:
     - Con la misma solicitud, la devuelve como repetición (`replayed`) y rehidrata la transacción y la tarjeta con el `customer_id` guardado.
     - Con otros datos, lanza `InvalidInputError`.
  4. Resuelve los datos del cliente; si alguno falla, lanza `EscalationDataNotFoundError`:
     - la transacción, con `TransactionRepository.find_customer_transaction`;
     - la tarjeta, con `CardRepository.find_customer_card`;
     - si se indicaron ambas, `transaction.card_id` debe ser igual a `card.card_id`.
  5. Contrasta las acciones previas con el core; si alguna no se cumple, lanza `EscalationDataNotFoundError`:
     - `DISPUTE_OPENED`: `DisputeRepository.find_by_id` debe devolver una disputa de `transaction_id`;
     - `CARD_BLOCKED`: la tarjeta resuelta debe estar `BLOCKED`.
  6. Registra la derivación con `EscalationRepository.add`, que es atómico.
  7. Audita una sola vez.

  Cualquier excepción inesperada tras la validación se convierte en `CoreUnavailableError` (RN-006-15), como en 003–005.
- **Puertos (decisión del usuario):**
  - Nuevo `EscalationRepository`, con `find_by_key(conversation_id, key)` y `add(...)`.
  - Se reutilizan `TransactionRepository.find_customer_transaction` y `CardRepository.find_customer_card`, que ya filtran por el cliente verificado.
  - `DisputeRepository` gana `find_by_id(dispute_id)`.
  - Las consultas de pertenencia se hacen siempre con el `customer_id` del almacén, nunca con un dato de la solicitud.
- **Tabla nueva `escalations` con columnas normalizadas** (decisión del usuario):
  - Guarda los identificadores, no una instantánea JSON.
  - Una repetición rehidrata `transaction` y `card` desde el core, como en 004 y 005.
  - `prior_actions` se guarda como texto canónico: códigos en el orden del catálogo, separados por comas, vacío si no hay.
  - Un índice único sobre `(conversation_id, idempotency_key)`.
  - `add` hace un único `INSERT` + `commit`; ante cualquier excepción hace `rollback` y la relanza, de modo que no queda nada registrado (RN-006-15).
- **Instantes:** `escalated_at` es `clock.now()` (UTC). Se guarda en UTC sin zona y la herramienta lo serializa en ISO 8601 con el offset de Bogotá, como `opened_at` y `blocked_at`.
- **Herramienta delgada `escalar_a_analista`** en un módulo propio (`escalation_tools.py`):
  - Firma permisiva: `str | None` en los textos y `list[str] | None` en `prior_actions`, para que toda violación salga como `INVALID_INPUT` auditado.
  - `ErrorCode` no cambia: los 4 códigos de la spec ya existen.
  - `summary.transaction` se construye con `to_transaction_item` de `transaction_tools.py`.
  - `summary.card` se construye con `mask_card(last4)`.
- **Auditoría sin PAN por construcción:**
  - `AuditEvent` gana, opcionales y al final: `escalation_reason`, `escalation_id`, `prior_actions: tuple[str, ...] = ()`, `note` e `identity_verified: bool | None`.
  - `transaction_id`, `card_id`, `dispute_id`, `idempotency_key` y `masked_card` ya existen.
  - Cada texto libre se registra solo si es válido según RN-006-10 y siempre pasa por `redact_card_numbers`.
  - `escalation_reason` solo se registra si es un código del catálogo; `prior_actions`, solo los códigos válidos y sin repetir.
  - `masked_card` solo se registra cuando la tarjeta del cliente verificado ya se resolvió (RN-006-16).
  - La entrada no se serializa (`input=None`).

Decisiones triviales tomadas:

- **`NOT_FOUND` idéntico:** una sola excepción, `EscalationDataNotFoundError`, para transacción, tarjeta, disputa, incoherencia transacción–tarjeta y acción previa no reflejada. El mensaje es una constante del módulo de la herramienta, p. ej. `"No se encontraron los datos indicados para este cliente."` (RN-006-04, RN-006-06).
- **Orden de `prior_actions` en la salida:** siempre el del catálogo (`DISPUTE_OPENED`, `CARD_BLOCKED`), sea cual sea el orden recibido. Así una repetición con el mismo conjunto en otro orden devuelve una respuesta idéntica (AC-006-13). La comparación de RN-006-09 usa `frozenset`.
- **`escalation_id`:** `ESC-NNNNNN` a partir del recuento de filas, como `DSP-NNNNNN` en 004; no deriva de ningún PAN.
- **Enum en el esquema de entrada:** `reason` publica `json_schema_extra={"enum": [...]}` con los 7 códigos. Los elementos de `prior_actions` publican `{"items": {"enum": ["DISPUTE_OPENED", "CARD_BLOCKED"]}}`.
- **Tipos fuera de esquema:** un `prior_actions` que no sea lista, o con elementos que no sean texto, lo rechaza la validación de argumentos de FastMCP antes del caso de uso, igual que un número en un campo `str` de 001–005. Esos casos no llegan a auditarse.
- **Esquemas de salida:** `EscalarAnalistaOut`, `EscalationSummaryOut` y `EscalationCardOut`, todos con `extra="forbid"`. Además: `status: Literal["PENDING"]`, `reason` como `Literal` de los 7 códigos y `prior_actions: list[Literal["DISPUTE_OPENED", "CARD_BLOCKED"]]`.
- **Resultado del caso de uso:** `EscalationResult(escalation: Escalation, transaction: Transaction | None, card: OwnedCard | None, outcome: Literal["escalated", "replayed"])`.
- **Repetición con rehidratación:** si al rehidratar no se encuentra una transacción o tarjeta guardada (no debería ocurrir, porque el core no borra), se trata como falla inesperada → `INTERNAL` (Art. 10).
- **`MAX_ID_LENGTH`:** se reutiliza la constante de `domain/models/dispute.py` (64). `MAX_NOTE_LENGTH = 300` va en `escalation.py`.
- **Regla y motivo auditados:**
  - Resultados: `escalated` → RN-006-08; `replayed` → RN-006-09.
  - Errores: `INVALID_INPUT` → RN-006-10 (RN-006-05 si es por incoherencia de acciones previas, RN-006-09 si es por clave reutilizada); `IDENTITY_NOT_VERIFIED` → RN-006-03; `NOT_FOUND` → RN-006-04 o RN-006-06; `INTERNAL` → RN-006-15.
- **`customer_id` en la auditoría:** se registra el verificado cuando ya se conoce, como en 003–005.
- **Misma sesión y mismo almacén:** `server.py` pasa al nuevo caso de uso la misma `Session` y la misma instancia de `InMemoryConversationVerificationStore`.

## 2. Componentes por capa

Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/models/escalation.py` — `EscalationReason`, `PriorAction`, `EscalationStatus`, `EscalationRequest`, `Escalation` | Nuevo | Value objects inmutables. `EscalationRequest.create(...)` aplica RN-006-05, RN-006-07 y RN-006-10 (campos recortados; `reason` y `prior_actions` exactos y sensibles a mayúsculas). `Escalation.same_request(...)` aplica RN-006-09. |
| `core_banking_mcp` | `application` | `application/errors.py` | Modificado | Se añade `EscalationDataNotFoundError` (RN-006-04, RN-006-06). |
| `core_banking_mcp` | `application` | `application/ports/escalation_repository.py` — `EscalationRepository` | Nuevo | `find_by_key(conversation_id, idempotency_key) -> Escalation \| None` y `add(...) -> Escalation`, atómico. |
| `core_banking_mcp` | `application` | `application/ports/dispute_repository.py` — `DisputeRepository` | Modificado | Nueva operación `find_by_id(dispute_id) -> Dispute \| None`. |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditEvent` | Modificado | Campos opcionales al final: `escalation_reason`, `escalation_id`, `note` (`str \| None = None`), `prior_actions` (`tuple[str, ...] = ()`) e `identity_verified` (`bool \| None = None`). Los eventos de 001–005 no cambian. |
| `core_banking_mcp` | `application` | `application/use_cases/escalate_to_analyst.py` — `EscalateToAnalyst`, `EscalateCommand`, `EscalationResult` | Nuevo | Orquesta el orden de RN-006-11 con un único evento de auditoría por invocación (RN-006-16). No escribe en el almacén de verificación ni en transacciones, tarjetas o disputas (RN-006-14). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Modificado | Se añaden `EscalarAnalistaOut`, `EscalationSummaryOut` y `EscalationCardOut` (`extra="forbid"`). `ErrorCode` no cambia. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/escalation_tools.py` — `register_escalation_tools(mcp, escalate)` | Nuevo | Herramienta delgada `escalar_a_analista` con docstring en español (spec §7). Todos los errores salen con `retryable=false`; serializa `escalated_at` en Bogotá. Mapeo de errores: <ul><li>`InvalidInputError` → `INVALID_INPUT`</li><li>`IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED`</li><li>`EscalationDataNotFoundError` → `NOT_FOUND` (mensaje constante)</li><li>`CoreUnavailableError` y el *catch-all* → `INTERNAL`</li></ul> |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/tables.py` | Modificado | Tabla nueva `EscalationRow` (§4). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_escalation_repository.py` — `SqlAlchemyEscalationRepository` | Nuevo | Implementa el puerto. Mapea `card_ref` ↔ `card_id` de dominio, `prior_actions` ↔ texto canónico y `escalated_at` con `tzinfo=UTC`. `add` hace `INSERT` + `commit`, y `rollback` ante cualquier excepción. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_dispute_repository.py` | Modificado | Implementa `find_by_id`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` | Modificado | Añade `escalation_reason`, `escalation_id`, `prior_actions`, `note` e `identity_verified` a `_OPTIONAL_KEYS` (se omiten si son `None` o `[]`; `false` se conserva). El JSON de 001–005 no cambia. |
| `core_banking_mcp` | arranque | `server.py` — `build_server` | Modificado | Crea `SqlAlchemyEscalationRepository` con la misma sesión. Construye `EscalateToAnalyst` con los repositorios de transacciones, tarjetas, disputas y derivaciones, y con el **mismo** almacén de verificación. Llama a `register_escalation_tools`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `EscalationRepository` | Nuevo | `SqlAlchemyEscalationRepository` | Fakes en `tests/fakes/`: uno en memoria y otro que falla en `add`. |
| `DisputeRepository` | Modificado | `SqlAlchemyDisputeRepository` | `find_by_id`. `FakeDisputeRepository` y `FailingDisputeRepository` la implementan para seguir cumpliendo el `Protocol` (mypy estricto). |
| `TransactionRepository` | Sin cambios | `SqlAlchemyTransactionRepository` | Se reutiliza `find_customer_transaction` (RN-006-04). |
| `CardRepository` | Sin cambios | `SqlAlchemyCardRepository` | Se reutiliza `find_customer_card`, que devuelve el estado de la tarjeta (RN-006-06). |
| `ConversationVerificationStore` | Sin cambios | `InMemoryConversationVerificationStore` | Solo `get(...)` (RN-002-13). |
| `AuditLogPort` (core) | Modificado | `JsonAuditLog` | `AuditEvent` gana campos opcionales; el puerto no cambia. |
| `Clock` | Sin cambios | `SystemClock` | `escalated_at` = `clock.now()`. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `EscalationReason` | Los 7 códigos de RN-006-02 | Enum cerrado. |
| `PriorAction` | `DISPUTE_OPENED`, `CARD_BLOCKED` | Enum cerrado; el orden de declaración es el orden canónico de salida. |
| `EscalationStatus` | `PENDING` | Única transición en esta versión: ninguna. |
| `EscalationRequest` | `conversation_id: str`, `reason: EscalationReason`, `idempotency_key: str`, `transaction_id: str \| None`, `card_id: str \| None`, `prior_actions: frozenset[PriorAction]`, `dispute_id: str \| None`, `note: str \| None` | Se crea solo con `create(...)`: <ul><li>`conversation_id` no vacío tras recortar.</li><li>`idempotency_key` de 1 a 64 caracteres tras recortar.</li><li>Ids opcionales: `None` o de 1 a 64 caracteres tras recortar.</li><li>`prior_actions`: códigos del enum, sin repetir. `DISPUTE_OPENED` exige `dispute_id` y `transaction_id`; `dispute_id` exige `DISPUTE_OPENED`; `CARD_BLOCKED` exige `card_id`.</li><li>`note`: recortada; vacía → `None`; máximo 300; con `redact_card_numbers` aplicado.</li></ul> Cualquier violación → `InvalidInputError(field, ...)`. `has_customer_data` es verdadero si hay `transaction_id`, `card_id` o `dispute_id`. |
| `Escalation` | `escalation_id`, `conversation_id`, `idempotency_key`, `reason`, `status`, `escalated_at: datetime`, `identity_verified: bool`, `customer_id: str \| None`, `transaction_id`, `card_id`, `prior_actions: frozenset[PriorAction]`, `dispute_id`, `note` | Textos obligatorios no vacíos; `escalated_at` con zona horaria. Si `identity_verified` es falso, `customer_id`, `transaction_id`, `card_id` y `dispute_id` son `None` y `prior_actions` está vacío (RN-006-08). `same_request(request) -> bool` (RN-006-09). `ordered_prior_actions()` las devuelve en orden de catálogo. |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `escalations` | <ul><li>`escalation_id` (`String`, PK, `ESC-NNNNNN`)</li><li>`conversation_id`, `idempotency_key`, `reason`, `status` (`String`)</li><li>`escalated_at` (`DateTime`, UTC sin zona)</li><li>`identity_verified` (`Boolean`)</li><li>`customer_id` (`String`, nulo, FK → `customers.customer_id`)</li><li>`transaction_id` (`String`, nulo, FK → `transactions.transaction_id`)</li><li>`card_id` (`Integer`, nulo, FK → `cards.card_id`)</li><li>`dispute_id` (`String`, nulo, FK → `disputes.dispute_id`)</li><li>`prior_actions` (`String`, texto canónico, `""` si no hay)</li><li>`note` (`String`, nulo, ya redactada)</li></ul> | Tabla nueva. Índice único `ux_escalations_conversation_key` sobre `(conversation_id, idempotency_key)`. |

### Semillas

No hay semillas nuevas. Las derivaciones nacen vacías y los datos ficticios de 001–005 cubren la demo y el smoke (Art. 1). Los tests usan builders (§5.3.7). Al arrancar sobre una base existente, `create_all` crea la tabla `escalations` vacía.

## 5. Dependencias nuevas

Ninguna. `enum`, `dataclasses` y `datetime` son de la biblioteca estándar; SQLAlchemy, Pydantic y `mcp` ya están en el stack.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes y builders nuevos en `tests/fakes/`:

- `EscalationBuilder`: valores por defecto válidos; motivo, conversación, clave, datos, verificación y fecha configurables.
- `FakeEscalationRepository`: derivaciones en memoria con la misma unicidad que el puerto exige y `ESC-NNNNNN` secuencial.
- `FailingEscalationRepository`: falla en `add` con una excepción que no es de dominio, sin registrar nada. Se puede "reparar" para AC-006-19.
- `FakeDisputeRepository` y `FailingDisputeRepository` ganan `find_by_id`.
- Se reutilizan `FakeTransactionRepository`, `FakeCardRepository`, `FakeVerificationStore`, `FakeAuditLog`, `FixedClock` y los builders de 003–005.

Los tests de herramienta usan una sesión MCP en memoria contra el servidor real con SQLite `:memory:`, como en 001–005. La verificación se prepara con `verificar_identidad` o con el almacén del servidor. Las disputas y los bloqueos previos se crean con `iniciar_disputa` y `bloquear_tarjeta`, o con los repositorios.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-006-01 | `EscalateToAnalyst` con fakes: `escalated` con `escalated_at` = reloj, `customer_id = "C-0001"`, `identity_verified = true`, transacción y tarjeta resueltas; 1 derivación en el fake; el almacén y los demás fakes no cambian | `escalar_a_analista` vía sesión MCP con SQLite: todos los campos de la spec, con `escalated_at = "2026-10-17T10:00:00-05:00"`, `summary.transaction` completo y `summary.card.masked_card = "**** 4321"`. Hay 1 fila en `escalations`; `TX-L1` sigue `CONFIRMED` y sin disputas; `CARD-L1` sigue `ACTIVE` | La salida cumple `EscalarAnalistaOut` | — |
| AC-006-02 | `EscalationRequest.create` acepta los 7 códigos (parametrizado) | La herramienta registra una derivación con cada código y devuelve el mismo `reason` (7 filas) | `reason` de salida es un enum de los 7 códigos | — |
| AC-006-03 | `EscalationRequest.create` rechaza `"FRAUD"`, minúsculas, texto en español, `""` y `None` → `InvalidInputError`; el caso de uso no toca los repositorios | La herramienta devuelve `INVALID_INPUT` con `retryable=false` y no hay filas en `escalations` (5 filas) | El esquema de entrada publica el `enum` de `reason` | — |
| AC-006-04 | El caso de uso con el almacén en las 3 situaciones y sin datos del cliente: `escalated` con `identity_verified = false` y `customer_id = None`; no consulta transacciones, tarjetas ni disputas; el almacén no cambia | La herramienta en las 3 situaciones. La conversación agotada se prepara con 3 `verificar_identidad` fallidos y la desconocida, con un `buscar_cliente` sin coincidencias. Resumen limitado con todos los campos nulos y `prior_actions = []`; 1 fila con `identity_verified = 0` | `summary` admite `null` en `customer_id`, `transaction`, `card`, `dispute_id` y `note` | — |
| AC-006-05 | El caso de uso con datos del cliente en las 6 situaciones → `IdentityNotVerifiedError`, sin consultar los repositorios; el almacén no cambia | La herramienta en las 6 filas (incluida `B` con `A` verificada vía `verificar_identidad`) → `IDENTITY_NOT_VERIFIED` con `retryable=false`; ninguna fila en `escalations` | — | — |
| AC-006-06 | El caso de uso con las 4 filas (parametrizado): `prior_actions` y `dispute_id` del resultado; `ordered_prior_actions()` en orden de catálogo | La herramienta con las 4 filas: la disputa `D-1` se crea con `iniciar_disputa` y el bloqueo con `bloquear_tarjeta` en la misma conversación. Se comprueban `summary.prior_actions`, `dispute_id` y `card` | `prior_actions` de salida es una lista de los 2 códigos | — |
| AC-006-07 | `EscalationRequest.create` parametrizado con las 7 filas → `InvalidInputError` | La herramienta devuelve `INVALID_INPUT` con `retryable=false` en cada fila; ninguna fila en `escalations` | El esquema de entrada publica el `enum` de los elementos de `prior_actions` | — |
| AC-006-08 | El caso de uso con las 4 filas → `EscalationDataNotFoundError` sin llamar a `add` | La herramienta con las 4 filas → `NOT_FOUND`; sobre idéntico campo a campo al de AC-006-12 y sin datos de `C-0002`. `SqlAlchemyDisputeRepository.find_by_id` devuelve la disputa con su `transaction_id`, o `None` | — | — |
| AC-006-09 | `EscalationRequest.create` con las 6 notas, incluidos los bordes de 300 y 301 caracteres tras recortar y la vacía → `None` | La herramienta con las 6 filas: `summary.note` y la columna `note` | `note` de entrada y de salida admite `null` | — |
| AC-006-10 | `EscalationRequest.create` redacta el PAN de la nota | La respuesta y la fila de `escalations` tienen `"... [REDACTED] ..."` y no contienen `4111111111114321` | — | — |
| AC-006-11 | Con la nota "de instrucción", el caso de uso solo llama a `EscalationRepository.add`: ningún otro método de escritura de los fakes se invoca | Tras la herramienta, `D-1` sigue `OPEN`, `TX-L1` sigue `CONFIRMED` y `CARD-L1` sigue `ACTIVE`; no hay filas nuevas en `disputes` ni en `card_blocks`; `summary.note` es el texto sin cambios | — | — |
| AC-006-12 | `find_customer_transaction` y `find_customer_card` de los fakes devuelven `None` para lo ajeno y lo inexistente; la transacción de otra tarjeta del cliente da la incoherencia → `EscalationDataNotFoundError` en las 5 filas | La herramienta con las 5 filas: los sobres son iguales entre sí campo a campo y no tienen datos de Pedro; ninguna fila en `escalations` | El catálogo de códigos incluye `NOT_FOUND` | — |
| AC-006-13 | Dos ejecuciones con la misma solicitud, con el reloj una hora después: misma `Escalation`, `outcome = "replayed"` y 1 sola derivación (3 filas, incluidas la no verificada y el mismo conjunto en otro orden) | La herramienta con las 3 filas: las dos respuestas son idénticas y hay 1 fila en `escalations` | — | — |
| AC-006-14 | La misma clave con cada uno de los 5 cambios → `InvalidInputError` sin llamar a `add` | La herramienta con las 5 filas: `INVALID_INPUT` y ninguna fila adicional | — | — |
| AC-006-15 | Dos claves en `A`, y `K-1` en `A` y en `B`: 2 derivaciones con ids distintos | La herramienta con las 2 filas: 2 filas en `escalations` y la primera sin cambios | — | — |
| AC-006-16 | `EscalationRequest.create` parametrizado con las 9 filas, incluidos los bordes de 64 y 65 caracteres | La herramienta devuelve `INVALID_INPUT` con `retryable=false` en cada fila; ninguna fila en `escalations` | El sobre de error cumple `ToolErrorOut` | — |
| AC-006-17 | El caso de uso parametrizado con las 6 filas: el primer resultado según RN-006-11 | La herramienta con las 6 filas; en la quinta, `cards.status` se cambia a `ACTIVE` directamente en la base tras la primera derivación | — | — |
| AC-006-18 | — | La respuesta serializada solo tiene los campos de RN-006-12, con `masked_card = "**** 4321"`, y no contiene `4111111111114321`, `D-1001` ni `Laura Méndez` | `EscalarAnalistaOut`, `EscalationSummaryOut` y `EscalationCardOut` tienen `additionalProperties: false` y exactamente los campos de la spec §7 | — |
| AC-006-19 | `FailingEscalationRepository` → `CoreUnavailableError` auditado como `INTERNAL`, sin derivación. Tras repararlo, la misma solicitud con `K-1` da `escalated` | `SqlAlchemyEscalationRepository.add` hace `rollback` ante un fallo forzado (p. ej. índice único violado): no queda la fila y la sesión sigue usable. La herramienta con un repositorio que falla devuelve `INTERNAL` con `retryable=false`, sin el texto de la excepción, trazas ni SQL | El sobre cumple `ToolErrorOut` | — |
| AC-006-20 | `FakeAuditLog` + `FixedClock`: exactamente un evento en cada uno de los 9 casos (parametrizado), con `conversation_id`, timestamp, `tool`, `escalation_reason`, `idempotency_key`, `transaction_id`, `card_id`, `dispute_id`, `prior_actions`, `note`, `masked_card`, `identity_verified` y el resultado. Además: `escalation_reason` vacío con `"FRAUD"`; `[REDACTED]` con el PAN en `card_id` y en `note`; `masked_card` vacío en `NOT_FOUND` y sin verificación. Ni el evento ni su JSON contienen `4111111111114321` ni `D-1001` | `JsonAuditLog` escribe los campos nuevos, conserva `identity_verified = false` y omite los vacíos; los eventos de 001–005 no cambian de claves; nada en `stdout` | — | — |

Adicionales (`mcp-testing.md` §7, §2):

- **Snapshot del catálogo:** `test_tool_catalog.py` pasa a esperar también `escalar_a_analista`, compara sus esquemas de entrada y salida con la spec §7 y falla ante herramientas no declaradas.
- **Art. 7 (§5.3.5):** la llamada con datos del cliente sin identificación previa la cubre AC-006-05. Que la derivación sin datos no exponga nada la cubren AC-006-04 y AC-006-18. También se prueba que la herramienta nunca escribe en el almacén (RN-006-14).
- **Escalamiento (§5.3.4):** los casos de la spec §8 se cubren con los motivos de AC-006-02 y AC-006-04; el `INTERNAL` de la propia herramienta, con AC-006-19.
- **Smoke por stdio:** se amplía el test existente. `list_tools` muestra las seis herramientas. Sin verificar, `escalar_a_analista` con `IDENTITY_VERIFICATION_FAILED` devuelve `PENDING` con `identity_verified = false`. Tras `verificar_identidad` con `C-0001`, con `card_id = "CARD-0001"` devuelve el resumen completo. La salida por `stdout` es solo protocolo.
- **`server.mcp`:** el test existente pasa a esperar las seis herramientas.
- **Regresión de 001–005:** `AuditEvent`, `DisputeRepository` y sus fakes se amplían. Las suites existentes deben seguir en verde sin cambios de comportamiento.
- El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global. En la verificación final, además, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Se asocian datos de un cliente a una derivación de una conversación no verificada, o de otro cliente | Alto | La comprobación de `has_customer_data` contra el almacén va antes de cualquier consulta. Las búsquedas filtran por el `customer_id` del almacén, nunca por un dato de la solicitud. AC-006-05, AC-006-08 y AC-006-12 lo prueban en fakes y en SQLite con dos clientes. |
| `.claude/rules/mcp-tools.md` §5 enumera como únicas excepciones a la identificación `buscar_cliente` y `verificar_identidad`; `escalar_a_analista` es una excepción parcial (spec RN-006-03) | Medio | La constitución prevalece (Art. 7 solo prohíbe devolver o modificar datos de un cliente sin verificación, y la derivación sin datos no lo hace). Hay que actualizar la rule para añadir la excepción parcial; esa edición está fuera de los archivos de esta feature y debe hacerla el usuario. |
| La herramienta comprueba la verificación contra un almacén distinto del de `verificar_identidad` | Alto | `server.py` crea una sola instancia y la comparte. El smoke por stdio y los tests de herramienta verifican primero con `verificar_identidad` y luego derivan en el mismo servidor. |
| Un fallo en `add` deja la sesión compartida en estado inválido (`PendingRollbackError`) | Alto | `add` hace `rollback` ante cualquier excepción antes de relanzarla. Un test de integración fuerza un `IntegrityError` y comprueba que la siguiente operación funciona. |
| Una nota o un campo de texto libre con un PAN llega a la base, a la respuesta o a la auditoría | Medio | La nota se redacta en `EscalationRequest.create`, antes de guardarse o devolverse. Los ids libres se redactan al auditar. AC-006-10 y AC-006-20 lo prueban en la fila, la respuesta, el evento y el JSON. |
| Una repetición devuelve un resumen distinto si la transacción cambió después (columnas normalizadas) | Bajo | En esta versión el core no modifica transacciones ni tarjetas fuera de `bloquear_tarjeta`. `card` no incluye el estado, y la transacción solo cambiaría por intervención manual en la base. La decisión está aceptada por el usuario y documentada aquí. |
| Ampliar `AuditEvent` y `DisputeRepository` afecta a 001–005 | Bajo | Son cambios compatibles (campos opcionales al final y una operación nueva). `server.py`, `schemas.py`, `tables.py`, `audit_log.py`, `dispute_repository.py` y `tests/fakes/*` se tratan como archivos compartidos al calcular las oleadas. |
| Una base SQLite local de 001–005 no tiene la tabla | Bajo | `create_all` crea `escalations` vacía al arrancar. Para volver al estado de las semillas, borrar `data/core_banking.db` (ignorado por git). |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | No hay semillas nuevas; los tests usan builders sobre los datos ficticios de 001–005. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento. El orden canónico de `prior_actions` en la salida concreta la respuesta idéntica de AC-006-13. Los 20 AC están trazados en §6. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); el dominio puro, el caso de uso y los fakes permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio usa solo stdlib; SQLAlchemy y Pydantic se quedan en infraestructura y se mapean en los adaptadores; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La herramienta solo registra la derivación; no decide si derivar ni toca `DisputePolicy` (spec §5). La nota nunca se interpreta (AC-006-11). |
| Art. 6 — Acciones vía MCP | Cumple | Las derivaciones solo se registran mediante la herramienta MCP `escalar_a_analista`. |
| Art. 7 — Identificación antes que información | Cumple | Sin verificación, la herramienta no acepta ni devuelve datos de ningún cliente (AC-006-04, AC-006-05). Con verificación, resuelve los datos con el `customer_id` del almacén (AC-006-08, AC-006-12) y solo muestra la tarjeta enmascarada (AC-006-18). |
| Art. 8 — Auditoría | Cumple | Cada invocación genera un único registro con `conversation_id`, marca de tiempo del reloj inyectado, herramienta, datos recibidos, verificación, resultado, regla y motivo, sin PAN ni documento (AC-006-20). |
| Art. 9 — Secretos | Cumple | No hay secretos ni configuración nueva. |
| Art. 10 — Ante la duda, escalar | Cumple | Es el mecanismo de escalamiento, disponible también sin verificación (AC-006-04). Una falla inesperada devuelve `INTERNAL` con `retryable = false` sin dejar nada registrado (AC-006-19). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
