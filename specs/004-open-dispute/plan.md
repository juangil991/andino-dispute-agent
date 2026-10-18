# Plan: Abrir una disputa sobre una transacción de un cliente verificado

| Campo | Valor |
|---|---|
| Feature | `004-open-dispute` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-17 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 |

---

## 1. Resumen técnico

Cuarta feature de `core_banking_mcp` y primera que escribe en el core. Añade la herramienta `iniciar_disputa` y las disputas del core simulado. Reutiliza el esqueleto, el patrón de errores, la auditoría, el reloj, el almacén de verificación y `TransactionItemOut` de 001–003. No toca `dispute_agent`.

- **Dominio puro** (stdlib): `DisputeReason` (enum de los 5 códigos, RN-004-02) y `DisputeStatus` (`OPEN`, `CLOSED`, `REJECTED`, RN-004-07). `DisputeRequest.create(conversation_id, transaction_id, reason, idempotency_key)` aplica RN-004-09 y lanza `InvalidInputError`. `Dispute` es la disputa registrada. `redact_card_numbers(text)` en `domain/masking.py` sustituye cada secuencia de 13 a 19 dígitos por `[REDACTED]` (RN-004-16).
- **Caso de uso** `OpenDispute`, en el orden de RN-004-10: valida → lee la verificación (`ConversationVerificationStore.get`) → busca la disputa por `(conversation_id, idempotency_key)` → busca la transacción del cliente verificado → comprueba que esté `CONFIRMED` → comprueba que no tenga una disputa `OPEN` → registra → audita. Si la clave ya existe con la misma transacción y motivo, devuelve esa disputa como repetición (`replayed`); si existe con otros datos, `InvalidInputError`. Errores nuevos: `TransactionNotFoundError`, `TransactionNotDisputableError` y `DisputeAlreadyOpenError(dispute_id)`. Cualquier excepción inesperada tras la validación se convierte en `CoreUnavailableError` (RN-004-15), como en 003.
- **Puerto `DisputeRepository`** (previsto en §3.3 de la constitución) con tres operaciones: `find_by_idempotency_key(conversation_id, key)`, `find_open_by_transaction(transaction_id)` y `add(...)`, que devuelve la `Dispute` con su ID asignado.
- **`TransactionRepository` gana `find_customer_transaction(customer_id, transaction_id)`**. Filtra por el cliente verificado con un `JOIN` a `cards`, así la transacción ajena y la inexistente salen por la misma rama (`None`, RN-004-04).
- **Idempotencia en la propia fila** (decisión del usuario): `disputes` guarda `conversation_id` e `idempotency_key`, con un índice único sobre ambas. Disputa y clave se insertan en un único `INSERT` + `commit`. Si falla, el adaptador hace `rollback` y no queda nada (RN-004-15).
- **`dispute_id` consecutivo** (decisión del usuario): `DSP-000001`, `DSP-000002`, …, asignado por el repositorio al insertar (siguiente al número de filas), igual que `card_ref`. Es determinista y no se deriva de la tarjeta (RN-004-11).
- **Una sola disputa `OPEN` por transacción** (decisión del usuario): el caso de uso consulta `find_open_by_transaction` para responder `DISPUTE_ALREADY_OPEN` con el ID existente. Además, un índice único parcial de SQLite (`transaction_id WHERE status = 'OPEN'`) impide duplicados en carrera; si choca, el `IntegrityError` sale como `INTERNAL` (Art. 10).
- **Instantes:** `opened_at` es `clock.now()` (UTC), se guarda en UTC sin zona (como `occurred_at`) y la herramienta lo serializa en ISO 8601 con el offset de Bogotá.
- **Herramienta delgada** `iniciar_disputa` en un módulo propio (`dispute_tools.py`), con la firma permisiva de 001–003 (`str | None` en todos los campos), para que toda violación salga como `INVALID_INPUT` auditado. `ErrorCode` gana `TRANSACTION_NOT_DISPUTABLE` y `DISPUTE_ALREADY_OPEN`. La transacción se mapea con el mismo conversor de `consultar_transacciones`, que pasa de `_to_item` a `to_transaction_item` (público) en `transaction_tools.py`.
- **Auditoría sin PAN por construcción:** `AuditEvent` gana `transaction_id`, `dispute_reason`, `idempotency_key` y `dispute_id`, opcionales y al final. `transaction_id` e `idempotency_key` se registran solo si son válidos según RN-004-09 y siempre pasan por `redact_card_numbers`. `dispute_reason` se registra solo si es un código del catálogo. La entrada no se serializa (`input=None`, como en 002 y 003).

