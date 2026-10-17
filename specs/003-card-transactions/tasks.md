# Tareas: Consultar las transacciones de una tarjeta del cliente en un rango de fechas

| Campo | Valor |
|---|---|
| Feature | `003-card-transactions` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-17 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas relativas a la raíz del repositorio. Los `__init__.py` de los paquetes ya existen (`domain/models`, `application/ports`, `application/use_cases`, `infrastructure/inbound/mcp`, `infrastructure/outbound/persistence` y `seeds`). Solo T-003-05 escribe en `tests/fakes/`; las demás tareas reutilizan los fakes sin modificarlos. Las tareas que cambian un contrato que usan los tests de 001/002 (catálogo `ErrorCode` en T-003-08, `card_ref` en T-003-09, firma de `seed_database` en T-003-11) adaptan esos tests en la misma tarea, para que la suite siga en verde al terminar cada oleada.

**Comentarios de trazabilidad (regla única, aprendida de las auditorías de 002; `mcp-testing.md` §4–5):**

1. Un test llamado `test_ac_003_NN_*` lleva encima `# Regla: RN-003-XX — <enunciado fiel de spec §4>` (una línea por RN), **donde cada RN citada figura en la línea `Cubre:` de AC-003-NN**, y `# AC-003-NN · Art. N`. Solo se usa ese prefijo si el test ejecuta el Given/When/Then de ese AC (o una de sus filas).
2. Un test de invariante (Art. 7, sin identificación) cita `# Invariante: Art. N — <enunciado>` y la línea `AC-003-NN · Art. N` del AC al que da soporte, con las mismas condiciones.
3. Un test de soporte puro (fakes, builders, mapeos técnicos sin AC) no lleva el prefijo `ac_003_` y declara `# Soporte de tests: <qué> · Art. 3`, fuera de la trazabilidad de AC.
4. Los tests de `tests/contract/` e `tests/integration/` se nombran `test_ac_003_NN_<tool>__<condición>__<resultado>`; los parametrizados llevan `ids=` legibles.

---

## Tareas

### [x] T-003-01 — Parseo estricto de fechas compartido (`parse_iso_date`)

- **Cubre:** AC-003-09 (fecha inexistente y formato distinto de `AAAA-MM-DD`, nivel dominio); refactor de 002 sin cambio de comportamiento (plan §2)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/dates.py`, `src/core_banking_mcp/domain/models/identity.py`, `tests/unit/core_banking_mcp/domain/test_dates.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_dates.py::test_ac_003_09_parse_iso_date_rejects_invalid_format_and_nonexistent_dates`
- **Red:** falla con `ImportError` porque `domain/dates.py` no existe. Parametrizado: `None`, `""`, `"01/09/2026"`, `"2026-09-31"`, `"20260901"`, `"2026-W36-2"`, `" 2026-09-01"` y dígitos no ASCII lanzan `InvalidInputError` con el `field` recibido; `"2026-09-01"` devuelve `date(2026, 9, 1)` (`test_parse_iso_date_returns_date_for_valid_input`, soporte). La regresión de 002 (`test_verification_request.py`, AC-002-08/09) debe seguir en verde.
- **Green:** `parse_iso_date(field: str, value: str | None) -> date` con `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")` y `date(...)` capturando `ValueError`, con los mismos mensajes que hoy usa `identity.py`. `identity._parse_date` llama a `parse_iso_date` y conserva la comprobación de "no puede ser posterior a hoy". Solo stdlib.
- **Refactor:** —

### [x] T-003-02 — Value objects `TransactionStatus`, `Transaction` y `CustomerCard`

