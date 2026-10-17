# Plan: Buscar un cliente por documento, nombre o últimos dígitos de tarjeta

| Campo | Valor |
|---|---|
| Feature | `001-customer-search` |
| Versión | 0.1.2 |
| Estado | Aprobado |
| Fecha | 2026-10-16 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 (0.1.1: rutas `infrastructure/inbound` / `outbound` por la enmienda 1.0.1; 0.1.2: riesgo de API privada de FastMCP) |

---

## 1. Resumen técnico

Primera feature del repositorio: además de la herramienta, monta el esqueleto del proyecto (`pyproject.toml` con uv, ruff, mypy estricto, pytest y pre-commit) y la aplicación `core_banking_mcp` con sus cuatro capas.

- **Dominio puro** (stdlib): `SearchCriteria` valida y normaliza la entrada (RN-001-01/02/03/04/05), las funciones `normalize_name` / `normalize_document` comparan, y `mask_document` / `mask_card` enmascaran (RN-001-09).
- **Caso de uso** `SearchCustomers`: valida, consulta `CustomerRepository` con un tope de 6 (`MAX_RESULTS + 1`) para detectar si hay más de 5, aplica RN-001-07 y audita **todas** las salidas, incluidas la entrada inválida y la falla inesperada (RN-001-12). Cualquier excepción del repositorio se convierte en `CoreUnavailableError` (RN-001-13).
- **Validación en el dominio** (decisión del usuario): la firma FastMCP declara todos los campos como `str | None` y documenta en `description` cuáles son obligatorios. Así toda violación, incluso un `conversation_id` ausente, sale como `INVALID_INPUT` y queda auditada.
- **Errores** (decisión del usuario): `CallToolResult` con `isError=true`, el sobre `{code, message, retryable}` como `structuredContent` y el mismo JSON en `TextContent`. Este es el patrón para las herramientas futuras.
- **Matching en SQL** (decisión del usuario): columnas `full_name_normalized` y `document_normalized` (calculadas con las mismas funciones del dominio) y `cards.last4`, consultadas por igualdad indexada, con AND entre criterios, `ORDER BY customer_id` y `LIMIT 6`.
- La auditoría se escribe en JSON en `stderr` (`mcp-tools.md` §12) y el reloj se inyecta (§5.3.6).

Decisiones triviales tomadas: `CustomerRepository` devuelve entidades de dominio ya mapeadas; la base por defecto es un archivo SQLite configurado por `CORE_DATABASE_URL`, y el servidor siembra los datos si la base está vacía; `AC-001-10` se verifica por la ausencia de cualquier campo o dependencia de identidad (todavía no existe un almacén de sesiones verificadas).

## 2. Componentes por capa