Decisiones triviales tomadas:

- **`NOT_FOUND` idéntico:** el mensaje es una constante del módulo de la herramienta y las dos situaciones pasan por la misma rama (`find_customer_transaction` devuelve `None`).
- **`DISPUTE_ALREADY_OPEN`:** mensaje fijo con el ID existente, p. ej. `"La transacción ya tiene una disputa abierta: DSP-000001."`.
- **Enum en el esquema de entrada:** `reason` se declara `str | None` para validar en el dominio, pero su `Field` publica `json_schema_extra={"enum": [...]}` con los 5 códigos, para que el LLM vea el catálogo (spec §7: `string (enum)`).
- **Esquema de salida:** `IniciarDisputaOut.status` es `Literal["OPEN"]` (spec §7) y `reason` es un `Literal` de los 5 códigos. `transaction` reutiliza `TransactionItemOut`.
- **Regla y motivo auditados:** `opened` → RN-004-11; `replayed` → RN-004-08; `INVALID_INPUT` → RN-004-09 (RN-004-08 si es por clave reutilizada); `IDENTITY_NOT_VERIFIED` → RN-004-03; `NOT_FOUND` → RN-004-04; `TRANSACTION_NOT_DISPUTABLE` → RN-004-05; `DISPUTE_ALREADY_OPEN` → RN-004-07 (con `dispute_id` existente); `INTERNAL` → RN-004-15.
- **`customer_id` en la auditoría:** se registra el verificado cuando ya se conoce, como en 003.
- **Repetición y transacción:** la respuesta de una repetición vuelve a leer la transacción con `find_customer_transaction` para devolver `TransactionItem` actual.
- **Regex de redacción:** `[0-9]{13,19}` con `re.sub` (solo dígitos ASCII).
- **Misma sesión y mismo almacén:** `server.py` pasa al nuevo caso de uso la misma `Session` y la misma instancia de `InMemoryConversationVerificationStore` que usan `VerifyIdentity` y `ListCardTransactions`.

