# Plan: Verificar la identidad del cliente con su fecha de nacimiento y la de expedición de su documento

| Campo | Valor |
|---|---|
| Feature | `002-identity-verification` |
| Versión | 0.1.2 |
| Estado | Aprobado |
| Fecha | 2026-10-17 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 (0.1.1: guía y smoke test para probar el servidor con MCP Inspector; 0.1.2: el Inspector se lanza con `uv run mcp dev`, que añade el extra `mcp[cli]` y un `mcp` perezoso en `server.py`) |

---

## 1. Resumen técnico

Segunda feature de `core_banking_mcp`: añade la herramienta `verificar_identidad` y el estado de verificación por conversación, reutilizando el esqueleto, el patrón de errores, la auditoría y el reloj de la feature 001. No toca `dispute_agent`.

- **Dominio puro** (stdlib): `VerificationRequest.create(...)` valida RN-002-07 (formato `AAAA-MM-DD` estricto, fecha existente, no posterior a hoy, expedición no anterior al nacimiento) y lanza `InvalidInputError`. `VerificationState` (cliente verificado + fallos acumulados) es inmutable. `evaluate_verification(state, request, identity)` es una función pura que aplica RN-002-02/03/04/05/06/10/11 y devuelve el nuevo estado, el resultado y el resultado de auditoría. "Hoy" se calcula en el dominio con `today_in_bogota(now)`, con offset fijo UTC−05:00.
- **Caso de uso** `VerifyIdentity`: valida → lee el estado → consulta las fechas registradas **solo si hace falta comparar** → evalúa → guarda el estado → audita. Cualquier excepción inesperada se convierte en `CoreUnavailableError` sin guardar estado (RN-002-16).
- **Estado en el servidor** (decisión del usuario): puerto `ConversationVerificationStore` con `get(conversation_id) -> VerificationState` y `save(conversation_id, state)`. El adaptador es un `dict` protegido con `Lock` dentro del proceso. Las herramientas futuras validarán el Art. 7 con el mismo puerto (RN-002-13): `get(...)` de una conversación desconocida devuelve el estado vacío (no verificada).
- **Fechas registradas** (decisión del usuario): value object `IdentityRecord(birth_date, document_issue_date)` y método nuevo `CustomerRepository.find_identity(customer_id)`. `Customer` no cambia, así que `buscar_cliente` nunca carga ni expone las fechas.
- **Zona horaria** (decisión del usuario): offset fijo UTC−05:00 con `datetime.timezone`, sin dependencias nuevas.
- **Herramienta delgada** `verificar_identidad` en un módulo propio, con la misma firma permisiva de 001 (`str | None` en todos los campos): toda violación, incluso un campo ausente, sale como `INVALID_INPUT` y queda auditada. Reutiliza el patrón de errores de 001 (`CallToolResult` con `isError=true` y sobre `{code, message, retryable}`).
- **Auditoría sin fechas por construcción**: `AuditEvent` no tiene ningún campo de fechas, y la entrada de esta herramienta no se serializa (`input=None`). Solo se añaden `customer_id` e `intento`.

Decisiones triviales tomadas:

- **Estricto con las fechas:** se aceptan solo con la forma `[0-9]{4}-[0-9]{2}-[0-9]{2}` (`re.fullmatch`) y no se recortan. `date.fromisoformat` no basta: en Python 3.12 acepta `20260115` y `2026-W03-2`.
- **`customer_id` exacto:** se compara con el valor recortado, sin distinguir nada más (sin normalizar mayúsculas), igual que el `customer_id` opaco de `buscar_cliente`.
- **Orden de evaluación** (derivado de RN-002-05/10/11): primero la validación de la entrada; luego, con el estado de la conversación: verificada para el mismo cliente → `already_verified`; verificada para otro → `other_customer`; bloqueada → `locked`; si no, se comparan las fechas.
- **Fallo del repositorio:** `find_identity` se invoca solo cuando hay que comparar, así que las respuestas idempotentes, de otro cliente o de bloqueo no dependen de la base.
- **Prueba manual con MCP Inspector:** se documenta en `docs/mcp-inspector.md` cómo lanzar `uv run mcp dev src/core_banking_mcp/server.py` (transporte stdio), con la secuencia de llamadas de los AC más representativos sobre las semillas. `mcp dev` no acepta funciones: exige un objeto `FastMCP` a nivel de módulo llamado `mcp`, `server` o `app`. Como crear el servidor al importar abriría la base y la sembraría como efecto secundario (y los tests importan `build_server`), `server.py` expone `mcp` de forma perezosa con un `__getattr__` de módulo que llama a `build_server()` una sola vez y lo cachea. El cableado sigue únicamente en `server.py` (§3.2.3). Un smoke test por stdio real ejercita la ruta de `main()`; otro test comprueba que `server.mcp` resuelve a un `FastMCP` con las dos herramientas.
- **Atomicidad:** FastMCP ejecuta las herramientas síncronas en el hilo del bucle de eventos, así que el ciclo leer-evaluar-guardar de una conversación no se intercala (ver riesgos).

## 2. Componentes por capa