Todos son nuevos (no existe código previo). Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| — | raíz | `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.env.example` | Nuevo | Proyecto uv con paquetes `src/core_banking_mcp` (y `src/dispute_agent` vacío), dependencias del stack necesarias, configuración de ruff, mypy `--strict`, pytest (`asyncio_mode=auto`, marcador `llm` excluido por defecto) y coverage (`fail_under=80`). `.env.example` con `CORE_DATABASE_URL`. |
| `core_banking_mcp` | `domain` | `domain/models/customer.py` — `Customer`, `Card`, `CardStatus` | Nuevo | Entidades inmutables (`dataclass(frozen=True)`). |
| `core_banking_mcp` | `domain` | `domain/models/search.py` — `SearchCriteria`, `CustomerSearchResult`, `MAX_RESULTS = 5` | Nuevo | `SearchCriteria.create(document, full_name, card_last4)` valida RN-001-01/05 y guarda los valores normalizados; `CustomerSearchResult.from_matches(matches)` aplica RN-001-07. |
| `core_banking_mcp` | `domain` | `domain/normalization.py` — `normalize_name`, `normalize_document` | Nuevo | `unicodedata` NFD + eliminación de marcas combinantes + `casefold` + colapso de espacios; documento: `strip` + `casefold`. |
| `core_banking_mcp` | `domain` | `domain/masking.py` — `mask_document`, `mask_card` | Nuevo | RN-001-09. |
| `core_banking_mcp` | `domain` | `domain/errors.py` — `DomainError`, `InvalidInputError(field, reason)` | Nuevo | Errores de dominio sin dependencias. |
| `core_banking_mcp` | `application` | `application/ports/customer_repository.py` — `CustomerRepository` | Nuevo | `find_matching(criteria: SearchCriteria, limit: int) -> list[Customer]`. |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditLogPort`, `AuditEvent` | Nuevo | `record(event)`. `AuditEvent`: `conversation_id`, `timestamp`, `tool`, `input` (documento enmascarado), `outcome`, `count`, `customer_ids`, `error_code`, `rule`, `reason`. |
| `core_banking_mcp` | `application` | `application/ports/clock.py` — `Clock` | Nuevo | `now() -> datetime` (UTC). |
| `core_banking_mcp` | `application` | `application/errors.py` — `CoreUnavailableError` | Nuevo | Señala la falla no recuperable (RN-001-13). |
| `core_banking_mcp` | `application` | `application/use_cases/search_customers.py` — `SearchCustomers`, `SearchCustomersCommand` | Nuevo | Orquesta validación → repositorio → resultado → auditoría (§1). Regla registrada: RN-001-01 (encontrado), RN-001-07 (refinamiento), RN-001-05 (inválido), RN-001-13 (falla). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Nuevo | Pydantic v2: `CustomerMatchOut` (`extra="forbid"`), `BuscarClienteOutput`, `ToolErrorOut`, `ErrorCode` (catálogo cerrado: `INVALID_INPUT`, `INTERNAL`), todos con `Field(description=...)`. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/errors.py` — `tool_error(...)` | Nuevo | Construye el `CallToolResult` de error (§1). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/tools.py` — `register_tools(mcp, search_customers)` | Nuevo | Herramienta delgada `buscar_cliente` con un docstring en español (propósito, cuándo usarla y cuándo no, no autentica, idempotente). Mapea `InvalidInputError` → `INVALID_INPUT`, `CoreUnavailableError` → `INTERNAL`, y tiene un *catch-all* defensivo → `INTERNAL`. El mensaje nunca incluye el texto de la excepción. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/` — `Base`, `CustomerRow`, `CardRow` | Nuevo | Modelos SQLAlchemy 2.x (`Mapped`). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/database.py` | Nuevo | `create_engine_from_url`, `session_factory`, `create_schema`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_customer_repository.py` | Nuevo | `find_matching` con igualdad sobre columnas normalizadas, `EXISTS` sobre `cards.last4`, `ORDER BY customer_id`, `LIMIT`; `add(customer)` calcula las columnas normalizadas con las funciones del dominio; mapea filas → entidades. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/customers.py` — `SEED_CUSTOMERS`, `seed_database` | Nuevo | Datos ficticios fijos, inserción idempotente vía repositorio. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` — `JsonAuditLog` | Nuevo | Una línea JSON por evento en un stream inyectable (por defecto `sys.stderr`). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/clock/system_clock.py` — `SystemClock` | Nuevo | `datetime.now(UTC)`. |
| `core_banking_mcp` | arranque | `config.py` — `CoreSettings` | Nuevo | pydantic-settings: `database_url` (default `sqlite:///./data/core_banking.db`), `seed_on_start` (default `true`). |
| `core_banking_mcp` | arranque | `server.py` — `build_server(settings)`, `main()` | Nuevo | Composición (repositorio, auditoría, reloj, caso de uso, `FastMCP`) y arranque stdio. Sin `print` a `stdout`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `CustomerRepository` | Nuevo | `SqlAlchemyCustomerRepository` | Puerto de §3.3. Fake en `tests/fakes/`. |
| `AuditLogPort` (core) | Nuevo | `JsonAuditLog` | No figura en §3.3 para el core; se justifica por el Art. 8 y por `mcp-tools.md` §6 (auditoría del lado del servidor). |
| `Clock` | Nuevo | `SystemClock` | Lo exige §5.3.6 (sin reloj real en los tests). |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `CardStatus` (enum) | `ACTIVE`, `BLOCKED`, `CANCELLED` | — |
| `Card` | `last4: str`, `status: CardStatus` | `last4` son exactamente 4 dígitos. El dominio no guarda el número completo. |
| `Customer` | `customer_id: str`, `full_name: str`, `document: str`, `cards: tuple[Card, ...]` | `customer_id`, `full_name` y `document` no vacíos. |
| `SearchCriteria` | `document: str \| None`, `full_name: str \| None`, `card_last4: str \| None` (ya normalizados) | Al menos uno presente; longitudes y formato de RN-001-05; si falla, `InvalidInputError`. |
| `CustomerSearchResult` | `customers: tuple[Customer, ...]`, `refinement_required: bool` | `len(customers) <= 5`; `refinement_required ⇒ customers == ()`. |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `customers` | `customer_id` (PK, str), `full_name`, `full_name_normalized` (índice), `document` (único), `document_normalized` (índice único) | Nueva |
| `cards` | `card_id` (PK), `customer_id` (FK), `pan` (ficticio), `last4` (índice), `status` | Nueva |