## 2. Componentes por capa

Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/masking.py` — `redact_card_numbers` | Modificado | Función nueva: sustituye cada secuencia de 13 a 19 dígitos por `[REDACTED]`. `mask_card` y `mask_document` no cambian. |
| `core_banking_mcp` | `domain` | `domain/models/dispute.py` — `DisputeReason`, `DisputeStatus`, `DisputeRequest`, `Dispute`, `MAX_ID_LENGTH = 64` | Nuevo | Value objects inmutables. `DisputeRequest.create(...)` aplica RN-004-09 (campos recortados; `reason` exacto y sensible a mayúsculas). `Dispute` con invariantes de §4. |
| `core_banking_mcp` | `application` | `application/errors.py` | Modificado | Se añaden `TransactionNotFoundError` (RN-004-04), `TransactionNotDisputableError` (RN-004-05) y `DisputeAlreadyOpenError` con atributo `dispute_id` (RN-004-07). |
| `core_banking_mcp` | `application` | `application/ports/transaction_repository.py` | Modificado | Operación nueva `find_customer_transaction(customer_id, transaction_id) -> Transaction \| None` (cualquier estado de tarjeta). |
| `core_banking_mcp` | `application` | `application/ports/dispute_repository.py` — `DisputeRepository` | Nuevo | `find_by_idempotency_key(conversation_id, key) -> Dispute \| None`, `find_open_by_transaction(transaction_id) -> Dispute \| None` y `add(conversation_id, idempotency_key, transaction_id, reason, status, opened_at) -> Dispute` (asigna `dispute_id`; atómico). |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditEvent` | Modificado | Campos opcionales al final: `transaction_id`, `dispute_reason`, `idempotency_key`, `dispute_id` (`str \| None = None`). Los eventos de 001–003 no cambian. |
| `core_banking_mcp` | `application` | `application/use_cases/open_dispute.py` — `OpenDispute`, `OpenDisputeCommand`, `OpenDisputeResult` | Nuevo | Orquesta el orden de RN-004-10 con un único evento de auditoría por invocación (RN-004-16). `OpenDisputeResult(dispute, transaction, replayed)`. No escribe en el almacén de verificación ni cambia transacciones o tarjetas (RN-004-14). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Modificado | `ErrorCode` gana `TRANSACTION_NOT_DISPUTABLE` y `DISPUTE_ALREADY_OPEN`. Se añaden `IniciarDisputaIn` e `IniciarDisputaOut` (`extra="forbid"`, `transaction: TransactionItemOut`). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/transaction_tools.py` | Modificado | `_to_item` pasa a ser `to_transaction_item` (público) para reutilizarlo. Sin cambio de comportamiento. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/dispute_tools.py` — `register_dispute_tools(mcp, open_dispute)` | Nuevo | Herramienta delgada `iniciar_disputa` con docstring en español (spec §7). Mapea `InvalidInputError` → `INVALID_INPUT`, `IdentityNotVerifiedError` → `IDENTITY_NOT_VERIFIED`, `TransactionNotFoundError` → `NOT_FOUND` (mensaje constante), `TransactionNotDisputableError` → `TRANSACTION_NOT_DISPUTABLE`, `DisputeAlreadyOpenError` → `DISPUTE_ALREADY_OPEN` (con el ID en el mensaje), y `CoreUnavailableError` y el *catch-all* → `INTERNAL`. Todos con `retryable=false`. Serializa `opened_at` en Bogotá. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/tables.py` | Modificado | Tabla nueva `DisputeRow` (§4). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_transaction_repository.py` | Modificado | Implementa `find_customer_transaction`: `JOIN` con `cards` filtrando `CardRow.customer_id` y `transaction_id`. Mismo mapeo a `Transaction`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_dispute_repository.py` — `SqlAlchemyDisputeRepository` | Nuevo | Implementa el puerto. `add` calcula `DSP-%06d`, inserta y hace `commit`; ante cualquier excepción hace `rollback` y la relanza. Mapea filas a `Dispute` (`opened_at` con `tzinfo=UTC`). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/disputes.py` — `SEED_DISPUTES`, `seed_disputes` | Nuevo | Disputas ficticias fijas (§4). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/customers.py` | Modificado | `seed_database` recibe también el repositorio de disputas y lo siembra tras las transacciones, solo cuando siembra los clientes. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` | Modificado | Añade los 4 campos nuevos a `_OPTIONAL_KEYS` para omitirlos si son `None`; el JSON de 001–003 no cambia. |
| `core_banking_mcp` | arranque | `server.py` — `build_server` | Modificado | Crea `SqlAlchemyDisputeRepository` con la misma sesión, lo pasa a `seed_database`, construye `OpenDispute` con el **mismo** almacén de verificación y llama a `register_dispute_tools`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `DisputeRepository` | Nuevo | `SqlAlchemyDisputeRepository` | Previsto en §3.3. Fakes en `tests/fakes/` (en memoria y uno que falla en `add`). |
| `TransactionRepository` | Modificado | `SqlAlchemyTransactionRepository` | Gana `find_customer_transaction`. La comprobación de pertenencia es una consulta filtrada por el `customer_id` verificado, no un dato de la solicitud. |
| `ConversationVerificationStore` | Sin cambios | `InMemoryConversationVerificationStore` | Solo `get(...)` (RN-002-13). |
| `AuditLogPort` (core) | Modificado | `JsonAuditLog` | `AuditEvent` gana campos opcionales; el puerto no cambia. |
| `Clock` | Sin cambios | `SystemClock` | `opened_at` = `clock.now()`. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `DisputeReason` | `UNRECOGNIZED_CHARGE`, `DUPLICATE_CHARGE`, `INCORRECT_AMOUNT`, `NOT_RECEIVED`, `OTHER` | Enum cerrado (RN-004-02). |
| `DisputeStatus` | `OPEN`, `CLOSED`, `REJECTED` | Enum cerrado (RN-004-07). |
| `DisputeRequest` | `conversation_id: str`, `transaction_id: str`, `reason: DisputeReason`, `idempotency_key: str` | Se crea solo con `create(...)`: `conversation_id` no vacío tras recortar; `transaction_id` e `idempotency_key` de 1 a 64 caracteres tras recortar; `reason` igual a un valor del enum (sin normalizar mayúsculas). Cualquier campo ausente o inválido → `InvalidInputError(field, ...)`. Los valores se guardan recortados. |
| `Dispute` | `dispute_id: str`, `conversation_id: str`, `idempotency_key: str`, `transaction_id: str`, `reason: DisputeReason`, `status: DisputeStatus`, `opened_at: datetime` | IDs no vacíos; `opened_at` con zona horaria. `same_request(transaction_id, reason) -> bool` para decidir entre repetición y conflicto de clave (RN-004-08). |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `disputes` | `dispute_id` (`String`, PK), `transaction_id` (FK → `transactions.transaction_id`, indexada), `conversation_id` (`String`), `idempotency_key` (`String`), `reason` (`String`), `status` (`String`), `opened_at` (`DateTime`, UTC sin zona) | Tabla nueva. Índice único `(conversation_id, idempotency_key)`. Índice único parcial `ux_disputes_open_transaction` sobre `transaction_id` con `sqlite_where=status = 'OPEN'`. |