Rutas relativas a `src/core_banking_mcp/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/models/identity.py` — `IdentityRecord`, `VerificationState`, `VerificationRequest`, `MAX_FAILED_ATTEMPTS = 3` | Nuevo | Value objects inmutables (`dataclass(frozen=True)`). `VerificationRequest.create` aplica RN-002-07; `VerificationState` expone `attempts_remaining`, `is_locked` e `is_verified_for(customer_id)` (RN-002-13). |
| `core_banking_mcp` | `domain` | `domain/identity_verification.py` — `evaluate_verification`, `VerificationDecision`, `VerificationOutcome` | Nuevo | Función pura con la tabla de transiciones de RN-002-02/03/04/05/06/10/11. Resultados: `VERIFIED`, `ALREADY_VERIFIED`, `FAILED`, `LOCKED`, `OTHER_CUSTOMER`. |
| `core_banking_mcp` | `domain` | `domain/clock.py` — `today_in_bogota(now)` | Nuevo | `now.astimezone(timezone(timedelta(hours=-5))).date()` (RN-002-08). |
| `core_banking_mcp` | `application` | `application/ports/conversation_verification_store.py` — `ConversationVerificationStore` | Nuevo | `get(conversation_id) -> VerificationState` (estado vacío si es desconocida) y `save(conversation_id, state)`. |
| `core_banking_mcp` | `application` | `application/ports/customer_repository.py` — `CustomerRepository` | Modificado | Se añade `find_identity(customer_id) -> IdentityRecord \| None`. |
| `core_banking_mcp` | `application` | `application/ports/audit_log.py` — `AuditEvent` | Modificado | `input` pasa a `AuditInput \| None`; se añaden `customer_id: str \| None = None` e `intento: int \| None = None` (con valor por defecto, al final). Los eventos de `buscar_cliente` no cambian de contenido. |
| `core_banking_mcp` | `application` | `application/use_cases/verify_identity.py` — `VerifyIdentity`, `VerifyIdentityCommand`, `VerificationResult` | Nuevo | Orquesta validación → estado → repositorio (solo si hay que comparar) → evaluación → guardado → auditoría. Reglas registradas: RN-002-02 (`verified`), RN-002-11 (`already_verified`), RN-002-03/04 (`failed`), RN-002-05 (`locked`), RN-002-10 (`other_customer`), RN-002-07 (inválido), RN-002-16 (falla). |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/schemas.py` | Modificado | Se añaden `VerificarIdentidadIn` y `VerificarIdentidadOut` (`extra="forbid"`, `attempts_remaining` con `ge=0, le=3`), con `Field(description=...)`. `ErrorCode` no cambia. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/errors.py` | Modificado | Se mueve aquí, como `ErrorPassthroughMetadata` (público), la clase `_ErrorPassthroughMetadata` de `tools.py` para reutilizarla sin importar un símbolo privado. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/tools.py` | Modificado | Solo importa `ErrorPassthroughMetadata` desde `errors.py`. Sin cambio de comportamiento. |
| `core_banking_mcp` | `infrastructure/inbound` | `infrastructure/inbound/mcp/identity_tools.py` — `register_identity_tools(mcp, verify_identity)` | Nuevo | Herramienta delgada `verificar_identidad` con docstring en español (§7 de la spec: cuándo usarla y cuándo no, efectos, no idempotente salvo RN-002-11). Mapea `InvalidInputError` → `INVALID_INPUT`, `CoreUnavailableError` y *catch-all* → `INTERNAL` (`retryable=false`, sin el texto de la excepción). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/models/tables.py` — `CustomerRow` | Modificado | Columnas `birth_date` y `document_issue_date` (`Date`, no nulas). |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/sqlalchemy_customer_repository.py` | Modificado | `find_identity` por clave primaria y mapeo a `IdentityRecord`. `add(customer, pans, identity)` recibe las fechas (obligatorias, RN-002-01). `_to_entity` y `find_matching` no las exponen. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/persistence/seeds/customers.py` | Modificado | Cada semilla incluye su `IdentityRecord`; `seed_database` las pasa a `add`. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/verification/in_memory_verification_store.py` — `InMemoryConversationVerificationStore` | Nuevo | `dict[str, VerificationState]` con `threading.Lock`; los estados son inmutables, así que no se copian. |
| `core_banking_mcp` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py` | Modificado | Serializa `customer_id` e `intento`; `input: null` cuando no hay entrada auditable. |
| `core_banking_mcp` | arranque | `server.py` — `build_server`, `mcp` | Modificado | Crea la única instancia del almacén de estado, construye `VerifyIdentity` y llama a `register_identity_tools`. Añade `__getattr__(name)` de módulo: para `"mcp"` devuelve `build_server()` construido una sola vez (caché) y para cualquier otro nombre lanza `AttributeError`; así `uv run mcp dev` encuentra el objeto sin efectos secundarios al importar. |
| — | raíz | `pyproject.toml`, `uv.lock` | Modificado | Se cambia la dependencia `mcp>=1.13,<2` por `mcp[cli]>=1.13,<2` (ver §5). `uv.lock` se regenera. |
| — | docs | `docs/mcp-inspector.md` | Nuevo | Guía en español para probar el servidor con MCP Inspector: requisitos (Node.js), comando `uv run mcp dev src/core_banking_mcp/server.py`, borrar `data/core_banking.db` si viene de 001, y una tabla de llamadas de ejemplo con las semillas (`C-0001`, fechas correctas, fechas incorrectas hasta el bloqueo, fechas inválidas, otra conversación) con la respuesta esperada. Los datos de ejemplo son los ficticios de §4. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `ConversationVerificationStore` | Nuevo | `InMemoryConversationVerificationStore` | No figura en §3.3 para el core; se justifica por el Art. 7 (defensa en profundidad, RN-002-13) y por §3.7: pasar a Redis o a base de datos, o añadir expiración, solo requiere un adaptador nuevo. Fake en `tests/fakes/`. |
| `CustomerRepository` | Modificado | `SqlAlchemyCustomerRepository` | Nueva operación `find_identity`; las fechas viajan en un value object aparte, no en `Customer`. |
| `AuditLogPort` (core) | Modificado | `JsonAuditLog` | `AuditEvent` gana campos opcionales; el puerto no cambia. |
| `Clock` | Sin cambios | `SystemClock` | Devuelve UTC; el dominio lo convierte a Bogotá. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `IdentityRecord` | `birth_date: date`, `document_issue_date: date` | `document_issue_date >= birth_date`. |
| `VerificationState` | `verified_customer_id: str \| None`, `failed_attempts: int` | `0 <= failed_attempts <= 3`. `is_locked ⇔ failed_attempts == 3`. `attempts_remaining = 3 - failed_attempts`. Verificado y bloqueado nunca coexisten. El estado inicial (conversación desconocida) es no verificada y sin fallos. |
| `VerificationRequest` | `conversation_id: str`, `customer_id: str`, `birth_date: date`, `document_issue_date: date` | Se crea solo con `create(...)`: `conversation_id` no vacío tras recortar; `customer_id` de 1 a 32 caracteres tras recortar; fechas con formato estricto, existentes, no posteriores a `today_in_bogota(now)` y con expedición no anterior al nacimiento. Si falla, `InvalidInputError`. |
| `VerificationDecision` | `state: VerificationState`, `verified: bool`, `escalation_required: bool`, `outcome: VerificationOutcome` | `escalation_required ⇒ state.is_locked`. |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `customers` | `birth_date` (`Date`, no nula), `document_issue_date` (`Date`, no nula) | Dos columnas nuevas. |