- **Cubre:** AC-003-03 (los tres estados), AC-003-16 (monto `Decimal` y moneda ISO 4217, nivel dominio); habilita AC-003-01…18 (plan §4 Dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/models/transaction.py`, `tests/unit/core_banking_mcp/domain/test_transaction.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_transaction.py::test_ac_003_16_transaction_accepts_amounts_with_up_to_two_decimals`
- **Red:** falla con `ImportError` porque `transaction.py` no existe. Casos: `Decimal("125000")`, `Decimal("49.9")` y `Decimal("0.05")` se aceptan (AC-003-16); `test_ac_003_03_transaction_accepts_every_status` con `CONFIRMED`, `PENDING` y `REVERSED`; soporte (`# Soporte de tests: invariantes de Transaction · Art. 3`): se rechazan monto `0`, negativo y `Decimal("1.005")`, monedas `"cop"`, `"CO"`, `"COPX"`, `"C0P"`, `occurred_at` sin zona horaria, `transaction_id`, `card_id` o `merchant` vacíos y `card_last4` que no son 4 dígitos; `CustomerCard` rechaza `card_id` vacío y `last4` inválido.
- **Green:** `TransactionStatus(Enum)`; `CustomerCard(card_id, last4)` y `Transaction(transaction_id, card_id, card_last4, occurred_at, merchant, amount, currency, status)` como `dataclass(frozen=True)` con invariantes en `__post_init__` lanzando `InvalidInputError`. Solo stdlib (`decimal`, `datetime`, `enum`).
- **Refactor:** extraer la validación de 4 dígitos a una función privada reutilizable por `TransactionQuery` (T-003-03).

### [x] T-003-03 — `BogotaDateRange` y validación de la consulta `TransactionQuery`

- **Cubre:** AC-003-02 (límites del rango en Bogotá), AC-003-07 (máximo 90 días), AC-003-09 (datos inválidos), AC-003-10 ("hoy" en Bogotá) — nivel dominio
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-003-01, T-003-02
- **Archivos:** `src/core_banking_mcp/domain/models/transaction.py`, `tests/unit/core_banking_mcp/domain/test_transaction_query.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_transaction_query.py::test_ac_003_09_invalid_query_is_rejected`
- **Red:** falla porque `TransactionQuery` no existe. Tests:
  - `test_ac_003_09_...`: las 13 filas de AC-003-09 con `today = 2026-10-17` (`None` = ausente) lanzan `InvalidInputError`.
  - `test_ac_003_07_range_limit_counts_both_ends`: 1, 89 y 90 días y `2019-01-01`…`2019-01-31` válidos; `2026-06-01`…`2026-08-30` (91 días, borde exacto) inválido.
  - `test_ac_003_10_query_date_to_limit_uses_today_in_bogota`: con `today_in_bogota` de `2026-10-17T15:00:00Z`, `2026-10-18T03:00:00Z` y `2026-10-18T05:00:00Z`, `date_to` = hoy es válida y `date_to = 2026-10-18` solo es válida en el tercer caso.
  - `test_ac_003_02_utc_bounds_follow_bogota_days`: los 6 instantes de AC-003-02 caen dentro o fuera de `[inicio, fin)` de `BogotaDateRange(2026-09-01, 2026-09-30).utc_bounds()` según la tabla (inicio `2026-09-01T05:00:00Z`, fin `2026-10-01T05:00:00Z`).
  - Soporte: `conversation_id` y `card_last4` se recortan / no se recortan según RN-003-06 (`" 4321"` es inválido), y una fecha de campo inválida se informa antes que el rango.
- **Green:** `MAX_RANGE_DAYS = 90`; `BogotaDateRange(date_from, date_to)` con invariantes y `utc_bounds()` (offset fijo UTC−05:00, como `domain/clock.py`); `TransactionQuery(conversation_id, card_last4, date_range)` con `create(conversation_id, card_last4, date_from, date_to, today)`, usando `parse_iso_date`. Solo stdlib.
- **Refactor:** reutilizar la constante de zona de `domain/clock.py` si se puede exponer sin cambiar su API.

### [x] T-003-04 — Tope de resultados `TransactionListResult`

- **Cubre:** AC-003-06 (sin transacciones), AC-003-08 (tope de 50) — nivel dominio
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-003-03
- **Archivos:** `src/core_banking_mcp/domain/models/transaction.py`, `tests/unit/core_banking_mcp/domain/test_transaction_list_result.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_transaction_list_result.py::test_ac_003_08_more_than_fifty_requires_refinement`
- **Red:** falla porque `TransactionListResult` no existe. Parametrizado 49 → 49/`false`, 50 → 50/`false`, 51 → 0/`true` (borde exacto); `test_ac_003_06_no_matches_is_empty_success`: `from_matches([])` → `()` y `false`; soporte: el orden recibido se conserva y `refinement_required = true` con transacciones es inválido.
- **Green:** `MAX_TRANSACTIONS = 50`; `TransactionListResult(transactions, refinement_required)` con `from_matches(matches)`, siguiendo el patrón de `CustomerSearchResult`.
- **Refactor:** —

### [x] T-003-05 — Puerto `TransactionRepository`, errores, `AuditEvent` ampliado y fakes

- **Cubre:** habilita AC-003-01…18 en unit e integración (plan §3 y §6)
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-003-02
- **Archivos:** `src/core_banking_mcp/application/ports/transaction_repository.py`, `src/core_banking_mcp/application/errors.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `tests/fakes/transaction_builder.py`, `tests/fakes/fake_transaction_repository.py`, `tests/fakes/failing_transaction_repository.py`, `tests/unit/core_banking_mcp/application/test_fakes.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_fakes.py::test_fake_transaction_repository_filters_by_customer_cards_and_interval`
- **Red:** falla con `ImportError` porque no existen el puerto, `TransactionBuilder` ni los fakes. Tests de soporte (`# Soporte de tests: ... · Art. 3`): `TransactionBuilder().build()` crea una `Transaction` válida y admite `with_occurred_at`, `with_status`, `with_amount`, `with_currency`, `with_card` y `with_id`; `FakeTransactionRepository(cards={"C-0001": [CustomerCard(...)]}, transactions=[...])`: `find_customer_cards` devuelve solo tarjetas de ese cliente con ese `last4` (cualquier estado) ordenadas por `card_id`, y `find_transactions` filtra por `card_ids` y `start ≤ occurred_at < end`, ordena por `occurred_at` desc y `transaction_id` asc y aplica `limit`; registra si fue invocado (para comprobar que no se consulta antes de tiempo); `FailingTransactionRepository` lanza `RuntimeError` en ambos métodos; `IdentityNotVerifiedError` y `CardNotFoundError` existen; `AuditEvent` se construye sin los campos nuevos (por defecto `None` / `()`).
- **Green:** puerto `TransactionRepository` (`find_customer_cards(customer_id, last4) -> list[CustomerCard]`, `find_transactions(card_ids, start, end, limit) -> list[Transaction]`); `IdentityNotVerifiedError` y `CardNotFoundError` en `application/errors.py`; `AuditEvent` gana al final `masked_card: str | None = None`, `date_from: str | None = None`, `date_to: str | None = None` y `transaction_ids: tuple[str, ...] = ()`; los fakes y el builder descritos.
- **Refactor:** —

### [x] T-003-06 — Caso de uso `ListCardTransactions` (comportamiento)

- **Cubre:** AC-003-01, AC-003-03, AC-003-04, AC-003-05, AC-003-06, AC-003-07, AC-003-08, AC-003-09, AC-003-10, AC-003-11, AC-003-12, AC-003-13, AC-003-15, AC-003-18
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-003-04, T-003-05
- **Archivos:** `src/core_banking_mcp/application/use_cases/list_card_transactions.py`, `tests/unit/core_banking_mcp/application/test_list_card_transactions.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_list_card_transactions.py::test_ac_003_01_lists_range_transactions_newest_first`
- **Red:** falla porque `ListCardTransactions` no existe. Con `FakeTransactionRepository`, `FakeVerificationStore` (conversación verificada para `C-0001` salvo que se indique), `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`:
  - `test_ac_003_01_...`: devuelve las 3 de septiembre en orden 20, 12, 5 y no la del 2 de octubre.
  - `test_ac_003_03_...` (3 estados), `test_ac_003_04_...` (tarjeta activa, bloqueada, cancelada → 2 transacciones), `test_ac_003_05_...` (dos tarjetas `4321` → 2 transacciones con `card_id` distintos).
  - `test_ac_003_06_...` vacía; `test_ac_003_08_...` pide `limit = 51` al repositorio y con 51 devuelve `refinement_required = true`.
  - `test_ac_003_07_...` y `test_ac_003_09_...`: entradas inválidas lanzan `InvalidInputError` sin consultar el almacén ni el repositorio; `test_ac_003_10_...` con los 3 instantes.
  - `test_ac_003_11_...`: las 4 situaciones (nunca verificada, 1 fallo, bloqueada, verificada solo en `A` y consulta en `B`) lanzan `IdentityNotVerifiedError`, sin llamar al repositorio, y el estado del almacén queda igual (RN-003-14).
  - `test_ac_003_12_...`: las 3 filas devuelven el primer error según RN-003-08.
  - `test_ac_003_13_...`: tarjeta de `C-0002` y `0000` lanzan `CardNotFoundError` igual; el repositorio se consulta con el `customer_id` del almacén.
  - `test_ac_003_15_...`: el orden del repositorio se conserva (dos simultáneas por `transaction_id`).
  - `test_ac_003_18_...`: con `FailingTransactionRepository` → `CoreUnavailableError` sin el texto de la excepción original.
- **Green:** `ListCardTransactionsCommand(conversation_id, card_last4, date_from, date_to)` (todos `str | None`) y `ListCardTransactions(repository, store, audit_log, clock).execute(command) -> TransactionListResult`: valida con `TransactionQuery.create(..., today_in_bogota(clock.now()))`; lee `store.get(conversation_id)` y, si no hay `verified_customer_id`, lanza `IdentityNotVerifiedError`; busca las tarjetas y, si no hay, `CardNotFoundError`; consulta con `utc_bounds()` y `MAX_TRANSACTIONS + 1`; devuelve `TransactionListResult.from_matches`. Las excepciones inesperadas posteriores a la validación se convierten en `CoreUnavailableError`. Nunca llama a `store.save`. El constructor ya recibe `audit_log`, pero esta tarea no lo usa (lo cubre T-003-07).
- **Refactor:** extraer métodos privados por paso si `execute` supera ~30 líneas.
- **Nota:** el subagente informó que escribió test y código antes de ejecutar nada, así que el Red de esta tarea no se evidenció (Art. 3, §5.1); el test de la tarea y la suite completa (439) pasan. Además, `CustomerCard` no tiene estado, así que las filas de AC-003-04 del caso de uso solo comprueban que la consulta no filtra por estado de tarjeta; el estado real se prueba en T-003-10 (repositorio) y T-003-13 (herramienta). Ambos puntos quedan para la auditoría de AC (5.5).

### [x] T-003-07 — Auditoría de `ListCardTransactions`

- **Cubre:** AC-003-17
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-003-06
- **Archivos:** `src/core_banking_mcp/application/use_cases/list_card_transactions.py`, `tests/unit/core_banking_mcp/application/test_list_card_transactions_audit.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_list_card_transactions_audit.py::test_ac_003_17_each_invocation_records_exactly_one_event`
- **Red:** el parametrizado con los 8 casos de AC-003-17 falla porque no se registra ningún evento. En cada caso: exactamente un evento con `conversation_id` (vacío si no llegó), el instante del `FixedClock`, `tool = "consultar_transacciones"`, `input = None`, `masked_card = "**** 4321"` (o `None` si `card_last4` no es válido), `date_from` / `date_to` recibidos, el `outcome` (`found` con `count` y `transaction_ids`; `found` con `count = 0`; `refinement_required`; `error` con `error_code` `INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND` o `INTERNAL`), `rule` y `reason`. Con `card_last4 = "4111111111114321"`, `masked_card` es `None` y ni el evento serializado con `dataclasses.asdict` ni su texto contienen `4111111111114321`.
- **Green:** `ListCardTransactions` llama a `audit_log.record(AuditEvent(...))` una vez en cada salida, con las reglas del plan §1 (`found` → RN-003-05, `refinement_required` → RN-003-10, `INVALID_INPUT` → RN-003-06, `IDENTITY_NOT_VERIFIED` → RN-003-02, `NOT_FOUND` → RN-003-04, `INTERNAL` → RN-003-16), motivo en español y `customer_id` verificado cuando ya se conoce. `masked_card` se calcula con `mask_card` solo si `card_last4` cumple el formato.
- **Refactor:** consolidar la construcción del evento en un método privado `_record`, como en `SearchCustomers`.

### [x] T-003-08 — Esquemas MCP de `consultar_transacciones` y catálogo `ErrorCode` (contrato)

- **Cubre:** AC-003-14 (campos exactos, `additionalProperties: false`), AC-003-03 (enum de `status`), AC-003-08 (`maxItems: 50`), AC-003-16 (`amount` y `currency` como `string`), AC-003-11 y AC-003-13 (catálogo con `IDENTITY_NOT_VERIFIED` y `NOT_FOUND`), AC-003-09 y AC-003-18 (sobre `ToolErrorOut`)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `tests/contract/core_banking_mcp/test_consultar_transacciones_contract.py`, `tests/contract/core_banking_mcp/test_buscar_cliente_contract.py`, `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_consultar_transacciones_contract.py::test_ac_003_14_consultar_transacciones__output_schema__has_exactly_spec_fields`
- **Red:** falla con `ImportError` porque `ConsultarTransaccionesOut` no existe. Además: `TransactionItemOut` tiene `additionalProperties: false` y exactamente los 8 campos de la spec §7; `status` admite solo `CONFIRMED`, `PENDING` y `REVERSED` (`test_ac_003_03_...`); `transactions` tiene `maxItems: 50` (`test_ac_003_08_...`); `amount` y `currency` son `string` (`test_ac_003_16_...`); `ConsultarTransaccionesIn` declara los 4 campos de entrada con `description`; `ErrorCode` es exactamente `{INVALID_INPUT, IDENTITY_NOT_VERIFIED, NOT_FOUND, INTERNAL}` (`test_ac_003_11_...` y `test_ac_003_13_...`) y `ToolErrorOut` sigue con `code`, `message` y `retryable`. Las aserciones de catálogo cerrado de `test_buscar_cliente_contract.py` (línea ~45) y `test_verificar_identidad_contract.py` (línea ~66) fallan con el catálogo nuevo: se actualizan al conjunto de 4 códigos, conservando sus citas de 001/002.
- **Green:** en `schemas.py`, `ErrorCode` gana `IDENTITY_NOT_VERIFIED` y `NOT_FOUND` (docstring genérico del catálogo); `ConsultarTransaccionesIn`, `TransactionItemOut` (`extra="forbid"`, `status: Literal[...]`) y `ConsultarTransaccionesOut` (`extra="forbid"`, `transactions` con `max_length=50`), todos con `Field(description=...)`.
- **Refactor:** —

### [x] T-003-09 — Columna `card_ref`, tabla `transactions` y asignación de `card_ref`

- **Cubre:** AC-003-05 (dos tarjetas con el mismo `last4` reciben `card_id` distintos, nivel persistencia)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_customer_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py::test_ac_003_05_add_assigns_distinct_card_refs_to_same_last4_cards`
- **Red:** falla porque `CardRow` no tiene `card_ref`. Con SQLite `:memory:`: un cliente con dos tarjetas `4321` recibe `CARD-0001` y `CARD-0002`; un segundo cliente continúa con `CARD-0003`; la columna es única; soporte: la tabla `transactions` existe con las columnas del plan §4 tras `create_schema`. Los tests de 001/002 del archivo siguen en verde (`find_matching` y `find_identity` no cambian).
- **Green:** `CardRow.card_ref` (`String`, `unique=True`, `index=True`, no nula); `TransactionRow` (`transaction_id` PK, `card_id` FK indexada, `occurred_at` `DateTime` indexada, `merchant`, `amount_minor` `Integer`, `currency` `String(3)`, `status`) con índice `(card_id, occurred_at)`; `SqlAlchemyCustomerRepository.add` asigna `f"CARD-{n:04d}"` a cada tarjeta nueva según el número de tarjetas ya guardadas.
- **Refactor:** —
- **Nota:** una base SQLite local creada con 001/002 no tiene `card_ref`; hay que borrar `data/core_banking.db` (plan §7).

### [x] T-003-10 — Adaptador `SqlAlchemyTransactionRepository`

- **Cubre:** AC-003-02, AC-003-04, AC-003-05, AC-003-13, AC-003-15, AC-003-16 (nivel repositorio)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-003-03, T-003-05, T-003-09
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_transaction_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_transaction_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_transaction_repository.py::test_ac_003_02_find_transactions_uses_bogota_day_bounds`
- **Red:** falla porque el adaptador no existe. Con SQLite `:memory:`, clientes de `CustomerBuilder` / `IdentityBuilder` y transacciones de `TransactionBuilder`:
  - `test_ac_003_02_...`: los 6 instantes de AC-003-02 aparecen o no con los límites de `BogotaDateRange(...).utc_bounds()`.
  - `test_ac_003_04_...`: `find_customer_cards` encuentra la tarjeta `4321` activa, bloqueada y cancelada.
  - `test_ac_003_05_...`: dos tarjetas `4321` del mismo cliente devuelven dos `CustomerCard` con `card_id` distintos y sus transacciones juntas.
  - `test_ac_003_13_...`: `find_customer_cards("C-0001", "8765")` no devuelve la tarjeta de `C-0002`, y `"0000"` devuelve `[]`.
  - `test_ac_003_15_...`: orden `occurred_at` desc y `transaction_id` asc con dos simultáneas; `limit` se aplica.
  - `test_ac_003_16_...`: `amount_minor` ↔ `Decimal` (`125000.00`, `49.90`, `0.05`) y `currency` se conservan.
  - Soporte: ida y vuelta de `occurred_at` con offset `−05:00` (se guarda en UTC y vuelve con `tzinfo=UTC`).
- **Green:** `SqlAlchemyTransactionRepository(session)` con `find_customer_cards`, `find_transactions` (`JOIN cards`, `card_ref IN`, `start ≤ occurred_at < end`, orden, `limit`) y `add(card_ref, transaction)`; mapea filas a entidades, sin exponer la PK entera.
- **Refactor:** —

### [x] T-003-11 — Semillas de transacciones

- **Cubre:** habilita el smoke por stdio (T-003-15) y la prueba manual (plan §4 Semillas)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-003-10
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/transactions.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/customers.py`, `src/core_banking_mcp/server.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_seeds.py::test_seed_database_seeds_transactions_once`
- **Red:** falla porque `seed_database` no recibe el repositorio de transacciones. Test de soporte (`# Soporte de tests: semillas ficticias reproducibles · Art. 1`): tras `seed_database(customers, transactions)` dos veces, existen exactamente las 9 transacciones del plan §4, con los `card_ref` `CARD-0001`…`CARD-0004` asignados a las tarjetas indicadas, y `find_transactions` de `CARD-0001` del 1 al 30 de septiembre de 2026 devuelve `TX-000004`, `TX-000003`, `TX-000002`, `TX-000001` en ese orden. Se adaptan las llamadas existentes de `test_seeds.py` a la nueva firma.
- **Green:** `SEED_TRANSACTIONS` (los 9 registros del plan §4, instantes en `−05:00`) y `seed_transactions(repository)`; `seed_database(customers, transactions)` siembra las transacciones solo cuando siembra los clientes; `server.py` crea `SqlAlchemyTransactionRepository(session)` y lo pasa a `seed_database` (sin registrar todavía la herramienta).
- **Refactor:** —

### [x] T-003-12 — Serialización JSON de los campos nuevos de auditoría

- **Cubre:** AC-003-17 (nivel integración del adaptador); regresión de AC-001-13 y AC-002-15
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-003-05
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/integration/core_banking_mcp/audit/test_json_audit_log.py::test_ac_003_17_consultar_transacciones_event_is_serialized_without_pan`
- **Red:** los tests existentes de 001/002 (`test_ac_001_13_...`, `test_ac_002_15_...`) fallan porque las claves nuevas (`masked_card: null`, `date_from: null`, `date_to: null`, `transaction_ids: []`) aparecen en sus líneas. El test nuevo: un evento de `consultar_transacciones` con `masked_card = "**** 4321"`, rango y `transaction_ids = ("TX-000001",)` escribe una línea JSON válida con esos campos como lista y cadena, y sin ningún PAN; un evento con `masked_card = None` no trae la clave; nada en `stdout`.
- **Green:** `JsonAuditLog.record` omite `masked_card`, `date_from` y `date_to` cuando son `None` y `transaction_ids` cuando está vacío; serializa `transaction_ids` como lista. Las líneas de 001/002 quedan idénticas.
- **Refactor:** generalizar la omisión de claves opcionales a una tupla de nombres si simplifica el código.

### [x] T-003-13 — Herramienta `consultar_transacciones` (camino exitoso)

- **Cubre:** AC-003-01, AC-003-02, AC-003-03, AC-003-04, AC-003-05, AC-003-06, AC-003-07 (filas exitosas), AC-003-08, AC-003-10 (filas exitosas), AC-003-14, AC-003-15, AC-003-16
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-003-06, T-003-08, T-003-10
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/transaction_tools.py`, `tests/integration/core_banking_mcp/mcp/test_consultar_transacciones_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_consultar_transacciones_tool.py::test_ac_003_01_consultar_transacciones__september_range__lists_newest_first`
- **Red:** falla porque `register_transaction_tools` no existe. Con una sesión MCP en memoria (`mcp.shared.memory`), SQLite `:memory:` con clientes y transacciones de builders, el `InMemoryConversationVerificationStore` real con la conversación verificada para `C-0001`, `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`:
  - AC-003-01: las 3 de septiembre en orden, con los 8 campos y `masked_card = "**** 4321"`; `occurred_at` en ISO 8601 con `−05:00`.
  - AC-003-02 (6 filas), AC-003-03 (3 estados, `amount = "125000.00"`), AC-003-04 (3 estados de tarjeta), AC-003-05 (mismo `masked_card`, `card_id` distintos).
  - AC-003-06 (`{"transactions": [], "refinement_required": false}`), AC-003-07 (filas 1, 89, 90 días y 2019), AC-003-08 (49/50/51), AC-003-10 (filas exitosas con `FixedClock`).
  - AC-003-14: la respuesta serializada solo tiene `transactions` y `refinement_required`, cada transacción solo los campos de RN-003-12, `card_id` no contiene el PAN y en ninguna parte aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`.
  - AC-003-15 (dos simultáneas) y AC-003-16 (`"125000.00"`, `"49.90"`, `"0.05"`).
- **Green:** `register_transaction_tools(mcp, list_card_transactions)` registra `consultar_transacciones` con firma `str | None` en los cuatro campos, `Field(description=...)` y docstring en español (spec §7: requiere identidad verificada, cuándo usarla y cuándo no, solo lectura e idempotente); devuelve `CallToolResult` con `structuredContent` de `ConsultarTransaccionesOut` (`amount` con `f"{amount:.2f}"`, `occurred_at` en Bogotá, `masked_card` con `mask_card`) y registra `ErrorPassthroughMetadata`, como `identity_tools.py`. El mapeo de errores queda para T-003-14.
- **Refactor:** extraer el mapeo `Transaction` → `TransactionItemOut` a una función privada.

### [x] T-003-14 — `consultar_transacciones`: errores, identidad y auditoría

- **Cubre:** AC-003-07 (fila de 91 días), AC-003-09, AC-003-10 (fila inválida), AC-003-11, AC-003-12, AC-003-13, AC-003-17, AC-003-18
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-003-07, T-003-12, T-003-13
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/transaction_tools.py`, `tests/integration/core_banking_mcp/mcp/test_consultar_transacciones_errors.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_consultar_transacciones_errors.py::test_ac_003_11_consultar_transacciones__unverified_conversation__returns_identity_not_verified`
- **Red:** falla porque las excepciones del caso de uso se propagan sin sobre de error. Con la misma sesión MCP en memoria:
  - AC-003-11: las 4 situaciones devuelven `isError=true`, `IDENTITY_NOT_VERIFIED`, `retryable = false`, sin transacciones, y el almacén queda igual. La de dos conversaciones registra también `verificar_identidad` en el servidor de prueba: `A` se verifica con esa herramienta y la consulta se hace en `B`.
  - AC-003-09 (13 filas), AC-003-07 (91 días) y AC-003-10 (`2026-10-18T03:00:00Z`): `INVALID_INPUT` con `retryable = false`.
  - AC-003-12: las 3 filas devuelven el código esperado.
  - AC-003-13: `8765` (de `C-0002`) y `0000` devuelven sobres `NOT_FOUND` iguales campo a campo, sin datos de `C-0002`.
  - AC-003-18: con `FailingTransactionRepository`, `INTERNAL` con `retryable = false`, sin transacciones y sin el texto de la excepción, trazas ni SQL.
  - AC-003-17: con un `JsonAuditLog` real sobre un `StringIO`, cada uno de los 8 casos deja una sola línea JSON con la herramienta, la tarjeta enmascarada, el rango y el resultado esperado; con `card_last4 = "4111111111114321"` la línea no contiene ese número.
- **Green:** en `transaction_tools.py`, `InvalidInputError` → `tool_error(INVALID_INPUT, "Los datos de la consulta no son válidos (campo: {error.field}).", retryable=False)`; `IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED` con mensaje fijo; `CardNotFoundError` → `NOT_FOUND` con una constante única de módulo; `CoreUnavailableError` y un *catch-all* defensivo → `INTERNAL` con mensaje fijo. Ningún mensaje incluye el texto de la excepción ni el valor recibido.
- **Refactor:** —

### [x] T-003-15 — Cableado del servidor, catálogo y smoke por stdio

- **Cubre:** AC-003-01 (por stdio real con las semillas), AC-003-11 (almacén compartido con `verificar_identidad`); catálogo de herramientas (`mcp-testing.md` §7)
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-003-11, T-003-14
- **Archivos:** `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_003_14_catalog_exposes_consultar_transacciones_with_spec_schemas`
- **Red:** el catálogo falla porque `list_tools` no incluye `consultar_transacciones`. El test espera `["buscar_cliente", "consultar_transacciones", "verificar_identidad"]` (o el orden que ya use el test), compara el esquema de entrada (4 campos con descripción) y el de salida con `ConsultarTransaccionesOut.model_json_schema()` (`additionalProperties: false`) y falla ante herramientas no declaradas; los tests existentes de 001/002 del archivo pasan a esperar las tres herramientas. `test_server_module.py`: `server.mcp` expone las tres herramientas. `test_stdio_smoke.py`, por stdio real y base sembrada: `test_ac_003_01_consultar_transacciones__stdio_server__lists_seeded_september` (tras `verificar_identidad` de `C-0001`, `4321` del 1 al 30 de septiembre de 2026 devuelve `TX-000004`, `TX-000003`, `TX-000002`, `TX-000001`) y `test_ac_003_11_consultar_transacciones__stdio_server__unverified_conversation_is_rejected` (otra conversación → `IDENTITY_NOT_VERIFIED`); `stdout` solo lleva protocolo.
- **Green:** `build_server` construye `ListCardTransactions(transaction_repository, store, JsonAuditLog(), SystemClock())` con la **misma** instancia de `InMemoryConversationVerificationStore` que `VerifyIdentity` y llama a `register_transaction_tools`. `main()` y el `__getattr__` no cambian.
- **Refactor:** —

### [x] T-003-16 — Verificación final

- **Cubre:** Definition of Done (§5.5): AC-003-01…18 en verde, cobertura, lint, formato y tipado
- **App / capa:** `core_banking_mcp` / todas
- **Depende de:** T-003-01, T-003-02, T-003-03, T-003-04, T-003-05, T-003-06, T-003-07, T-003-08, T-003-09, T-003-10, T-003-11, T-003-12, T-003-13, T-003-14, T-003-15
- **Archivos:** — (solo verificación; no modifica archivos)
- **Test primero:** `uv run pytest --cov` (suite completa de 001, 002 y 003)
- **Red:** si algún comando falla, la tarea queda `[ ]` con el motivo y se corrige en la tarea que corresponda.
- **Green:** pasan, sin errores: `uv run pytest --cov` (umbral global ≥ 80 %), `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.
- **Refactor:** —

## Correcciones de la primera auditoría de AC (fase 5.5, veredicto «No cumple»: 1 Bloqueante, 4 Mayores y 2 Menores)

Cambios de trazabilidad en los tests, sin cambio de comportamiento ni de `src/` (§4.3.5): no hay Red de pytest; el Red es el hallazgo de `verify-ac-coverage` (informe `H-01…H-07`). La suite debe seguir en verde. Siguen la regla única de la cabecera: cada RN citada debe figurar en el `Cubre:` de su AC en `spec.md`, y un test solo cita un AC cuyo Given/When/Then ejecuta. Fuera de esta ronda: H-06 (convención de nombres de persistencia y auditoría, patrón heredado de 001/002, se fija en la rule) y H-07 (aserciones del caso de uso más débiles que el AC; la integración sí las cubre); no bloquean.

### [x] T-003-17 — H-01: citas de los dos tests de soporte de integración

- **Cubre:** corrige H-01
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound` (tests)
- **Depende de:** T-003-16
- **Archivos:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_transaction_repository.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`
- **Test primero:** los mismos tests existentes de esos dos archivos (deben seguir en verde)
- **Red:** hallazgo H-01: `test_support_occurred_at_roundtrips_as_utc` (~línea 213) y `test_seed_database_seeds_transactions_once` (~línea 88) llevan solo `# Soporte de tests: ...`, sin línea `Regla:` ni `AC-` (`mcp-testing.md` §4: un test sin ellas no pasa revisión).
- **Green:** en el primero, añadir `# Regla: RN-003-05 — <enunciado fiel de spec §4>` y `# AC-003-02 · Art. 3`; en el de semillas, citar una RN y un AC de la spec que el test realmente ejecute (la consulta de las transacciones sembradas de septiembre en orden), o `# Invariante: Art. 1 — datos semilla ficticios y reproducibles` con la línea del AC al que da soporte, comprobando antes en `spec.md` que cada RN citada figura en el `Cubre:` de ese AC y que el enunciado es fiel. Conservar el comentario `# Soporte de tests` como información adicional. No cambiar aserciones ni `src/`.
- **Refactor:** —

### [x] T-003-18 — H-02 y H-03: tests del caso de uso `ListCardTransactions`

- **Cubre:** corrige H-02 y H-03
- **App / capa:** `core_banking_mcp` / `application` (tests)
- **Depende de:** T-003-16
- **Archivos:** `tests/unit/core_banking_mcp/application/test_list_card_transactions.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-02 (~líneas 140-147): `test_ac_003_04_*` se parametriza por `card_state` («activa», «bloqueada», «cancelada») pero ese valor no entra en el Arrange (el puerto no expone el estado de la tarjeta), así que no reproduce el Given del AC. Hallazgo H-03 (~líneas 389-390): el test cita `RN-003-03` con `AC-003-13`, cuyo `Cubre:` es HU-003-02, RN-003-04 y RN-003-13.
- **Green:** H-02: eliminar el test unitario de AC-003-04 (el estado de la tarjeta lo cubren los tests de integración del repositorio y de la herramienta, que sí lo reproducen) o reformularlo como un caso único, no parametrizado, sin citar los estados ni el prefijo `ac_003_04`; si se elimina, comprobar con grep que ningún otro archivo ni `tasks.md` cita su nombre salvo la matriz de este documento (que actualiza el orquestador). H-03: citar `RN-003-04` (y, si el test lo ejecuta, `RN-003-02`, que figura en `Cubre:` de AC-003-11) con `AC-003-13`, verificando en `spec.md` que cada RN figura en el `Cubre:` del AC citado. No cambiar otras aserciones ni `src/`.
- **Refactor:** —

### [x] T-003-19 — H-04 y H-05: citas de los tests de contrato

- **Cubre:** corrige H-04 y H-05
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound` (tests)
- **Depende de:** T-003-16
- **Archivos:** `tests/contract/core_banking_mcp/test_consultar_transacciones_contract.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-04 (~líneas 76-79): el test de los 4 campos de entrada cita `RN-003-01` con `AC-003-09`, cuyo `Cubre:` es solo RN-003-06. Hallazgo H-05 (~líneas 91-103 y 106-112): los tests del catálogo de errores citan `RN-003-14` (solo lectura) y `RN-003-13` (sin datos de otros clientes) pero solo comprueban que `ErrorCode` contiene `IDENTITY_NOT_VERIFIED` y `NOT_FOUND`.
- **Green:** H-04: citar `RN-003-06` (los campos de entrada del esquema) con `AC-003-09`. H-05: quitar `RN-003-14` y `RN-003-13` de esos dos tests y dejar como citas `RN-003-02` (con AC-003-11) y `RN-003-04` (con AC-003-13), respectivamente; esas dos reglas ya están cubiertas en `test_consultar_transacciones_errors.py`. Comprobar en `spec.md` que cada RN citada figura en el `Cubre:` de su AC. No cambiar aserciones ni `src/`.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-003-01 | T-003-06, T-003-13, T-003-15 | `test_ac_003_01_lists_range_transactions_newest_first`, `test_ac_003_01_consultar_transacciones__september_range__lists_newest_first`, `test_ac_003_01_consultar_transacciones__stdio_server__lists_seeded_september` |
| AC-003-02 | T-003-03, T-003-10, T-003-13 | `test_ac_003_02_utc_bounds_follow_bogota_days`, `test_ac_003_02_find_transactions_uses_bogota_day_bounds` |
| AC-003-03 | T-003-02, T-003-06, T-003-08, T-003-13 | `test_ac_003_03_transaction_accepts_every_status` |
| AC-003-04 | T-003-06, T-003-10, T-003-13 | `test_ac_003_04_*` (caso de uso, repositorio y herramienta) |
| AC-003-05 | T-003-06, T-003-09, T-003-10, T-003-13 | `test_ac_003_05_add_assigns_distinct_card_refs_to_same_last4_cards` |
| AC-003-06 | T-003-04, T-003-06, T-003-13 | `test_ac_003_06_no_matches_is_empty_success` |
| AC-003-07 | T-003-03, T-003-06, T-003-13, T-003-14 | `test_ac_003_07_range_limit_counts_both_ends` |
| AC-003-08 | T-003-04, T-003-06, T-003-08, T-003-13 | `test_ac_003_08_more_than_fifty_requires_refinement` |
| AC-003-09 | T-003-01, T-003-03, T-003-06, T-003-08, T-003-14 | `test_ac_003_09_parse_iso_date_rejects_invalid_format_and_nonexistent_dates`, `test_ac_003_09_invalid_query_is_rejected` |
| AC-003-10 | T-003-03, T-003-06, T-003-13, T-003-14 | `test_ac_003_10_query_date_to_limit_uses_today_in_bogota` |
| AC-003-11 | T-003-06, T-003-08, T-003-14, T-003-15 | `test_ac_003_11_consultar_transacciones__unverified_conversation__returns_identity_not_verified`, `test_ac_003_11_consultar_transacciones__stdio_server__unverified_conversation_is_rejected` |
| AC-003-12 | T-003-06, T-003-14 | `test_ac_003_12_*` (caso de uso y herramienta) |
| AC-003-13 | T-003-06, T-003-08, T-003-10, T-003-14 | `test_ac_003_13_*` (caso de uso, contrato, repositorio y herramienta) |
| AC-003-14 | T-003-08, T-003-13, T-003-15 | `test_ac_003_14_consultar_transacciones__output_schema__has_exactly_spec_fields`, `test_ac_003_14_catalog_exposes_consultar_transacciones_with_spec_schemas` |
| AC-003-15 | T-003-06, T-003-10, T-003-13 | `test_ac_003_15_*` (caso de uso, repositorio y herramienta) |
| AC-003-16 | T-003-02, T-003-08, T-003-10, T-003-13 | `test_ac_003_16_transaction_accepts_amounts_with_up_to_two_decimals` |
| AC-003-17 | T-003-07, T-003-12, T-003-14 | `test_ac_003_17_each_invocation_records_exactly_one_event`, `test_ac_003_17_consultar_transacciones_event_is_serialized_without_pan` |
| AC-003-18 | T-003-06, T-003-14 | `test_ac_003_18_*` (caso de uso y herramienta) |

**Casos de escalamiento (spec §8):** `INTERNAL` con `retryable = false` → AC-003-18 (T-003-06, T-003-14). **Art. 7 (sin identificación previa):** AC-003-11 (T-003-06, T-003-14, T-003-15), con la comprobación de que la herramienta no escribe en el almacén (RN-003-14). **Tabla `DP-`:** no aplica. **Tareas de soporte sin AC propio:** T-003-05, T-003-11.

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [ ] Spec actualizada al comportamiento implementado.
- [ ] Sin secretos ni datos reales.
