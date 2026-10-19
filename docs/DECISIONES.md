# Registro de decisiones — Agente de Disputas Banco Andino

Índice consolidado de las decisiones tomadas en el proyecto. **No sustituye** a `docs/constitution.md`: si algo aquí la contradice, prevalece la constitución.

Precedencia: `constitution.md` > `.claude/rules/` > `spec.md` > `plan.md` > `tasks.md` > código.
Última actualización: 2026-10-19. Cada decisión cita su fuente (Art. / § de la constitución, rule o spec NNN).

---

## 1. Producto y alcance

| Decisión | Motivo | Fuente |
|---|---|---|
| Agente de IA que atiende disputas de transacciones y contracargos de Banco Andino por chat web. | Maximizar resolución en primer contacto. | Constitución §1.1 |
| Banco Andino es completamente ficticio; todo dato es sintético y reproducible por semillas. Prohibida la PII real. | Evitar riesgo con datos reales. | Art. 1 |
| Objetivos: resolución en primer contacto, escalar correctamente (cero casos auto-resueltos que debían escalarse), trazabilidad total, seguridad del cliente, respuestas claras en español. | — | §1.2 |
| Fuera de alcance: integración con bancos/redes/pasarelas reales, dinero real, bandeja de trabajo para analistas (el escalamiento solo se registra en el core simulado). | Acotar la v1. | §1.3 |

## 2. Metodología y proceso

| Decisión | Motivo | Fuente |
|---|---|---|
| SDD puro, sin frameworks de SDD; modelo **spec-anchored**: la spec se escribe antes y permanece viva. | La spec es fuente de verdad del comportamiento. | Art. 2, §4.1 |
| Flujo en cuatro fases por feature (Specify → Plan → Tasks → Implement) en `specs/NNN-feature-name/`, con gate de aprobación en cada una. | Trazabilidad y control. | §4.2 |
| Sin spec aprobada no hay código; un cambio de comportamiento actualiza spec, test y código en el mismo cambio; una divergencia spec/código es un defecto. | — | §4.3 |
| Cada criterio de aceptación tiene ID `AC-NNN-XX` y los tests lo citan. Las reglas de `DisputePolicy` van en tabla de decisión, una fila ≥ 1 test. | Trazabilidad. | §4.3.2, §4.3.6 |
| TDD obligatorio (Red → Green → Refactor), evidenciable en el historial. | Ningún código sin test que antes falló. | Art. 3, §5.1 |
| Niveles de test: unitario, integración, contrato, e2e. Cobertura ≥ 90 % en `domain`+`application` y ≥ 80 % global. | La cobertura es un piso, no un objetivo. | §5.2, §5.4 |
| Definition of Done: spec aprobada y trazada, tests primero, cobertura, ruff + mypy strict, spec alineada, sin secretos ni datos reales. | — | §5.5 |
| Enmiendas a la constitución con semver (MAJOR/MINOR/PATCH) y checklist de cumplimiento en revisión. | — | §6.2–6.3 |
| Enmienda 1.0.1: `infrastructure/in` → `inbound` y `out` → `outbound`. | `in` es palabra reservada de Python y no se puede importar; `out` se renombra por simetría. | §6.4 |
| Hook `check_mcp_boundaries.py` impone las fronteras entre capas y aplicaciones (no una rule). | Lo verificable automáticamente se automatiza. | `.claude/rules/README.md` |
| Hook `ac_coverage_gate.py` bloquea el PR sin veredicto `Cumple` vigente de `verify-ac-coverage`. | Auditoría de trazabilidad antes del PR (§4.3). | `.claude/rules/README.md` |
| `verify-ac-coverage` opera en dos fases: la primera auditoría es completa; si da `No cumple`, la siguiente solo verifica que se corrigieron los hallazgos `H-NN`. | Evitar auditorías interminables. | `.claude/rules/README.md` |
| Rules con frontmatter `paths:`, reglas numeradas y cortas, que citan el Artículo que concretan y no repiten la constitución. | — | `.claude/rules/README.md` |
| Skills del flujo: `specify`, `plan-feature`, `tasks-feature`, `sdd-feature`, `qa-spec`, `verify-ac-coverage`; subagente `task-implementer` implementa una tarea con TDD estricto. | — | `CLAUDE.md`, `.claude/` |
| Agregar una dependencia nueva exige justificarla en el `plan.md` de la feature. | Control de superficie. | §2 |