El estado de verificación **no se persiste** (RN-002-09): vive en memoria del proceso del servidor.

### Semillas

Ficticias y fijas (Art. 1). Se añaden las fechas a las siete semillas de 001; los AC usan `C-0001` y `C-0002`. Los tests usan builders de `tests/fakes/`, no estas semillas (§5.3.7).

- `C-0001` · nacimiento `1990-03-15` · expedición `2008-04-20`.
- `C-0002` · nacimiento `1985-07-02` · expedición `2003-08-10`.
- `C-0003` · `1992-11-30` / `2010-12-01`; `C-0004` · `1988-01-09` / `2006-02-14`.
- `C-0005` · `1979-05-21` / `1997-06-30`; `C-0006` · `1995-09-12` / `2013-10-05`.
- `C-0007` · `2000-02-29` / `2018-03-12`.

## 5. Dependencias nuevas

Un único cambio de declaración, sin paquetes nuevos en el entorno. `datetime`, `re` y `threading` son de la biblioteca estándar.

| Paquete | Versión | Justificación | Alternativa descartada |
|---|---|---|---|
| `mcp[cli]` (sustituye a `mcp`) | `>=1.13,<2` | Es el stack de §2 (SDK oficial `mcp`); el extra `cli` habilita el comando `uv run mcp dev`, que es como el equipo prueba el servidor con MCP Inspector. El extra solo declara `typer` y `python-dotenv`, que ya están instalados (`typer` ya figura en `pyproject.toml`; `python-dotenv` llega por `pydantic-settings`), así que el entorno y el resultado de `uv sync` no cambian de paquetes. | `npx @modelcontextprotocol/inspector uv run python -m core_banking_mcp.server`: no toca `pyproject.toml`, pero el equipo pidió `uv run mcp dev`. |

El Inspector en sí (`@modelcontextprotocol/inspector`) no se añade al proyecto: `mcp dev` lo descarga con `npx`, por lo que requiere Node.js en la máquina del desarrollador, y no entra en `pyproject.toml` ni en la suite de tests. Se descartó también `zoneinfo` + `tzdata`: en Windows exige añadir `tzdata`, y la spec ya fija UTC−05:00 (Colombia no aplica horario de verano).

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Fakes y builders nuevos en `tests/fakes/`:

- `IdentityBuilder` (fechas por defecto).
- `FakeVerificationStore`, con helpers para preparar los "Given": cliente ya verificado y N fallos previos.
- `FakeCustomerRepository` pasa a aceptar identidades.
- `FailingCustomerRepository.find_identity` falla con una excepción no de dominio.
- `FakeAuditLog` y `FixedClock` se reutilizan (el reloj acepta un instante).

