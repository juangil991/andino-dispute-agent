# Tareas: Bloquear una tarjeta de un cliente verificado por sospecha de fraude

| Campo | Valor |
|---|---|
| Feature | `005-card-block` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-17 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas relativas a la raíz del repositorio.

- Los `__init__.py` de los paquetes ya existen (`domain/models`, `application/ports`, `application/use_cases`, `infrastructure/inbound/mcp` y `infrastructure/outbound/persistence`).
- Solo T-005-02 escribe en `tests/fakes/`; las demás tareas reutilizan los fakes sin modificarlos.
- Las tareas que cambian un contrato que usan los tests de 001–004 adaptan esos tests en la misma tarea, para que la suite siga en verde al terminar cada oleada:
  - T-005-02: los campos nuevos de `AuditEvent` y la serialización JSON van juntos.
  - T-005-05: el catálogo `ErrorCode`.

**TDD evidenciable (Art. 3, §5.1):** en cada tarea, ejecutar primero el test y comprobar que falla por el motivo indicado en **Red** antes de escribir código de producción; informarlo en el resultado.

**Comentarios de trazabilidad** (`mcp-testing.md` §3–5; lecciones de las auditorías de 002–004):

1. Un test llamado `test_ac_005_NN_*` lleva encima `# Regla: RN-005-XX — <enunciado literal de spec §4>`, una línea por RN. Cada RN citada debe figurar en la línea `Cubre:` de AC-005-NN. Debajo va `# AC-005-NN · Art. N`. Solo se usa ese prefijo si el test ejecuta el Given/When/Then de ese AC, o una de sus filas, con su Arrange real: un parámetro que no entra en el Arrange no reproduce el Given.
2. Un test de invariante (Art. 7, sin identificación) cita `# Invariante: Art. N — <enunciado>` y la línea `AC-005-NN · Art. N` del AC al que da soporte, con las mismas condiciones.
3. Un test de soporte puro (fakes, builders, mapeos técnicos sin AC) no lleva el prefijo `ac_005_` y declara `# Soporte de tests: <qué> · Art. 3`. Queda fuera de la trazabilidad de AC. Un test de soporte en `tests/integration/` cita además una RN y un AC que realmente ejecute, o una `Invariante:`.
4. Los tests de `tests/contract/` y `tests/integration/` se nombran `test_ac_005_NN_<tool>__<condición>__<resultado>`. Los parametrizados llevan `ids=` legibles.
5. Las aserciones del test reproducen el **Then** completo del AC, incluidas las líneas `And`, no un subconjunto.
6. Antes de citar una RN o un AC, comprobar en `spec.md` el `Cubre:` del AC y copiar el enunciado literal de la RN.

---

## Tareas

### [x] T-005-01 — Value objects `BlockReason`, `CardBlockRequest`, `OwnedCard` y `CardBlock`

- **Cubre:** AC-005-02 (motivos permitidos), AC-005-03 (motivo inválido) y AC-005-10 (datos inválidos), a nivel de dominio. Habilita AC-005-01…15 (plan §4 Dominio).
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/models/card_block.py`, `tests/unit/core_banking_mcp/domain/test_card_block.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_card_block.py::test_ac_005_03_card_block_request_rejects_invalid_reason`
- **Red:** falla con `ImportError` porque `card_block.py` no existe. Tests:
  - `test_ac_005_03_...`: `"STOLEN"`, `"fraud_suspected"`, `"sospecha de fraude"`, `""` y `None` lanzan `InvalidInputError` con `field = "reason"`.
  - `test_ac_005_02_card_block_request_accepts_every_reason`: `FRAUD_SUSPECTED` y `LOST_OR_STOLEN` crean un `CardBlockRequest` con ese `BlockReason`.
  - `test_ac_005_10_card_block_request_rejects_invalid_fields`: las 7 filas de AC-005-10 lanzan `InvalidInputError` con el `field` correspondiente. Son `card_id` e `idempotency_key` ausentes, vacíos, solo espacios o de 65 caracteres, y `conversation_id` ausente, vacío o solo espacios. 64 caracteres (borde exacto) es válido.
  - Soporte (`# Soporte de tests: invariantes de OwnedCard y CardBlock · Art. 3`):
    - Los valores se guardan recortados.
    - `OwnedCard` rechaza `card_id` vacío y `last4` que no tenga 4 dígitos.
    - `CardBlock` rechaza textos vacíos y `blocked_at` sin zona.
    - `CardBlock.same_request(card_id, reason)` es `True` solo si coinciden ambos.
- **Green:** todos `dataclass(frozen=True)` y solo stdlib.
  - `BlockReason(Enum)` con `FRAUD_SUSPECTED` y `LOST_OR_STOLEN`.
  - `CardBlockRequest(conversation_id, card_id, reason, idempotency_key)`, con `create(...)` que acepta `str | None` en todos los campos y usa `MAX_ID_LENGTH` de `domain/models/dispute.py`.
  - `OwnedCard(card_id, last4, status: CardStatus)`, que reutiliza `CardStatus` de `customer.py` y `validate_last4` de `transaction.py`.
  - `CardBlock(card_id, conversation_id, idempotency_key, reason, blocked_at)`, con invariantes en `__post_init__` y `same_request`.
- **Refactor:** reutilizar `_require_text` de `dispute.py` solo si se puede sin cambiar su API; si no, una función privada equivalente.