## 3. Stack técnico

| Decisión | Fuente |
|---|---|
| Python 3.12, uv (`pyproject.toml` + `uv.lock`). | §2 |
| FastAPI + Uvicorn; Pydantic v2; pydantic-settings (`.env`). | §2 |
| LLM: Claude vía SDK oficial `anthropic`; modelo por variable de entorno. | §2 |
| Orquestación: loop de *tool use* propio, sin frameworks de agentes. | §2 |
| MCP: SDK oficial `mcp` (FastMCP), transporte **stdio**; el agente lanza el servidor como subproceso. | §2 |
| Persistencia del core: SQLite + SQLAlchemy 2.x con semillas reproducibles. | §2 |
| Front: HTML + CSS + JS vanilla mínimo, servido por FastAPI como estáticos. | §2 |
| Calidad: ruff, mypy `--strict`, pre-commit (ruff + mypy + pytest rápido). | §2 |
| Tests: pytest, pytest-asyncio, pytest-cov, `TestClient`/httpx. | §2 |
| Observabilidad: logging JSON con `conversation_id` como correlation id. | §2 |
| Idiomas: documentación, specs y mensajes al cliente en español; código, identificadores, archivos y commits en inglés. Excepción: nombres de herramientas MCP en español (parte del contrato). | §2, §3.4 |
| Secretos solo en variables de entorno/`.env`; se versiona únicamente `.env.example`. | Art. 9 |

## 4. Arquitectura

| Decisión | Motivo | Fuente |
|---|---|---|
| Dos aplicaciones hexagonales independientes (`dispute_agent` y `core_banking_mcp`) que solo se comunican por MCP. | Simular un core bancario desacoplado. | §3.1 |
| Capas: `domain` (solo stdlib) → `application` (casos de uso y puertos `Protocol`) → `infrastructure/inbound` y `outbound`. Dependencias hacia adentro. | Art. 4 | §3.2 |
| Prohibido importar código entre las dos apps; el contrato son los esquemas MCP, verificados con tests de contrato. | Art. 6 | §3.2.2 |
| El cableado (inyección de dependencias) ocurre solo en `main.py` / `server.py`. | — | §3.2.3 |
| Modelos SQLAlchemy y Pydantic no cruzan al dominio; se mapean en el adaptador. | — | §3.2.4 |
| Puertos del agente: `LLMPort`, `BankingToolsPort`, `ConversationRepository` (en memoria v1), `AuditLogPort`. Puertos del core: repositorios de cliente, transacción y disputa. | Sustituibilidad. | §3.3 |
| Evolución prevista sin tocar dominio ni aplicación: MCP stdio → HTTP streamable, SQLite → PostgreSQL, memoria → Redis, Claude → otro proveedor. Cada cambio requiere spec propia. | — | §3.7 |
| **El dominio decide, el LLM conversa**: `DisputePolicy` determinista decide `RESOLVE`/`REJECT`/`ESCALATE`; el LLM no puede sobrescribirla. | Art. 5 | §1.4 |
| Toda acción sobre el core pasa por herramientas MCP; prohibido acceso directo a la BD desde el agente. | Art. 6 | §1.4 |
| Ante la duda, escalar: reglas no concluyentes, fallo no recuperable o salida inválida del LLM ⇒ escalar. | Art. 10 | §1.4 |

## 5. Contrato de herramientas MCP