Los tests de herramienta usan una sesión MCP en memoria contra el servidor real con SQLite `:memory:`, como en 001.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-002-01 | `evaluate_verification` con ambas fechas correctas devuelve `VERIFIED` y deja el cliente en el estado; `VerifyIdentity` guarda el estado | `verificar_identidad` vía sesión MCP con SQLite; el almacén indica `C-0001` | La salida cumple `VerificarIdentidadOut` (campos exactos) | — |
| AC-002-02 | `evaluate_verification` (parametrizado: 3 filas) → `FAILED` con 2 restantes; la respuesta no distingue qué dato falló | La herramienta, 3 filas: misma respuesta y sin cliente verificado | — | — |
| AC-002-03 | `VerificationRequest.create` con expedición anterior al nacimiento → `InvalidInputError`; el caso de uso no cambia el estado | La herramienta devuelve `INVALID_INPUT` con `retryable=false`; el estado sigue vacío | El sobre de error cumple `ToolErrorOut` | — |
| AC-002-04 | Cliente inexistente (`find_identity` → `None`) produce la misma decisión que fechas incorrectas y suma 1 fallo | La herramienta con `C-9999`: respuesta idéntica campo a campo a la de AC-002-02 | — | — |
| AC-002-05 | `evaluate_verification` parametrizado (0/1/2 fallos previos → restantes y derivar; borde exacto del 3.er fallo) | La herramienta, 3 filas, con el almacén preparado con N fallos | — | — |
| AC-002-06 | Fechas correctas con 2 fallos previos → `VERIFIED` con `attempts_remaining = 1` | La herramienta devuelve `verified = true`, 1 restante; el almacén indica `C-0001` | — | — |
| AC-002-07 | Estado bloqueado + fechas correctas → `LOCKED`, 0 restantes, derivar, sin verificar | La herramienta con el almacén bloqueado; sigue sin cliente verificado | — | — |
| AC-002-08 | `VerificationRequest.create` parametrizado (13 filas: vacías, ausentes/`null`, inexistentes, formato distinto, futuras, expedición anterior, `customer_id` ausente/vacío/espacios/33 caracteres, `conversation_id` ausente/vacío/espacios); el caso de uso no cambia el estado | La herramienta devuelve `INVALID_INPUT` con `retryable=false` en cada fila; estado intacto | El catálogo de códigos sigue cerrado | — |
| AC-002-09 | `today_in_bogota` y `create` parametrizados con los 4 instantes (borde 03:00Z y 05:00Z, hoy y nacimiento igual a expedición) | La herramienta con `FixedClock` en cada instante | — | — |
| AC-002-10 | Con 2 fallos previos, una entrada inválida deja el estado igual; una llamada posterior con fechas correctas verifica | La misma secuencia a través de la herramienta | — | — |
| AC-002-11 | `evaluate_verification` verificada para `C-0001` + solicitud para otro (3 filas) → `OTHER_CUSTOMER`, sin contar intento ni derivar | La herramienta, 3 filas; el almacén sigue indicando `C-0001` | — | — |
| AC-002-12 | Verificada para el mismo cliente con fechas correctas e incorrectas (2 filas) → `ALREADY_VERIFIED` sin consultar el repositorio de identidades | La herramienta, 2 filas; sin fallos acumulados | — | — |
| AC-002-13 | `InMemoryConversationVerificationStore`: conversaciones independientes y `get` de una desconocida devuelve el estado vacío | Dos conversaciones por la herramienta: `B` no verificada, con contador propio (2 restantes); `A` conserva a `C-0001` | — | — |
| AC-002-14 | `VerificationResult` solo trae los 3 campos | La respuesta serializada (2 filas) no contiene `1990-03-15`, `2008-04-20`, `Laura Méndez`, `D-1001` ni un PAN | `VerificarIdentidadOut` tiene `additionalProperties: false` y solo los 3 campos | — |
| AC-002-15 | `FakeAuditLog` + `FixedClock`: exactamente un evento por cada uno de los 8 casos (parametrizado), con `customer_id`, `intento`, resultado y sin fechas (verificado sobre el evento y su JSON) | `JsonAuditLog` escribe JSON válido en el stream inyectado, sin fechas y sin nada en `stdout` | — | — |
| AC-002-16 | `FailingCustomerRepository` → `CoreUnavailableError`, auditado como `INTERNAL`, sin cambiar el estado | La herramienta devuelve `INTERNAL` con `retryable=false`, sin el texto de la excepción, trazas ni SQL | El sobre cumple `ToolErrorOut` | — |

