# Tareas: Verificar la identidad del cliente con su fecha de nacimiento y la de expedición de su documento

| Campo | Valor |
|---|---|
| Feature | `002-identity-verification` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.2 |
| Fecha | 2026-10-17 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas relativas a la raíz del repositorio. Los `__init__.py` de los paquetes de 001 ya existen; el de `infrastructure/outbound/verification/` lo crea T-002-11. Solo T-002-05 escribe en `tests/fakes/`: las demás tareas los reutilizan sin modificarlos. Las tareas que cambian la firma de `SqlAlchemyCustomerRepository.add` (T-002-10) adaptan en la misma tarea los tests y las semillas de 001 que lo llaman, para que la suite siga en verde al terminar cada oleada.

---

## Tareas

### [x] T-002-01 — Value objects `IdentityRecord` y `VerificationState`

- **Cubre:** AC-002-05 (límite de 3 fallos), AC-002-13 (conversación desconocida = no verificada); habilita AC-002-01…16 (plan §4 Dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/models/identity.py`, `tests/unit/core_banking_mcp/domain/test_identity_models.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_identity_models.py::test_ac_002_05_state_attempts_remaining_and_lock_boundaries`
- **Red:** el parametrizado con 0, 1, 2 y 3 fallos (restantes `3, 2, 1, 0`; `is_locked` solo con 3) falla con `ImportError` porque `VerificationState` no existe. También: el estado vacío tiene `verified_customer_id = None` y `failed_attempts = 0`, y `is_verified_for` es `False` (`test_ac_002_13_empty_state_is_not_verified`); `with_failure()` suma uno y `with_verified(customer_id)` fija el cliente; se rechaza `failed_attempts` fuera de 0–3 y un estado verificado y bloqueado a la vez; `IdentityRecord` rechaza una expedición anterior al nacimiento y acepta fechas iguales.
- **Green:** `MAX_FAILED_ATTEMPTS = 3`, `IdentityRecord(birth_date, document_issue_date)` y `VerificationState(verified_customer_id, failed_attempts)` como `dataclass(frozen=True)` con invariantes en `__post_init__`, propiedades `attempts_remaining` e `is_locked`, `is_verified_for(customer_id)`, `with_failure()` y `with_verified(customer_id)`; errores con `InvalidInputError` o `ValueError` solo con stdlib.
- **Refactor:** —
- **Nota:** el subagente citó `RN-002-05` / `AC-002-05` en todos los tests, incluidos los de `IdentityRecord` (que corresponden a RN-002-01 / RN-002-07, sin AC propio) y el de estado vacío. Pendiente de corregir los comentarios de trazabilidad antes de la auditoría de AC (5.5).

### [x] T-002-02 — Conversión de "hoy" a la zona America/Bogota

- **Cubre:** AC-002-09 (borde de las 03:00Z y las 05:00Z)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/clock.py`, `tests/unit/core_banking_mcp/domain/test_clock.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_clock.py::test_ac_002_09_today_in_bogota_boundaries`
- **Red:** el parametrizado con `2026-10-17T15:00:00Z → 2026-10-17`, `2026-10-18T03:00:00Z → 2026-10-17`, `2026-10-18T04:59:59Z → 2026-10-17` y `2026-10-18T05:00:00Z → 2026-10-18` falla porque `today_in_bogota` no existe.
- **Green:** `today_in_bogota(now: datetime) -> date` con `now.astimezone(timezone(timedelta(hours=-5))).date()`, solo con stdlib.
- **Refactor:** —

### [x] T-002-03 — Validación de la solicitud `VerificationRequest`

- **Cubre:** AC-002-08, AC-002-03, AC-002-09 (límites de las fechas válidas, nivel dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-002-01
- **Archivos:** `src/core_banking_mcp/domain/models/identity.py`, `tests/unit/core_banking_mcp/domain/test_verification_request.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_verification_request.py::test_ac_002_08_invalid_request_is_rejected`
- **Red:** el parametrizado con las 13 filas del AC-002-08 (cada fila con el resto de campos válidos; `None` equivale a ausente) falla porque `VerificationRequest` no existe: fechas vacías o `None`, `1990-02-31`, `2008-02-31`, `15/03/1990`, `2026-10-18` como nacimiento y como expedición con `today = 2026-10-17`, expedición `1990-03-14` con nacimiento `1990-03-15`, `customer_id` ausente/vacío/solo espacios, `customer_id` de 33 caracteres y `conversation_id` ausente/vacío/solo espacios. Se añaden: `test_ac_002_03_swapped_dates_are_invalid` (`2008-04-20` / `1990-03-15`), formatos que `date.fromisoformat` aceptaría pero la spec no (`20260115`, `2026-W03-2`, ` 1990-03-15`, dígitos no ASCII), `test_ac_002_09_request_date_limits` (con `today`: expedición igual a hoy y nacimiento igual a expedición son válidas), borde de `customer_id` con 32 caracteres y recorte de `customer_id` y `conversation_id`.
- **Green:** `VerificationRequest(conversation_id, customer_id, birth_date, document_issue_date)` con `create(conversation_id, customer_id, birth_date, document_issue_date, today)`: recorta `conversation_id` y `customer_id`, valida 1–32 caracteres, parsea las fechas con `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")` y `date(...)` (captura `ValueError`), y rechaza futuras y expedición anterior al nacimiento con `InvalidInputError(field, reason)`. Solo stdlib.
- **Refactor:** —

### [x] T-002-04 — Decisión pura `evaluate_verification`

- **Cubre:** AC-002-01, AC-002-02, AC-002-04, AC-002-05, AC-002-06, AC-002-07, AC-002-11, AC-002-12
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-002-03
- **Archivos:** `src/core_banking_mcp/domain/identity_verification.py`, `tests/unit/core_banking_mcp/domain/test_identity_verification.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_identity_verification.py::test_ac_002_02_any_wrong_date_fails_without_revealing_which`
- **Red:** falla porque `evaluate_verification` no existe. Tests table-driven, uno por cada regla de la spec:
  - `test_ac_002_02_...`: 3 filas (nacimiento incorrecto, expedición incorrecta, ambas) → `FAILED`, `attempts_remaining = 2`, sin escalar, y la decisión no contiene cuál dato falló.
  - `test_ac_002_01_...`: ambas fechas correctas → `VERIFIED`, estado con `C-0001`, 3 restantes.
  - `test_ac_002_04_...`: identidad `None` (cliente inexistente) produce la misma decisión que las fechas incorrectas y suma un fallo.
  - `test_ac_002_05_...`: 0, 1 y 2 fallos previos → `2/false`, `1/false`, `0/true` (borde exacto del 3.er fallo, `LOCKED`).
  - `test_ac_002_06_...`: dos fallos previos y fechas correctas → `VERIFIED` con 1 restante.
  - `test_ac_002_07_...`: estado bloqueado con fechas correctas → `LOCKED`, 0 restantes, escalar y sigue sin cliente verificado.
  - `test_ac_002_11_...`: verificada para `C-0001` y solicitud para otro cliente (3 filas) → `OTHER_CUSTOMER`, 3 restantes, sin escalar, el estado no cambia.
  - `test_ac_002_12_...`: mismo cliente con fechas correctas e incorrectas (2 filas) → `ALREADY_VERIFIED` con el estado igual.
- **Green:** `VerificationOutcome` (`VERIFIED`, `ALREADY_VERIFIED`, `FAILED`, `LOCKED`, `OTHER_CUSTOMER`), `VerificationDecision(state, verified, escalation_required, outcome)` y `evaluate_verification(state, request, identity)`: verificada para el mismo cliente → `ALREADY_VERIFIED`; verificada para otro → `OTHER_CUSTOMER`; bloqueada → `LOCKED`; si no, compara ambas fechas con `identity` (`None` cuenta como no coincidencia) y devuelve `VERIFIED` o suma un fallo (`FAILED`, o `LOCKED` si es el tercero). `escalation_required` solo con `LOCKED`. Puro y solo con stdlib.
- **Refactor:** extraer la comparación de fechas a una función privada si `evaluate_verification` supera ~30 líneas.

### [x] T-002-05 — Puertos, `AuditEvent` ampliado y fakes de test

- **Cubre:** habilita AC-002-01…16 en unit e integración (plan §3 y §6); AC-002-13 (`FakeVerificationStore`)
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-002-01
- **Archivos:** `src/core_banking_mcp/application/ports/conversation_verification_store.py`, `src/core_banking_mcp/application/ports/customer_repository.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `tests/fakes/identity_builder.py`, `tests/fakes/fake_verification_store.py`, `tests/fakes/fake_customer_repository.py`, `tests/fakes/failing_customer_repository.py`, `tests/unit/core_banking_mcp/application/test_fakes.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_fakes.py::test_fake_verification_store_unknown_conversation_is_not_verified` (antes `test_ac_002_13_...`; renombrado en la tercera auditoría: es un test de soporte, fuera de la trazabilidad de AC)
- **Red:** falla porque no existen `FakeVerificationStore`, `IdentityBuilder` ni `find_identity`. Se añaden: `get` de una conversación desconocida devuelve el estado vacío y `save` lo conserva por conversación; helpers `with_verified(conversation_id, customer_id)` y `with_failures(conversation_id, n)` para los "Given" de los AC; `IdentityBuilder().build()` devuelve fechas por defecto y admite `with_birth_date` / `with_issue_date`; `FakeCustomerRepository([...], identities={"C-001": ...}).find_identity` devuelve la identidad o `None` y el constructor sin `identities` sigue funcionando; `FailingCustomerRepository.find_identity` lanza `RuntimeError`; `AuditEvent` se construye sin `customer_id` ni `intento` (valores por defecto `None`) y con `input=None`.
- **Green:** puerto `ConversationVerificationStore` (`get(conversation_id) -> VerificationState`, `save(conversation_id, state)`); `CustomerRepository.find_identity(customer_id) -> IdentityRecord | None`; `AuditEvent.input: AuditInput | None` y los campos `customer_id: str | None = None` e `intento: int | None = None` al final; los fakes y el builder descritos. Los eventos de `buscar_cliente` no cambian de contenido.
- **Refactor:** —

### [x] T-002-06 — Caso de uso `VerifyIdentity` (comportamiento)

- **Cubre:** AC-002-01, AC-002-02, AC-002-03, AC-002-04, AC-002-06, AC-002-07, AC-002-08, AC-002-09, AC-002-10, AC-002-11, AC-002-12, AC-002-13, AC-002-14, AC-002-16
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-002-04, T-002-05
- **Archivos:** `src/core_banking_mcp/application/use_cases/verify_identity.py`, `tests/unit/core_banking_mcp/application/test_verify_identity.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_verify_identity.py::test_ac_002_01_correct_dates_verify_and_store_customer`
- **Red:** falla porque `VerifyIdentity` no existe. Con `FakeCustomerRepository`, `FakeVerificationStore`, `FakeAuditLog` y `FixedClock` (los AC parten de `C-0001`/`C-0002` construidos con builders):
  - `test_ac_002_01_...`: devuelve `verified = true`, `3`, `false` y el almacén indica `C-0001`.
  - `test_ac_002_06_...` y `test_ac_002_07_...`: con 2 y 3 fallos preparados.
  - `test_ac_002_02_...` y `test_ac_002_04_...`: fecha incorrecta y cliente inexistente producen la misma respuesta, sin cliente verificado y con un fallo acumulado.
  - `test_ac_002_11_...` y `test_ac_002_12_...`: otro cliente e idempotencia sin contar intentos. En AC-002-12 el repositorio de identidades no se consulta (se verifica con un repositorio que falla si se invoca).
  - `test_ac_002_13_verification_is_per_conversation`: `A` verificada, `B` sin estado y con su propio contador (2 restantes).
  - `test_ac_002_08_...` y `test_ac_002_03_...`: entradas inválidas (incluidas `None`) lanzan `InvalidInputError` sin cambiar el estado ni consultar el repositorio.
  - `test_ac_002_09_...`: cuatro instantes UTC de la spec con `FixedClock`.
  - `test_ac_002_10_invalid_input_does_not_consume_attempts`: con 2 fallos, una entrada inválida y luego fechas correctas → `verified = true`.
  - `test_ac_002_14_result_has_only_three_fields`: `VerificationResult` solo tiene `verified`, `attempts_remaining` y `escalation_required`.
  - `test_ac_002_16_unexpected_failure_raises_core_unavailable`: con `FailingCustomerRepository` → `CoreUnavailableError` sin el texto de la excepción original y con el estado intacto.
- **Green:** `VerifyIdentityCommand(conversation_id, customer_id, birth_date, document_issue_date)` (todos `str | None`), `VerificationResult(verified, attempts_remaining, escalation_required)` y `VerifyIdentity(repository, store, audit_log, clock).execute(command)`: calcula `today_in_bogota(clock.now())`, crea `VerificationRequest`, lee el estado con `store.get`, consulta `repository.find_identity` solo si el estado exige comparar, llama a `evaluate_verification`, guarda con `store.save` y devuelve el resultado; cualquier excepción distinta de `InvalidInputError` se convierte en `CoreUnavailableError` sin guardar. El constructor ya recibe `audit_log` pero esta tarea no lo usa (lo cubre T-002-07).
- **Refactor:** extraer una función privada que decide si hace falta consultar el repositorio, si aclara el flujo.

### [x] T-002-07 — Auditoría de `VerifyIdentity`

- **Cubre:** AC-002-15
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-002-06
- **Archivos:** `src/core_banking_mcp/application/use_cases/verify_identity.py`, `tests/unit/core_banking_mcp/application/test_verify_identity_audit.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_verify_identity_audit.py::test_ac_002_15_each_invocation_records_exactly_one_event`
- **Red:** el parametrizado de los 8 casos de la spec falla porque no se registra ningún evento: `verified`, `already_verified`, `failed` con `intento = 1`, el 3.er fallo → `locked`, solicitud en conversación bloqueada → `locked`, `other_customer`, datos inválidos → código `INVALID_INPUT` y falla inesperada → código `INTERNAL`. En cada caso: exactamente un evento con `conversation_id`, el instante del `FixedClock`, `tool = "verificar_identidad"`, el `customer_id` recibido (o `None` si no llegó), `input = None`, `rule` y `reason`; y ninguna fecha, recibida ni registrada, aparece en el evento serializado con `dataclasses.asdict` (se buscan los valores `1990-03-15`, `2008-04-20` y los recibidos en su texto). Un caso con `conversation_id` ausente registra `conversation_id` vacío.
- **Green:** `VerifyIdentity` llama a `audit_log.record(AuditEvent(...))` una vez en cada salida: `outcome` = `verified`, `already_verified`, `failed`, `locked`, `other_customer` o `error` (con `error_code`), `intento` solo en `failed`, y la regla de cada caso (RN-002-02, RN-002-11, RN-002-03/04, RN-002-05, RN-002-10, RN-002-07, RN-002-16) con un motivo en español. Nunca se copia ninguna fecha al evento.
- **Refactor:** consolidar la construcción del evento en un método privado `_record` como en `SearchCustomers`.

### [x] T-002-08 — Esquemas MCP de `verificar_identidad` (contrato)

- **Cubre:** AC-002-14 (la salida tiene exactamente 3 campos), AC-002-03 y AC-002-16 (sobre de error cumple `ToolErrorOut`, catálogo de códigos cerrado)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py::test_ac_002_14_output_schema_has_exactly_three_fields`
- **Red:** falla con `ImportError` porque `VerificarIdentidadOut` no existe. Además: `additionalProperties` es `false` y los 3 campos son `verified`, `attempts_remaining` y `escalation_required`; `attempts_remaining` acepta 0–3 y rechaza `-1` y `4`; `VerificarIdentidadIn` declara los 4 campos de entrada de la spec §7 con `description`; `ErrorCode` sigue siendo exactamente `INVALID_INPUT` e `INTERNAL`.
- **Green:** `VerificarIdentidadIn` (`conversation_id`, `customer_id`, `birth_date`, `document_issue_date`, todos con `Field(description=...)`) y `VerificarIdentidadOut` (`extra="forbid"`, `attempts_remaining` con `ge=0, le=3`) en `schemas.py`; `ErrorCode` y `ToolErrorOut` no cambian.
- **Refactor:** —

### [x] T-002-09 — Mover `ErrorPassthroughMetadata` a `errors.py`

- **Cubre:** habilita AC-002-03 y AC-002-16 (errores `isError=true` de `verificar_identidad` con `outputSchema`)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/errors.py`, `src/core_banking_mcp/infrastructure/inbound/mcp/tools.py`, `tests/integration/core_banking_mcp/mcp/test_error_passthrough.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_error_passthrough.py::test_error_passthrough_metadata_returns_error_results_untouched`
- **Red:** falla con `ImportError` porque `ErrorPassthroughMetadata` no existe en `errors.py`. Comprueba que un `CallToolResult` con `isError=True` pasa intacto por `convert_result` aunque no cumpla el esquema de salida, y que un éxito sí se valida. Los tests de `buscar_cliente` de 001 deben seguir en verde (regresión).
- **Green:** mover la clase `_ErrorPassthroughMetadata` de `tools.py` a `errors.py` como `ErrorPassthroughMetadata` pública; `tools.py` la importa. Sin cambio de comportamiento.
- **Refactor:** —

### [x] T-002-10 — Persistir las fechas, `find_identity` y semillas

- **Cubre:** AC-002-01 y AC-002-04 (nivel repositorio), AC-002-14 (`buscar_cliente` no expone las fechas); habilita los tests de herramienta y el smoke por stdio
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-002-05
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_customer_repository.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/customers.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`, `tests/integration/core_banking_mcp/mcp/test_buscar_cliente_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py::test_ac_002_01_find_identity_returns_registered_dates`
- **Red:** falla porque `add` no acepta `identity` y `find_identity` no existe. Casos nuevos: ida y vuelta de las dos fechas (`find_identity("C-001")`), `find_identity` de un `customer_id` inexistente devuelve `None` (`test_ac_002_04_find_identity_unknown_customer_returns_none`), y `test_ac_002_14_find_matching_entities_do_not_expose_dates` (la entidad `Customer` devuelta no tiene atributos de fechas). `test_seeds.py::test_ac_002_01_seeded_customers_have_registered_dates`: las 7 semillas tienen identidad y `C-0001` / `C-0002` tienen las fechas de la spec (`1990-03-15` / `2008-04-20` y `1985-07-02` / `2003-08-10`).
- **Green:** `CustomerRow` gana `birth_date` y `document_issue_date` (`Date`, no nulas); `SqlAlchemyCustomerRepository.add(customer, pans=None, *, identity)` las guarda y `find_identity(customer_id)` las lee por clave primaria y las mapea a `IdentityRecord`; `_to_entity` y `find_matching` no cambian. `SEED_CUSTOMERS` incluye la identidad de cada semilla (fechas del plan §4) y `seed_database` la pasa a `add`. Se adaptan los `repo.add(...)` de `test_sqlalchemy_customer_repository.py`, el desempaquetado de `test_seeds.py` y el `repo.add` de `test_buscar_cliente_tool.py` con `identity=IdentityBuilder().build()`, para que la suite de 001 siga en verde.
- **Refactor:** —
- **Nota:** una base SQLite creada con la feature 001 no tiene las columnas nuevas; hay que borrar `data/core_banking.db` (plan §7).

### [x] T-002-11 — Almacén en memoria del estado de verificación

- **Cubre:** AC-002-13 (nivel integración del adaptador)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-002-05
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/verification/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/verification/in_memory_verification_store.py`, `tests/integration/core_banking_mcp/verification/test_in_memory_verification_store.py`
- **Test primero:** `tests/integration/core_banking_mcp/verification/test_in_memory_verification_store.py::test_ac_002_13_store_keeps_conversations_independent`
- **Red:** falla porque `InMemoryConversationVerificationStore` no existe. Casos: `get` de una conversación desconocida devuelve el estado vacío; guardar el estado de `A` no cambia el de `B`; un segundo `save` reemplaza al anterior; y una prueba con varios hilos que guardan estados de conversaciones distintas no pierde ninguno.
- **Green:** `InMemoryConversationVerificationStore` con un `dict[str, VerificationState]` protegido con `threading.Lock`; `get` devuelve `VerificationState()` vacío si no hay entrada. Los estados son inmutables, no se copian.
- **Refactor:** —

### [x] T-002-12 — Serialización JSON de auditoría sin fechas

- **Cubre:** AC-002-15 (nivel integración del adaptador); corrige la regresión de AC-001-13 causada por T-002-05
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-002-05
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/integration/core_banking_mcp/audit/test_json_audit_log.py::test_ac_001_13_audit_event_is_written_as_json_line` (ya existe y hoy **falla**: es el Red) y `::test_ac_002_15_verificar_identidad_event_is_serialized_without_dates`
- **Red:** `test_ac_001_13_...` falla porque la línea JSON de un evento de `buscar_cliente` trae `customer_id: null` e `intento: null` (claves nuevas de `AuditEvent` serializadas por `asdict`). Además, un evento de `verificar_identidad` (`input=None`, `customer_id="C-0001"`, `intento=1`, `outcome="failed"`) debe escribir una línea JSON válida con `customer_id`, `intento`, `input` nulo y el instante en ISO, sin ninguna cadena `AAAA-MM-DD` de fechas de identidad y sin nada en `stdout`. Se añade un caso de `verificar_identidad` con `customer_id` pero sin `intento` (la línea no trae `intento`). No se modifica el test de 001.
- **Green:** `JsonAuditLog.record` omite del JSON las claves `customer_id` e `intento` cuando valen `None` (el resto de claves, incluidas las nulas existentes como `error_code`, `rule` e `input`, no cambia), de modo que las líneas de `buscar_cliente` quedan idénticas a las de 001.
- **Refactor:** —
- **Nota:** decisión del usuario (2026-10-17) tras la oleada 2: omitir las claves nulas nuevas en lugar de actualizar el test de 001. Esta tarea se ejecuta sola antes de la oleada 3 para recuperar la suite en verde.

### [x] T-002-13 — Herramienta `verificar_identidad` (camino exitoso)

- **Cubre:** AC-002-01, AC-002-02, AC-002-04, AC-002-05, AC-002-06, AC-002-07, AC-002-11, AC-002-12, AC-002-13, AC-002-14
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-002-06, T-002-08, T-002-09, T-002-10, T-002-11
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/identity_tools.py`, `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_tool.py::test_ac_002_01_verificar_identidad__correct_dates__verifies_customer`
- **Red:** falla porque `register_identity_tools` no existe. Con una sesión MCP en memoria (`mcp.shared.memory`), SQLite `:memory:` con clientes construidos con `CustomerBuilder` e `IdentityBuilder`, el `InMemoryConversationVerificationStore` real, `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`:
  - AC-002-01: `{"verified": true, "attempts_remaining": 3, "escalation_required": false}`, `isError=false`, y el almacén indica `C-0001`.
  - AC-002-02: 3 filas, respuesta `false/2/false` sin indicar cuál dato falló y sin cliente verificado.
  - AC-002-04: `C-9999` devuelve exactamente la respuesta de AC-002-02 y suma un fallo.
  - AC-002-05: 3 filas con el almacén preparado con 0, 1 y 2 fallos.
  - AC-002-06 y AC-002-07: con 2 y 3 fallos.
  - AC-002-11 (3 filas) y AC-002-12 (2 filas).
  - AC-002-13: `B` no verificada, con su contador (2 restantes) y `A` conserva a `C-0001`.
  - AC-002-14 (2 filas): la respuesta serializada tiene exactamente los 3 campos y no contiene `1990-03-15`, `2008-04-20`, `Laura Méndez`, `D-1001` ni un PAN.
- **Green:** `register_identity_tools(mcp, verify_identity)` registra `verificar_identidad` con firma `str | None` en los cuatro campos, `Field(description=...)` y docstring en español (propósito, cuándo usarla y cuándo no, efectos, no idempotente salvo RN-002-11), devuelve `CallToolResult` con `structuredContent` del modelo `VerificarIdentidadOut` y registra `ErrorPassthroughMetadata`, como `tools.py`. El mapeo de errores queda para T-002-14.
- **Refactor:** —

### [x] T-002-14 — `verificar_identidad`: errores, entradas inválidas y auditoría

- **Cubre:** AC-002-03, AC-002-08, AC-002-09, AC-002-10, AC-002-15, AC-002-16
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-002-07, T-002-12, T-002-13
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/identity_tools.py`, `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py::test_ac_002_08_verificar_identidad__invalid_input__returns_invalid_input`
- **Red:** falla porque la excepción del caso de uso se propaga sin sobre de error. Casos, con la misma sesión MCP en memoria:
  - AC-002-08: las 13 filas devuelven `isError=true`, `code = "INVALID_INPUT"` y `retryable = false`.
  - AC-002-03: las fechas intercambiadas devuelven `INVALID_INPUT` y la conversación sigue sin cliente verificado ni fallos.
  - AC-002-09: los 4 instantes con `FixedClock`.
  - AC-002-10: con 2 fallos, una fecha inválida y luego fechas correctas → `verified = true`.
  - AC-002-16: con un repositorio que falla, `INTERNAL` con `retryable = false`; el mensaje no contiene la excepción original, trazas ni SQL; sin cliente verificado ni fallos.
  - AC-002-15: con un `JsonAuditLog` real sobre un `StringIO`, cada llamada de los 8 casos deja una sola línea JSON con la herramienta, el `customer_id` recibido y el resultado esperado, y el texto de la línea no contiene ninguna fecha recibida ni registrada.
- **Green:** en `identity_tools.py`, `InvalidInputError` → `tool_error(INVALID_INPUT, "Los datos de verificación no son válidos (campo: {error.field}).", retryable=False)`, `CoreUnavailableError` y un *catch-all* defensivo → `tool_error(INTERNAL, mensaje_fijo, retryable=False)`, con mensajes que nunca incluyen el texto de la excepción.
- **Refactor:** —

### [x] T-002-15 — Declarar el extra `mcp[cli]`

- **Cubre:** habilita la prueba manual con MCP Inspector (plan §5)
- **App / capa:** `core_banking_mcp` / raíz (configuración)
- **Depende de:** —
- **Archivos:** `pyproject.toml`, `uv.lock`, `tests/unit/test_project_setup.py`
- **Test primero:** `tests/unit/test_project_setup.py::test_mcp_cli_extra_is_declared`
- **Red:** falla porque `pyproject.toml` declara `mcp>=1.13,<2` sin el extra `cli`; el test lee el archivo con `tomllib` y comprueba que la dependencia sea `mcp[cli]>=1.13,<2`.
- **Green:** cambiar la dependencia a `mcp[cli]>=1.13,<2` y ejecutar `uv sync` para regenerar `uv.lock`. No se añaden paquetes nuevos al entorno (`typer` y `python-dotenv` ya están instalados).
- **Refactor:** —

### [x] T-002-16 — Cableado del servidor, `mcp` perezoso y smoke por stdio

- **Cubre:** AC-002-01 (por stdio real), AC-002-05 (conversación nueva con 2 restantes por stdio); catálogo de herramientas (`mcp-testing.md` §7)
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-002-10, T-002-11, T-002-14, T-002-15
- **Archivos:** `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_002_01_catalog_exposes_buscar_cliente_and_verificar_identidad`
- **Red:** el catálogo falla porque `list_tools` solo devuelve `buscar_cliente`. El test actualizado de 001 espera `["buscar_cliente", "verificar_identidad"]`, compara el esquema de entrada de `verificar_identidad` (4 campos, descripción de `conversation_id`) y el de salida con `VerificarIdentidadOut.model_json_schema()` (`additionalProperties: false`), y falla ante herramientas no declaradas. `test_server_module.py::test_ac_002_01_server_mcp_attribute_is_lazy_and_exposes_both_tools` (con `CORE_DATABASE_URL` en memoria): importar `server` no construye nada, `server.mcp` devuelve un `FastMCP` con las dos herramientas, dos accesos devuelven la misma instancia y `server.otro_nombre` lanza `AttributeError`. En `test_stdio_smoke.py`, por stdio real y base sembrada: `list_tools` muestra las dos herramientas, `verificar_identidad` de `C-0001` con `1990-03-15` / `2008-04-20` devuelve `verified = true` (`test_ac_002_01_verificar_identidad__stdio_server__verifies_seeded_customer`) y, en otra conversación, una fecha incorrecta devuelve `verified = false` con `attempts_remaining = 2`. Este último pasa en cuanto el servidor está cableado.
- **Green:** `build_server` crea la única instancia de `InMemoryConversationVerificationStore`, construye `VerifyIdentity(repository, store, JsonAuditLog(), SystemClock())` y llama a `register_identity_tools`; se añade `__getattr__(name)` de módulo que, para `"mcp"`, devuelve `build_server()` construido una sola vez (caché) y, para cualquier otro nombre, lanza `AttributeError`. `main()` no cambia.
- **Refactor:** —

### [x] T-002-17 — Guía para probar con MCP Inspector

- **Cubre:** habilita la prueba manual (plan §1 y §2)
- **App / capa:** — / docs
- **Depende de:** T-002-10, T-002-15, T-002-16
- **Archivos:** `docs/mcp-inspector.md`, `tests/unit/test_mcp_inspector_guide.py`
- **Test primero:** `tests/unit/test_mcp_inspector_guide.py::test_mcp_inspector_guide_documents_command_and_seed_examples`
- **Red:** falla porque `docs/mcp-inspector.md` no existe. El test comprueba que el archivo contiene el comando `uv run mcp dev src/core_banking_mcp/server.py`, la mención a Node.js, el aviso de borrar `data/core_banking.db` si viene de 001, y que las fechas de `C-0001` que cita coinciden con `SEED_CUSTOMERS` (se leen de las semillas, no se copian a mano).
- **Green:** `docs/mcp-inspector.md`, en español: requisitos (Node.js), comando de arranque, aviso de que reconectar el Inspector reinicia el estado de verificación (RN-002-09) y de que la auditoría sale por `stderr`, y una tabla de llamadas de ejemplo con las semillas y la respuesta esperada: fechas correctas, fechas incorrectas hasta el bloqueo, fechas inválidas y otra conversación. Solo datos ficticios.
- **Refactor:** —

### [x] T-002-18 — Verificación final

- **Cubre:** Definition of Done (§5.5): AC-002-01…16 en verde, cobertura, lint, formato y tipado
- **App / capa:** `core_banking_mcp` / todas
- **Depende de:** T-002-01, T-002-02, T-002-03, T-002-04, T-002-05, T-002-06, T-002-07, T-002-08, T-002-09, T-002-10, T-002-11, T-002-12, T-002-13, T-002-14, T-002-15, T-002-16, T-002-17
- **Archivos:** — (solo verificación; no modifica archivos)
- **Test primero:** `uv run pytest --cov` (suite completa de 001 y 002)
- **Red:** si algún comando falla, la tarea queda `[ ]` con el motivo y se corrige en la tarea que corresponda.
- **Green:** pasan, sin errores: `uv run pytest --cov` (umbral global ≥ 80 %), `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.
- **Refactor:** —

## Correcciones de la auditoría de AC (fase 5.5, veredicto «No cumple»)

Cambios de trazabilidad en los tests, sin cambio de comportamiento (§4.3.5): no hay Red de pytest; el Red es el hallazgo de `verify-ac-coverage` (2 Bloqueantes, 9 Mayores). Cada tarea cita la RN y el AC reales según la spec (`spec.md` §4 y §6), mueve el comentario `Regla:` sobre el `def` o el `@pytest.mark.parametrize` y añade `ids=` donde falten. La suite debe seguir en verde. Quedan fuera de esta ronda y se reportan: nombrado `test_<tool>__<condición>__<resultado>` de los tests de `contract/` e `integration/` (m2, renombrarlos cambia la matriz), datos de fixtures distintos a los de la spec (m4), cita del test de concurrencia (m5) y los hallazgos de spec.

### [x] T-002-19 — Trazabilidad de los tests de dominio

- **Cubre:** corrige M1, M2, M3, M4, m1 y m3 de los tests de dominio (AC-002-03, AC-002-04, AC-002-05, AC-002-06, AC-002-08)
- **App / capa:** `core_banking_mcp` / `domain` (tests)
- **Depende de:** T-002-18
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_identity_models.py`, `tests/unit/core_banking_mcp/domain/test_verification_request.py`, `tests/unit/core_banking_mcp/domain/test_identity_verification.py`
- **Test primero:** los mismos tests existentes de esos tres archivos (deben seguir en verde)
- **Red:** hallazgos M1–M4 de la auditoría: `test_identity_models.py` cita RN-002-05 y AC-002-05 donde corresponde RN-002-04 (3.er fallo, límites) y, para los invariantes del modelo (estado inmutable, `0..3`, verificado y bloqueado excluyentes), el Artículo en lugar de una RN; el test de `IdentityRecord` (expedición anterior al nacimiento) corresponde a RN-002-07 y AC-002-03; `test_identity_verification.py` cita RN-002-06 para «los fallos previos no impiden verificar», que es RN-002-05 con AC-002-06.
- **Green:** corregir las citas; mover los comentarios `Regla:` sobre el `def` / el `parametrize` en `test_identity_models.py` y `test_verification_request.py` (m1); añadir `ids=` legibles a los parametrizados de esos dos archivos (m3). No cambiar ninguna aserción ni el código de `src/`.
- **Refactor:** —

### [x] T-002-20 — Trazabilidad de los tests de contrato, catálogo y passthrough

- **Cubre:** corrige B1, B2, M5, M6, M9, m3 y m7 (AC-002-01, AC-002-03, AC-002-05, AC-002-08, AC-002-16)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound` (tests)
- **Depende de:** T-002-18
- **Archivos:** `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/mcp/test_error_passthrough.py`
- **Test primero:** los mismos tests existentes de esos cuatro archivos (deben seguir en verde)
- **Red:** hallazgos B1, B2, M5, M6, M9 de la auditoría: `test_error_passthrough.py` no cita ninguna RN (debe citar RN-002-07 y RN-002-16 con AC-002-03 y AC-002-16); en `test_verificar_identidad_contract.py`, los tests de `attempts_remaining` (0 y 3; −1 y 4) citan `Regla: spec §7` y deben citar RN-002-04 con AC-002-05, el de los 4 campos de entrada debe citar RN-002-07 con AC-002-08 (no AC-002-14) y el del sobre de error se separa o cita RN-002-07 con AC-002-03 y RN-002-16 con AC-002-16 (m7: citar también AC-002-08 por el catálogo cerrado de códigos); `test_tool_catalog.py` y `test_server_module.py` citan RN-002-01 donde deben citar el Artículo o la spec §7, o decir qué parte de RN-002-01 verifican.
- **Green:** corregir las citas; añadir `ids=` a los parametrizados del archivo de contrato (m3). No cambiar ninguna aserción ni el código de `src/`.
- **Refactor:** —

### [x] T-002-21 — Trazabilidad de los tests de fakes, almacén y errores de herramienta

- **Cubre:** corrige M7, M8 y m3 (AC-002-15, AC-002-16) y deja citados los tests huérfanos de `test_fakes.py`
- **App / capa:** `core_banking_mcp` / `application` e `infrastructure` (tests)
- **Depende de:** T-002-18
- **Archivos:** `tests/unit/core_banking_mcp/application/test_fakes.py`, `tests/integration/core_banking_mcp/verification/test_in_memory_verification_store.py`, `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py`
- **Test primero:** los mismos tests existentes de esos tres archivos (deben seguir en verde)
- **Red:** hallazgos M7 y M8 de la auditoría: en `test_fakes.py`, el test de `FailingCustomerRepository.find_identity` cita RN-002-14 y AC-002-14 y corresponde a RN-002-16 y AC-002-16, y el de los campos nuevos de `AuditEvent` mezcla RN-001-12 con AC-002-01 y corresponde a RN-002-15 y AC-002-15; los cinco tests de fakes sin `Regla:` ni `AC-` (líneas 21, 48, 55, 75 y 155) no tienen ninguna cita.
- **Green:** corregir las dos citas; añadir a los cinco tests huérfanos su comentario de trazabilidad con la regla y el AC que habilitan (AC-001-13 / RN-001-12 para los de auditoría de 001, el Art. 3 para los de soporte); añadir `ids=` al parametrizado de AC-002-15 de `test_verificar_identidad_errors.py` (m3). No cambiar ninguna aserción ni el código de `src/`.
- **Refactor:** —

## Correcciones de la segunda auditoría de AC (veredicto «No cumple»: 4 Mayores y 6 Menores)

Mismas reglas que la ronda anterior: trazabilidad de tests sin cambio de comportamiento ni de `src/`. Solo se añaden aserciones donde el hallazgo lo exige (filas «ausente» en integración, un test explícito de RN-002-09). Quedan fuera y se reportan: m1 (convención de nombres, se fija en la rule, fuera de la escritura permitida) y los hallazgos de spec (AC para `server.mcp` perezoso y la guía del Inspector, y un AC propio de RN-002-09), que requieren `/specify`.

### [x] T-002-22 — Los tests de fakes dejan de citar RN y AC de la spec

- **Cubre:** corrige M1
- **App / capa:** `core_banking_mcp` / `application` (tests)
- **Depende de:** T-002-21
- **Archivos:** `tests/unit/core_banking_mcp/application/test_fakes.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo M1 de la auditoría: los tests de los fakes (`FakeVerificationStore`, `IdentityBuilder`, `FakeCustomerRepository.find_identity`, `FailingCustomerRepository.find_identity`, campos nuevos de `AuditEvent`) citan RN-002-13, RN-002-01, RN-002-16 y RN-002-15 con sus AC, pero verifican dobles de prueba y no una regla de la spec; uno dice «habilita AC-002-01..16».
- **Green:** quitar de los tests de fakes de 002 las líneas `Regla:` y `AC-`; dejar un comentario `# Soporte de tests: ...` con el Art. 3 (TDD); no cambiar aserciones ni nombres de tests que usa la matriz. Los tests heredados de 001 conservan sus citas de 001.
- **Refactor:** —

### [x] T-002-23 — Citas de smoke, módulo `server`, semillas y repositorio

- **Cubre:** corrige M2, M3 y m4
- **App / capa:** `core_banking_mcp` / arranque e `infrastructure/outbound` (tests)
- **Depende de:** T-002-21
- **Archivos:** `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`
- **Test primero:** los mismos tests existentes de esos cuatro archivos (deben seguir en verde)
- **Red:** hallazgos M2, M3 y m4: `test_server_module.py` cita `spec §7` y AC-002-01 para el atributo perezoso `server.mcp`, que la spec no declara (es comportamiento del plan); `test_stdio_smoke.py` cita `RN-002-01` con el enunciado de RN-002-02 y su docstring de módulo sigue diciendo AC-001-01; `test_seeds.py` y `test_sqlalchemy_customer_repository.py` citan RN-002-02 para probar que las fechas se guardan y se leen (corresponde RN-002-01).
- **Green:** en `test_server_module.py`, línea `Invariante:` con el Art. 4 (cableado solo en `server.py`, sin efectos al importar) y sin AC; en `test_stdio_smoke.py`, `Regla: RN-002-02` (con RN-002-01 y RN-002-09 como citas adicionales) y un docstring de módulo que mencione AC-001-01 y AC-002-01/05; en seeds y repositorio, citar RN-002-01. No cambiar aserciones.
- **Refactor:** —

### [x] T-002-24 — Citas de contrato, modelos de dominio y passthrough

- **Cubre:** corrige M4, m2, m3, m6 y la sugerencia de citar RN-002-06
- **App / capa:** `core_banking_mcp` / `domain` e `infrastructure/inbound` (tests)
- **Depende de:** T-002-21
- **Archivos:** `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`, `tests/unit/core_banking_mcp/domain/test_identity_models.py`, `tests/unit/core_banking_mcp/domain/test_identity_verification.py`, `tests/integration/core_banking_mcp/mcp/test_error_passthrough.py`
- **Test primero:** los mismos tests existentes de esos cuatro archivos (deben seguir en verde)
- **Red:** hallazgos M4, m2, m3, m6: el test de los 4 campos de entrada del contrato cita RN-002-07 (validación de valores) cuando solo comprueba nombres y descripciones (corresponde RN-002-01 con AC-002-01); dos tests de contrato se llaman `test_ac_002_14_*` pero citan AC-002-05 y AC-002-08; `test_identity_models.py` cita AC-002-05 para inmutabilidad y exclusión verificado/bloqueado, que ese AC no describe; `test_error_passthrough.py` cita RN-002-07, RN-002-16, AC-002-03 y AC-002-16 para un test de transporte de `isError`.
- **Green:** en el contrato, citar RN-002-01 y AC-002-01 para el test de los 4 campos y renombrar los dos tests cuyo nombre no coincide con el AC citado (`test_ac_002_05_...`, `test_ac_002_01_...`), sin tocar el de salida de 3 campos (`test_ac_002_14_output_schema_has_exactly_three_fields`); en `test_identity_models.py`, los tests de invariantes citan solo el Artículo (quitar el AC-002-05); en `test_error_passthrough.py`, citar `Invariante:` con el Art. 10 y el plan §2 (soporte de AC-002-03/16) sin presentar el test como cobertura de esos AC; en `test_identity_verification.py`, añadir RN-002-06 a la cita del test de bloqueo con escalamiento (AC-002-05/07). No cambiar aserciones.
- **Refactor:** —

### [x] T-002-25 — Filas «ausente» en integración y test explícito de RN-002-09

- **Cubre:** corrige m5; refuerza RN-002-09 (AC-002-01)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound` (tests)
- **Depende de:** T-002-21
- **Archivos:** `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py`, `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py::test_ac_002_08_verificar_identidad__invalid_input__returns_invalid_input` y `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_tool.py::test_ac_002_01_verificar_identidad__verification_persists_across_calls__stays_verified`
- **Red:** hallazgo m5: `test_verificar_identidad_errors.py` prueba `customer_id` y `conversation_id` solo en blanco y le faltan las filas «ausente» (argumento omitido) que sí cubren los tests unitarios; además, RN-002-09 (la verificación dura mientras viva el proceso) solo se afirma de forma indirecta. Los casos nuevos pasan sin cambio de código, porque el comportamiento ya existe: son cobertura que faltaba, no código nuevo.
- **Green:** añadir a la tabla de AC-002-08 las filas `customer_id` ausente y `conversation_id` ausente (con `ids=`), y un test en `test_verificar_identidad_tool.py` con `Regla: RN-002-09` y `AC-002-01 · Art. 7`: tras una verificación exitosa, llamadas posteriores de la misma conversación (incluida una de otro cliente, AC-002-11) no cambian el cliente verificado en el almacén. No cambiar `src/`.
- **Refactor:** —

## Correcciones de la tercera auditoría de AC (veredicto «No cumple»: 6 Bloqueantes, 1 Mayor, 6 Menores)

La ronda 2 pidió quitar `Regla:` y `AC-` a los tests de soporte e invariantes, y la ronda 3 los marca por no tenerlos. Regla única para cerrar el ciclo: (1) un test llamado `test_ac_002_NN_*` lleva su línea `AC-002-NN · Art. N`; (2) un test de invariante cita el Artículo y el AC de la spec al que da soporte; (3) un test de soporte puro (fakes, guía, setup) se renombra sin el prefijo `ac_002_` y declara `# Soporte de tests: ... · Art. N`, fuera de la trazabilidad de AC. Sin cambio de comportamiento ni de `src/`. Fuera de esta ronda: H-m2 (convención de nombres, se fija en la rule) y los hallazgos de spec (`/specify`).

### [x] T-002-26 — Invariantes y tests de soporte de dominio, almacén, módulo `server` y setup

- **Cubre:** corrige H-B1, H-B2, H-B4, H-B6 y H-M1
- **App / capa:** `core_banking_mcp` / varias (tests)
- **Depende de:** T-002-25
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_identity_models.py`, `tests/integration/core_banking_mcp/verification/test_in_memory_verification_store.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/mcp/test_error_passthrough.py`, `tests/unit/test_project_setup.py`, `tests/unit/test_mcp_inspector_guide.py`
- **Test primero:** los mismos tests existentes de esos seis archivos (deben seguir en verde)
- **Red:** hallazgos H-B1 (tres invariantes de `VerificationState` sin línea `AC-`), H-B2 (test de concurrencia solo con `Art. 7`), H-B4 (`test_server_module` y `test_error_passthrough` sin línea `AC-`), H-B6 (`test_project_setup` y `test_mcp_inspector_guide` sin `Regla:` ni `AC-`), H-M1 (`IdentityRecord` rechaza expedición anterior al nacimiento cita RN-002-07 y AC-002-03, pero verifica la invariante del registro, no la validación de la solicitud).
- **Green:** aplicar la regla única: en `test_identity_models.py`, las tres invariantes llevan `Invariante: Art. 7` y la línea del AC al que dan soporte (rango 0–3 y bloqueo → AC-002-05; inmutabilidad y exclusión verificado/bloqueado → AC-002-07 o AC-002-11, el que el texto de la spec respalde); el test de `IdentityRecord` pasa a `Invariante: Art. 7` sin `RN-002-07` ni AC-002-03 y se renombra sin el prefijo `ac_002_03`; en el almacén, añadir `AC-002-13 · Art. 7` al test de concurrencia; en `test_server_module.py`, añadir `AC-002-01 · Art. 4`; en `test_error_passthrough.py`, añadir `AC-002-03 · AC-002-16 · Art. 10`; en `test_project_setup.py` y `test_mcp_inspector_guide.py`, `# Soporte de tests: ... · Art. N` explícito, fuera de la trazabilidad de AC. Si se renombra algún test, actualizar su docstring y comprobar con grep que ningún otro archivo lo referencia. No cambiar aserciones.
- **Refactor:** —

### [x] T-002-27 — Tests de fakes, catálogo, contrato, repositorio, smoke y filas de integración

- **Cubre:** corrige H-B3, H-B5, H-m1, H-m3, H-m4, H-m5 y H-m6
- **App / capa:** `core_banking_mcp` / varias (tests)
- **Depende de:** T-002-25
- **Archivos:** `tests/unit/core_banking_mcp/application/test_fakes.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/contract/core_banking_mcp/test_verificar_identidad_contract.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`, `tests/integration/core_banking_mcp/mcp/test_verificar_identidad_errors.py`
- **Test primero:** los mismos tests existentes de esos seis archivos (deben seguir en verde), más las filas nuevas de `test_verificar_identidad_errors.py`
- **Red:** hallazgos H-B3 (cinco tests de fakes de 002 llamados `test_ac_002_*` sin `Regla:` ni `AC-`), H-B5 (el test del catálogo de 002 cita también `RN-001-10` y `AC-001-01`), H-m1 (faltan en integración `birth_date = null`, `document_issue_date = null`, `customer_id = ""` y `conversation_id = ""`; los casos nuevos pasan sin cambio de código), H-m3 (Art. 1 mal citado en catálogo y contrato donde corresponde Art. 7; `Art. 3` en el repositorio donde corresponde Art. 7), H-m4 (los tests de rango de `attempts_remaining` citan el cálculo y solo validan el rango 0–3), H-m5 (la cita de RN-002-03 en el repositorio es más estrecha que la regla), H-m6 (smoke mezcla RN en la línea del AC).
- **Green:** aplicar la regla única: los cinco tests de fakes de 002 se renombran sin el prefijo `ac_002_` y quedan como `# Soporte de tests: ... · Art. 3`; el comentario del test del catálogo cita solo IDs de 002; corregir los artículos citados (Art. 7 para mínima exposición y RN-002-14); acotar el enunciado de los tests de rango a «rango 0–3»; en el repositorio, enunciar RN-002-03 de forma acorde a lo que verifica o citar RN-002-01; en el smoke, poner las RN en líneas `Regla:` y dejar solo `AC-NNN · Art. N` en la del AC; añadir las cuatro filas a la tabla de AC-002-08 de `test_verificar_identidad_errors.py` con `ids=`. No cambiar otras aserciones ni `src/`.
- **Refactor:** —

## Correcciones de la cuarta auditoría de AC (veredicto «No cumple»: 1 Bloqueante, 2 Mayores, 4 Menores)

Los hallazgos quedan en dos archivos. Los tests de invariantes del modelo reciben exigencias opuestas (con AC se les reprocha no ejecutar su When/Then; sin AC, la falta de la línea `AC-`), así que se tratan como tests de soporte (regla 3 de la ronda anterior), como los fakes, que ya no generan hallazgo. Fuera de esta ronda: los menores de nombrado (H-m2), de datos de fixtures y de cobertura parcial de contrato, y los hallazgos de spec.

### [x] T-002-28 — Invariantes del modelo como soporte y cita de RN-002-03 en el repositorio

- **Cubre:** corrige el Bloqueante y los dos Mayores de la cuarta auditoría
- **App / capa:** `core_banking_mcp` / `domain` e `infrastructure/outbound` (tests)
- **Depende de:** T-002-27
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_identity_models.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`
- **Test primero:** los mismos tests existentes de esos dos archivos (deben seguir en verde)
- **Red:** hallazgos de la auditoría: en `test_identity_models.py`, `test_identity_record_rejects_issue_date_before_birth_date` no tiene línea `AC-`, y los tests de inmutabilidad de `with_failure`/`with_verified` (cita AC-002-11) y de «verificado y bloqueado a la vez es imposible» (cita AC-002-07) no ejecutan el When ni el Then de esos AC; en `test_sqlalchemy_customer_repository.py`, `test_ac_002_04_find_identity_unknown_customer_returns_none` cita `Regla: RN-002-01` bajo AC-002-04, cuyo `Cubre:` es RN-002-03 y RN-002-04.
- **Green:** convertir esos tres tests de invariantes en tests de soporte: `# Soporte de tests: invariante de VerificationState/IdentityRecord · Art. 7`, sin RN ni AC, y renombrarlos sin el prefijo `ac_002_` (`test_with_failure_and_with_verified_return_new_states`, `test_state_rejects_verified_and_locked_at_once`; el de `IdentityRecord` ya no lleva prefijo); en el repositorio, citar `Regla: RN-002-03` para el test de identidad inexistente y conservar `AC-002-04 · Art. 7`. No cambiar aserciones. Comprobar con grep que ningún test o documento que no sea `tasks.md` cita los nombres antiguos.
- **Refactor:** —

## Correcciones de la quinta auditoría de AC (veredicto «No cumple»: 1 Bloqueante, 2 Mayores, 2 Menores)

Primera auditoría tras fijar la línea base real del hook (informe `H-01…H-05`). Se aplican las correcciones que propone el informe; solo cambian comentarios de trazabilidad y un test, sin cambio de comportamiento ni de `src/`. Fuera de esta ronda: H-04 (convención de nombres, opcional, se fija en la rule) y H-05 (sin acción). **Riesgo conocido:** las rondas 3 y 4 recibieron exigencias opuestas sobre los tests de invariantes (con `AC-` se les reprocha no ejecutar su When/Then; sin `AC-`, no tener la línea); esta ronda sigue la corrección literal del informe y la fase 2 dirá si basta.

### [x] T-002-29 — H-01: citas de los tres tests de invariantes de `test_identity_models.py`

- **Cubre:** corrige H-01 (V4)
- **App / capa:** `core_banking_mcp` / `domain` (tests)
- **Depende de:** T-002-28
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_identity_models.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-01: `test_with_failure_and_with_verified_return_new_states`, `test_state_rejects_verified_and_locked_at_once` y `test_identity_record_rejects_issue_date_before_birth_date` solo tienen `# Soporte de tests: ...`, sin línea `Regla:`/`Invariante:` ni línea `AC-NNN-XX`.
- **Green:** en los dos tests de `VerificationState`, sustituir el comentario por `# Invariante: Art. 7 — <enunciado de lo que verifica>` y `# AC-002-05 · Art. 7`, igual que ya hace el test de las líneas ~55-57 del mismo archivo; en el test de `IdentityRecord`, `# Regla: RN-002-07 — <enunciado copiado de spec §4>` y `# AC-002-03 · Art. 7`. Antes de citar, comprobar en `spec.md` que la RN aparece en la línea `Cubre:` del AC citado (V6) y que el enunciado es fiel (V7); si no coincide, citar la RN que sí figure y reportarlo. No renombrar tests ni cambiar aserciones ni `src/`.
- **Refactor:** —

### [x] T-002-30 — H-02: cita del test de bordes del 3.er fallo en `test_identity_verification.py`

- **Cubre:** corrige H-02 (V6, V8 parcial)
- **App / capa:** `core_banking_mcp` / `domain` (tests)
- **Depende de:** T-002-28
- **Archivos:** `tests/unit/core_banking_mcp/domain/test_identity_verification.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-02 (líneas ~79-103): el test de 0/1/2 fallos previos con fecha incorrecta cita `Regla: RN-002-04`, `Regla: RN-002-06` y `AC-002-05 · AC-002-07`. AC-002-07 tiene `Cubre: RN-002-05, RN-002-06`, no RN-002-04, y el test no ejecuta su Given/When (conversación bloqueada con fechas correctas), que cubre el test de la línea ~120.
- **Green:** dejar la cita como `# Regla: RN-002-04 — <enunciado fiel de spec §4>` y `# AC-002-05 · Art. 10 · borde exacto: 3.er fallo`; quitar `RN-002-06` y `AC-002-07` de ese test. Comprobar en `spec.md` que RN-002-04 figura en el `Cubre:` de AC-002-05; no tocar la cita del test de bloqueo (~120). No cambiar aserciones ni `src/`.
- **Refactor:** —

### [x] T-002-31 — H-03: el test de reemplazo del almacén verifica la independencia entre conversaciones

- **Cubre:** corrige H-03 (V8)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound` (tests)
- **Depende de:** T-002-28
- **Archivos:** `tests/integration/core_banking_mcp/verification/test_in_memory_verification_store.py`
- **Test primero:** los mismos tests existentes del archivo (deben seguir en verde)
- **Red:** hallazgo H-03 (líneas ~24-33): el test cita `Regla: RN-002-12 — cada conversación tiene su propio contador de intentos` y `AC-002-13`, pero solo comprueba que un segundo `save` de `conv-a` reemplaza al primero; no hay segunda conversación ni se compara ningún contador. El caso pasa sin cambio de código: es cobertura que faltaba.
- **Green:** ampliar ese test (conservando la aserción de reemplazo): guardar en `conv-a` un estado con `failed_attempts=1` y comprobar que `store.get("conv-b")` sigue siendo `VerificationState()`. Verificar que el enunciado de la `Regla:` sigue siendo fiel a RN-002-12 en `spec.md` y que la RN figura en el `Cubre:` de AC-002-13. Usar los builders o constructores que ya usa el archivo. No cambiar `src/`.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-002-01 | T-002-04, T-002-06, T-002-10, T-002-13, T-002-16 | `test_ac_002_01_correct_dates_verify_and_store_customer`, `test_ac_002_01_find_identity_returns_registered_dates`, `test_ac_002_01_verificar_identidad__correct_dates__verifies_customer`, `test_ac_002_01_catalog_exposes_buscar_cliente_and_verificar_identidad`, `test_ac_002_01_verificar_identidad__stdio_server__verifies_seeded_customer` |
| AC-002-02 | T-002-04, T-002-06, T-002-13 | `test_ac_002_02_any_wrong_date_fails_without_revealing_which` |
| AC-002-03 | T-002-03, T-002-06, T-002-08, T-002-14 | `test_ac_002_03_swapped_dates_are_invalid` |
| AC-002-04 | T-002-04, T-002-06, T-002-10, T-002-13 | `test_ac_002_04_find_identity_unknown_customer_returns_none` |
| AC-002-05 | T-002-01, T-002-04, T-002-13, T-002-16 | `test_ac_002_05_state_attempts_remaining_and_lock_boundaries` |
| AC-002-06 | T-002-04, T-002-06, T-002-13 | `test_ac_002_06_correct_dates_before_lock_verify` |
| AC-002-07 | T-002-04, T-002-06, T-002-13 | `test_ac_002_07_locked_conversation_does_not_verify` |
| AC-002-08 | T-002-03, T-002-06, T-002-14 | `test_ac_002_08_invalid_request_is_rejected`, `test_ac_002_08_verificar_identidad__invalid_input__returns_invalid_input` |
| AC-002-09 | T-002-02, T-002-03, T-002-06, T-002-14 | `test_ac_002_09_today_in_bogota_boundaries`, `test_ac_002_09_request_date_limits` |
| AC-002-10 | T-002-06, T-002-14 | `test_ac_002_10_invalid_input_does_not_consume_attempts` |
| AC-002-11 | T-002-04, T-002-06, T-002-13 | `test_ac_002_11_other_customer_does_not_change_verified_customer` |
| AC-002-12 | T-002-04, T-002-06, T-002-13 | `test_ac_002_12_reverification_of_same_customer_is_idempotent` |
| AC-002-13 | T-002-01, T-002-05, T-002-06, T-002-11, T-002-13 | `test_ac_002_13_empty_state_is_not_verified`, `test_ac_002_13_verification_is_per_conversation`, `test_ac_002_13_store_keeps_conversations_independent` |
| AC-002-14 | T-002-06, T-002-08, T-002-10, T-002-13 | `test_ac_002_14_output_schema_has_exactly_three_fields`, `test_ac_002_14_result_has_only_three_fields`, `test_ac_002_14_find_matching_entities_do_not_expose_dates` |
| AC-002-15 | T-002-07, T-002-12, T-002-14 | `test_ac_002_15_each_invocation_records_exactly_one_event`, `test_ac_002_15_verificar_identidad_event_is_serialized_without_dates` |
| AC-002-16 | T-002-06, T-002-08, T-002-14 | `test_ac_002_16_unexpected_failure_raises_core_unavailable` |

**Casos de escalamiento (spec §8):** `escalation_required = true` → AC-002-05 y AC-002-07 (T-002-04, T-002-06, T-002-13); `INTERNAL` con `retryable = false` → AC-002-16 (T-002-06, T-002-14). **Art. 7:** una conversación sin verificación exitosa o desconocida es no verificada → AC-002-13. **Tareas de soporte sin AC propio:** T-002-09, T-002-15 y T-002-17.

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [ ] Spec actualizada al comportamiento implementado.
- [ ] Sin secretos ni datos reales.