### [x] T-005-02 — Puerto `CardRepository`, errores, `AuditEvent` ampliado, serialización JSON y fakes

- **Nota (desviación de TDD, Art. 3):** el subagente informó que escribió producción y tests en el mismo paso, sin observar el Red. Los tests pasan (suite completa verde), pero el ciclo Red → Green de esta tarea no es evidenciable. `CardNotFoundError` ya existía en `errors.py` y se reutilizó.

- **Cubre:** AC-005-15 a nivel de integración del adaptador de auditoría. Es regresión de AC-001-13, AC-002-15, AC-003-17 y AC-004-17, y habilita AC-005-01…15 en unit e integración (plan §3 y §6).
- **App / capa:** `core_banking_mcp` / `application` (más el ajuste de `infrastructure/outbound/audit`, para no dejar en rojo la auditoría de 001–004)
- **Depende de:** T-005-01
- **Archivos:** `src/core_banking_mcp/application/ports/card_repository.py`, `src/core_banking_mcp/application/errors.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/fakes/owned_card_builder.py`, `tests/fakes/card_block_builder.py`, `tests/fakes/fake_card_repository.py`, `tests/fakes/failing_card_repository.py`, `tests/unit/core_banking_mcp/application/test_card_fakes.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_card_fakes.py::test_fake_card_repository_finds_customer_cards_and_blocks`
- **Red:** falla con `ImportError` porque no existen el puerto ni los fakes. Tests de soporte (`# Soporte de tests: ... · Art. 3`):
  - `OwnedCardBuilder().build()` crea una `OwnedCard` válida y admite `with_id`, `with_last4` y `with_status`.
  - `CardBlockBuilder().build()` crea un `CardBlock` válido y admite `with_card`, `with_conversation`, `with_key`, `with_reason` y `with_blocked_at`.
  - `FakeCardRepository(cards={customer_id: [OwnedCard...]}, blocks=[...])`:
    - `find_customer_card(customer_id, card_id)` devuelve la tarjeta solo si es de ese cliente, y `None` si es ajena o no existe.
    - `find_block_by_key(conversation_id, key)` solo encuentra el bloqueo de esa conversación.
    - `find_block_by_card(card_id)` devuelve el bloqueo registrado o `None`.
    - `block(...)` deja la tarjeta `BLOCKED`, guarda el `CardBlock` y lo devuelve.
    - Respeta la unicidad por `(conversation_id, key)` y por tarjeta, y expone los bloqueos guardados y si se llamó a `block`.
  - `FailingCardRepository`: `block` lanza `RuntimeError` sin cambiar nada; las lecturas funcionan; `repair()` hace que el siguiente `block` funcione.
  - `CardNotFoundError` y `CardNotBlockableError` existen.
  - `AuditEvent` se construye sin los campos nuevos (por defecto `None`).
  - En `test_json_audit_log.py`, el test nuevo `test_ac_005_15_bloquear_tarjeta_event_is_serialized_without_pan`:
    - Un evento de `bloquear_tarjeta` con `card_id = "[REDACTED]"`, `block_reason`, `idempotency_key` y `masked_card` escribe una línea JSON válida con esos campos, sin ningún PAN ni documento.
    - Con `card_id` y `block_reason` a `None`, la línea no trae esas claves.
    - Las líneas de 001–004 no cambian de claves y nada sale por `stdout`.
- **Green:**
  - Puerto `CardRepository` con:
    - `find_customer_card(customer_id, card_id) -> OwnedCard | None`
    - `find_block_by_key(conversation_id, idempotency_key) -> CardBlock | None`
    - `find_block_by_card(card_id) -> CardBlock | None`
    - `block(conversation_id, idempotency_key, card_id, reason, blocked_at) -> CardBlock`, documentado como atómico.
  - Los 2 errores en `application/errors.py`.
  - `AuditEvent` gana al final `card_id` y `block_reason` (`str | None = None`), y se añaden a `_OPTIONAL_KEYS` de `JsonAuditLog`.
  - Los builders y fakes descritos.
- **Refactor:** —

### [x] T-005-03 — Caso de uso `BlockCard` (comportamiento)

- **Nota:** las líneas `# Regla:` de `test_block_card.py` citan un fragmento del enunciado de la RN, no el literal de spec §4 que exige la cabecera. Queda para la auditoría de AC (fase 5.5). `BlockCardResult.card` devuelve la tarjeta con su estado posterior (`BLOCKED` en `blocked`).

