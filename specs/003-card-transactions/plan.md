# Plan: Consultar las transacciones de una tarjeta del cliente en un rango de fechas

| Campo | Valor |
|---|---|
| Feature | `003-card-transactions` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-17 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 |

---

## 1. Resumen técnico

Tercera feature de `core_banking_mcp`. Añade la herramienta `consultar_transacciones` y las transacciones de tarjeta en el core simulado. Reutiliza el esqueleto, el patrón de errores, la auditoría, el reloj y el almacén de verificación de las features 001 y 002. No toca `dispute_agent`.

- **Dominio puro** (stdlib): `TransactionQuery.create(...)` aplica RN-003-06/07 (`card_last4` de 4 dígitos, fechas `AAAA-MM-DD` estrictas y existentes, `date_from ≤ date_to ≤ hoy`, a lo sumo 90 días contando ambos extremos) y lanza `InvalidInputError`. `BogotaDateRange.utc_bounds()` convierte el rango de días de Bogotá en el intervalo semiabierto de instantes UTC `[date_from 00:00 −05:00, date_to + 1 día 00:00 −05:00)` (RN-003-05). `Transaction` lleva `Decimal` y `occurred_at` con zona. `TransactionListResult.from_matches(...)` aplica el tope de 50 (RN-003-10), con el mismo patrón que `CustomerSearchResult`.
- **Parseo de fechas compartido:** el parseo estricto `[0-9]{4}-[0-9]{2}-[0-9]{2}` de 002 (`_parse_date` en `identity.py`) se extrae a `domain/dates.py` como `parse_iso_date(field, value)`; `identity.py` lo reutiliza sin cambiar su comportamiento (los tests de 002 deben seguir en verde).
- **Caso de uso** `ListCardTransactions`: valida → lee el estado de verificación de la conversación (`ConversationVerificationStore.get`) → busca las tarjetas del cliente verificado con esos 4 dígitos → consulta las transacciones (límite 51 para detectar el exceso) → audita. Errores en el orden de RN-003-08: `InvalidInputError`, `IdentityNotVerifiedError`, `CardNotFoundError`. Cualquier excepción inesperada después de la validación se convierte en `CoreUnavailableError` (RN-003-16).
- **Puerto `TransactionRepository`** (decisión del usuario, §3.3 de la constitución) con dos operaciones: `find_customer_cards(customer_id, last4)` y `find_transactions(card_ids, start, end, limit)`. `CustomerRepository` no cambia.
- **`card_id` opaco** (decisión del usuario): columna nueva `cards.card_ref` (`CARD-0001`, `CARD-0002`, …), única, que asigna el repositorio al insertar como siguiente consecutivo. La PK entera no sale del adaptador.
- **Monto** (decisión del usuario): columna `amount_minor` (`Integer`, centavos); el adaptador lo mapea a `Decimal` con 2 decimales y la herramienta lo formatea como `f"{amount:.2f}"`.
- **Instantes:** `occurred_at` se guarda en UTC (columna `DateTime` sin zona, por SQLite) y el adaptador lo devuelve con `tzinfo=UTC`. La herramienta lo serializa en ISO 8601 con el offset de Bogotá (`2026-09-20T14:32:00-05:00`), como el ejemplo de la spec §7.
- **Herramienta delgada** `consultar_transacciones` en un módulo propio (`transaction_tools.py`), con la misma firma permisiva de 001/002 (`str | None` en todos los campos): toda violación, incluso un campo ausente, sale como `INVALID_INPUT` y queda auditada. `ErrorCode` gana `IDENTITY_NOT_VERIFIED` y `NOT_FOUND`.
- **Auditoría sin PAN por construcción:** `AuditEvent` gana `masked_card`, `date_from`, `date_to` y `transaction_ids` (opcionales y al final). La entrada no se serializa (`input=None`, como en 002); `masked_card` se calcula solo si `card_last4` es válido, así que nunca se registra lo que llegó en ese campo cuando no lo es (RN-003-15).

Decisiones triviales tomadas:

- **`NOT_FOUND` idéntico:** el mensaje es una constante única del módulo de la herramienta; la tarjeta ajena y la inexistente pasan por la misma rama (`find_customer_cards` filtra por `customer_id`, así que no distingue entre los dos casos).
- **Orden en la base:** `ORDER BY occurred_at DESC, transaction_id ASC` en el adaptador (RN-003-11); el dominio no reordena.
- **Formato de los IDs de las semillas:** `transaction_id` = `TX-000001`… y `card_ref` = `CARD-0001`…; los dos son opacos para el consumidor.
- **`customer_id` en la auditoría:** el evento lleva el `customer_id` verificado cuando ya se conoce (pasos 3 y 4), usando el campo existente de 002. Es un dato interno del registro, no de la respuesta.
- **Regla y motivo auditados:** `found` → RN-003-05, `refinement_required` → RN-003-10, `INVALID_INPUT` → RN-003-06, `IDENTITY_NOT_VERIFIED` → RN-003-02, `NOT_FOUND` → RN-003-04, `INTERNAL` → RN-003-16.
- **Misma sesión y mismo almacén:** `server.py` pasa al nuevo caso de uso la misma `Session` y la misma instancia de `InMemoryConversationVerificationStore` que usa `VerifyIdentity`; si no, la verificación no se vería (Art. 7).
- **Guía del Inspector:** `docs/mcp-inspector.md` no se modifica en esta feature (la spec no lo pide).