| Decisión | Fuente |
|---|---|
| Catálogo inicial: `buscar_cliente`, `verificar_identidad`, `consultar_transacciones`, `iniciar_disputa`, `bloquear_tarjeta`, `escalar_a_analista`. | §3.4 |
| Nombres `verbo_sustantivo` en snake_case español; no cambian sin spec y versión de contrato. | `mcp-tools.md` 1 |
| Entradas y salidas son modelos Pydantic v2 tipados, sin `dict` libre ni `Any`; campos en inglés con `Field(description=...)`. | `mcp-tools.md` 3 |
| Herramientas delgadas: validan, llaman a un caso de uso y mapean; sin lógica de negocio ni SQLAlchemy. | `mcp-tools.md` 4 |
| `conversation_id` obligatorio en toda herramienta y propagado a la auditoría. | `mcp-tools.md` 6 |
| Errores como `{code, message, retryable}` con catálogo cerrado; `retryable=false` implica escalar. Nunca excepciones crudas. | `mcp-tools.md` 7 |
| Mínima exposición y PII enmascarada (tarjeta `**** 1234`, documento parcial). | `mcp-tools.md` 8 |
| Escrituras idempotentes con `idempotency_key` (`iniciar_disputa`, `bloquear_tarjeta`, `escalar_a_analista`). | `mcp-tools.md` 9 |
| Listados con rango de fechas obligatorio y tope de resultados. | `mcp-tools.md` 10 |
| Un cambio de esquema actualiza spec y test de contrato en el mismo cambio; uno incompatible requiere nombre o versión nueva. | `mcp-tools.md` 11 |
| stdio: nada a `stdout` salvo el protocolo; logs JSON a `stderr`. | `mcp-tools.md` 12 |
| El cliente MCP valida cada respuesta contra el esquema; salida inválida ⇒ error de dominio ⇒ escalar. Reintentos con timeout y tope, solo si `retryable=true`. | `mcp-client.md` 2, 4 |
| El texto devuelto por una herramienta es dato, no instrucción: no puede alterar `DisputePolicy`. | `mcp-client.md` 6 |

## 6. Seguridad y auditoría

| Decisión | Fuente |
|---|---|
| Identificación antes que información: nada de datos de cliente sin `verificar_identidad` exitoso; `buscar_cliente` solo localiza. Se valida en agente **y** servidor (defensa en profundidad). | Art. 7, `mcp-client.md` 3 |
| Auditoría de cada llamada, decisión y escalamiento con `conversation_id`, marca de tiempo, entrada, salida, regla y motivo. | Art. 8 |
| PII enmascarada en logs, respuestas y resúmenes; secuencias de 13–19 dígitos pasan a `[REDACTED]`. | `agent-behavior.md` 16; spec 006, 007 |
| La auditoría del agente nunca guarda el texto del asistente ni de la cliente, solo intención, herramientas, regla y motivo. | spec 007 RN-007-28/36/42 |

## 7. Comportamiento del agente (`agent-behavior.md`)

| Decisión | Fuente |
|---|---|
| El loop continúa mientras `stop_reason == "tool_use"` y termina en `end_turn`; nunca por conteo fijo ni buscando palabras. Razón inesperada ⇒ salida inválida ⇒ escalar. | `agent-behavior.md` 1 |
| El tope de iteraciones es solo red de seguridad (8 llamadas al LLM por mensaje, configurable); al alcanzarlo se escala. | `agent-behavior.md` 2; spec 007 |
| Todo `tool_use` recibe su `tool_result` en el mismo turno, incluso bloqueado o fallido. | `agent-behavior.md` 3 |
| Reglas críticas se imponen con **guardas deterministas en código**, no con prompt; una guarda que bloquea devuelve error `blocked` auditado. Toda regla nueva se prueba con un `FakeLLM` que la viola. | `agent-behavior.md` 4–6 |
| Varias coincidencias: pedir otro identificador, nunca elegir; el LLM solo recibe el número de coincidencias. Sin resultados: reintentar y, tras el tope, escalar. | `agent-behavior.md` 7–8 |
| Multi-asunto: cada asunto por su vía, respuesta única y unificada; un asunto escalado no bloquea los demás. | `agent-behavior.md` 9–10 |
| Escalar solo si el cliente lo pide, el monto supera el umbral o la política no es concluyente; lo decide `DisputePolicy` o una guarda, con `EscalationReason`. Tras escalar, la conversación se cierra. | `agent-behavior.md` 11–13 |
| Handoff: el analista no ve la conversación; el resumen lo construye `EscalationService` (no el LLM), con cliente (solo id), transacciones, acciones previas, causa y acción recomendada. | `agent-behavior.md` 14–16 |
| Cada herramienta del LLM describe cuándo usarla y cuándo no. | `agent-behavior.md` 17–18 |
| Errores en cuatro categorías: transitorio (reintento con tope), validación, negocio, permisos; los irrecuperables escalan sin detalle interno. | `agent-behavior.md` 19–20 |

## 8. Política de tests