- **Cubre:** AC-005-01, AC-005-02, AC-005-03, AC-005-04, AC-005-05, AC-005-06, AC-005-07, AC-005-08, AC-005-09, AC-005-10, AC-005-11, AC-005-12, AC-005-14
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-005-02
- **Archivos:** `src/core_banking_mcp/application/use_cases/block_card.py`, `tests/unit/core_banking_mcp/application/test_block_card.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_block_card.py::test_ac_005_01_blocks_active_card`
- **Red:** falla porque `BlockCard` no existe. Fixtures comunes: `FakeCardRepository` (`C-0001` con `CARD-L1` `ACTIVE` terminada en `4321`), `FakeVerificationStore` (conversación `A` verificada para `C-0001` salvo que se indique), `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`. Tests:
  - `test_ac_005_01_...`: devuelve `BlockCardResult` con `outcome = "blocked"`, la `OwnedCard` de `CARD-L1` y un `CardBlock` con `blocked_at` igual al instante del reloj y `reason = FRAUD_SUSPECTED`. El fake deja `CARD-L1` `BLOCKED` con exactamente 1 bloqueo. El almacén no cambia.
  - `test_ac_005_02_...` (2 códigos).
  - `test_ac_005_03_...` y `test_ac_005_10_...`: las entradas inválidas lanzan `InvalidInputError` sin consultar el almacén ni el repositorio.
  - `test_ac_005_04_...`, con las 4 filas:
    - `ACTIVE` → `blocked`.
    - `BLOCKED` con bloqueo `LOST_OR_STOLEN` del 15 de octubre → `already_blocked` con ese `CardBlock`.
    - `BLOCKED` sin bloqueo → `already_blocked` con `block = None`.
    - `CANCELLED` → `CardNotBlockableError`.

    En las 3 últimas no se llama a `block`.
  - `test_ac_005_05_...`: segunda ejecución con `K-1`, `CARD-L1` y el mismo motivo, con el reloj una hora después → mismo `CardBlock` (mismo `blocked_at`), `outcome = "replayed"` y 1 solo bloqueo.
  - `test_ac_005_06_...`: `K-1` con `CARD-L2` y con `LOST_OR_STOLEN` → `InvalidInputError` sin llamar a `block`; `CARD-L2` sigue `ACTIVE`.
  - `test_ac_005_07_...`: `K-1` ya usada en `A`; en `B`, verificada para `C-0001` → `already_blocked` con el bloqueo de `A` y 1 solo bloqueo.
  - `test_ac_005_08_...`: `CARD-P1` de `C-0002` y `CARD-9999` → `CardNotFoundError` en ambos; el repositorio se consulta con el `customer_id` del almacén y `CARD-P1` sigue `ACTIVE`.
  - `test_ac_005_09_...`: las 4 situaciones → `IdentityNotVerifiedError` sin llamar al repositorio; el almacén queda igual (RN-005-12).
  - `test_ac_005_11_...`: las 5 filas devuelven el primer resultado según RN-005-09. La última es una repetición tras cancelar la tarjeta, y devuelve `replayed` con el bloqueo original.
  - `test_ac_005_12_...`: tras bloquear `CARD-L1`, `CARD-L2` sigue `ACTIVE` y sin bloqueo.
  - `test_ac_005_14_...`: con `FailingCardRepository` → `CoreUnavailableError` sin el texto de la excepción; `CARD-L1` sigue `ACTIVE` y sin bloqueo. Tras `repair()`, la misma solicitud con `K-1` da `outcome = "blocked"`.
- **Green:**
  - `BlockCardCommand(conversation_id, card_id, reason, idempotency_key)`, todos `str | None`.
  - `BlockCardResult(card, block, outcome)`.
  - `BlockCard(cards, store, audit_log, clock).execute(command)`, en el orden de RN-005-09:
    1. `CardBlockRequest.create`.
    2. `store.get` → `IdentityNotVerifiedError`.
    3. `find_block_by_key`: con `same_request` es una repetición y vuelve a leer la tarjeta con `find_customer_card`; si no coincide, `InvalidInputError`.
    4. `find_customer_card` → `CardNotFoundError`.
    5. Estado: `CANCELLED` → `CardNotBlockableError`; `BLOCKED` → `already_blocked` con `find_block_by_card`; `ACTIVE` → `block(..., clock.now())`.
  - Las excepciones inesperadas posteriores a la validación se convierten en `CoreUnavailableError`.
  - Nunca llama a `store.save`.
  - El constructor ya recibe `audit_log`, pero esta tarea no lo usa (lo cubre T-005-04).
- **Refactor:** extraer métodos privados por paso si `execute` supera ~30 líneas, como en `OpenDispute`.

### [x] T-005-04 — Auditoría de `BlockCard`

- **Nota:** `masked_card` se audita también en `CARD_NOT_BLOCKABLE` e `INTERNAL` (la tarjeta ya estaba resuelta); en `INVALID_INPUT` por clave reutilizada queda vacío porque el error salta antes de resolverla. La spec RN-005-14 no define este último caso: queda para la auditoría de AC (fase 5.5). El `# Regla:` del test de `conversation_id` vacío cita un fragmento, no el literal.

- **Cubre:** AC-005-15
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-005-03
- **Archivos:** `src/core_banking_mcp/application/use_cases/block_card.py`, `tests/unit/core_banking_mcp/application/test_block_card_audit.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_block_card_audit.py::test_ac_005_15_each_invocation_records_exactly_one_event`
- **Red:** el parametrizado con los 10 casos de AC-005-15 falla porque no se registra ningún evento.
  - En cada caso debe quedar exactamente un evento con:
    - `conversation_id` (vacío si no llegó), el instante del `FixedClock`, `tool = "bloquear_tarjeta"` e `input = None`.
    - `card_id`, `block_reason` e `idempotency_key` recibidos: cada uno `None` si no es válido según RN-005-08, y redactados con `redact_card_numbers`.
    - `masked_card = "**** 4321"` solo si la tarjeta del cliente verificado ya se resolvió; `None` en `NOT_FOUND`, `INVALID_INPUT` y sin verificación.
    - `outcome`: `blocked`, `replayed`, `already_blocked`, o `error` con `error_code` `CARD_NOT_BLOCKABLE`, `NOT_FOUND`, `INVALID_INPUT`, `IDENTITY_NOT_VERIFIED` o `INTERNAL`.
    - `rule` y `reason`.
  - Casos concretos:
    - Con `reason = "STOLEN"`, `block_reason` es `None`.
    - Con `card_id = "4111111111114321"`, el evento trae `"[REDACTED]"` y `NOT_FOUND`.
    - Con `idempotency_key = "bloqueo-4111111111114321"`, trae `"bloqueo-[REDACTED]"` y `blocked`.
  - Ni el evento serializado con `dataclasses.asdict` ni su texto contienen `4111111111114321` ni `D-1001`.