### Semillas

Ficticias y fijas (Art. 1). Los tests usan builders de `tests/fakes/`, no estas semillas (§5.3.7); las semillas sirven para la ejecución manual y para el smoke test por stdio.

- `C-0001` · "Laura Méndez" · `D-1001` · tarjetas `4111111111114321` (activa) y `5500000000008765` (bloqueada).
- `C-0002` · "Pedro Ríos" · `D-1002` · tarjeta `4000000000001234` (activa).
- `C-0003` y `C-0004` · "Ana Torres" · `D-2001` / `D-2002`.
- `C-0005` · "José Álvarez" · `D-3001`; `C-0006` · "José Álvarez Pérez" · `D-3002`.
- `C-0007` · "Marta Gil" · `AB12` (documento corto) · tarjeta `6011000000005555` (cancelada).

## 5. Dependencias nuevas

No se añade nada fuera del stack de §2. Como es la primera feature, se declaran en `pyproject.toml` los paquetes del stack que usa:

| Paquete | Versión | Justificación | Alternativa descartada |
|---|---|---|---|
| `mcp` | `>=1.13,<2` | Servidor FastMCP stdio (§2); la versión mínima admite `structured_output` y devolver `CallToolResult` desde la herramienta. | — (stack) |
| `sqlalchemy` | `>=2.0,<3` | Persistencia del core (§2). | — (stack) |
| `pydantic`, `pydantic-settings` | `>=2.7,<3` | Esquemas de E/S y configuración (§2). | — (stack) |
| Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `pre-commit` | Últimas estables | Testing, lint, tipado y hooks (§2). | — (stack) |

`fastapi`, `uvicorn` y `anthropic` no se añaden: los introducirá la feature del agente.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes en `tests/fakes/`: `CustomerBuilder`, `FakeCustomerRepository`, `FailingCustomerRepository`, `FakeAuditLog`, `FixedClock`. Los tests de herramienta usan una sesión MCP en memoria (`mcp.shared.memory`) contra el servidor real con SQLite `:memory:`.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-001-01 | `SearchCustomers` devuelve 1 cliente con los campos exactos | `buscar_cliente` por documento vía sesión MCP; smoke por **stdio** real con base sembrada | Los campos de `CustomerMatchOut` son exactamente los 4 de §7 (`additionalProperties: false`) | — |
| AC-001-02 | `normalize_document` (parametrizado: 4 filas) | El repositorio encuentra / no encuentra según la fila | — | — |
| AC-001-03 | — | Repositorio y herramienta: tarjeta activa, bloqueada y cancelada (parametrizado) | — | — |
| AC-001-04 | El caso de uso conserva el orden del repositorio | El repositorio ordena por `customer_id`; la herramienta devuelve 2 homónimos distinguibles | — | — |
| AC-001-05 | `normalize_name` (parametrizado: 7 filas) | El repositorio con `José Álvarez` y `José Álvarez Pérez` (7 filas) | — | — |
| AC-001-06 | Resultado vacío con `refinement_required=false` | La herramienta devuelve éxito con `customers=[]` e `isError=false` | — | — |
| AC-001-07 | `CustomerSearchResult.from_matches` con 4/5/6 (parametrizado, borde exacto 5) | La herramienta con 6 coincidencias devuelve `[]` + `true` | — | — |
| AC-001-08 | — | El repositorio combina documento y nombre con AND (dos casos) | — | — |
| AC-001-09 | `SearchCriteria.create` y el caso de uso (parametrizado: 9 filas) | La herramienta devuelve `isError=true` con `INVALID_INPUT` y `retryable=false` en cada fila | El sobre de error cumple `ToolErrorOut`; el catálogo de códigos es cerrado | — |
| AC-001-10 | `SearchCustomers` no recibe ningún puerto de identidad; la única escritura es la auditoría | La herramienta responde sin verificación previa | El esquema de salida no tiene campos de identidad o verificación | — |
| AC-001-11 | `mask_document` / `mask_card` | La respuesta serializada no contiene `D-1001` ni PAN completos | — | — |
| AC-001-12 | `mask_document("AB12") == "****"` (bordes: 4 y 5 caracteres) | — | — | — |
| AC-001-13 | `FakeAuditLog` + `FixedClock`: un evento por cada uno de los 6 casos (parametrizado), con el documento enmascarado | `JsonAuditLog` escribe JSON válido en el stream inyectado y nada en `stdout` | — | — |
| AC-001-14 | `FailingCustomerRepository` → `CoreUnavailableError`, auditado | La herramienta devuelve `INTERNAL`, `retryable=false`, sin el texto de la excepción | — | — |