| Decisión | Fuente |
|---|---|
| El LLM nunca se llama en la suite por defecto; se usa `FakeLLM` guionizado. Pruebas con Claude real con `@pytest.mark.llm`, excluidas por defecto. | §5.3.1–2 |
| `DisputePolicy` con tests parametrizados (una fila por regla, incluidos casos límite). Todo caso que deba escalar tiene test. | §5.3.3–4 |
| Se testean invariantes: sin identificación previa, decisiones no ejecutables, límite del loop. | §5.3.5 |
| Determinismo: `Clock` inyectado, sin aleatoriedad sin semilla; datos con builders en `tests/fakes/`. | §5.3.6–7 |
| Cada herramienta: test de contrato en ambos lados y casos obligatorios (feliz, inválida, sin identidad, no encontrado, error no recuperable). | `mcp-testing.md` 1–2 |
| Nombrado `test_<tool>__<condition>__<expected>` y comentario de trazabilidad `Regla:` + `AC-NNN-XX · Art. N`; sin ellos no pasa revisión. | `mcp-testing.md` 3–4 |
| Snapshot de catálogo que falla ante herramientas no declaradas. | `mcp-testing.md` 7 |

## 9. Decisiones por feature

### 001 — Búsqueda de cliente (`buscar_cliente`)
| Decisión | Fuente |
|---|---|
| Alcance: solo el servidor MCP; agente y escalamiento fuera. | spec 001 §9 |
| Más de 5 coincidencias: respuesta exitosa con `customers = []` y `refinement_required = true` (no es error). | RN-001-07 |
| Datos mínimos: `customer_id`, nombre, documento enmascarado (2 últimos caracteres) y tarjetas `**** NNNN`. | RN-001-08/09 |
| Nombre "completo" = nombre registrado normalizado (acentos, mayúsculas, espacios); los parciales no coinciden. Documento: comparación exacta recortada, sin distinguir mayúsculas. | RN-001-02/03 |
| `card_last4` considera todas las tarjetas en cualquier estado. Longitudes máx.: documento 32, nombre 100 (`INVALID_INPUT`). | RN-001-04/05 |
| Riesgo aceptado: se sustituye el `FuncMetadata` de FastMCP (API privada) para conservar `outputSchema` con `isError=true`; decisión del usuario 2026-10-16, protegida por tests. | plan 001 §7 |
| Auditoría a `stderr`, sin `print`, para no romper stdio. | plan 001 §7 |

### 002 — Verificación de identidad (`verificar_identidad`)
| Decisión | Fuente |
|---|---|
| Verificación no exitosa = respuesta exitosa `{verified, attempts_remaining, escalation_required}`; errores solo `INVALID_INPUT` e `INTERNAL`. Límite de 3 intentos. | spec 002 §9; plan §7 |
| Estado de verificación en memoria del proceso MCP, sin expiración ni persistencia. | RN-002-09 |
| `INVALID_INPUT` no consume intentos. Fechas intercambiadas (expedición anterior al nacimiento) son `INVALID_INPUT` (prevalece la validación; confirmado por el usuario). | RN-002-07 |
| Conversación ya verificada: otro cliente ⇒ `verified=false` sin contar; mismo cliente con fechas erróneas ⇒ `verified=true` sin evaluar. | RN-002-10/11 |
| "Hoy" en `America/Bogota` desde el reloj inyectado; fechas ISO `AAAA-MM-DD`; las fechas nunca llegan a auditoría ni respuesta. | RN-002-08/14/15 |
| Sin migraciones: ante cambios de esquema se borra `data/core_banking.db` (datos ficticios, ignorada por git). | plan 002–007 §7 |

### 003 — Transacciones (`consultar_transacciones`)
| Decisión | Fuente |
|---|---|
| `card_id` opaco del core (no derivado del número) además de `masked_card`. | RN-003-12 |
| `amount` como texto decimal con 2 decimales y `currency` ISO 4217. | RN-003-12 |
| Rango por fecha local `America/Bogota`; orden descendente por `occurred_at` y luego `transaction_id`; máximo 90 días, sin límite al pasado, fin no posterior a hoy. | RN-003-05/06/11 |
| Tarjeta ajena o inexistente: `NOT_FOUND` con el mismo mensaje (no revela existencia). Orden de errores: validación → identidad → tarjeta. | RN-003-04/08 |
| Transacción reversada conserva el monto positivo; se indica con `status = REVERSED`. | RN-003-09 |
| Una sola instancia del almacén de verificación compartida entre herramientas. | plan 003 §7 |

