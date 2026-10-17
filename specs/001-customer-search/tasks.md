# Tareas: Buscar un cliente por documento, nombre o últimos dígitos de tarjeta

| Campo | Valor |
|---|---|
| Feature | `001-customer-search` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.2 |
| Fecha | 2026-10-16 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas de `src` relativas a la raíz del repositorio. Todos los `__init__.py` los crea T-001-01; ninguna otra tarea los modifica. Solo T-001-07 escribe en `tests/fakes/`.

---

## Tareas

### [x] T-001-01 — Esqueleto del proyecto y paquetes

- **Cubre:** habilita todas las tareas (plan §2, fila raíz)
- **App / capa:** `core_banking_mcp` / raíz (configuración)
- **Depende de:** —
- **Archivos:** `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.env.example`, `src/dispute_agent/__init__.py`, `src/core_banking_mcp/__init__.py`, `src/core_banking_mcp/domain/__init__.py`, `src/core_banking_mcp/domain/models/__init__.py`, `src/core_banking_mcp/application/__init__.py`, `src/core_banking_mcp/application/ports/__init__.py`, `src/core_banking_mcp/application/use_cases/__init__.py`, `src/core_banking_mcp/infrastructure/__init__.py`, `src/core_banking_mcp/infrastructure/inbound/__init__.py`, `src/core_banking_mcp/infrastructure/inbound/mcp/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/models/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/audit/__init__.py`, `src/core_banking_mcp/infrastructure/outbound/clock/__init__.py`, `tests/__init__.py`, `tests/fakes/__init__.py`, `tests/unit/test_project_setup.py`
- **Test primero:** `tests/unit/test_project_setup.py::test_core_banking_mcp_package_is_importable`
- **Red:** falla con `ModuleNotFoundError` porque no existen ni el paquete ni el proyecto uv.
- **Green:** `pyproject.toml` (uv, build con hatchling y paquetes `src/core_banking_mcp` y `src/dispute_agent`; dependencias `mcp>=1.13,<2`, `sqlalchemy>=2.0,<3`, `pydantic>=2.7,<3`, `pydantic-settings>=2.7,<3`; dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`; pytest con `asyncio_mode="auto"`, `pythonpath=["."]`, marcador `llm` excluido por defecto (`-m "not llm"`); ruff; mypy `strict`; coverage con `source=["src"]`, `branch=true`, `fail_under=80`), `uv sync` para generar `uv.lock`, los `__init__.py` vacíos, `.pre-commit-config.yaml` (ruff, ruff-format, mypy, pytest rápido) y `.env.example` con `CORE_DATABASE_URL`.
- **Refactor:** —

### [x] T-001-02 — Normalización de nombre y documento

- **Cubre:** AC-001-02, AC-001-05
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-001-01
- **Archivos:** `src/core_banking_mcp/domain/normalization.py`, `tests/unit/core_banking_mcp/domain/test_normalization.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_normalization.py::test_ac_001_05_name_normalization_ignores_accents_case_and_spaces`
- **Red:** los tests parametrizados fallan porque `normalize_name` y `normalize_document` no existen. Filas: las 7 del AC-001-05 comparadas contra `normalize_name("José Álvarez")` / `normalize_name("José Álvarez Pérez")`, las 4 del AC-001-02 (`test_ac_001_02_document_normalization_trims_and_ignores_case`) y un caso `Muñoz`/`Munoz` (plan §7).
- **Green:** `normalize_name` (NFD + eliminación de marcas combinantes + `casefold` + `strip` + colapso de espacios) y `normalize_document` (`strip` + `casefold`), solo con stdlib.
- **Refactor:** —
- **Nota:** el subagente no ejecutó el Red antes del Green; el orquestador lo verificó a posteriori: con una normalización identidad fallan 6 de 12 tests.

### [x] T-001-03 — Enmascarado de documento y tarjeta

- **Cubre:** AC-001-11, AC-001-12
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-001-01
- **Archivos:** `src/core_banking_mcp/domain/masking.py`, `tests/unit/core_banking_mcp/domain/test_masking.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_masking.py::test_ac_001_11_document_and_card_are_masked`
- **Red:** falla porque `mask_document` y `mask_card` no existen. Incluye `test_ac_001_12_short_document_is_fully_masked` con bordes de 4 caracteres (`AB12` → `****`) y 5 (`AB123` → `****23`), y `mask_card("4321") == "**** 4321"`.
- **Green:** `mask_document` (`****` + 2 últimos caracteres; solo `****` si la longitud es ≤ 4) y `mask_card` (`**** ` + `last4`).
- **Refactor:** —

### [x] T-001-04 — Entidades `Customer`, `Card`, `CardStatus` y errores de dominio

- **Cubre:** habilita AC-001-01, AC-001-03 (plan §4 Dominio)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-001-01
- **Archivos:** `src/core_banking_mcp/domain/models/customer.py`, `src/core_banking_mcp/domain/errors.py`, `tests/unit/core_banking_mcp/domain/test_customer.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_customer.py::test_card_rejects_last4_that_is_not_four_digits`
- **Red:** falla porque las entidades no existen. También cubre: `Customer` rechaza `customer_id`, `full_name` o `document` vacíos, e `InvalidInputError` expone `field` y `reason`.
- **Green:** dataclasses inmutables con validación en `__post_init__`, `CardStatus` (`ACTIVE`, `BLOCKED`, `CANCELLED`), `DomainError` e `InvalidInputError(field, reason)`.
- **Refactor:** —

### [x] T-001-05 — Value object `SearchCriteria`

- **Cubre:** AC-001-09 (filas de criterios), AC-001-08 (combinación de criterios)
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-001-02, T-001-04
- **Archivos:** `src/core_banking_mcp/domain/models/search.py`, `tests/unit/core_banking_mcp/domain/test_search_criteria.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_search_criteria.py::test_ac_001_09_invalid_criteria_are_rejected`
- **Red:** el parametrizado (8 filas del AC-001-09 sin `conversation_id`: sin criterios, `document=""`, `document` de 33 caracteres, `full_name="   "`, `full_name` de 101 caracteres, `card_last4` `"123"`, `"12345"`, `"12a4"`) falla porque `SearchCriteria` no existe. Se añade un caso válido con los tres criterios que conserva los valores normalizados, y bordes válidos de 32 y 100 caracteres.
- **Green:** `SearchCriteria.create(document, full_name, card_last4)` valida RN-001-01/05, lanza `InvalidInputError` y guarda los valores normalizados con `normalize_document` / `normalize_name`.
- **Refactor:** —

### [x] T-001-06 — `CustomerSearchResult` con tope de 5

- **Cubre:** AC-001-07, AC-001-06
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** T-001-05
- **Archivos:** `src/core_banking_mcp/domain/models/search.py`, `tests/unit/core_banking_mcp/domain/test_customer_search_result.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_customer_search_result.py::test_ac_001_07_result_is_capped_at_five`
- **Red:** el parametrizado 0/4/5/6 (borde exacto 5) falla porque `CustomerSearchResult` y `MAX_RESULTS` no existen. Con 0 coincidencias también verifica `test_ac_001_06_no_matches_is_empty_result`.
- **Green:** `MAX_RESULTS = 5` y `CustomerSearchResult.from_matches(matches)`: con más de 5, `customers=()` y `refinement_required=True`; si no, todas con `False`. Invariantes en `__post_init__`.
- **Refactor:** —

### [x] T-001-07 — Puertos de aplicación y fakes de test

- **Cubre:** habilita AC-001-01…14 en unit e integración (plan §3 y §6)
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-001-05
- **Archivos:** `src/core_banking_mcp/application/ports/customer_repository.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `src/core_banking_mcp/application/ports/clock.py`, `src/core_banking_mcp/application/errors.py`, `tests/fakes/customer_builder.py`, `tests/fakes/fake_customer_repository.py`, `tests/fakes/failing_customer_repository.py`, `tests/fakes/fake_audit_log.py`, `tests/fakes/fixed_clock.py`, `tests/unit/core_banking_mcp/application/test_fakes.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_fakes.py::test_fake_customer_repository_filters_with_and_and_orders_by_id`
- **Red:** falla porque no existen ni los puertos ni los fakes. También cubre: `FixedClock.now()` devuelve el instante dado, `FakeAuditLog` acumula eventos, `FailingCustomerRepository` lanza una excepción no de dominio y `CustomerBuilder` genera clientes deterministas.
- **Green:** `Protocol`s `CustomerRepository.find_matching(criteria, limit)`, `AuditLogPort.record(event)` y `Clock.now()`; dataclass `AuditEvent` (campos del plan §2); `CoreUnavailableError`; los cinco fakes (el repositorio falso filtra con las funciones de normalización, AND, orden por `customer_id` y `limit`).
- **Refactor:** —

### [x] T-001-08 — `SearchCustomers`: camino de búsqueda

- **Cubre:** AC-001-01, AC-001-04, AC-001-06, AC-001-07, AC-001-10
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-001-06, T-001-07
- **Archivos:** `src/core_banking_mcp/application/use_cases/search_customers.py`, `tests/unit/core_banking_mcp/application/test_search_customers.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_search_customers.py::test_ac_001_01_single_customer_by_document`
- **Red:** falla porque `SearchCustomers` no existe. Además: `test_ac_001_04_homonyms_keep_repository_order`, `test_ac_001_06_no_matches_returns_empty`, `test_ac_001_07_more_than_five_requires_refinement` (pide `limit=6` al repositorio) y `test_ac_001_10_search_does_not_require_nor_confirm_identity` (el constructor solo recibe repositorio, auditoría y reloj; la única escritura es la auditoría).
- **Green:** `SearchCustomersCommand(conversation_id, document, full_name, card_last4)` y `SearchCustomers.execute` → `SearchCriteria.create` → `find_matching(criteria, MAX_RESULTS + 1)` → `CustomerSearchResult.from_matches`.
- **Refactor:** —

### [x] T-001-09 — `SearchCustomers`: validación, auditoría y falla inesperada

- **Cubre:** AC-001-09, AC-001-13, AC-001-14
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-001-08, T-001-03
- **Archivos:** `src/core_banking_mcp/application/use_cases/search_customers.py`, `tests/unit/core_banking_mcp/application/test_search_customers.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_search_customers.py::test_ac_001_13_every_invocation_is_audited`
- **Red:** el parametrizado de 6 casos (un cliente, varios, ninguno, más de 5, inválido, falla) falla porque no se emite `AuditEvent`. Comprueba exactamente 1 evento con `conversation_id`, el instante de `FixedClock`, `tool="buscar_cliente"`, el documento enmascarado (nunca completo), `outcome`/`count`/`customer_ids` o `error_code`, `rule` y `reason`. Además: `test_ac_001_09_missing_conversation_id_is_invalid_input` (ausente y vacío) y `test_ac_001_14_repository_failure_raises_core_unavailable` con `FailingCustomerRepository` (sin el texto original en el error).
- **Green:** validar `conversation_id` (`InvalidInputError`), envolver la consulta capturando cualquier excepción del repositorio → `CoreUnavailableError`, y registrar el `AuditEvent` en todas las salidas (regla RN-001-01 / 07 / 05 / 13) antes de devolver o relanzar. La entrada se audita con `mask_document`.
- **Refactor:** extraer la construcción del `AuditEvent` a una función privada.

### [x] T-001-10 — Esquemas MCP de `buscar_cliente` y sobre de error

- **Cubre:** AC-001-01, AC-001-09, AC-001-10 (nivel contrato)
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-001-01
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `src/core_banking_mcp/infrastructure/inbound/mcp/errors.py`, `tests/contract/core_banking_mcp/test_buscar_cliente_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_buscar_cliente_contract.py::test_ac_001_01_customer_match_schema_has_exactly_spec_fields`
- **Red:** falla porque los esquemas no existen. Además: `test_ac_001_10_output_schema_has_no_identity_fields` (la salida tiene solo `customers` y `refinement_required`), `test_ac_001_09_error_envelope_matches_spec` (`ToolErrorOut` con `code`/`message`/`retryable`, `ErrorCode` cerrado = {`INVALID_INPUT`, `INTERNAL`}) y `tool_error(...)` devuelve un `CallToolResult` con `isError=True`, `structuredContent` igual al sobre y el mismo JSON en `TextContent` (riesgo del plan §7).
- **Green:** modelos Pydantic v2 con `Field(description=...)`, `CustomerMatchOut` con `extra="forbid"`, enum `ErrorCode` y helper `tool_error`.
- **Refactor:** —

### [x] T-001-11 — Persistencia: tablas, base y repositorio (documento y tarjeta)

- **Cubre:** AC-001-02, AC-001-03
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-001-05, T-001-07
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/database.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_customer_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py::test_ac_001_02_document_match_is_trimmed_and_case_insensitive`
- **Red:** falla porque no existen las tablas ni el repositorio (SQLite `:memory:`). Además: `test_ac_001_03_card_last4_matches_any_card_status` (activa, bloqueada, cancelada) y un test que comprueba que `add` rellena `full_name_normalized` / `document_normalized` con las funciones del dominio (riesgo del plan §7).
- **Green:** `Base`, `CustomerRow`, `CardRow` (plan §4), `create_engine_from_url` / `session_factory` / `create_schema`, y `SqlAlchemyCustomerRepository.add` y `find_matching` por documento y `EXISTS` sobre `cards.last4`, con mapeo a entidades.
- **Refactor:** —

### [x] T-001-12 — Repositorio: nombre, AND, orden y límite

- **Cubre:** AC-001-04, AC-001-05, AC-001-08
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-001-11
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_customer_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_customer_repository.py::test_ac_001_05_full_name_must_equal_registered_name`
- **Red:** el parametrizado de 7 filas falla porque no se filtra por nombre. Además: `test_ac_001_08_criteria_are_combined_with_and`, `test_ac_001_04_results_are_ordered_by_customer_id` y un test de que `limit` se aplica.
- **Green:** filtro por `full_name_normalized`, combinación AND de todos los criterios presentes, `ORDER BY customer_id` y `LIMIT`.
- **Refactor:** construir la consulta a partir de una lista de condiciones.

### [x] T-001-13 — Auditoría JSON a `stderr`

- **Cubre:** AC-001-13 (integración)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-001-07
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/integration/core_banking_mcp/audit/test_json_audit_log.py::test_ac_001_13_audit_event_is_written_as_json_line`
- **Red:** falla porque `JsonAuditLog` no existe. Comprueba una línea JSON válida en el stream inyectado con todos los campos de `AuditEvent` (timestamp ISO 8601) y que no se escribe nada en `stdout` (`capsys`).
- **Green:** `JsonAuditLog(stream=sys.stderr).record(event)` → `json.dumps` + `\n` + `flush`.
- **Refactor:** —

### [x] T-001-14 — Reloj del sistema

- **Cubre:** habilita AC-001-13 en tiempo de ejecución (plan §3, `Clock`)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-001-07
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/clock/system_clock.py`, `tests/integration/core_banking_mcp/clock/test_system_clock.py`
- **Test primero:** `tests/integration/core_banking_mcp/clock/test_system_clock.py::test_system_clock_returns_timezone_aware_utc`
- **Red:** falla porque `SystemClock` no existe.
- **Green:** `SystemClock.now()` → `datetime.now(UTC)`.
- **Refactor:** —

### [x] T-001-15 — Herramienta `buscar_cliente`: respuestas exitosas

- **Cubre:** AC-001-01, AC-001-03, AC-001-04, AC-001-06, AC-001-07, AC-001-10, AC-001-11
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-001-09, T-001-10, T-001-12
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/tools.py`, `tests/integration/core_banking_mcp/mcp/test_buscar_cliente_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_buscar_cliente_tool.py::test_ac_001_01_buscar_cliente__single_document__returns_one_customer`
- **Red:** falla porque `register_tools` no existe. La fixture del test arma `FastMCP` con `SearchCustomers` real, `SqlAlchemyCustomerRepository` sobre `:memory:`, `FakeAuditLog` y `FixedClock`, y abre una sesión MCP en memoria. Además: `test_ac_001_03_...card_last4_any_status...`, `test_ac_001_04_...homonyms...`, `test_ac_001_06_...no_matches__returns_empty_success`, `test_ac_001_07_...six_matches__requires_refinement`, `test_ac_001_10_...unverified_conversation__returns_customer` y `test_ac_001_11_...response_never_contains_full_document_or_pan` (nombrado `test_buscar_cliente__<condición>__<resultado>`, con comentarios de trazabilidad según `mcp-testing.md`).
- **Green:** `register_tools(mcp, search_customers)` con la herramienta `buscar_cliente` (parámetros `str | None` con `description`, docstring en español del plan §2) que llama al caso de uso y mapea a `BuscarClienteOutput` con enmascarado.
- **Refactor:** —

### [x] T-001-16 — Herramienta `buscar_cliente`: errores

- **Cubre:** AC-001-09, AC-001-14
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-001-15
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/tools.py`, `tests/integration/core_banking_mcp/mcp/test_buscar_cliente_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_buscar_cliente_tool.py::test_ac_001_09_buscar_cliente__invalid_input__returns_invalid_input_error`
- **Red:** el parametrizado de las 9 filas del AC-001-09 falla porque la excepción no se mapea a `isError=true` con `INVALID_INPUT` y `retryable=false`. Además: `test_ac_001_14_buscar_cliente__repository_failure__returns_internal_not_retryable` (con `FailingCustomerRepository`, el mensaje no contiene el texto de la excepción) y un *catch-all* defensivo → `INTERNAL`.
- **Green:** `try/except` en la herramienta: `InvalidInputError` → `tool_error(INVALID_INPUT, ...)`, `CoreUnavailableError` y `Exception` → `tool_error(INTERNAL, ..., retryable=False)`, con mensajes fijos en español.
- **Refactor:** —

### [x] T-001-17 — Semillas ficticias

- **Cubre:** habilita AC-001-01 en el smoke test por stdio (plan §4 Semillas)
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-001-12
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/seeds/customers.py`, `tests/integration/core_banking_mcp/persistence/test_seeds.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_seeds.py::test_seed_database_is_idempotent_and_reproducible`
- **Red:** falla porque `seed_database` no existe. Comprueba los 7 clientes del plan §4, que una segunda ejecución no duplica y que la inserción pasa por el repositorio (columnas normalizadas).
- **Green:** `SEED_CUSTOMERS` fijo y `seed_database(repository)` que inserta solo si la tabla está vacía.
- **Refactor:** —

### [x] T-001-18 — Configuración, composición del servidor y snapshot del catálogo

- **Cubre:** AC-001-01, AC-001-09, AC-001-10 (catálogo, `mcp-testing.md` §7)
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-001-13, T-001-14, T-001-16, T-001-17
- **Archivos:** `src/core_banking_mcp/config.py`, `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_001_01_catalog_exposes_only_buscar_cliente_with_spec_schema`
- **Red:** falla porque `build_server` no existe. Comprueba que `list_tools` devuelve solo `buscar_cliente`, con los parámetros de entrada de spec §7 (descriptions que marcan `conversation_id` como obligatorio y al menos un criterio) y el esquema de salida de `BuscarClienteOutput`.
- **Green:** `CoreSettings` (pydantic-settings: `database_url`, `seed_on_start`) y `build_server(settings)`, que compone el engine, el esquema, las semillas opcionales, el repositorio, `JsonAuditLog`, `SystemClock`, `SearchCustomers` y `FastMCP` + `register_tools`; `main()` con `mcp.run("stdio")` y sin escritura a `stdout`.
- **Refactor:** —

### [x] T-001-19 — Smoke test por stdio real

- **Cubre:** AC-001-01 (integración por stdio)
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-001-18
- **Archivos:** `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/integration/core_banking_mcp/test_stdio_smoke.py::test_ac_001_01_buscar_cliente__stdio_server__finds_seeded_customer`
- **Red:** se escribe el test que lanza `python -m core_banking_mcp.server` como subproceso con `CORE_DATABASE_URL` en `tmp_path`, busca `D-1001` y espera `C-0001` con `masked_document="****01"`; si falla, la causa es la composición o el transporte (stdout contaminado).
- **Green:** solo ajustes mínimos en el test o en `server.py` si hiciera falta (si toca `server.py`, se informa).
- **Refactor:** —

### [x] T-001-20 — Verificación final

- **Cubre:** Definition of Done (§5.5), todos los AC
- **App / capa:** — / —
- **Depende de:** T-001-01 … T-001-19
- **Archivos:** — (solo ejecución)
- **Test primero:** `uv run pytest --cov`
- **Red:** —
- **Green:** pasan `uv run pytest --cov` (global ≥ 80 %), `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.
- **Refactor:** —
- **Resultado:** 105 tests en verde, cobertura global 97,75 %, `domain` + `application` 100 %, `ruff check`, `ruff format --check` y `mypy --strict` sin errores. Para que ruff pase sobre todo el repo hubo que formatear `.claude/hooks/check_mcp_boundaries.py` (línea 37 > 100 caracteres), con autorización del usuario; el comportamiento del hook no cambió.

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-001-01 | T-001-08, T-001-10, T-001-15, T-001-18, T-001-19 | `test_ac_001_01_single_customer_by_document`, `test_ac_001_01_customer_match_schema_has_exactly_spec_fields`, `test_ac_001_01_buscar_cliente__single_document__returns_one_customer`, `test_ac_001_01_catalog_exposes_only_buscar_cliente_with_spec_schema`, `test_ac_001_01_buscar_cliente__stdio_server__finds_seeded_customer` |
| AC-001-02 | T-001-02, T-001-11 | `test_ac_001_02_document_normalization_trims_and_ignores_case`, `test_ac_001_02_document_match_is_trimmed_and_case_insensitive` |
| AC-001-03 | T-001-11, T-001-15 | `test_ac_001_03_card_last4_matches_any_card_status`, `test_ac_001_03_buscar_cliente__card_last4_any_status__returns_customer` |
| AC-001-04 | T-001-08, T-001-12, T-001-15 | `test_ac_001_04_homonyms_keep_repository_order`, `test_ac_001_04_results_are_ordered_by_customer_id`, `test_ac_001_04_buscar_cliente__homonyms__returns_two_distinguishable` |
| AC-001-05 | T-001-02, T-001-12 | `test_ac_001_05_name_normalization_ignores_accents_case_and_spaces`, `test_ac_001_05_full_name_must_equal_registered_name` |
| AC-001-06 | T-001-06, T-001-08, T-001-15 | `test_ac_001_06_no_matches_is_empty_result`, `test_ac_001_06_no_matches_returns_empty`, `test_ac_001_06_buscar_cliente__no_matches__returns_empty_success` |
| AC-001-07 | T-001-06, T-001-08, T-001-15 | `test_ac_001_07_result_is_capped_at_five`, `test_ac_001_07_more_than_five_requires_refinement`, `test_ac_001_07_buscar_cliente__six_matches__requires_refinement` |
| AC-001-08 | T-001-05, T-001-12 | `test_ac_001_09_invalid_criteria_are_rejected` (caso válido combinado), `test_ac_001_08_criteria_are_combined_with_and` |
| AC-001-09 | T-001-05, T-001-09, T-001-10, T-001-16, T-001-18 | `test_ac_001_09_invalid_criteria_are_rejected`, `test_ac_001_09_missing_conversation_id_is_invalid_input`, `test_ac_001_09_error_envelope_matches_spec`, `test_ac_001_09_buscar_cliente__invalid_input__returns_invalid_input_error` |
| AC-001-10 | T-001-08, T-001-10, T-001-15, T-001-18 | `test_ac_001_10_search_does_not_require_nor_confirm_identity`, `test_ac_001_10_output_schema_has_no_identity_fields`, `test_ac_001_10_buscar_cliente__unverified_conversation__returns_customer` |
| AC-001-11 | T-001-03, T-001-15 | `test_ac_001_11_document_and_card_are_masked`, `test_ac_001_11_buscar_cliente__response_never_contains_full_document_or_pan` |
| AC-001-12 | T-001-03 | `test_ac_001_12_short_document_is_fully_masked` |
| AC-001-13 | T-001-09, T-001-13 | `test_ac_001_13_every_invocation_is_audited`, `test_ac_001_13_audit_event_is_written_as_json_line` |
| AC-001-14 | T-001-09, T-001-16 | `test_ac_001_14_repository_failure_raises_core_unavailable`, `test_ac_001_14_buscar_cliente__repository_failure__returns_internal_not_retryable` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