Adicionales (`mcp-testing.md` §7, §2): snapshot del catálogo de herramientas (`buscar_cliente` es la única expuesta y su esquema coincide con §7 de la spec), y verificación de que el servidor no escribe en `stdout` fuera del protocolo. El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente, que reutilizará estos esquemas en `tests/contract/`. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global y, en la verificación final, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La versión de `mcp` no permite devolver `CallToolResult` con `structuredContent` en error, o choca con el `outputSchema` | Medio | Fijar `mcp>=1.13`; la primera tarea de herramienta lo verifica con un test de integración en memoria antes de construir el resto. |
| Las columnas normalizadas se desincronizan si se escribe en la base sin pasar por el repositorio | Medio | Solo `SqlAlchemyCustomerRepository.add` (que usan las semillas) escribe en `customers`, y calcula las columnas con las funciones del dominio. Un test de integración lo comprueba. |
| Una escritura a `stdout` rompe el transporte stdio | Medio | La auditoría va a `stderr` y no hay `print`. Un smoke test por stdio real lo detecta. |
| El esquema permisivo (`str \| None`) hace que el LLM omita `conversation_id` | Bajo | El `description` lo marca como obligatorio, la respuesta es `INVALID_INPUT` auditada y un test de contrato verifica el texto. |
| La normalización Unicode convierte `ñ` en `n` ("Muñoz" coincide con "Munoz") | Bajo | Es coherente con RN-001-03 ("quitar diacríticos"); se documenta con un test explícito. |
| `tools.py` sustituye el `FuncMetadata` de la herramienta vía `mcp._tool_manager` (API privada de FastMCP 1.30) para que los `CallToolResult` con `isError=true` no se validen contra `outputSchema` | Medio | Decisión del usuario (2026-10-16) para conservar `outputSchema` en `list_tools`. Los tests de error de T-001-16 (`INVALID_INPUT`/`INTERNAL` con sobre) fallan si una actualización de `mcp` rompe el parche; revisar al subir de versión. |
| pytest-cov no impone un umbral por capas | Bajo | Hay un comando `coverage report --include ... --fail-under=90` en la tarea de verificación final. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Semillas fijas inventadas (§4) y builders en los tests; PAN de prueba no reales. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento; los AC están trazados en §6. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); los fakes permiten el ciclo rojo-verde en el dominio y la aplicación. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio solo usa stdlib (`unicodedata`, `dataclasses`, `enum`); Pydantic y SQLAlchemy se quedan en infraestructura y se mapean en el adaptador; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La búsqueda no decide sobre disputas; no se toca `DisputePolicy`. |
| Art. 6 — Acciones vía MCP | Cumple | El core se expone solo como herramienta MCP; no se crea ningún acceso alternativo. |
| Art. 7 — Identificación antes que información | Cumple | `buscar_cliente` es la excepción explícita y no devuelve datos sensibles (RN-001-08/09), ni autentica ni marca la sesión (AC-001-10). |
| Art. 8 — Auditoría | Cumple | `AuditLogPort` del core registra cada invocación con `conversation_id`, marca de tiempo, entrada enmascarada, salida, regla y motivo (AC-001-13). |
| Art. 9 — Secretos | Cumple | No hay secretos; solo `CORE_DATABASE_URL` en `.env.example`, y `.env` está en `.gitignore`. |
| Art. 10 — Ante la duda, escalar | Cumple | Las fallas inesperadas devuelven `INTERNAL` con `retryable=false` (AC-001-14); el escalamiento lo ejecutará el consumidor (fuera de alcance, spec §8). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