### 004 — Abrir disputa (`iniciar_disputa`)
| Decisión | Fuente |
|---|---|
| Motivo como enum cerrado: `UNRECOGNIZED_CHARGE`, `DUPLICATE_CHARGE`, `INCORRECT_AMOUNT`, `NOT_RECEIVED`, `OTHER`. | RN-004-02 |
| Disputa abierta ya existente: `DISPUTE_ALREADY_OPEN` con el `dispute_id` en `message`. | RN-004-07 |
| Clave de reintento única por conversación; misma clave con otros datos ⇒ `INVALID_INPUT`. Orden: validación → identidad → clave → transacción del cliente → confirmada → disputa abierta. | RN-004-08/10 |
| Se puede disputar una transacción de tarjeta bloqueada o cancelada. | RN-004-04 |
| Índice único parcial para impedir dos disputas `OPEN`; `rollback` ante cualquier excepción. | plan 004 §7 |

### 005 — Bloqueo de tarjeta (`bloquear_tarjeta`)
| Decisión | Fuente |
|---|---|
| Se indica la tarjeta con el `card_id` opaco; motivo enum `FRAUD_SUSPECTED` / `LOST_OR_STOLEN`. | RN-005-01/02 |
| Ya bloqueada: éxito con `already_blocked = true` y datos del bloqueo original (`null` si vino por semilla). Cancelada: `CARD_NOT_BLOCKABLE`. | RN-005-05/06 |
| Mismo patrón de idempotencia que 004. `UPDATE` y `INSERT` en un solo `commit`. | RN-005-07; plan 005 §7 |

### 006 — Escalamiento a analista (`escalar_a_analista`)
| Decisión | Fuente |
|---|---|
| Motivo enum: `FRAUD_SUSPECTED`, `AMOUNT_OVER_THRESHOLD`, `INSUFFICIENT_OR_CONTRADICTORY_INFO`, `INCONCLUSIVE_RULES`, `UNRECOVERABLE_SYSTEM_FAILURE`, `IDENTITY_VERIFICATION_FAILED`, `OTHER`. | RN-006-02 |
| `prior_actions` (`DISPUTE_OPENED`/`CARD_BLOCKED`) con coherencia validada por el servidor. | RN-006-05/06 |
| Resumen con solo `customer_id`, nunca nombre ni documento; nota máx. 300 caracteres con PAN a `[REDACTED]`. | RN-006-07/08 |
| Estado inicial `PENDING`; esta feature nunca lo cambia. | RN-006-08 |
| Excepción parcial a la identificación: derivar sin datos de cliente no exige verificación (la constitución prevalece sobre `mcp-tools.md` §5, que debe actualizarse). | plan 006 §7 |

### 007 — Agente de resolución de disputas
| Decisión | Fuente |
|---|---|
| `merchant_country` (ISO 3166-1; `CO` = nacional) añadido a `TransactionItem`; `cards: [{card_id, masked_card}]` añadido a `buscar_cliente` (cambio compatible). | spec 007 §9 |
| Moneda extranjera: tasa fija configurable, solo USD, 1 USD = 4.000 COP por defecto; otra moneda ⇒ `INCONCLUSIVE_RULES`. | RN-007-09 |
| Sin coincidencias en 2 búsquedas ⇒ `INSUFFICIENT_OR_CONTRADICTORY_INFO`. | RN-007-05/23 |
| La política no depende del motivo; el LLM lo traduce al enum. Una derivación por transacción. | RN-007-10/20 |
| Tras derivar por petición de persona, identidad o falla, la conversación se cierra con mensaje fijo. | RN-007-18/24 |
| El texto del LLM se filtra de forma determinista (13–19 dígitos, documentos). | RN-007-26 |
| (v0.2.0) La fuente de verdad de lo realizado es `outcomes`; el `reply` no se filtra por palabras. Razón de parada incoherente ⇒ `UNRECOVERABLE_SYSTEM_FAILURE`. | RN-007-33/35 |
| (v0.3.0) Antes de verificar, todas las respuestas son textos fijos; nada del LLM llega a la cliente. `INVALID_INPUT` en verificación ⇒ pedir fechas sin contar intento. | RN-007-38/40 |
| (v0.3.0) Si se verifica y pide disputar/declara fraude en el mismo mensaje, se atiende en ese turno (fraude: bloquear y derivar). | RN-007-37/39 |
| El endpoint `POST /api/chat` forma parte de esta feature. | spec 007 §9 |
| Las escrituras nunca las pide el LLM: las ejecuta la aplicación tras `DisputePolicy`. | plan 007 §7 |
| Comportamiento seguro ante razón de parada nueva del SDK: derivar (Art. 10). | plan 007 §7 |