- **Green:** `BlockCard` llama una vez a `audit_log.record(AuditEvent(...))` en cada salida.
  - Usa las reglas del plan §1, un motivo en español y el `customer_id` verificado cuando ya se conoce.
  - `card_id` e `idempotency_key` se auditan con un `_audited_id` equivalente al de `open_dispute.py`; `block_reason` solo si es un código del catálogo.
- **Refactor:** consolidar la construcción del evento en un método privado `_record`, como en `OpenDispute`.

### [x] T-005-05 — Esquema MCP de `bloquear_tarjeta` y catálogo `ErrorCode` (contrato)

- **Cubre:**
  - AC-005-13: campos exactos y `additionalProperties: false`.
  - AC-005-02: enum de `reason` en la salida.
  - AC-005-03: enum publicado en la entrada.
  - AC-005-04: catálogo con `CARD_NOT_BLOCKABLE`; `blocked_at` y `reason` admiten `null`.
  - AC-005-08: catálogo con `NOT_FOUND`.
  - AC-005-10 y AC-005-14: sobre `ToolErrorOut`.
  - AC-005-01: la salida cumple `BloquearTarjetaOut`.
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `tests/contract/core_banking_mcp/test_bloquear_tarjeta_contract.py`, `tests/contract/core_banking_mcp/test_buscar_cliente_contract.py`, `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`, `tests/contract/core_banking_mcp/test_consultar_transacciones_contract.py`, `tests/contract/core_banking_mcp/test_iniciar_disputa_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_bloquear_tarjeta_contract.py::test_ac_005_13_bloquear_tarjeta__output_schema__has_exactly_spec_fields`
- **Red:** falla con `ImportError` porque `BloquearTarjetaOut` no existe. Además:
  - `BloquearTarjetaOut` tiene `additionalProperties: false` y exactamente `card_id`, `masked_card`, `status`, `blocked_at`, `reason` y `already_blocked`.
    - `status` admite solo `BLOCKED`.
    - `reason` admite solo los 2 códigos o `null` (`test_ac_005_02_...`).
    - `blocked_at` admite `string` o `null`.
    - `already_blocked` es `boolean`.
  - El esquema de entrada de la herramienta se probará en el catálogo (T-005-09). Aquí se prueba la constante `BLOCK_REASON_CODES` que publica el `enum` de `reason` (`test_ac_005_03_...`).
  - `ErrorCode` es exactamente `{INVALID_INPUT, IDENTITY_NOT_VERIFIED, NOT_FOUND, TRANSACTION_NOT_DISPUTABLE, DISPUTE_ALREADY_OPEN, CARD_NOT_BLOCKABLE, INTERNAL}` (`test_ac_005_04_...`, `test_ac_005_08_...`).
  - `ToolErrorOut` sigue con `code`, `message` y `retryable` (`test_ac_005_10_...`, `test_ac_005_14_...`).
  - Las aserciones de catálogo cerrado de los contratos de 001–004 fallan con el catálogo nuevo. Se actualizan al conjunto de 7 códigos, conservando sus citas.
- **Green:** en `schemas.py`:
  - `ErrorCode` gana `CARD_NOT_BLOCKABLE`.
  - Se añade `BLOCK_REASON_CODES = ("FRAUD_SUSPECTED", "LOST_OR_STOLEN")`.
  - Se añade `BloquearTarjetaOut` con `extra="forbid"`, `status: Literal["BLOCKED"]`, `blocked_at: str | None`, `reason: Literal["FRAUD_SUSPECTED", "LOST_OR_STOLEN"] | None` y `already_blocked: bool`, todos con `Field(description=...)`.
- **Refactor:** —

### [x] T-005-06 — Tabla `card_blocks` y adaptador `SqlAlchemyCardRepository`