Adicionales (`mcp-testing.md` §7, §2):

- **Snapshot del catálogo:** el test existente de 001 pasa a esperar `buscar_cliente` y `verificar_identidad`, comparando el esquema de entrada y de salida del nuevo con la spec §7 y fallando ante herramientas no declaradas.
- **Art. 7:** el caso "sin identificación previa" de `mcp-testing.md` §2 no aplica a esta herramienta, que es la excepción explícita (`mcp-tools.md` §5). Se cubre el invariante equivalente: una conversación sin verificación exitosa o desconocida se considera no verificada (AC-002-13).
- **Escalamiento (§5.3.4):** los dos casos de la spec §8 tienen test: `escalation_required = true` en AC-002-05 y AC-002-07, y `INTERNAL` con `retryable = false` en AC-002-16.
- **`server.mcp` perezoso (ruta de `mcp dev`):** test de integración con `CORE_DATABASE_URL` en memoria: importar `server` no construye nada; `server.mcp` devuelve un `FastMCP` con `buscar_cliente` y `verificar_identidad`, dos accesos devuelven la misma instancia y un nombre inexistente lanza `AttributeError`.
- **Smoke por stdio (ruta de `main()`):** el test de 001 que lanza el servidor como subproceso se amplía: `list_tools` muestra las dos herramientas y `verificar_identidad` con las semillas devuelve `verified = true` (AC-002-01) y, con una fecha incorrecta en otra conversación, `verified = false` con 2 restantes; la salida del subproceso por `stdout` es solo protocolo.
- **Persistencia:** test de integración de `find_identity` y de las columnas nuevas, y de que `find_matching` / `buscar_cliente` no exponen las fechas.
- **Regresión de 001:** adaptar los `add(...)` y los fakes existentes a las fechas obligatorias; la suite de 001 debe seguir en verde.
- El lado cliente del contrato (`mcp-testing.md` §1) queda pendiente para la feature del agente, que reutilizará estos esquemas en `tests/contract/`. **E2E** (chat → agente → MCP) no aplica: el agente está fuera de alcance.