### 008 — Página de chat
| Decisión | Fuente |
|---|---|
| Saludo inicial fijo en la página, sin llamar al backend. | RN-008-03 |
| Pruebas de navegador con navegador real (Playwright/Chromium) dentro de la suite por defecto; dependencia justificada en el plan. | spec 008 §9; plan §7 |
| Aviso de demora a los 60 s; "volver a intentar" reenvía el mismo texto sin duplicar la burbuja. | RN-008-16/17 |
| Solo se muestra `reply`, no `outcomes`. `404` ⇒ conversación cerrada y ofrecer una nueva. | RN-008-10/15 |
| Límite de 2000 caracteres con contador desde los 200 restantes; Enter envía, Shift+Enter salto de línea. | RN-008-05/06 |
| Sin `innerHTML` ni almacenamiento del navegador, impuesto con guardas estáticas. | plan 008 §7 |
| Pruebas con `page.route` y `page.clock`, sin `sleep`; las respuestas tardías se descartan por identificador de intento. | plan 008 §7 |

### 009 — Respuesta en streaming
| Decisión | Fuente |
|---|---|
| El ciclo de 007 decide y actúa sin mostrar nada; al `end_turn`, una llamada de redacción sin herramientas se transmite en vivo. No cuenta para las 8 llamadas. | RN-009-02/03/04 |
| Endpoint nuevo de streaming; `POST /api/chat` queda intacto (se enmienda RN-008-01). | RN-009-01/13 |
| Espera máxima de 30 s sin texto nuevo, configurable. | RN-009-09 |
| Se audita el texto filtrado junto a los `outcomes` para revisión humana, sin detección automática. | RN-009-05/11 |
| Texto parcial conservado y marcado `Incompleto`; `Reintentar` reenvía el mismo mensaje. | RN-009-24 |
| La decisión corre en tarea propia con `asyncio.shield` para que una desconexión no deje acciones a medias. | plan 009 §7 |
| `IncrementalRedactor` retiene texto mientras pueda completarse un número de tarjeta repartido en fragmentos. | plan 009 §7 |
| Coste extra de una llamada al LLM por mensaje aceptado. | plan 009 §7 |
| La página exige solo `conversation_id`, `reply` y `status` en `end`/`interrupted`. | RN-009-23 |

### 010 — Corrección de entradas inválidas
| Decisión | Fuente |
|---|---|
| El `INVALID_INPUT` de `consultar_transacciones` y `buscar_cliente` no es una falla: se devuelve al LLM para corregir, con tope de 2 por mensaje; al agotarse se deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO`. Motivo: incidente ESC-000010 (derivación por un dato mal formado corregible). | spec 010 RN-010-01/03/04 |

### 011 — Guardas de consulta de transacciones
| Decisión | Fuente |
|---|---|
| El agente no consulta con una tarjeta que no es de la clienta (4 dígitos, sin coincidencia con sus tarjetas conocidas): devuelve `unknown_card` al LLM; el `NOT_FOUND` del core deja de derivar y se devuelve como error de negocio; ambos comparten el tope de 2 correcciones. Motivo: conversaciones ESC-000012/ESC-000013 (derivación por tecleo de la tarjeta y rangos de 91 días). El límite de rango se declara como 89 días y el prompt de redacción lleva la fecha actual. | spec 011 RN-011-01/02/03/05/06 |

## 10. Riesgos aceptados y transversales

| Decisión | Fuente |
|---|---|
| Sin migraciones de BD: datos ficticios y reproducibles; se borra `data/core_banking.db` ante cambios de esquema. | plan 002–007 §7 |
| Estado de verificación y conversaciones en memoria (v1); se pierden al reiniciar. | RN-002-09; §3.3 |
| Cambios de `ErrorCode`, `AuditEvent` y esquemas son compatibles (campos opcionales al final). | plan 003–006 §7 |
| `server.py`, `schemas.py`, `tables.py` y `tests/fakes/*` son archivos compartidos al calcular oleadas de tareas paralelas. | plan 004–007 §7 |
