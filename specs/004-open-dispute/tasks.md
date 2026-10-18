# Tareas: Abrir una disputa sobre una transacción de un cliente verificado

| Campo | Valor |
|---|---|
| Feature | `004-open-dispute` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-17 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas relativas a la raíz del repositorio. Los `__init__.py` de los paquetes ya existen (`domain/models`, `application/ports`, `application/use_cases`, `infrastructure/inbound/mcp`, `infrastructure/outbound/persistence` y `seeds`). Solo T-004-03 escribe en `tests/fakes/`; las demás tareas reutilizan los fakes sin modificarlos. Las tareas que cambian un contrato que usan los tests de 001–003 (catálogo `ErrorCode` en T-004-06, firma de `seed_database` en T-004-10, `_to_item` → `to_transaction_item` en T-004-11) adaptan esos tests en la misma tarea, para que la suite siga en verde al terminar cada oleada.

**TDD evidenciable (Art. 3, §5.1):** en cada tarea, ejecutar primero el test y comprobar que falla por el motivo indicado en **Red** antes de escribir código de producción; informarlo en el resultado.

**Comentarios de trazabilidad (`mcp-testing.md` §3–5; lecciones de las auditorías de 002 y 003):**

1. Un test llamado `test_ac_004_NN_*` lleva encima `# Regla: RN-004-XX — <enunciado fiel de spec §4>` (una línea por RN), **donde cada RN citada figura en la línea `Cubre:` de AC-004-NN**, y `# AC-004-NN · Art. N`. Solo se usa ese prefijo si el test ejecuta el Given/When/Then de ese AC (o una de sus filas), con su Arrange real: un parámetro que no entra en el Arrange no reproduce el Given.
2. Un test de invariante (Art. 7, sin identificación) cita `# Invariante: Art. N — <enunciado>` y la línea `AC-004-NN · Art. N` del AC al que da soporte, con las mismas condiciones.
3. Un test de soporte puro (fakes, builders, mapeos técnicos sin AC) no lleva el prefijo `ac_004_` y declara `# Soporte de tests: <qué> · Art. 3`, fuera de la trazabilidad de AC. Los tests de integración de soporte (semillas, ida y vuelta de instantes) citan además una RN y un AC que realmente ejecuten, o una `Invariante:`.
4. Los tests de `tests/contract/` e `tests/integration/` se nombran `test_ac_004_NN_<tool>__<condición>__<resultado>`; los parametrizados llevan `ids=` legibles.
5. Las aserciones del test reproducen el **Then** completo del AC (incluidas las líneas `And`), no un subconjunto.

---

## Tareas

### [x] T-004-01 — Redacción de números de tarjeta en texto libre (`redact_card_numbers`)