Cobertura: `pytest --cov` con `fail_under=80` global y, en la verificación final, `coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Una base SQLite local creada con la feature 001 no tiene las columnas nuevas; `create_all` no altera tablas existentes y cualquier consulta a `customers` (también `buscar_cliente`) fallaría con "no such column" | Alto | No hay herramienta de migraciones en el stack y los datos son ficticios y reproducibles (Art. 1). Se documenta que hay que borrar `data/core_banking.db` (ignorado por git); el servidor la recrea y siembra al arrancar. Un test de integración crea el esquema desde cero. |
| Las fechas llegan a la auditoría o a la respuesta por un cambio futuro (RN-002-14/15) | Alto | `AuditEvent` y `VerificarIdentidadOut` no tienen campos de fechas; los tests de AC-002-14 y AC-002-15 comparan la respuesta y el JSON auditado con los valores sembrados. |
| El ciclo leer-evaluar-guardar no es atómico si se ejecuta desde varios hilos, y dos solicitudes simultáneas podrían saltarse el límite de 3 intentos | Medio | FastMCP ejecuta las herramientas síncronas en el hilo del bucle de eventos y el transporte stdio es de un único cliente. El `Lock` del adaptador protege cada operación. Si el servidor pasa a atender solicitudes concurrentes (MCP HTTP, §3.7), la nueva spec deberá añadir una operación atómica `update` al puerto. |
| El estado en memoria crece sin límite y se pierde al reiniciar | Bajo | Es el alcance acordado (RN-002-09: sin expiración ni persistencia). El puerto permite un adaptador persistente sin tocar `domain` ni `application`. |
| `AuditEvent.input` pasa a opcional y se añaden campos: puede romper los tests de auditoría de 001 | Bajo | Los campos nuevos son opcionales y van al final. Los tests de AC-001-13 se ejecutan en la regresión de 001. |
| El snapshot de catálogo de 001 deja de cumplirse al publicar una segunda herramienta | Bajo | Se actualiza el test en el mismo cambio. La spec 001 no cambia: su comportamiento sigue siendo el mismo. |
| `date.fromisoformat` acepta formatos que la spec no admite (`20260115`, `2026-W03-2`) | Bajo | La validación usa `re.fullmatch` sobre `[0-9]{4}-[0-9]{2}-[0-9]{2}` antes de construir la fecha; test parametrizado en AC-002-08. |
| `uv run mcp dev` exige Node.js, su CLI es del extra `mcp[cli]` (versión 1.30 instalada) y su carga de módulos puede cambiar entre versiones; además el estado de verificación vive en el proceso, así que reconectar el Inspector reinicia los intentos | Bajo | La guía fija el comando exacto, indica que reconectar reinicia el estado (RN-002-09) y avisa de que la auditoría sale por `stderr`. La corrección del servidor la cubren los smoke tests (`server.mcp` y stdio), no el Inspector. |
| El `__getattr__` perezoso de `server.py` oculta errores de arranque hasta el primer acceso a `mcp` y, mal escrito, devolvería `None` para otros nombres y rompería `from server import ...` | Bajo | Solo responde a `"mcp"`, lanza `AttributeError` para el resto y cachea la instancia; lo cubre el test de `server.mcp`. `build_server` y `main()` no cambian. |
| `uv.lock` y `pyproject.toml` son archivos compartidos y cambian en esta feature | Bajo | La tarea correspondiente se ejecuta sola en su oleada y la verificación final corre `uv sync` y la suite completa. |
| El reloj inyectado debe llevar zona horaria para convertir a Bogotá | Bajo | `SystemClock` ya devuelve UTC y `FixedClock` se construye con `tzinfo=UTC`; `today_in_bogota` lo prueba con los bordes de AC-002-09. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Las fechas de las semillas son inventadas y fijas (§4); los tests usan builders y no las semillas. |
| Art. 2 — Spec-anchored | Cumple | El plan implementa la spec 0.1.0 aprobada sin añadir comportamiento; los 16 AC están trazados en §6. Los ajustes a tests de 001 no cambian el comportamiento de 001. |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test (fase Tasks); el dominio puro, el caso de uso y los fakes permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | El dominio usa solo stdlib (`dataclasses`, `datetime`, `re`); Pydantic y SQLAlchemy se quedan en infraestructura y se mapean en el adaptador; el almacén es un puerto con adaptador en `outbound`; el cableado solo está en `server.py`. Lo refuerza el hook `check_mcp_boundaries`. |
| Art. 5 — El dominio decide | N.A. | La verificación de identidad no decide sobre disputas; no se toca `DisputePolicy`. La decisión de verificar sí vive en una función pura del dominio, no en el LLM. |
| Art. 6 — Acciones vía MCP | Cumple | La verificación se expone solo como herramienta MCP; no se crea ningún acceso alternativo. |
| Art. 7 — Identificación antes que información | Cumple | `verificar_identidad` es la excepción explícita y no devuelve datos del cliente (RN-002-14). Es la herramienta que crea el estado de verificación en el servidor y el puerto que lo expone (RN-002-13), para que las herramientas futuras lo validen. |
| Art. 8 — Auditoría | Cumple | Cada invocación genera un único registro con `conversation_id`, marca de tiempo del reloj inyectado, herramienta, `customer_id`, resultado, regla y motivo, sin las fechas (AC-002-15). |
| Art. 9 — Secretos | Cumple | No hay secretos ni configuración nueva; las fechas de las semillas son ficticias y la guía del Inspector no incluye credenciales. |
| Art. 10 — Ante la duda, escalar | Cumple | 3 fallos bloquean la conversación y devuelven `escalation_required = true` (AC-002-05/07); una falla inesperada devuelve `INTERNAL` con `retryable = false` sin cambiar el estado (AC-002-16). El escalamiento lo ejecutará el consumidor (fuera de alcance, spec §8). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