- **Cubre** (todo a nivel de repositorio):
  - AC-005-04: tarjeta bloqueada sin registro → `find_block_by_card` devuelve `None`.
  - AC-005-05: búsqueda por clave.
  - AC-005-08: tarjeta ajena o inexistente.
  - AC-005-12: solo cambia la tarjeta indicada.
  - AC-005-14: rollback; la tarjeta no cambia.
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-005-02
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_card_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_card_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_card_repository.py::test_ac_005_08_find_customer_card_ignores_other_customers`
- **Red:** falla porque `CardBlockRow` y el adaptador no existen. Con SQLite `:memory:` y clientes creados con `CustomerBuilder` / `IdentityBuilder` vía `SqlAlchemyCustomerRepository` (asigna `card_ref` `CARD-0001`, …):
  - `test_ac_005_08_...`: `find_customer_card("C-0001", <card_ref de Pedro>)` y `("C-0001", "CARD-9999")` devuelven `None`. Con una tarjeta de Laura devuelve `OwnedCard` con `card_id`, `last4` y `status` correctos.
  - `test_ac_005_12_...`: `block` sobre la tarjeta `4321` la deja `BLOCKED`, registra 1 fila en `card_blocks` y la otra tarjeta de Laura sigue `ACTIVE`.
  - `test_ac_005_05_...`:
    - `find_block_by_key("A", "K-1")` devuelve el bloqueo creado con esos datos, con `blocked_at` igual al instante guardado (`−05:00` → UTC con `tzinfo=UTC`).
    - `("B", "K-1")` devuelve `None`.
    - La pareja `(conversation_id, idempotency_key)` es única.
  - `test_ac_005_04_...`: una tarjeta insertada `BLOCKED` sin fila en `card_blocks` → `find_block_by_card` devuelve `None`. Tras `block` sobre una `ACTIVE`, devuelve ese bloqueo.
  - `test_ac_005_14_...`: el `rollback` ante cualquier fallo deja todo como estaba y la sesión usable (una lectura y un `block` válido posteriores funcionan). Tres fallos:
    - Un `block` que viola un índice único (misma clave en la misma conversación).
    - Un `block` sobre una tarjeta que no está `ACTIVE`, con `UPDATE` sin filas.
    - Un fallo forzado tras el `UPDATE`.
- **Green:**
  - `CardBlockRow`, según el plan §4: `block_id` PK autoincremental, FK `card_id` → `cards.card_id`, `conversation_id`, `idempotency_key`, `reason` y `blocked_at` en UTC sin zona, con los índices únicos `ux_card_blocks_conversation_key` y `ux_card_blocks_card`.
  - `SqlAlchemyCardRepository(session)` implementa el puerto, mapeando `card_ref` ↔ `card_id` de dominio.
  - `block` hace el `UPDATE cards SET status='BLOCKED' WHERE card_ref=? AND status='ACTIVE'`, exige 1 fila afectada, inserta el bloqueo y hace un solo `commit`; ante cualquier excepción hace `rollback` y la relanza.
- **Refactor:** —

### [x] T-005-07 — Herramienta `bloquear_tarjeta` (camino exitoso)

- **Cubre:** AC-005-01, AC-005-02, AC-005-04 (filas `ACTIVE` y `BLOCKED`), AC-005-05, AC-005-07, AC-005-12, AC-005-13
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-005-03, T-005-05, T-005-06
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/card_tools.py`, `tests/integration/core_banking_mcp/mcp/test_bloquear_tarjeta_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_bloquear_tarjeta_tool.py::test_ac_005_01_bloquear_tarjeta__active_card__blocks_card`
- **Red:** falla porque `register_card_tools` no existe. Entorno: sesión MCP en memoria (`mcp.shared.memory`), como en `test_iniciar_disputa_tool.py`; SQLite `:memory:` con clientes y tarjetas de builders; el `InMemoryConversationVerificationStore` real con la conversación `A` verificada para `C-0001`; `FakeAuditLog`; y `FixedClock` en `2026-10-17T15:00:00Z`. Casos:
  - AC-005-01: los 6 campos, con `blocked_at = "2026-10-17T10:00:00-05:00"`, `masked_card = "**** 4321"` y `already_blocked = false`. `cards.status = 'BLOCKED'` y 1 fila en `card_blocks`.
  - AC-005-02: los 2 códigos.
  - AC-005-04: tres filas.
    - `ACTIVE`.
    - `BLOCKED` con bloqueo original `LOST_OR_STOLEN` del `2026-10-15T09:00:00-05:00`, preparado con una primera llamada con `K-0` y el reloj en esa fecha → `already_blocked = true` con ese `blocked_at` y ese `reason`, y 1 sola fila.
    - `BLOCKED` sin registro → `blocked_at = null` y `reason = null`.
  - AC-005-05: la segunda llamada con `K-1` y el reloj una hora después devuelve la misma respuesta y hay 1 fila.
  - AC-005-07: `A` y `B` verificadas con `verificar_identidad`, registrada también en el servidor de prueba. `B` con `K-1` recibe `already_blocked = true` con el `blocked_at` de `A`, y hay 1 fila.
  - AC-005-12: la otra tarjeta de Laura sigue `ACTIVE` y sin bloqueo.
  - AC-005-13: la respuesta serializada solo tiene los 6 campos de RN-005-10, `card_id` no contiene el PAN, y en ninguna parte aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`.
- **Green:** `register_card_tools(mcp, block_card)` registra `bloquear_tarjeta`.
  - Firma `str | None` en los 4 campos, con `Field(description=...)`; `reason` publica `json_schema_extra={"enum": list(BLOCK_REASON_CODES)}`.
  - Docstring en español según la spec §7: requiere identidad verificada, cuándo usarla y cuándo no, cómo actuar ante cada respuesta, efectos e idempotencia.
  - Devuelve `CallToolResult` con `structuredContent` de `BloquearTarjetaOut`: `masked_card` con `mask_card`, `blocked_at` en Bogotá o `null`, y `already_blocked = outcome == "already_blocked"`.
  - Registra `ErrorPassthroughMetadata`, como `dispute_tools.py`.
  - El mapeo de errores queda para T-005-08.
- **Refactor:** —

### [x] T-005-08 — `bloquear_tarjeta`: errores, identidad y auditoría

- **Nota:** el test de AC-005-09 cita RN-005-03 pero no RN-005-12, que sí figura en el `Cubre:` de ese AC; queda para la auditoría de AC (fase 5.5).

- **Cubre:** AC-005-03, AC-005-04 (fila `CANCELLED`), AC-005-06, AC-005-08, AC-005-09, AC-005-10, AC-005-11, AC-005-14, AC-005-15
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-005-04, T-005-07
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/card_tools.py`, `tests/integration/core_banking_mcp/mcp/test_bloquear_tarjeta_errors.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_bloquear_tarjeta_errors.py::test_ac_005_09_bloquear_tarjeta__unverified_conversation__returns_identity_not_verified`
- **Red:** falla porque las excepciones del caso de uso se propagan sin sobre de error. Con la misma sesión MCP en memoria:
  - AC-005-09: las 4 situaciones devuelven `isError=true`, `IDENTITY_NOT_VERIFIED` y `retryable = false`. La tarjeta sigue `ACTIVE`, no hay filas en `card_blocks` y el almacén queda igual. En la situación de dos conversaciones, `A` se verifica con `verificar_identidad` y la solicitud se hace en `B`.
  - AC-005-03 (5 filas), AC-005-10 (7 filas) y AC-005-06 (2 filas): `INVALID_INPUT` con `retryable = false`, sin cambios en `cards` ni filas adicionales.
  - AC-005-04: `CANCELLED` → `CARD_NOT_BLOCKABLE` con `retryable = false`; la tarjeta sigue `CANCELLED` y sin filas.
  - AC-005-08: `CARD-P1` (de `C-0002`) y `CARD-9999` devuelven sobres `NOT_FOUND` iguales campo a campo, sin datos de `C-0002`; la tarjeta de Pedro sigue `ACTIVE`.
  - AC-005-11: las 5 filas devuelven el resultado esperado. En la última, la tarjeta se cancela directamente en la base tras el primer bloqueo y la repetición devuelve el bloqueo original con `already_blocked = false`.
  - AC-005-14: con `FailingCardRepository` → `INTERNAL` con `retryable = false`, sin el texto de la excepción, trazas ni SQL; la tarjeta sigue `ACTIVE`.
  - AC-005-15: con un `JsonAuditLog` real sobre un `StringIO`, cada uno de los 10 casos deja una sola línea JSON con la herramienta, `card_id`, `block_reason`, `idempotency_key`, `masked_card` y el resultado esperado. Ninguna línea contiene `4111111111114321` ni `D-1001`.