### Semillas

Ficticias y fijas (Art. 1). Los tests usan builders de `tests/fakes/`, no estas semillas (§5.3.7). Usan `conversation_id = "SEED"` y claves `SEED-1`…`SEED-3`, que ninguna conversación real reutilizará. Dejan libres para la demo `TX-000001` y `TX-000005` (confirmadas, de Laura, sin disputa).

| ID | Transacción | Estado | Motivo | `opened_at` (Bogotá) |
|---|---|---|---|---|
| `DSP-000001` | `TX-000002` (Laura, StreamFlix Andina, `CONFIRMED`) | `OPEN` | `UNRECOGNIZED_CHARGE` | 2026-09-14 10:00 |
| `DSP-000002` | `TX-000006` (Laura, tarjeta bloqueada, `CONFIRMED`) | `CLOSED` | `NOT_RECEIVED` | 2026-09-20 09:30 |
| `DSP-000003` | `TX-000008` (Pedro, `CONFIRMED`) | `REJECTED` | `INCORRECT_AMOUNT` | 2026-09-25 16:45 |

## 5. Dependencias nuevas

Ninguna. `re`, `enum`, `dataclasses` y `datetime` son de la biblioteca estándar; SQLAlchemy (índices parciales con `sqlite_where`), Pydantic y `mcp` ya están en el stack.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes y builders nuevos en `tests/fakes/`:

- `DisputeBuilder` (valores por defecto válidos; estado, transacción, conversación y clave configurables).
- `FakeDisputeRepository`: disputas en memoria, con IDs `DSP-%06d`, búsqueda por clave y por disputa abierta, y la misma unicidad que el puerto exige.
- `FailingDisputeRepository`: falla en `add` con una excepción que no es de dominio y no guarda nada. Se puede "reparar" para AC-004-16.
- `FakeTransactionRepository` gana `find_customer_transaction` (usa sus tarjetas por cliente).
- `FakeVerificationStore`, `FakeAuditLog`, `FixedClock` y `TransactionBuilder` se reutilizan.