## 2. Componentes por capa

Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/dates.py` — `parse_iso_date` | Nuevo | Parseo estricto `AAAA-MM-DD` + fecha existente; lanza `InvalidInputError(field, ...)`. Sin la comprobación de "no posterior a hoy", que hace cada llamador. |
| `core_banking_mcp` | `domain` | `domain/models/identity.py` | Modificado | `_parse_date` usa `parse_iso_date` y conserva la comprobación de "posterior a hoy" y sus mensajes. Sin cambio de comportamiento. |
| `core_banking_mcp` | `domain` | `domain/models/transaction.py` — `TransactionStatus`, `Transaction`, `CustomerCard`, `BogotaDateRange`, `TransactionQuery`, `TransactionListResult`, `MAX_TRANSACTIONS = 50`, `MAX_RANGE_DAYS = 90` | Nuevo | Value objects inmutables (`dataclass(frozen=True)`). `TransactionQuery.create(conversation_id, card_last4, date_from, date_to, today)` aplica RN-003-06. `BogotaDateRange.utc_bounds()` aplica RN-003-05. `TransactionListResult.from_matches(matches)` aplica RN-003-10. |
| `core_banking_mcp` | `application` | `application/errors.py` | Modificado | Se añaden `IdentityNotVerifiedError` (RN-003-02) y `CardNotFoundError` (RN-003-04). |
| `core_banking_mcp` | `application` | `application/ports/transaction_repository.py` — `TransactionRepository` | Nuevo | `find_customer_cards(customer_id, last4) -> list[CustomerCard]` y `find_transactions(card_ids, start, end, limit) -> list[Transaction]` (instantes UTC, `start` incluido y `end` excluido, ordenadas según RN-003-11). |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditEvent` | Modificado | Campos opcionales al final: `masked_card: str \| None = None`, `date_from: str \| None = None`, `date_to: str \| None = None`, `transaction_ids: tuple[str, ...] = ()`. Los eventos de 001 y 002 no cambian. |
| `core_banking_mcp` | `application` | `application/use_cases/list_card_transactions.py` — `ListCardTransactions`, `ListCardTransactionsCommand` | Nuevo | Orquesta validación → verificación → tarjetas → transacciones → auditoría, con un único evento por invocación (RN-003-15) y el orden de errores de RN-003-08. No escribe nada en el almacén ni en los repositorios (RN-003-14). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Modificado | `ErrorCode` gana `IDENTITY_NOT_VERIFIED` y `NOT_FOUND` (y su docstring deja de mencionar solo `buscar_cliente`). Se añaden `ConsultarTransaccionesIn`, `TransactionItemOut` y `ConsultarTransaccionesOut` (`extra="forbid"`, `status` como `Literal["CONFIRMED", "PENDING", "REVERSED"]`, `transactions` con `max_length=50`), con `Field(description=...)`. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/transaction_tools.py` — `register_transaction_tools(mcp, list_card_transactions)` | Nuevo | Herramienta delgada `consultar_transacciones` con docstring en español (spec §7: requiere identidad verificada, cuándo usarla y cuándo no, solo lectura, idempotente). Mapea `InvalidInputError` → `INVALID_INPUT`, `IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED`, `CardNotFoundError` → `NOT_FOUND` (mensaje constante), `CoreUnavailableError` y *catch-all* → `INTERNAL`; todos con `retryable=false`. Formatea `amount` con 2 decimales, `occurred_at` en Bogotá y `masked_card` con `mask_card`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/tables.py` | Modificado | `CardRow` gana `card_ref` (`String`, única, indexada). Tabla nueva `TransactionRow`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_customer_repository.py` | Modificado | `add(...)` asigna `card_ref` consecutivo (`CARD-%04d`, según el número de tarjetas ya guardadas) a cada tarjeta nueva. `find_matching`, `find_identity` y `_to_entity` no cambian. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_transaction_repository.py` — `SqlAlchemyTransactionRepository` | Nuevo | Implementa el puerto: `find_customer_cards` filtra por `customer_id` y `last4` (cualquier estado), ordenado por `card_ref`; `find_transactions` hace un `JOIN` con `cards`, filtra por `card_ref IN (...)` y `start ≤ occurred_at < end`, ordena y limita. Mapea filas a `Transaction` (`Decimal(amount_minor) / 100`, `occurred_at` con `tzinfo=UTC`). `add(card_ref, transaction)` para semillas y tests. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/transactions.py` — `SEED_TRANSACTIONS`, `seed_transactions` | Nuevo | Transacciones ficticias fijas (§4). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/customers.py` | Modificado | `seed_database` recibe también el repositorio de transacciones y, solo cuando siembra los clientes, siembra las transacciones. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` | Modificado | Serializa los campos nuevos; omite `masked_card`, `date_from` y `date_to` si son `None` y `transaction_ids` si está vacío, para que el JSON de 001 y 002 no cambie. |
| `core_banking_mcp` | arranque | `server.py` — `build_server` | Modificado | Crea `SqlAlchemyTransactionRepository` con la misma sesión, se lo pasa a `seed_database`, construye `ListCardTransactions` con el **mismo** almacén de verificación que `VerifyIdentity` y llama a `register_transaction_tools`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `TransactionRepository` | Nuevo | `SqlAlchemyTransactionRepository` | Previsto en §3.3. Incluye la resolución de las tarjetas por `customer_id` + `last4`, de modo que la comprobación de pertenencia (RN-003-04) es una consulta filtrada y no lógica en la herramienta. Fakes en `tests/fakes/`. |
| `ConversationVerificationStore` | Sin cambios | `InMemoryConversationVerificationStore` | Se usa solo `get(...)` (RN-002-13); esta feature nunca llama a `save`. |
| `CustomerRepository` | Sin cambios de interfaz | `SqlAlchemyCustomerRepository` | Solo cambia el adaptador, que asigna `card_ref` al insertar. |
| `AuditLogPort` (core) | Modificado | `JsonAuditLog` | `AuditEvent` gana campos opcionales; el puerto no cambia. |
| `Clock` | Sin cambios | `SystemClock` | Devuelve UTC; el dominio calcula "hoy" con `today_in_bogota`. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `TransactionStatus` | `CONFIRMED`, `PENDING`, `REVERSED` | Enum cerrado (RN-003-09). |
| `CustomerCard` | `card_id: str`, `last4: str` | `card_id` no vacío; `last4` de 4 dígitos. |
| `Transaction` | `transaction_id: str`, `card_id: str`, `card_last4: str`, `occurred_at: datetime`, `merchant: str`, `amount: Decimal`, `currency: str`, `status: TransactionStatus` | `occurred_at` con zona horaria; `amount > 0` y con 2 decimales como máximo; `currency` de 3 letras mayúsculas `A-Z`; IDs y comercio no vacíos; `card_last4` de 4 dígitos. |
| `BogotaDateRange` | `date_from: date`, `date_to: date` | `date_from ≤ date_to`; `(date_to − date_from).days + 1 ≤ 90`. `utc_bounds()` → `(inicio, fin)` UTC, fin excluido. |
| `TransactionQuery` | `conversation_id: str`, `card_last4: str`, `date_range: BogotaDateRange` | Se crea solo con `create(...)`: `conversation_id` no vacío tras recortar; `card_last4` exactamente 4 dígitos ASCII sin espacios; fechas con `parse_iso_date`; `date_to ≤ today`; invariantes del rango. Si falla, `InvalidInputError`. Las comprobaciones de campo se evalúan antes que las del rango. |
| `TransactionListResult` | `transactions: tuple[Transaction, ...]`, `refinement_required: bool` | `refinement_required ⇒ transactions == ()`; `len(transactions) ≤ 50`. |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `cards` | `card_ref` (`String`, única, indexada, no nula) | Columna nueva. |
| `transactions` | `transaction_id` (`String`, PK), `card_id` (FK → `cards.card_id`, indexada), `occurred_at` (`DateTime`, UTC sin zona, indexada), `merchant` (`String`), `amount_minor` (`Integer`), `currency` (`String(3)`), `status` (`String`) | Tabla nueva. Índice compuesto `(card_id, occurred_at)`. |

### Semillas

Ficticias y fijas (Art. 1). Los tests usan builders de `tests/fakes/`, no estas semillas (§5.3.7). Con el orden actual de las semillas de clientes, `card_ref` queda: `CARD-0001` = Laura `4321` (activa), `CARD-0002` = Laura `8765` (bloqueada), `CARD-0003` = Pedro `1234` (activa), `CARD-0004` = Marta `5555` (cancelada).

| ID | Tarjeta | `occurred_at` (Bogotá) | Comercio | Monto | Estado |
|---|---|---|---|---|---|
| `TX-000001` | `CARD-0001` | 2026-09-05 09:15 | Supermercado La Cosecha | 185000.00 COP | `CONFIRMED` |
| `TX-000002` | `CARD-0001` | 2026-09-12 20:40 | StreamFlix Andina | 15.99 USD | `CONFIRMED` |
| `TX-000003` | `CARD-0001` | 2026-09-20 14:32 | Aerolínea Cóndor del Sur | 1250000.00 COP | `PENDING` |
| `TX-000004` | `CARD-0001` | 2026-09-25 11:05 | Farmacia Vida Plena | 42000.00 COP | `REVERSED` |
| `TX-000005` | `CARD-0001` | 2026-10-02 18:20 | Café Montaña Azul | 12500.00 COP | `CONFIRMED` |
| `TX-000006` | `CARD-0002` | 2026-09-18 22:10 | Tienda Online Mercurio | 320000.00 COP | `CONFIRMED` |
| `TX-000007` | `CARD-0003` | 2026-09-08 07:45 | Gasolinera El Páramo | 98000.00 COP | `CONFIRMED` |
| `TX-000008` | `CARD-0003` | 2026-09-22 13:00 | Librería Letras Andinas | 64000.00 COP | `CONFIRMED` |
| `TX-000009` | `CARD-0004` | 2026-08-30 16:30 | Restaurante Fogón Criollo | 75000.00 COP | `CONFIRMED` |

## 5. Dependencias nuevas

Ninguna. `decimal`, `datetime`, `re` y `dataclasses` son de la biblioteca estándar; SQLAlchemy, Pydantic y `mcp` ya están en el stack.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes y builders nuevos en `tests/fakes/`:

- `TransactionBuilder` (valores por defecto válidos; `occurred_at`, estado, monto, moneda y tarjeta configurables).
- `FakeTransactionRepository`: tarjetas por cliente y transacciones en memoria, con el mismo filtrado y orden que el puerto exige.
- `FailingTransactionRepository`: falla con una excepción que no es de dominio.
- `FakeVerificationStore`, `FakeAuditLog` y `FixedClock` se reutilizan.

Los tests de herramienta usan una sesión MCP en memoria contra el servidor real con SQLite `:memory:`, como en 001 y 002, preparando la verificación por `verificar_identidad` o con el almacén del servidor.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-003-01 | `ListCardTransactions` con el fake: devuelve las 3 de septiembre en orden 20, 12, 5 y excluye la del 2 de octubre | `consultar_transacciones` vía sesión MCP con SQLite: mismas 3, campos exactos y `masked_card = "**** 4321"` | La salida cumple `ConsultarTransaccionesOut` / `TransactionItemOut` | — |
| AC-003-02 | `BogotaDateRange.utc_bounds()` parametrizado con los 6 instantes (incluidos los dos en UTC que cruzan el día en Bogotá) | `SqlAlchemyTransactionRepository.find_transactions` con los 6 instantes: aparecen o no según la tabla | — | — |
| AC-003-03 | `Transaction` acepta los 3 estados; el caso de uso los devuelve (parametrizado) | La herramienta devuelve cada estado con `amount = "125000.00"` (3 filas) | `status` admite solo los 3 valores del enum | — |
| AC-003-04 | El caso de uso consulta la tarjeta en los 3 estados (parametrizado) | `find_customer_cards` encuentra la tarjeta activa, bloqueada y cancelada; la herramienta devuelve las 2 transacciones en cada fila | — | — |
| AC-003-05 | Con dos `CustomerCard` terminadas en `4321`, el resultado combina las 2 transacciones con `card_id` distintos | `add` asigna `card_ref` distintos a dos tarjetas con el mismo `last4`; la herramienta devuelve 2 transacciones con el mismo `masked_card` y `card_id` distintos | — | — |
| AC-003-06 | `TransactionListResult.from_matches([])` → vacía y `refinement_required = false` | La herramienta responde con éxito `{"transactions": [], "refinement_required": false}` | — | — |
| AC-003-07 | `TransactionQuery.create` parametrizado: 1, 89, 90 días y rango de 2019 válidos; 91 días → `InvalidInputError` | La herramienta: 4 filas exitosas y 91 días → `INVALID_INPUT` con `retryable=false` | — | — |
| AC-003-08 | `TransactionListResult.from_matches` con 49, 50 y 51 (borde exacto); el caso de uso pide 51 al repositorio | La herramienta con 49/50/51 transacciones sembradas | `transactions` tiene `maxItems: 50` | — |
| AC-003-09 | `TransactionQuery.create` parametrizado con las 13 filas; el caso de uso no consulta el almacén ni el repositorio | La herramienta devuelve `INVALID_INPUT` con `retryable=false` y sin transacciones en cada fila | El sobre de error cumple `ToolErrorOut` | — |
| AC-003-10 | `TransactionQuery.create` con los 3 instantes (`today_in_bogota` en el borde 03:00Z y 05:00Z) | La herramienta con `FixedClock` en cada instante | — | — |
| AC-003-11 | El caso de uso con el almacén en las 4 situaciones → `IdentityNotVerifiedError`, sin llamar al repositorio, y el estado del almacén no cambia | La herramienta en las 4 situaciones (incluida la conversación `B` mientras `A` está verificada vía `verificar_identidad`) → `IDENTITY_NOT_VERIFIED` con `retryable=false`; el almacén queda igual | El catálogo de códigos incluye `IDENTITY_NOT_VERIFIED` | — |
| AC-003-12 | Caso de uso parametrizado con las 3 filas: el primer error según RN-003-08 | La herramienta con las 3 filas | — | — |
| AC-003-13 | `find_customer_cards` del fake devuelve `[]` para la tarjeta ajena y la inexistente → `CardNotFoundError` en ambos casos | La herramienta con `8765` (de Pedro) y `0000`: los dos sobres son iguales campo a campo y sin datos de Pedro; el repositorio SQL no devuelve tarjetas de otro cliente | El catálogo de códigos incluye `NOT_FOUND` | — |
| AC-003-14 | — | La respuesta serializada solo tiene los campos de RN-003-12, `masked_card = "**** 4321"`, y no contiene `4111111111114321`, `D-1001` ni `Laura Méndez` | `ConsultarTransaccionesOut` y `TransactionItemOut` tienen `additionalProperties: false` y exactamente los campos de la spec §7 | — |
| AC-003-15 | El fake respeta el orden; test del orden en el caso de uso | `find_transactions` en SQLite: dos transacciones simultáneas por `transaction_id` ascendente después de la más reciente | — | — |
| AC-003-16 | `Transaction` acepta `Decimal("125000")`, `Decimal("49.9")` y `Decimal("0.05")` y rechaza montos ≤ 0, con más de 2 decimales o monedas que no son 3 letras | El adaptador mapea `amount_minor` ↔ `Decimal`; la herramienta formatea `"125000.00"`, `"49.90"` y `"0.05"` (3 filas) | `amount` y `currency` son `string` | — |
| AC-003-17 | `FakeAuditLog` + `FixedClock`: exactamente un evento en cada uno de los 8 casos (parametrizado), con `conversation_id`, timestamp, `tool`, `masked_card` (vacía con el PAN en `card_last4`), rango, resultado y `transaction_ids`; ni el evento ni su JSON contienen un PAN | `JsonAuditLog` escribe los campos nuevos y omite los vacíos; los eventos de 001/002 no cambian de claves; nada en `stdout` | — | — |
| AC-003-18 | `FailingTransactionRepository` → `CoreUnavailableError`, auditado como `INTERNAL` | La herramienta devuelve `INTERNAL` con `retryable=false`, sin transacciones ni el texto de la excepción, trazas o SQL | El sobre cumple `ToolErrorOut` | — |

Adicionales (`mcp-testing.md` §7, §2):

- **Snapshot del catálogo:** `test_tool_catalog.py` pasa a esperar `buscar_cliente`, `verificar_identidad` y `consultar_transacciones`, compara los esquemas de entrada y salida de la nueva con la spec §7 y falla ante herramientas no declaradas.
- **Art. 7 (§5.3.5):** la llamada sin identificación previa la cubre AC-003-11; también se prueba que la herramienta nunca escribe en el almacén (RN-003-14).
- **Escalamiento (§5.3.4):** el caso de la spec §8 (`INTERNAL` con `retryable = false`) lo cubre AC-003-18.
- **Smoke por stdio:** el test existente que lanza el servidor como subproceso se amplía: `list_tools` muestra las tres herramientas y, tras `verificar_identidad` con `C-0001`, `consultar_transacciones` con `4321` del 1 al 30 de septiembre de 2026 devuelve las 4 transacciones sembradas de septiembre; la salida por `stdout` es solo protocolo. El reloj del subproceso es el real, así que el rango usado es siempre pasado.
- **`server.mcp`:** el test existente pasa a esperar las tres herramientas.
- **Semillas:** test de integración de que se siembran las 9 transacciones con los `card_ref` de §4, una sola vez.
- **Regresión de 001 y 002:** `identity.py` reutiliza `parse_iso_date`; `seed_database` cambia de firma; `card_ref` es obligatorio. Las suites de 001 y 002 deben seguir en verde, ajustando solo los puntos de llamada.
- El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global y, en la verificación final, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Una base SQLite local creada con 001/002 no tiene `cards.card_ref` ni la tabla `transactions`; `create_all` crea la tabla nueva pero no altera `cards`, y `buscar_cliente` fallaría con "no such column" | Alto | Como en 002: no hay migraciones en el stack y los datos son ficticios (Art. 1). Hay que borrar `data/core_banking.db` (ignorado por git); el servidor la recrea y siembra al arrancar. Un test de integración crea el esquema desde cero. |
| La herramienta comprueba la verificación contra un almacén distinto del de `verificar_identidad` y rechaza (o, peor, acepta) conversaciones por error | Alto | `server.py` crea una sola instancia y se la pasa a los dos casos de uso; el smoke por stdio y los tests de herramienta verifican primero con `verificar_identidad` y luego consultan en el mismo servidor. |
| Fuga de transacciones de otro cliente con los mismos 4 dígitos | Alto | `find_customer_cards` filtra por `customer_id` del almacén, nunca por un dato que llegue en la solicitud; AC-003-13 lo prueba en el fake y en SQLite con dos clientes. |
| Errores de borde de zona horaria en el rango (un movimiento a las 23:30 en Bogotá es del día siguiente en UTC) | Medio | El rango se convierte en instantes UTC en el dominio (`utc_bounds`) y el adaptador compara instantes; AC-003-02 prueba los dos cruces de día. `SystemClock` y los instantes del adaptador llevan `tzinfo=UTC`. |
| SQLite guarda `DateTime` sin zona: un instante con offset mal convertido se compararía mal | Medio | El adaptador convierte a UTC antes de escribir y añade `tzinfo=UTC` al leer; test de ida y vuelta con un instante en `−05:00`. |
| El cambio de `_parse_date` a `parse_iso_date` altera la validación de 002 | Bajo | Solo se extrae el parseo; la comprobación de "posterior a hoy" y los mensajes se quedan en `identity.py`. Los tests de AC-002-08/09 se ejecutan en la regresión. |
| Añadir valores a `ErrorCode` cambia el esquema del sobre de error de las herramientas de 001 y 002 | Bajo | Es un cambio compatible (catálogo ampliado, como prevé `mcp-tools.md` §7). Los tests de contrato del sobre se actualizan en el mismo cambio. |
| `card_ref` por consecutivo choca si dos procesos insertan a la vez | Bajo | Solo inserta el sembrado al arrancar, en un único proceso; la columna es única, así que un choque fallaría en vez de duplicar. |
| `seed_database` cambia de firma y la usan `server.py` y los tests de semillas | Bajo | La tarea que la cambia actualiza sus llamadas; `server.py` se ejecuta en su propia oleada (archivo compartido). |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Las transacciones de las semillas, sus comercios y montos son inventados y fijos (§4); los PAN siguen siendo los ficticios de 001; los tests usan builders. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento; los 18 AC están trazados en §6. Los ajustes a 001/002 (parseo compartido, `card_ref`, firma de `seed_database`) no cambian su comportamiento. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); el dominio puro, el caso de uso y los fakes permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio usa solo stdlib (`dataclasses`, `datetime`, `decimal`, `re`); SQLAlchemy y Pydantic se quedan en infraestructura y se mapean en los adaptadores; la PK de `cards` no sale del adaptador; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La consulta de transacciones no decide sobre disputas; no se toca `DisputePolicy`. |
| Art. 6 — Acciones vía MCP | Cumple | Las transacciones solo se exponen mediante la herramienta MCP `consultar_transacciones`. |
| Art. 7 — Identificación antes que información | Cumple | Primera herramienta que exige la verificación en el servidor: el caso de uso consulta el almacén de 002 antes de tocar cualquier dato y usa el `customer_id` verificado, no uno de la solicitud, para resolver la tarjeta (AC-003-11, AC-003-13). La respuesta solo enmascara la tarjeta (AC-003-14). |
| Art. 8 — Auditoría | Cumple | Cada invocación genera un único registro con `conversation_id`, marca de tiempo del reloj inyectado, herramienta, tarjeta enmascarada, rango, resultado, regla y motivo, sin PAN (AC-003-17). |
| Art. 9 — Secretos | Cumple | No hay secretos ni configuración nueva. |
| Art. 10 — Ante la duda, escalar | Cumple | Una falla inesperada devuelve `INTERNAL` con `retryable = false` y sin transacciones (AC-003-18); el escalamiento lo ejecutará el consumidor (fuera de alcance, spec §8). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