- **Green:** en `card_tools.py`, todos con `retryable=False`. Ningún mensaje incluye el texto de la excepción ni el valor recibido.

  | Excepción | Código | Mensaje |
  |---|---|---|
  | `InvalidInputError` | `INVALID_INPUT` | `"Los datos de la solicitud no son válidos (campo: {error.field})."` |
  | `IdentityNotVerifiedError` | `IDENTITY_NOT_VERIFIED` | fijo |
  | `CardNotFoundError` | `NOT_FOUND` | constante única del módulo |
  | `CardNotBlockableError` | `CARD_NOT_BLOCKABLE` | `"Una tarjeta cancelada no se puede bloquear."` |
  | `CoreUnavailableError` y *catch-all* defensivo | `INTERNAL` | fijo |
- **Refactor:** —

### [x] T-005-09 — Cableado del servidor, catálogo y smoke por stdio

- **Nota:** el subagente solo observó el Red del test de catálogo; los de smoke y `server.mcp` se escribieron junto al cableado. `test_stdio_smoke.py` no tiene ninguna aserción de que `stdout` solo lleve protocolo (tampoco para 002–004): la tarea la pedía y queda para la auditoría de AC (fase 5.5).

- **Cubre:**
  - AC-005-01: por stdio real, sobre la tarjeta semilla `CARD-0001`.
  - AC-005-04: `CARD-0002` bloqueada sin registro.
  - AC-005-09: almacén compartido con `verificar_identidad`.
  - AC-005-13: esquemas en el catálogo.
  - Catálogo de herramientas (`mcp-testing.md` §7).
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-005-08
- **Archivos:** `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_005_13_catalog_exposes_bloquear_tarjeta_with_spec_schemas`
- **Red:**
  - **Catálogo:** falla porque `list_tools` no incluye `bloquear_tarjeta`.
    - El test espera las cinco herramientas y falla ante herramientas no declaradas.
    - Compara el esquema de entrada (4 campos con descripción y el `enum` de `reason`) y el de salida con `BloquearTarjetaOut.model_json_schema()` (`additionalProperties: false`).
    - Los tests existentes de 001–004 del archivo pasan a esperar las cinco herramientas.
  - **`test_server_module.py`:** `server.mcp` expone las cinco herramientas.
  - **`test_stdio_smoke.py`**, por stdio real y con la base sembrada:
    - `test_ac_005_01_bloquear_tarjeta__stdio_server__blocks_seeded_active_card`: tras `verificar_identidad` de `C-0001`, `bloquear_tarjeta` sobre `CARD-0001` devuelve `status = "BLOCKED"`, `masked_card = "**** 4321"` y `already_blocked = false`.
    - `test_ac_005_04_bloquear_tarjeta__stdio_server__seeded_blocked_card_reports_already_blocked`: sobre `CARD-0002` devuelve `already_blocked = true` con `blocked_at = null` y `reason = null`.
    - `test_ac_005_09_bloquear_tarjeta__stdio_server__unverified_conversation_is_rejected`: otra conversación recibe `IDENTITY_NOT_VERIFIED`.
    - `stdout` solo lleva protocolo.