Los tests de herramienta usan una sesión MCP en memoria contra el servidor real con SQLite `:memory:`, como en 001–003, preparando la verificación con `verificar_identidad` o con el almacén del servidor.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-004-01 | `OpenDispute` con fakes: devuelve `Dispute` `OPEN` con `opened_at` = reloj, `replayed = false`, y el fake guarda exactamente 1 disputa; el almacén no cambia | `iniciar_disputa` vía sesión MCP con SQLite: `status = "OPEN"`, `opened_at = "2026-10-17T10:00:00-05:00"`, `transaction` con los campos exactos y `masked_card = "**** 4321"`; la transacción sigue `CONFIRMED` y la tarjeta activa | La salida cumple `IniciarDisputaOut` | — |
| AC-004-02 | `DisputeRequest.create` acepta los 5 códigos (parametrizado) | La herramienta abre una disputa con cada código y devuelve el mismo `reason` (5 filas) | `reason` de salida es un enum de los 5 códigos | — |
| AC-004-03 | `DisputeRequest.create` rechaza `"FRAUD"`, minúsculas, texto en español, `""` y `None` → `InvalidInputError`; el caso de uso no toca repositorios | La herramienta devuelve `INVALID_INPUT` con `retryable=false` y no hay disputas en la base (5 filas) | El esquema de entrada publica el `enum` de `reason` | — |
| AC-004-04 | El caso de uso con la transacción `CONFIRMED`, `PENDING` y `REVERSED` → disputa, `TransactionNotDisputableError` y `TransactionNotDisputableError` (parametrizado) | La herramienta con los 3 estados: `OPEN`, `TRANSACTION_NOT_DISPUTABLE` y `TRANSACTION_NOT_DISPUTABLE`, sin disputas registradas en los dos últimos | El catálogo de códigos incluye `TRANSACTION_NOT_DISPUTABLE` | — |
| AC-004-05 | El caso de uso abre la disputa con transacciones de hace 1, 90 y 400 días respecto al `FixedClock` (parametrizado) | La herramienta con las 3 fechas | — | — |
| AC-004-06 | — | `find_customer_transaction` encuentra la transacción con la tarjeta activa, bloqueada y cancelada; la herramienta abre la disputa en las 3 filas | — | — |
| AC-004-07 | El caso de uso con una disputa previa `OPEN` → `DisputeAlreadyOpenError` con `dispute_id = "D-OLD"`; con `CLOSED` o `REJECTED`, una disputa nueva con otro ID | La herramienta con las 3 filas: `DISPUTE_ALREADY_OPEN` con `D-OLD` en el `message` y una sola disputa; nueva `OPEN` en las otras dos. El índice parcial rechaza un segundo `OPEN` insertado directamente en el repositorio SQL | El catálogo de códigos incluye `DISPUTE_ALREADY_OPEN` | — |
| AC-004-08 | Dos ejecuciones con la misma clave, transacción y motivo, con el reloj una hora después: misma `Dispute`, `replayed = true` y 1 sola disputa en el fake | La herramienta: la segunda respuesta tiene el mismo `dispute_id` y `opened_at`, no `DISPUTE_ALREADY_OPEN`, y hay 1 fila en `disputes` | — | — |
| AC-004-09 | La misma clave con otra transacción y con otro motivo → `InvalidInputError` sin llamar a `add` (2 filas) | La herramienta con las 2 filas: `INVALID_INPUT` y sin disputas adicionales | — | — |
| AC-004-10 | Con la clave `K-1` usada en `A`, una solicitud en `B` (verificada para el mismo cliente) → `DisputeAlreadyOpenError` con `D-1` | La herramienta en `A` y `B` verificadas con `verificar_identidad`: `B` recibe `DISPUTE_ALREADY_OPEN` con el ID de `A` y hay 1 fila | — | — |
| AC-004-11 | `find_customer_transaction` del fake devuelve `None` para la transacción ajena y la inexistente → `TransactionNotFoundError` en ambos casos | La herramienta con `TX-P1` (de Pedro) y `TX-9999`: los dos sobres son iguales campo a campo y no tienen datos de Pedro; el repositorio SQL no devuelve transacciones de otro cliente | El catálogo de códigos incluye `NOT_FOUND` | — |
| AC-004-12 | El caso de uso con el almacén en las 4 situaciones → `IdentityNotVerifiedError`, sin llamar a los repositorios; el almacén no cambia | La herramienta en las 4 situaciones (incluida `B` con `A` verificada vía `verificar_identidad`) → `IDENTITY_NOT_VERIFIED` con `retryable=false`, sin disputas y con el almacén igual | — | — |
| AC-004-13 | `DisputeRequest.create` parametrizado con las 7 filas (incluidos los bordes de 64 y 65 caracteres) | La herramienta devuelve `INVALID_INPUT` con `retryable=false` y sin disputas en cada fila | El sobre de error cumple `ToolErrorOut` | — |
| AC-004-14 | El caso de uso parametrizado con las 5 filas: el primer resultado según RN-004-10 | La herramienta con las 5 filas | — | — |
| AC-004-15 | — | La respuesta serializada solo tiene los campos de RN-004-12, `masked_card = "**** 4321"`, y no contiene `4111111111114321`, `D-1001` ni `Laura Méndez`; `dispute_id` no contiene el PAN | `IniciarDisputaOut` y `TransactionItemOut` tienen `additionalProperties: false` y exactamente los campos de la spec §7 | — |
| AC-004-16 | `FailingDisputeRepository` → `CoreUnavailableError`, auditado como `INTERNAL`, sin disputa guardada; tras repararlo, la misma solicitud con `K-1` crea la disputa (`replayed = false`) | `SqlAlchemyDisputeRepository.add` hace `rollback` ante un fallo y la sesión sigue usable. La herramienta con un repositorio que falla devuelve `INTERNAL` con `retryable=false`, sin el texto de la excepción, trazas ni SQL | El sobre cumple `ToolErrorOut` | — |
| AC-004-17 | `FakeAuditLog` + `FixedClock`: exactamente un evento en cada uno de los 10 casos (parametrizado), con `conversation_id`, timestamp, `tool`, `transaction_id`, `dispute_reason`, `idempotency_key`, resultado y `dispute_id`. `reason` vacío con `"FRAUD"`; `[REDACTED]` con el PAN en `transaction_id` y en `idempotency_key`. Ni el evento ni su JSON contienen `4111111111114321` ni `D-1001`. Test unitario de `redact_card_numbers` (12, 13, 19 dígitos y texto mixto) | `JsonAuditLog` escribe los campos nuevos y omite los vacíos; los eventos de 001–003 no cambian de claves; nada en `stdout` | — | — |