- **Cubre:** AC-004-17 (redacción de PAN en `transaction_id` e `idempotency_key`, nivel dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/masking.py`, `tests/unit/core_banking_mcp/domain/test_masking.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_masking.py::test_ac_004_17_redact_card_numbers_replaces_13_to_19_digit_runs`
- **Red:** falla con `ImportError` porque `redact_card_numbers` no existe. Parametrizado: `"4111111111114321"` → `"[REDACTED]"`; `"pago-4111111111114321"` → `"pago-[REDACTED]"`; 13 dígitos (borde inferior) y 19 dígitos (borde superior) se redactan; 12 dígitos (`"123456789012"`) y `"TX-L1"` quedan iguales; dos secuencias en el mismo texto se redactan ambas. Los tests existentes de `mask_card` y `mask_document` siguen en verde.
- **Green:** `redact_card_numbers(text: str) -> str` con `re.sub(r"[0-9]{13,19}", "[REDACTED]", text)`. Solo stdlib.
- **Refactor:** —

### [x] T-004-02 — Value objects `DisputeReason`, `DisputeStatus`, `DisputeRequest` y `Dispute`

- **Cubre:** AC-004-02 (motivos permitidos), AC-004-03 (motivo inválido), AC-004-13 (datos inválidos) — nivel dominio; habilita AC-004-01…17 (plan §4 Dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/models/dispute.py`, `tests/unit/core_banking_mcp/domain/test_dispute.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_dispute.py::test_ac_004_03_dispute_request_rejects_invalid_reason`
- **Red:** falla con `ImportError` porque `dispute.py` no existe. Tests:
  - `test_ac_004_03_...`: `"FRAUD"`, `"unrecognized_charge"`, `"no reconoce el cargo"`, `""` y `None` lanzan `InvalidInputError` con `field = "reason"`.
  - `test_ac_004_02_dispute_request_accepts_every_reason`: los 5 códigos crean un `DisputeRequest` con ese `DisputeReason`.
  - `test_ac_004_13_dispute_request_rejects_invalid_fields`: las 7 filas de AC-004-13 (`transaction_id` / `idempotency_key` ausentes, vacíos, solo espacios y de 65 caracteres; `conversation_id` ausente, vacío o solo espacios) lanzan `InvalidInputError` con el `field` correspondiente; 64 caracteres (borde exacto) es válido.
  - Soporte (`# Soporte de tests: invariantes de Dispute · Art. 3`): los valores se guardan recortados; `Dispute` rechaza IDs vacíos y `opened_at` sin zona; `Dispute.same_request(transaction_id, reason)` es `True` solo si coinciden ambos.
- **Green:** `DisputeReason(Enum)` y `DisputeStatus(Enum)` (`OPEN`, `CLOSED`, `REJECTED`); `MAX_ID_LENGTH = 64`; `DisputeRequest(conversation_id, transaction_id, reason, idempotency_key)` con `create(...)` que acepta `str | None` en todos los campos; `Dispute(dispute_id, conversation_id, idempotency_key, transaction_id, reason, status, opened_at)` con invariantes en `__post_init__` y `same_request`. Todos `dataclass(frozen=True)`; solo stdlib.
- **Refactor:** reutilizar el patrón de `_require_text` de `transaction.py` si se puede sin cambiar su API.

### [x] T-004-03 — Puertos, errores, `AuditEvent` ampliado y fakes

- **Cubre:** habilita AC-004-01…17 en unit e integración (plan §3 y §6)
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-004-02
- **Archivos:** `src/core_banking_mcp/application/ports/dispute_repository.py`, `src/core_banking_mcp/application/ports/transaction_repository.py`, `src/core_banking_mcp/application/errors.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `tests/fakes/dispute_builder.py`, `tests/fakes/fake_dispute_repository.py`, `tests/fakes/failing_dispute_repository.py`, `tests/fakes/fake_transaction_repository.py`, `tests/unit/core_banking_mcp/application/test_dispute_fakes.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_dispute_fakes.py::test_fake_dispute_repository_assigns_ids_and_finds_by_key_and_open`
- **Red:** falla con `ImportError` porque no existen el puerto ni los fakes. Tests de soporte (`# Soporte de tests: ... · Art. 3`):
  - `DisputeBuilder().build()` crea una `Dispute` válida y admite `with_id`, `with_status`, `with_transaction`, `with_conversation`, `with_key`, `with_reason` y `with_opened_at`.
  - `FakeDisputeRepository(disputes=[...])`: `add(...)` asigna `DSP-000001`, `DSP-000002`, … (siguiente al número de disputas), `find_by_idempotency_key(conversation_id, key)` solo encuentra la de esa conversación, `find_open_by_transaction` ignora `CLOSED` y `REJECTED`; expone las disputas guardadas y si fue invocado.
  - `FailingDisputeRepository`: `add` lanza `RuntimeError` sin guardar nada; las lecturas funcionan; `repair()` hace que el siguiente `add` funcione.
  - `FakeTransactionRepository.find_customer_transaction(customer_id, transaction_id)` devuelve la transacción si pertenece a una tarjeta de ese cliente y `None` si es de otro cliente o no existe. Los tests existentes de `test_fakes.py` siguen en verde.
  - `TransactionNotFoundError`, `TransactionNotDisputableError` y `DisputeAlreadyOpenError("D-OLD").dispute_id == "D-OLD"` existen; `AuditEvent` se construye sin los campos nuevos (por defecto `None`).
- **Green:** puerto `DisputeRepository` (`find_by_idempotency_key`, `find_open_by_transaction`, `add(conversation_id, idempotency_key, transaction_id, reason, status, opened_at) -> Dispute`); `TransactionRepository` gana `find_customer_transaction(customer_id, transaction_id) -> Transaction | None`; los 3 errores en `application/errors.py`; `AuditEvent` gana al final `transaction_id`, `dispute_reason`, `idempotency_key` y `dispute_id` (`str | None = None`); los fakes y el builder descritos.
- **Refactor:** —
- **Nota:** al cerrar esta tarea, `test_ac_001_13_audit_event_is_written_as_json_line` falla porque los 4 campos nuevos de `AuditEvent` salen como `null` en el JSON de `JsonAuditLog`. Es el efecto previsto en el Red de T-004-09, que lo corrige; la suite queda en verde al terminar esa tarea.

### [x] T-004-04 — Caso de uso `OpenDispute` (comportamiento)

- **Cubre:** AC-004-01, AC-004-02, AC-004-03, AC-004-04, AC-004-05, AC-004-07, AC-004-08, AC-004-09, AC-004-10, AC-004-11, AC-004-12, AC-004-13, AC-004-14, AC-004-16
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-004-03
- **Archivos:** `src/core_banking_mcp/application/use_cases/open_dispute.py`, `tests/unit/core_banking_mcp/application/test_open_dispute.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_open_dispute.py::test_ac_004_01_opens_dispute_on_confirmed_transaction`
- **Red:** falla porque `OpenDispute` no existe. Con `FakeTransactionRepository` (`C-0001` con la tarjeta `4321` y `TX-L1` `CONFIRMED`), `FakeDisputeRepository`, `FakeVerificationStore` (conversación `A` verificada para `C-0001` salvo que se indique), `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`:
  - `test_ac_004_01_...`: devuelve `OpenDisputeResult` con `Dispute` `OPEN`, `opened_at` = instante del reloj, `reason = UNRECOGNIZED_CHARGE`, la `Transaction` de `TX-L1` y `replayed = false`; el fake guarda exactamente 1 disputa; el estado del almacén no cambia.
  - `test_ac_004_02_...` (5 códigos) y `test_ac_004_03_...` / `test_ac_004_13_...` (entradas inválidas lanzan `InvalidInputError` sin consultar el almacén ni los repositorios).
  - `test_ac_004_04_...`: `CONFIRMED` → disputa; `PENDING` y `REVERSED` → `TransactionNotDisputableError` sin llamar a `add`.
  - `test_ac_004_05_...`: transacciones de hace 1, 90 y 400 días respecto al reloj abren la disputa (el `occurred_at` entra en el Arrange).
  - `test_ac_004_07_...`: con `D-OLD` `OPEN` → `DisputeAlreadyOpenError` con `dispute_id = "D-OLD"` y una sola disputa; con `CLOSED` o `REJECTED` → disputa nueva con otro ID.
  - `test_ac_004_08_...`: segunda ejecución con `K-1`, `TX-L1` y el mismo motivo, con el reloj una hora después → misma `Dispute` (ID y `opened_at`), `replayed = true`, 1 sola disputa.
  - `test_ac_004_09_...`: `K-1` con `TX-L2` y con `DUPLICATE_CHARGE` → `InvalidInputError` sin llamar a `add`.
  - `test_ac_004_10_...`: `K-1` usado en `A`; en `B`, verificada para `C-0001`, → `DisputeAlreadyOpenError` con el ID de `A`.
  - `test_ac_004_11_...`: `TX-P1` de `C-0002` y `TX-9999` → `TransactionNotFoundError` en ambos; el repositorio se consulta con el `customer_id` del almacén.
  - `test_ac_004_12_...`: las 4 situaciones → `IdentityNotVerifiedError` sin llamar a los repositorios; el almacén queda igual (RN-004-14).
  - `test_ac_004_14_...`: las 5 filas devuelven el primer resultado según RN-004-10.
  - `test_ac_004_16_...`: con `FailingDisputeRepository` → `CoreUnavailableError` sin el texto de la excepción y sin disputas; tras `repair()`, la misma solicitud con `K-1` crea la disputa con `replayed = false`.
- **Green:** `OpenDisputeCommand(conversation_id, transaction_id, reason, idempotency_key)` (todos `str | None`), `OpenDisputeResult(dispute, transaction, replayed)` y `OpenDispute(transactions, disputes, store, audit_log, clock).execute(command)`, en el orden de RN-004-10: `DisputeRequest.create`; `store.get` → `IdentityNotVerifiedError`; `find_by_idempotency_key` → repetición (vuelve a leer la transacción) o `InvalidInputError`; `find_customer_transaction` → `TransactionNotFoundError`; estado → `TransactionNotDisputableError`; `find_open_by_transaction` → `DisputeAlreadyOpenError`; `add(..., DisputeStatus.OPEN, clock.now())`. Las excepciones inesperadas posteriores a la validación se convierten en `CoreUnavailableError`. Nunca llama a `store.save`. El constructor ya recibe `audit_log`, pero esta tarea no lo usa (lo cubre T-004-05).
- **Refactor:** extraer métodos privados por paso si `execute` supera ~30 líneas.
- **Nota:** en una repetición (RN-004-08) la transacción se vuelve a leer; si ya no existe para el cliente, el caso de uso lanza `TransactionNotFoundError`. La spec no define ese caso (decisión menor del subagente); queda para la auditoría de AC (5.5).

### [x] T-004-05 — Auditoría de `OpenDispute`

- **Cubre:** AC-004-17
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-004-01, T-004-04
- **Archivos:** `src/core_banking_mcp/application/use_cases/open_dispute.py`, `tests/unit/core_banking_mcp/application/test_open_dispute_audit.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_open_dispute_audit.py::test_ac_004_17_each_invocation_records_exactly_one_event`
- **Red:** el parametrizado con los 10 casos de AC-004-17 falla porque no se registra ningún evento. En cada caso: exactamente un evento con `conversation_id` (vacío si no llegó), el instante del `FixedClock`, `tool = "iniciar_disputa"`, `input = None`, `transaction_id`, `dispute_reason` e `idempotency_key` recibidos (cada uno `None` si no es válido según RN-004-09, y redactados con `redact_card_numbers`), el `outcome` (`opened` o `replayed` con `dispute_id`; `error` con `error_code` `DISPUTE_ALREADY_OPEN` y el `dispute_id` existente, `TRANSACTION_NOT_DISPUTABLE`, `NOT_FOUND`, `INVALID_INPUT`, `IDENTITY_NOT_VERIFIED` o `INTERNAL`), `rule` y `reason`. Con `reason = "FRAUD"`, `dispute_reason` es `None`. Con `transaction_id = "4111111111114321"`, el evento trae `"[REDACTED]"`. Con `idempotency_key = "pago-4111111111114321"`, trae `"pago-[REDACTED]"`. Ni el evento serializado con `dataclasses.asdict` ni su texto contienen `4111111111114321` ni `D-1001`.
- **Green:** `OpenDispute` llama a `audit_log.record(AuditEvent(...))` una vez en cada salida, con las reglas del plan §1, motivo en español y `customer_id` verificado cuando ya se conoce.
- **Refactor:** consolidar la construcción del evento en un método privado `_record`, como en `ListCardTransactions`.

### [x] T-004-06 — Esquemas MCP de `iniciar_disputa` y catálogo `ErrorCode` (contrato)

- **Cubre:** AC-004-15 (campos exactos, `additionalProperties: false`), AC-004-02 (enum de `reason` en la salida), AC-004-03 (enum publicado en la entrada), AC-004-04 y AC-004-07 (catálogo con `TRANSACTION_NOT_DISPUTABLE` y `DISPUTE_ALREADY_OPEN`), AC-004-11 (catálogo con `NOT_FOUND`), AC-004-13 y AC-004-16 (sobre `ToolErrorOut`), AC-004-01 (la salida cumple `IniciarDisputaOut`)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `tests/contract/core_banking_mcp/test_iniciar_disputa_contract.py`, `tests/contract/core_banking_mcp/test_buscar_cliente_contract.py`, `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`, `tests/contract/core_banking_mcp/test_consultar_transacciones_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_iniciar_disputa_contract.py::test_ac_004_15_iniciar_disputa__output_schema__has_exactly_spec_fields`
- **Red:** falla con `ImportError` porque `IniciarDisputaOut` no existe. Además:
  - `IniciarDisputaOut` tiene `additionalProperties: false` y exactamente `dispute_id`, `status`, `opened_at`, `reason` y `transaction`; `transaction` es `TransactionItemOut`; `status` admite solo `OPEN`; `reason` admite solo los 5 códigos (`test_ac_004_02_...`).
  - `IniciarDisputaIn` declara los 4 campos con `description`, y `reason` publica el `enum` de los 5 códigos (`test_ac_004_03_...`).
  - `ErrorCode` es exactamente `{INVALID_INPUT, IDENTITY_NOT_VERIFIED, NOT_FOUND, TRANSACTION_NOT_DISPUTABLE, DISPUTE_ALREADY_OPEN, INTERNAL}` (`test_ac_004_04_...`, `test_ac_004_07_...`, `test_ac_004_11_...`) y `ToolErrorOut` sigue con `code`, `message` y `retryable` (`test_ac_004_13_...`, `test_ac_004_16_...`).
  - Las aserciones de catálogo cerrado de `test_buscar_cliente_contract.py`, `test_verificar_identidad_contract.py` y `test_consultar_transacciones_contract.py` fallan con el catálogo nuevo: se actualizan al conjunto de 6 códigos, conservando sus citas de 001–003.
- **Green:** en `schemas.py`, `ErrorCode` gana `TRANSACTION_NOT_DISPUTABLE` y `DISPUTE_ALREADY_OPEN`. Se añaden `IniciarDisputaIn` (`reason` con `json_schema_extra={"enum": [...]}`) e `IniciarDisputaOut` (`extra="forbid"`, `status: Literal["OPEN"]`, `reason: Literal[...]`, `transaction: TransactionItemOut`), todos con `Field(description=...)`.
- **Refactor:** —

### [x] T-004-07 — Tabla `disputes` y adaptador `SqlAlchemyDisputeRepository`

- **Cubre:** AC-004-07 (índice parcial: una sola `OPEN` por transacción), AC-004-08 (búsqueda por clave), AC-004-16 (rollback, nada registrado) — nivel repositorio
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-004-03
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_dispute_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_dispute_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_dispute_repository.py::test_ac_004_07_partial_index_rejects_second_open_dispute`
- **Red:** falla porque `DisputeRow` y el adaptador no existen. Con SQLite `:memory:`, clientes de `CustomerBuilder` / `IdentityBuilder` y transacciones de `TransactionBuilder`:
  - `test_ac_004_07_...`: un segundo `add` `OPEN` sobre la misma transacción lanza una excepción y queda 1 sola `OPEN`; con la previa `CLOSED` o `REJECTED`, el `add` `OPEN` funciona. `find_open_by_transaction` devuelve solo la `OPEN`.
  - `test_ac_004_08_...`: `find_by_idempotency_key("A", "K-1")` devuelve la disputa creada con esos datos; `("B", "K-1")` devuelve `None`; la pareja `(conversation_id, idempotency_key)` es única.
  - `test_ac_004_16_...`: tras un `add` que falla (índice parcial o clave duplicada), la sesión sigue usable (una lectura y un `add` válido posteriores funcionan) y no queda la fila fallida.
  - Soporte: `add` asigna `DSP-000001`, `DSP-000002`, …; `opened_at` en `−05:00` se guarda en UTC y vuelve con `tzinfo=UTC`.
- **Green:** `DisputeRow` (plan §4: PK `dispute_id`, FK `transaction_id`, `conversation_id`, `idempotency_key`, `reason`, `status`, `opened_at`), con índice único `(conversation_id, idempotency_key)` e índice único parcial `ux_disputes_open_transaction` (`sqlite_where=status = 'OPEN'`). `SqlAlchemyDisputeRepository(session)` implementa el puerto; `add` hace `commit` y, ante cualquier excepción, `rollback` y la relanza.
- **Refactor:** —

### [x] T-004-08 — `SqlAlchemyTransactionRepository.find_customer_transaction`

- **Cubre:** AC-004-06 (tarjeta en cualquier estado), AC-004-11 (transacción ajena o inexistente) — nivel repositorio
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-004-03
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_transaction_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_transaction_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_transaction_repository.py::test_ac_004_11_find_customer_transaction_ignores_other_customers`
- **Red:** falla porque el método no existe. Con SQLite `:memory:`:
  - `test_ac_004_11_...`: `find_customer_transaction("C-0001", "TX-P1")` (de `C-0002`) y `("C-0001", "TX-9999")` devuelven `None`; `("C-0001", "TX-L1")` devuelve la `Transaction` con `card_id`, `card_last4`, monto y estado correctos.
  - `test_ac_004_06_...`: con la tarjeta `4321` activa, bloqueada y cancelada (el estado entra en el Arrange), la transacción se encuentra.
  - Los tests existentes de 003 del archivo siguen en verde.
- **Green:** `find_customer_transaction` con `JOIN cards` filtrando `CardRow.customer_id == customer_id` y `TransactionRow.transaction_id == transaction_id`, con el mismo mapeo a `Transaction` que `find_transactions`.
- **Refactor:** extraer el mapeo fila → `Transaction` a una función privada compartida por los dos métodos.

### [x] T-004-09 — Serialización JSON de los campos nuevos de auditoría

- **Cubre:** AC-004-17 (nivel integración del adaptador); regresión de AC-001-13, AC-002-15 y AC-003-17
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-004-03
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/integration/core_banking_mcp/audit/test_json_audit_log.py::test_ac_004_17_iniciar_disputa_event_is_serialized_without_pan`
- **Red:** los tests existentes de 001–003 fallan porque las claves nuevas (`transaction_id`, `dispute_reason`, `idempotency_key`, `dispute_id` a `null`) aparecen en sus líneas. El test nuevo: un evento de `iniciar_disputa` con `transaction_id = "[REDACTED]"`, `dispute_reason`, `idempotency_key` y `dispute_id` escribe una línea JSON válida con esos campos y sin ningún PAN ni documento; un evento con esos campos a `None` no trae las claves; nada en `stdout`.
- **Green:** añadir los 4 campos a `_OPTIONAL_KEYS` de `JsonAuditLog`. Las líneas de 001–003 quedan idénticas.
- **Refactor:** —

### [x] T-004-10 — Semillas de disputas

- **Cubre:** AC-004-07 (con datos semilla); habilita el smoke por stdio (T-004-13) y la prueba manual (plan §4 Semillas)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-004-07
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/disputes.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/customers.py`, `src/core_banking_mcp/server.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_seeds.py::test_support_seed_database_seeds_disputes_once`
- **Red:** falla porque `seed_database` no recibe el repositorio de disputas. Tras `seed_database(customers, transactions, disputes)` dos veces, existen exactamente las 3 disputas del plan §4 (`DSP-000001` `OPEN` sobre `TX-000002`, `DSP-000002` `CLOSED` sobre `TX-000006`, `DSP-000003` `REJECTED` sobre `TX-000008`), y `find_open_by_transaction("TX-000002")` devuelve `DSP-000001` mientras que `TX-000006` y `TX-000008` no tienen disputa abierta. El test cita `# Regla: RN-004-07 — ...` y `# AC-004-07 · Art. 1` (lo que ejecuta: una transacción con disputa `OPEN` frente a otras con disputas cerradas o rechazadas). Se adaptan las llamadas existentes de `test_seeds.py` a la nueva firma.
- **Green:** `SEED_DISPUTES` (los 3 registros del plan §4, `conversation_id = "SEED"`, claves `SEED-1`…`SEED-3`, instantes en `−05:00`) y `seed_disputes(repository)`. `seed_database(customers, transactions, disputes)` siembra las disputas solo cuando siembra los clientes. `server.py` crea `SqlAlchemyDisputeRepository(session)` y lo pasa a `seed_database`, sin registrar todavía la herramienta.
- **Refactor:** —

### [x] T-004-11 — Herramienta `iniciar_disputa` (camino exitoso)

- **Cubre:** AC-004-01, AC-004-02, AC-004-04 (fila `CONFIRMED`), AC-004-05, AC-004-06, AC-004-07 (filas `CLOSED` y `REJECTED`), AC-004-08, AC-004-15
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-004-04, T-004-06, T-004-07, T-004-08
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/transaction_tools.py`, `src/core_banking_mcp/infrastructure/inbound/mcp/dispute_tools.py`, `tests/integration/core_banking_mcp/mcp/test_iniciar_disputa_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_iniciar_disputa_tool.py::test_ac_004_01_iniciar_disputa__confirmed_transaction__opens_dispute`
- **Red:** falla porque `register_dispute_tools` no existe. Con una sesión MCP en memoria (`mcp.shared.memory`), SQLite `:memory:` con clientes y transacciones de builders, el `InMemoryConversationVerificationStore` real con la conversación `A` verificada para `C-0001`, `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`:
  - AC-004-01: `status = "OPEN"`, `opened_at = "2026-10-17T10:00:00-05:00"`, `reason = "UNRECOGNIZED_CHARGE"` y `transaction` con los 8 campos exactos (`masked_card = "**** 4321"`); 1 fila en `disputes`; la transacción sigue `CONFIRMED`, la tarjeta activa y el almacén igual.
  - AC-004-02 (5 códigos), AC-004-04 (`CONFIRMED`), AC-004-05 (1, 90 y 400 días), AC-004-06 (tarjeta activa, bloqueada y cancelada).
  - AC-004-07: con la previa `CLOSED` o `REJECTED`, disputa nueva `OPEN` con otro `dispute_id`.
  - AC-004-08: la segunda llamada con `K-1` y el reloj una hora después devuelve el mismo `dispute_id` y `opened_at` (no `DISPUTE_ALREADY_OPEN`) y hay 1 fila.
  - AC-004-15: la respuesta serializada solo tiene los campos de RN-004-12; ni `dispute_id` ni `card_id` contienen el PAN; en ninguna parte aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`.
  - Los tests de 003 siguen en verde tras renombrar `_to_item` a `to_transaction_item`.
- **Green:** en `transaction_tools.py`, `_to_item` pasa a `to_transaction_item` (público) sin cambiar su comportamiento. `register_dispute_tools(mcp, open_dispute)` registra `iniciar_disputa` con firma `str | None` en los 4 campos, `Field(description=...)` (`reason` con el `enum`) y docstring en español (spec §7: requiere identidad verificada, cuándo usarla y cuándo no, efectos e idempotencia). Devuelve `CallToolResult` con `structuredContent` de `IniciarDisputaOut` (`opened_at` en Bogotá, `transaction` con `to_transaction_item`) y registra `ErrorPassthroughMetadata`, como `transaction_tools.py`. El mapeo de errores queda para T-004-12.
- **Refactor:** —

### [x] T-004-12 — `iniciar_disputa`: errores, identidad y auditoría

- **Cubre:** AC-004-03, AC-004-04 (filas `PENDING` y `REVERSED`), AC-004-07 (fila `OPEN`), AC-004-09, AC-004-10, AC-004-11, AC-004-12, AC-004-13, AC-004-14, AC-004-16, AC-004-17
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-004-05, T-004-09, T-004-11
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/dispute_tools.py`, `tests/integration/core_banking_mcp/mcp/test_iniciar_disputa_errors.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_iniciar_disputa_errors.py::test_ac_004_12_iniciar_disputa__unverified_conversation__returns_identity_not_verified`
- **Red:** falla porque las excepciones del caso de uso se propagan sin sobre de error. Con la misma sesión MCP en memoria:
  - AC-004-12: las 4 situaciones devuelven `isError=true`, `IDENTITY_NOT_VERIFIED`, `retryable = false`, sin disputas, y el almacén queda igual. La de dos conversaciones registra también `verificar_identidad` en el servidor de prueba: `A` se verifica con esa herramienta y la solicitud se hace en `B`.
  - AC-004-03 (5 filas), AC-004-13 (7 filas) y AC-004-09 (2 filas): `INVALID_INPUT` con `retryable = false` y sin disputas adicionales.
  - AC-004-04: `PENDING` y `REVERSED` → `TRANSACTION_NOT_DISPUTABLE` con `retryable = false` y sin disputas.
  - AC-004-07: con `D-OLD` `OPEN` → `DISPUTE_ALREADY_OPEN` con `retryable = false`, `message` que contiene `D-OLD` y una sola disputa.
  - AC-004-10: `A` y `B` verificadas con `verificar_identidad` para `C-0001`; `B` con `K-1` recibe `DISPUTE_ALREADY_OPEN` con el ID de `A` y hay 1 fila.
  - AC-004-11: `TX-P1` (de `C-0002`) y `TX-9999` devuelven sobres `NOT_FOUND` iguales campo a campo, sin datos de `C-0002` y sin disputas.
  - AC-004-14: las 5 filas devuelven el resultado esperado.
  - AC-004-16: con `FailingDisputeRepository`, `INTERNAL` con `retryable = false`, sin disputas y sin el texto de la excepción, trazas ni SQL.
  - AC-004-17: con un `JsonAuditLog` real sobre un `StringIO`, cada uno de los 10 casos deja una sola línea JSON con la herramienta, `transaction_id`, `dispute_reason`, `idempotency_key` y el resultado esperado; ninguna línea contiene `4111111111114321` ni `D-1001`.
- **Green:** en `dispute_tools.py`: `InvalidInputError` → `tool_error(INVALID_INPUT, "Los datos de la solicitud no son válidos (campo: {error.field}).", retryable=False)`; `IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED` con mensaje fijo; `TransactionNotFoundError` → `NOT_FOUND` con una constante única de módulo; `TransactionNotDisputableError` → `TRANSACTION_NOT_DISPUTABLE` con mensaje fijo; `DisputeAlreadyOpenError` → `DISPUTE_ALREADY_OPEN` con `"La transacción ya tiene una disputa abierta: {dispute_id}."`; `CoreUnavailableError` y un *catch-all* defensivo → `INTERNAL` con mensaje fijo. Ningún mensaje incluye el texto de la excepción ni el valor recibido, salvo el `dispute_id` existente.
- **Refactor:** —

### [x] T-004-13 — Cableado del servidor, catálogo y smoke por stdio

- **Cubre:** AC-004-01 (por stdio real con las semillas), AC-004-12 (almacén compartido con `verificar_identidad`); catálogo de herramientas (`mcp-testing.md` §7)
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-004-10, T-004-12
- **Archivos:** `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_004_15_catalog_exposes_iniciar_disputa_with_spec_schemas`
- **Red:** el catálogo falla porque `list_tools` no incluye `iniciar_disputa`. El test espera las cuatro herramientas, compara el esquema de entrada (4 campos con descripción y el `enum` de `reason`) y el de salida con `IniciarDisputaOut.model_json_schema()` (`additionalProperties: false`), y falla ante herramientas no declaradas; los tests existentes de 001–003 del archivo pasan a esperar las cuatro herramientas. `test_server_module.py`: `server.mcp` expone las cuatro herramientas. `test_stdio_smoke.py`, por stdio real y base sembrada:
  - `test_ac_004_01_iniciar_disputa__stdio_server__opens_dispute_on_seeded_transaction`: tras `verificar_identidad` de `C-0001`, `iniciar_disputa` sobre `TX-000001` devuelve `status = "OPEN"` y `transaction.transaction_id = "TX-000001"`.
  - `test_ac_004_12_iniciar_disputa__stdio_server__unverified_conversation_is_rejected`: otra conversación devuelve `IDENTITY_NOT_VERIFIED`.
  - `stdout` solo lleva protocolo.
- **Green:** `build_server` construye `OpenDispute(transaction_repository, dispute_repository, store, JsonAuditLog(), SystemClock())` con la **misma** instancia de `InMemoryConversationVerificationStore` que `VerifyIdentity` y `ListCardTransactions`, y llama a `register_dispute_tools`. `main()` y el `__getattr__` no cambian.
- **Refactor:** —

### [x] T-004-14 — Verificación final

- **Cubre:** Definition of Done (§5.5): AC-004-01…17 en verde, cobertura, lint, formato y tipado
- **App / capa:** `core_banking_mcp` / todas
- **Depende de:** T-004-01, T-004-02, T-004-03, T-004-04, T-004-05, T-004-06, T-004-07, T-004-08, T-004-09, T-004-10, T-004-11, T-004-12, T-004-13
- **Archivos:** — (solo verificación; no modifica archivos)
- **Test primero:** `uv run pytest --cov` (suite completa de 001–004)
- **Red:** si algún comando falla, la tarea queda `[ ]` con el motivo y se corrige en la tarea que corresponda.
- **Green:** pasan sin errores: `uv run pytest --cov` (umbral global ≥ 80 %), `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.
- **Refactor:** —

## Correcciones de la primera auditoría de AC (fase 5.5, veredicto «No cumple»: 1 Bloqueante, 2 Mayores y 3 Menores)

Cambios de trazabilidad en los tests, sin cambio de comportamiento ni de `src/` (§4.3.5): no hay Red de pytest; el Red es el hallazgo de `verify-ac-coverage` (`H-01…H-06`). La suite debe seguir en verde. Siguen la regla única de la cabecera: cada RN citada debe figurar en el `Cubre:` de su AC en `spec.md`, el enunciado de `Regla:` es el literal de spec §4, y un test solo cita un AC cuyo Given/When/Then ejecuta. Fuera de esta ronda: H-06 (convención de nombres de persistencia y auditoría, coherente con 001–003; no bloquea).

### [x] T-004-15 — H-01 y H-05: citas de los tests de repositorio de disputas y de semillas

- **Cubre:** corrige H-01 y H-05
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound` (tests)
- **Depende de:** T-004-14
- **Archivos:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_dispute_repository.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`
- **Test primero:** los mismos tests existentes de esos dos archivos (deben seguir en verde)
- **Red:** hallazgo H-01: `test_support_add_assigns_sequential_ids_and_stores_utc` (~línea 145) está en `tests/integration` y no tiene línea `Regla:` ni `AC-` (`mcp-testing.md` §4). Hallazgo H-05: `test_support_seed_database_seeds_disputes_once` (~líneas 126-129) cita `RN-004-07` y `AC-004-07` pero solo verifica que se siembren las disputas.
- **Green:** H-01: añadir `# Regla: RN-004-11 — <enunciado literal de spec §4>` y `# AC-004-01 · Art. 3`, conservando el comentario `# Soporte de tests`; comprobar en `spec.md` que `RN-004-11` figura en el `Cubre:` de AC-004-01 y que el test realmente verifica esa regla (`dispute_id` opaco y único, `opened_at` como instante UTC). H-05: dejar el test como soporte de semillas (`# Invariante: Art. 1 — datos semilla ficticios y reproducibles`) sin citar `AC-004-07`/`RN-004-07`, o ajustar los asertos para que ejerzan la regla; elegir lo más simple y verificar con grep que nada más cita el nombre. No cambiar `src/`.
- **Refactor:** —

### [x] T-004-16 — H-02 y H-04: citas y asertos de los tests de contrato

- **Cubre:** corrige H-02 y H-04
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound` (tests)
- **Depende de:** T-004-14
- **Archivos:** `tests/contract/core_banking_mcp/test_iniciar_disputa_contract.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`
- **Test primero:** los mismos tests existentes de esos dos archivos (deben seguir en verde)
- **Red:** hallazgo H-02 (~líneas 54-55): el test de AC-004-02 cita `RN-004-11`, cuyo AC no la incluye en `Cubre:` (AC-004-02: HU-004-01, RN-004-02). Hallazgo H-04 (~líneas 102-106): el comentario dice que los esquemas de entrada y salida son cerrados con `additionalProperties: false`, pero solo se comprueba el de salida.
- **Green:** H-02: quitar la línea `RN-004-11` (dejar la de `RN-004-02`) o mover el aserto de `status = OPEN` a un test citado bajo AC-004-01; verificar en `spec.md` cada RN citada. H-04: añadir el aserto de `inputSchema` (o ajustar el comentario a lo que realmente se comprueba, lo más simple); si se afirma `additionalProperties: false` en la entrada, comprobar antes que el esquema de entrada de `IniciarDisputaIn` lo declara, sin cambiar `src/` (si no lo declara, ajustar el comentario).
- **Refactor:** —

### [x] T-004-17 — H-03: citas y asertos de los tests de smoke por stdio

- **Cubre:** corrige H-03
- **App / capa:** `core_banking_mcp` / arranque (tests)
- **Depende de:** T-004-14
- **Archivos:** `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-03 (~líneas 186-190 y 227-229): los enunciados de `Regla:` no son los de spec §4 y `RN-004-14` se cita sin que el test compruebe lo que dice la regla (la herramienta no cambia la transacción, la tarjeta ni el estado de verificación); en el test de rechazo, el aserto de «no revela datos» es de `RN-004-13`; `RN-004-11` y `RN-004-12` se citan pero solo se afirma `status` y `transaction_id`.
- **Green:** citar el enunciado literal de spec §4 de cada RN. Quitar `RN-004-14` de ambos tests o añadir los asertos que la sustenten; en el de rechazo citar solo RN que figuren en el `Cubre:` de AC-004-12 (RN-004-03 y RN-004-14) y ajustar los asertos al enunciado. Si se cita `RN-004-11` o `RN-004-12`, afirmar también `opened_at`, `reason` y los campos de `transaction`; si no, quitar la cita. Verificar en `spec.md` que cada RN citada figura en el `Cubre:` del AC citado. No cambiar `src/`.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-004-01 | T-004-04, T-004-06, T-004-11, T-004-13 | `test_ac_004_01_opens_dispute_on_confirmed_transaction`, `test_ac_004_01_iniciar_disputa__confirmed_transaction__opens_dispute`, `test_ac_004_01_iniciar_disputa__stdio_server__opens_dispute_on_seeded_transaction` |
| AC-004-02 | T-004-02, T-004-04, T-004-06, T-004-11 | `test_ac_004_02_dispute_request_accepts_every_reason`, `test_ac_004_02_*` (caso de uso, contrato y herramienta) |
| AC-004-03 | T-004-02, T-004-04, T-004-06, T-004-12 | `test_ac_004_03_dispute_request_rejects_invalid_reason`, `test_ac_004_03_*` (caso de uso, contrato y herramienta) |
| AC-004-04 | T-004-04, T-004-06, T-004-11, T-004-12 | `test_ac_004_04_*` (caso de uso, contrato y herramienta) |
| AC-004-05 | T-004-04, T-004-11 | `test_ac_004_05_*` (caso de uso y herramienta) |
| AC-004-06 | T-004-08, T-004-11 | `test_ac_004_06_*` (repositorio y herramienta) |
| AC-004-07 | T-004-04, T-004-06, T-004-07, T-004-10, T-004-11, T-004-12 | `test_ac_004_07_partial_index_rejects_second_open_dispute`, `test_support_seed_database_seeds_disputes_once`, `test_ac_004_07_*` (caso de uso, contrato y herramienta) |
| AC-004-08 | T-004-04, T-004-07, T-004-11 | `test_ac_004_08_*` (caso de uso, repositorio y herramienta) |
| AC-004-09 | T-004-04, T-004-12 | `test_ac_004_09_*` (caso de uso y herramienta) |
| AC-004-10 | T-004-04, T-004-12 | `test_ac_004_10_*` (caso de uso y herramienta) |
| AC-004-11 | T-004-04, T-004-06, T-004-08, T-004-12 | `test_ac_004_11_find_customer_transaction_ignores_other_customers`, `test_ac_004_11_*` (caso de uso, contrato y herramienta) |
| AC-004-12 | T-004-04, T-004-12, T-004-13 | `test_ac_004_12_iniciar_disputa__unverified_conversation__returns_identity_not_verified`, `test_ac_004_12_iniciar_disputa__stdio_server__unverified_conversation_is_rejected`, `test_ac_004_12_*` (caso de uso) |
| AC-004-13 | T-004-02, T-004-04, T-004-06, T-004-12 | `test_ac_004_13_dispute_request_rejects_invalid_fields`, `test_ac_004_13_*` (caso de uso, contrato y herramienta) |
| AC-004-14 | T-004-04, T-004-12 | `test_ac_004_14_*` (caso de uso y herramienta) |
| AC-004-15 | T-004-06, T-004-11, T-004-13 | `test_ac_004_15_iniciar_disputa__output_schema__has_exactly_spec_fields`, `test_ac_004_15_catalog_exposes_iniciar_disputa_with_spec_schemas`, `test_ac_004_15_*` (herramienta) |
| AC-004-16 | T-004-04, T-004-06, T-004-07, T-004-12 | `test_ac_004_16_*` (caso de uso, contrato, repositorio y herramienta) |
| AC-004-17 | T-004-01, T-004-05, T-004-09, T-004-12 | `test_ac_004_17_redact_card_numbers_replaces_13_to_19_digit_runs`, `test_ac_004_17_each_invocation_records_exactly_one_event`, `test_ac_004_17_iniciar_disputa_event_is_serialized_without_pan`, `test_ac_004_17_*` (herramienta) |

**Casos de escalamiento (spec §8):** `INTERNAL` con `retryable = false` → AC-004-16 (T-004-04, T-004-07, T-004-12). **Art. 7 (sin identificación previa):** AC-004-12 (T-004-04, T-004-12, T-004-13), con la comprobación de que la herramienta no escribe en el almacén (RN-004-14). **Tabla `DP-`:** no aplica. **Tareas de soporte sin AC propio:** T-004-03.

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [ ] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