- **Green:** `build_server` crea `SqlAlchemyCardRepository(session)` y construye `BlockCard(card_repository, store, JsonAuditLog(), SystemClock())`, usando la **misma** instancia de `InMemoryConversationVerificationStore` que las demás herramientas. Después llama a `register_card_tools`. `main()` y el `__getattr__` no cambian.
- **Refactor:** —

### [x] T-005-10 — Verificación final

- **Cubre:** Definition of Done (§5.5): AC-005-01…15 en verde, cobertura, lint, formato y tipado.
- **App / capa:** `core_banking_mcp` / todas
- **Depende de:** T-005-01, T-005-02, T-005-03, T-005-04, T-005-05, T-005-06, T-005-07, T-005-08, T-005-09
- **Archivos:** — (solo verificación; no modifica archivos)
- **Test primero:** `uv run pytest --cov` (suite completa de 001–005)
- **Red:** si algún comando falla, la tarea queda `[ ]` con el motivo y se corrige en la tarea que corresponda.
- **Green:** pasan sin errores:
  - `uv run pytest --cov` (umbral global ≥ 80 %)
  - `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy --strict src`
- **Refactor:** —

## Correcciones de la primera auditoría de AC (fase 5.5, veredicto «No cumple»: 2 Bloqueantes, 1 Mayor y 3 Menores)

Cambios de trazabilidad en los tests, sin cambio de comportamiento ni de `src/` (§4.3.5): no hay Red de pytest; el Red es el hallazgo de `verify-ac-coverage` (`H-01…H-06`). La suite debe seguir en verde. Regla única de la cabecera: cada RN citada debe figurar en el `Cubre:` de su AC en `spec.md`, el enunciado de `Regla:` es el literal de spec §4 y los comentarios `# Regla:` / `# AC-005-NN · Art. N` van **encima** del `def`.

### [x] T-005-11 — H-01 y H-06 (auditoría JSON): cita inexistente y nombres

- **Cubre:** corrige H-01 y la parte de H-06 de `test_json_audit_log.py`
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound` (tests)
- **Depende de:** T-005-10
- **Archivos:** `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** H-01: las líneas `:181` y `:203` citan `RN-005-15`, que no existe (la spec llega a RN-005-14). H-06: `test_ac_005_15_bloquear_tarjeta_event_is_serialized_without_pan` y `test_ac_005_15_event_without_block_fields_omits_keys` (`:183`, `:205`) no siguen `test_ac_005_NN_<tool>__<condición>__<resultado>`.
- **Green:** cambiar ambas citas a `RN-005-14` con su enunciado literal de spec §4 (comprobando que figura en el `Cubre:` de AC-005-15); renombrar los dos tests al patrón con `__` conservando el prefijo `test_ac_005_15_`.
- **Refactor:** —

### [x] T-005-12 — H-02: tests de dominio sin `Regla:` ni `AC-… · Art.`

- **Cubre:** corrige H-02 y los tests huérfanos de `test_card_block.py`
- **App / capa:** `core_banking_mcp` / `domain` (tests)
- **Depende de:** T-005-10
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_card_block.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** H-02: los tests de `:19`, `:27`, `:34` y `:66` solo citan el AC en el docstring. Los de `:74`, `:83`, `:105`, `:115` y `:119` (invariantes de dominio) no citan nada.
- **Green:** encima de cada `def`: `:19` → `# Regla: RN-005-02 — …` y `# AC-005-03 · Art. 3`; `:27` → `RN-005-02` y `AC-005-02 · Art. 3`; `:34` y `:66` → `RN-005-08` y `AC-005-10 · Art. 3`. Enunciados literales de spec §4; cada RN debe figurar en el `Cubre:` de su AC. Los tests de invariantes sin AC llevan `# Soporte de tests: <qué> · Art. 3`.
- **Refactor:** —

### [x] T-005-13 — H-03: RN citada fuera del `Cubre:` en el contrato

- **Cubre:** corrige H-03
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound` (tests)
- **Depende de:** T-005-10
- **Archivos:** `tests/contract/core_banking_mcp/test_bloquear_tarjeta_contract.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** `:49` cita `RN-005-06` bajo AC-005-02, cuyo `Cubre:` solo incluye HU-005-01 y RN-005-02.
- **Green:** quitar la línea `Regla: RN-005-06` del test de AC-005-02. Si se conserva la aserción de que `reason` admite `null`, moverla al test de AC-005-04 (`:69`), cuyo `Cubre:` sí incluye RN-005-06. Verificar en `spec.md` cada RN citada.
- **Refactor:** —

### [x] T-005-14 — H-04 y H-05: posición y enunciados de los comentarios en los tests del caso de uso