Adicionales (`mcp-testing.md` §7, §2):

- **Snapshot del catálogo:** `test_tool_catalog.py` pasa a esperar también `iniciar_disputa`, compara sus esquemas de entrada y salida con la spec §7 y falla ante herramientas no declaradas.
- **Art. 7 (§5.3.5):** la llamada sin identificación previa la cubre AC-004-12; también se prueba que la herramienta nunca escribe en el almacén (RN-004-14).
- **Escalamiento (§5.3.4):** el caso de la spec §8 (`INTERNAL` con `retryable = false`) lo cubre AC-004-16.
- **Smoke por stdio:** el test existente que lanza el servidor como subproceso se amplía: `list_tools` muestra las cuatro herramientas y, tras `verificar_identidad` con `C-0001`, `iniciar_disputa` sobre `TX-000001` devuelve `OPEN`; la salida por `stdout` es solo protocolo.
- **`server.mcp`:** el test existente pasa a esperar las cuatro herramientas.
- **Semillas:** test de integración de que se siembran las 3 disputas de §4, una sola vez, y de que `TX-000002` queda con su disputa `OPEN`.
- **Regresión de 001–003:** `seed_database` cambia de firma, `_to_item` cambia de nombre, `FakeTransactionRepository` gana un método y `ErrorCode` se amplía. Las suites de 001–003 deben seguir en verde, ajustando solo los puntos de llamada.
- El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global y, en la verificación final, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Una solicitud fallida deja la sesión SQLAlchemy compartida en estado inválido (`PendingRollbackError`) y todas las herramientas posteriores fallan | Alto | `SqlAlchemyDisputeRepository.add` hace `rollback` en cualquier excepción antes de relanzarla; un test de integración fuerza un `IntegrityError` y comprueba que la siguiente operación funciona. |
| La herramienta comprueba la verificación contra un almacén distinto del de `verificar_identidad` | Alto | `server.py` crea una sola instancia y la comparte; el smoke por stdio y los tests de herramienta verifican primero con `verificar_identidad` y luego abren la disputa en el mismo servidor. |
| Fuga o disputa de una transacción de otro cliente | Alto | `find_customer_transaction` filtra por el `customer_id` del almacén, nunca por un dato de la solicitud; AC-004-11 lo prueba en el fake y en SQLite con dos clientes. |
| Una base SQLite local creada con 001–003 no tiene la tabla `disputes`, ni las semillas de disputas, porque los clientes ya existen | Medio | `create_all` crea la tabla vacía y la herramienta funciona. Para tener las semillas de disputas hay que borrar `data/core_banking.db` (ignorado por git), como en 003. |
| Dos solicitudes simultáneas crean dos disputas `OPEN` | Medio | Índice único parcial en SQLite; el choque sale como `INTERNAL` (Art. 10). Hay un test de integración del índice. |
| El `dispute_id` consecutivo (número de filas + 1) se repite si se borran filas | Bajo | Esta versión no borra disputas; la PK es única, así que un choque fallaría en vez de duplicar. |
| Un PAN escrito en un campo de texto libre llega a la auditoría | Medio | `redact_card_numbers` se aplica siempre a `transaction_id` e `idempotency_key` antes de crear el evento; AC-004-17 lo prueba en el evento y en el JSON. |
| Ampliar `ErrorCode` cambia el esquema del sobre de error de 001–003 | Bajo | Es un cambio compatible (catálogo ampliado, `mcp-tools.md` §7). Los tests de contrato del sobre se actualizan en el mismo cambio. |
| `seed_database` y `FakeTransactionRepository` cambian y los usan varios tests | Bajo | La tarea que los cambia actualiza sus llamadas; `server.py`, `conftest.py` y `tests/fakes/*` se tratan como archivos compartidos al calcular las oleadas. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Las 3 disputas de las semillas son inventadas y fijas (§4) y reutilizan transacciones ficticias de 003; los tests usan builders. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento; los 17 AC están trazados en §6. Los ajustes a 001–003 (renombrado de `_to_item`, firma de `seed_database`, catálogo de errores) no cambian su comportamiento. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); el dominio puro, el caso de uso y los fakes permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio usa solo stdlib (`dataclasses`, `enum`, `datetime`, `re`); SQLAlchemy y Pydantic se quedan en infraestructura y se mapean en los adaptadores; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La herramienta solo registra la disputa; no decide si procede ni toca `DisputePolicy` (spec §5). |
| Art. 6 — Acciones vía MCP | Cumple | Las disputas solo se crean mediante la herramienta MCP `iniciar_disputa`. |
| Art. 7 — Identificación antes que información | Cumple | El caso de uso consulta el almacén de 002 antes de tocar datos y resuelve la transacción con el `customer_id` verificado (AC-004-11, AC-004-12). La respuesta solo enmascara la tarjeta (AC-004-15). |
| Art. 8 — Auditoría | Cumple | Cada invocación genera un único registro con `conversation_id`, marca de tiempo del reloj inyectado, herramienta, transacción, motivo, clave, resultado, regla y motivo de auditoría, sin PAN ni documento (AC-004-17). |
| Art. 9 — Secretos | Cumple | No hay secretos ni configuración nueva. |
| Art. 10 — Ante la duda, escalar | Cumple | Una falla inesperada, incluido un choque del índice parcial, devuelve `INTERNAL` con `retryable = false` sin dejar nada registrado (AC-004-16); el escalamiento lo ejecutará el consumidor (spec §8). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