- **Cubre:** corrige H-04 y H-05
- **App / capa:** `core_banking_mcp` / `application` (tests)
- **Depende de:** T-005-10
- **Archivos:** `tests/unit/core_banking_mcp/application/test_block_card.py`, `tests/unit/core_banking_mcp/application/test_block_card_audit.py`
- **Test primero:** los mismos tests existentes de esos dos archivos (deben seguir en verde)
- **Red:** H-04: en `test_block_card.py` los comentarios `# Regla:` y `# AC-005-… · Art. 3` van dentro del cuerpo, tras el docstring (p. ej. `:119-122`). H-05: `test_block_card_audit.py:185` corta el enunciado de RN-005-14 en `tool = "bloquear_tarjeta"`; y las citas `# Regla:` de `test_block_card.py` son fragmentos, no el literal de spec §4.
- **Green:** mover cada bloque de comentarios encima de su `def`; completar el enunciado literal de spec §4 en cada `# Regla:` (también el de `:185`); comprobar que cada RN citada figura en el `Cubre:` de su AC. En AC-005-09 citar también RN-005-12 (figura en su `Cubre:` y el test comprueba que el almacén no cambia).
- **Refactor:** —

### [x] T-005-15 — H-06 (repositorio SQL): nombres de tests de integración

- **Cubre:** corrige la parte de H-06 de `test_sqlalchemy_card_repository.py`
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound` (tests)
- **Depende de:** T-005-10
- **Archivos:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_card_repository.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** los tests de `:96`, `:109`, `:122`, `:143` y `:159` no siguen `test_ac_005_NN_<tool>__<condición>__<resultado>` (`mcp-testing.md` §4).
- **Green:** renombrarlos al patrón con `__`, conservando el prefijo `test_ac_005_NN_`; los parametrizados llevan `ids=` legibles.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-005-01 | T-005-03, T-005-05, T-005-07, T-005-09 | `test_ac_005_01_blocks_active_card`, `test_ac_005_01_bloquear_tarjeta__active_card__blocks_card`, `test_ac_005_01_bloquear_tarjeta__stdio_server__blocks_seeded_active_card` |
| AC-005-02 | T-005-01, T-005-03, T-005-05, T-005-07 | `test_ac_005_02_card_block_request_accepts_every_reason`, `test_ac_005_02_*` (caso de uso, contrato y herramienta) |
| AC-005-03 | T-005-01, T-005-03, T-005-05, T-005-08 | `test_ac_005_03_card_block_request_rejects_invalid_reason`, `test_ac_005_03_*` (caso de uso, contrato y herramienta) |
| AC-005-04 | T-005-03, T-005-05, T-005-06, T-005-07, T-005-08, T-005-09 | `test_ac_005_04_*` (caso de uso, contrato, repositorio y herramienta), `test_ac_005_04_bloquear_tarjeta__stdio_server__seeded_blocked_card_reports_already_blocked` |
| AC-005-05 | T-005-03, T-005-06, T-005-07 | `test_ac_005_05_*` (caso de uso, repositorio y herramienta) |
| AC-005-06 | T-005-03, T-005-08 | `test_ac_005_06_*` (caso de uso y herramienta) |
| AC-005-07 | T-005-03, T-005-07 | `test_ac_005_07_*` (caso de uso y herramienta) |
| AC-005-08 | T-005-03, T-005-05, T-005-06, T-005-08 | `test_ac_005_08_find_customer_card__other_customer_or_missing__returns_none`, `test_ac_005_08_*` (caso de uso, contrato y herramienta) |
| AC-005-09 | T-005-03, T-005-08, T-005-09 | `test_ac_005_09_bloquear_tarjeta__unverified_conversation__returns_identity_not_verified`, `test_ac_005_09_bloquear_tarjeta__stdio_server__unverified_conversation_is_rejected`, `test_ac_005_09_*` (caso de uso) |
| AC-005-10 | T-005-01, T-005-03, T-005-05, T-005-08 | `test_ac_005_10_card_block_request_rejects_invalid_fields`, `test_ac_005_10_*` (caso de uso, contrato y herramienta) |
| AC-005-11 | T-005-03, T-005-08 | `test_ac_005_11_*` (caso de uso y herramienta) |
| AC-005-12 | T-005-03, T-005-06, T-005-07 | `test_ac_005_12_*` (caso de uso, repositorio y herramienta) |
| AC-005-13 | T-005-05, T-005-07, T-005-09 | `test_ac_005_13_bloquear_tarjeta__output_schema__has_exactly_spec_fields`, `test_ac_005_13_catalog_exposes_bloquear_tarjeta_with_spec_schemas`, `test_ac_005_13_*` (herramienta) |
| AC-005-14 | T-005-03, T-005-05, T-005-06, T-005-08 | `test_ac_005_14_*` (caso de uso, contrato, repositorio y herramienta) |
| AC-005-15 | T-005-02, T-005-04, T-005-08 | `test_ac_005_15_bloquear_tarjeta__event_with_block_fields__serialized_without_pan`, `test_ac_005_15_each_invocation_records_exactly_one_event`, `test_ac_005_15_*` (herramienta) |

- **Casos de escalamiento (spec §8):** `INTERNAL` con `retryable = false` → AC-005-14 (T-005-03, T-005-06, T-005-08).
- **Art. 7 (sin identificación previa):** AC-005-09 (T-005-03, T-005-08, T-005-09), con la comprobación de que la herramienta no escribe en el almacén (RN-005-12).
- **Tabla `DP-`:** no aplica.
- **Tareas de soporte sin AC propio:** ninguna (T-005-02 cubre AC-005-15 en el adaptador de auditoría).

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [ ] Spec actualizada al comportamiento implementado.
- [ ] Sin secretos ni datos reales.
