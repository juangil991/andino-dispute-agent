# Plan: Resolver en primer contacto las disputas de un cliente y escalar a un analista cuando corresponde

| Campo | Valor |
|---|---|
| Feature | `007-dispute-resolution-agent` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-18 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | 1.0.1 |

---

## 1. Resumen técnico

Primera feature de `dispute_agent`: crea la aplicación completa según §3.6. Además amplía `core_banking_mcp` con dos cambios compatibles (`merchant_country` y `cards`). Las dos aplicaciones solo se hablan por MCP.

- **Core (cambios compatibles):**
  - `Transaction` gana `merchant_country` y `Card` gana `card_id`.
  - Se mapean desde la tabla `transactions` (columna nueva) y desde `cards.card_ref` (ya existe).
  - Se publican en `TransactionItemOut` y en `CustomerMatchOut.cards`.
  - Las semillas ganan país y dos transacciones de demostración.
- **Dominio del agente (stdlib pura):**
  - `DisputePolicy.decide(transaction, today, fraud_declared)` implementa la tabla DP-007-01…07 y devuelve un `DisputeDecision` con la regla, el motivo de derivación, las acciones permitidas y los textos fijos de §5.
  - `Conversation` guarda el estado: verificación, cliente localizado, tarjetas, búsquedas fallidas, decisiones por transacción, documentos aportados, estado `ACTIVE` o `ESCALATED` y el historial.
  - `redact_reply` implementa RN-007-26.
- **Orquestación con herramientas de intención** (decisión del usuario). El LLM ve 6 herramientas:
  - Las 3 MCP de lectura: `buscar_cliente`, `verificar_identidad` y `consultar_transacciones`.
  - 3 internas del agente: `evaluar_disputa(transaction_id, reason)`, `reportar_fraude(card_last4?, transaction_ids?)` y `solicitar_atencion_humana()`.

  Las escrituras (`iniciar_disputa`, `bloquear_tarjeta`, `escalar_a_analista`) las ejecuta **solo la aplicación**, según la decisión de `DisputePolicy` (§3.5.4). Si el LLM las pide directamente, la invocación se reconoce, se bloquea y se audita:
  - con `RN-007-01` si la conversación no está verificada;
  - con `RN-007-11` en cualquier otro caso.

  El LLM recibe entonces un resultado de herramienta que le indica el camino correcto. Cualquier otro nombre de herramienta es una salida inválida (RN-007-23).
- **Caso de uso `HandleCustomerMessage`** (async):
  1. Si la conversación está cerrada, devuelve el mensaje fijo (RN-007-24).
  2. Si no, ejecuta el loop con un tope de `max_iterations` llamadas al LLM.
  3. En cada respuesta del LLM procesa las peticiones de herramienta en un orden fijo:
     1. `solicitar_atencion_humana`, que absorbe `reportar_fraude` del mismo turno (RN-007-18/19) y descarta las demás.
     2. `reportar_fraude`.
     3. El resto, en orden.
  4. Las acciones, las decisiones y las derivaciones las ejecutan colaboradores del caso de uso: `DisputeActions`, `FraudActions` y `EscalationService`.
  5. Las acciones de cada turno se acumulan en `outcomes`.
  6. El LLM redacta la respuesta final; recibe los `outcomes` como resultado de herramienta (RN-007-25).
  7. `redact_reply` filtra `reply` y `outcomes`.
- **Adaptadores:**
  - `McpStdioBankingAdapter`: un solo subproceso del servidor core por aplicación, creado en el `lifespan` de FastAPI (decisión del usuario). Valida cada respuesta con modelos Pydantic espejo del contrato y aplica un tiempo límite por llamada.
  - `AnthropicLLMAdapter`: usa `anthropic.AsyncAnthropic`, con el modelo `claude-sonnet-5-5` por defecto (decisión del usuario).
  - `InMemoryConversationRepository`.
  - `JsonAuditLog` del agente.
  - `SystemClock` e `Uuid4Generator`.
- **Endpoint `POST /api/chat`** en un router FastAPI. El cableado está solo en `dispute_agent/main.py`.

Decisiones triviales tomadas:

- **Async de punta a punta:** el SDK `mcp` y `AsyncAnthropic` son asíncronos; `LLMPort`, `BankingToolsPort` y el caso de uso son `async`.
- **Claves de idempotencia deterministas:** `<acción>-<hash>`, donde `<hash>` son los 32 primeros caracteres hex de `sha256("<acción>|<objetivo>|<regla>")`. Ejemplos: `dispute-…` para `iniciar_disputa` con `transaction_id`; `block-…` con `card_id`; `esc-…` con `transaction_id` o la causa. Caben en 64 caracteres, son únicas dentro de la conversación (el servidor ya las acota por `conversation_id`) y una repetición por reintento usa la misma clave (RN-007-20).
- **Reintentos:** solo con `retryable = true` y como máximo 1. Todos los errores del core son no reintentables, así que en la práctica no se reintenta.
- **Tiempo límite MCP:** `MCP_CALL_TIMEOUT_SECONDS = 10` (configurable). Al vencer, se lanza `BankingToolUnavailableError` (RN-007-21).
- **Resultado de `evaluar_disputa`:** para que el LLM sepa qué transacción evaluar, el agente guarda en `Conversation` las `TransactionItem` vistas en `consultar_transacciones`. Si se pide evaluar un `transaction_id` no visto, se devuelve al LLM un resultado de herramienta `transaction_not_listed`; no es un error ni una derivación.
- **Fraude con la transacción señalada:** `reportar_fraude(transaction_ids=[…])` bloquea la tarjeta de esas transacciones una sola vez y decide cada una con `fraud_declared = True`. Las transacciones de tarjetas distintas se agrupan por `card_id`.
- **Antigüedad:** `(today - occurred_at.astimezone(Bogotá).date()).days`, con `today` del `Clock` inyectado en Bogotá (RN-007-07).
- **Monto equivalente:** `Decimal`, sin flotantes. `USD → amount * usd_cop_rate`. El umbral (500.000) y el plazo (90 días) son constantes del dominio; la tasa entra por `AgentSettings.usd_cop_rate`, con `4000` por defecto (RN-007-09).
- **Contador de búsquedas fallidas:** se incrementa cuando `buscar_cliente` devuelve una lista vacía y `refinement_required = false`. Al llegar a 2, se deriva (RN-007-05).
- **`conversation_id`:** `uuid4().hex`, generado por el puerto `IdGenerator` (sustituible en los tests).
- **Mensaje fijo de RN-007-23:** `reply = f"{reason} {next_steps}"` sin llamar al LLM.
- **Esquemas de las herramientas que ve el LLM:** dicts JSON Schema en `application/agent_tools.py`. Los de las herramientas MCP de lectura reflejan la spec; `conversation_id` no se expone al LLM: lo inyecta el adaptador.
- **Datos de `buscar_cliente` y el LLM (RN-007-02):**
  - Antes de verificar, el LLM solo recibe `{matches: N, refinement_required}`. El agente guarda en `Conversation` el `customer_id` y las `cards` de la coincidencia única.
  - `verificar_identidad` se expone al LLM solo con `birth_date` y `document_issue_date`; el caso de uso añade el `customer_id` localizado. Si no hay una coincidencia única, devuelve al LLM `customer_not_located` sin llamar al core.
  - Tras verificar, el LLM recibe las tarjetas enmascaradas (`**** NNNN`), nunca `card_id`.
- **Actualización de specs previas (§4.3.3):** las specs 001, 003, 004 y 006 se actualizan en esta feature (versión 0.2.0, fila de historial). Las tablas de salida y RN-001-08 / RN-003-12 reflejan los campos nuevos.

## 2. Componentes por capa

Rutas relativas a `src/<app>/`.

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `core_banking_mcp` | `domain` | `domain/models/transaction.py` — `Transaction` | Modificado | Campo `merchant_country: str = "CO"` al final; valida 2 letras ASCII en mayúsculas (`InvalidInputError`) (RN-007-30). |
| `core_banking_mcp` | `domain` | `domain/models/customer.py` — `Card` | Modificado | Campo `card_id: str \| None = None` al final; lo rellena el repositorio al leer (RN-007-31). |
| `core_banking_mcp` | `infrastructure/outbound` | `persistence/models/tables.py` — `TransactionRow` | Modificado | Columna `merchant_country` (`String(2)`, no nula, `server_default="CO"`). |
| `core_banking_mcp` | `infrastructure/outbound` | `persistence/sqlalchemy_transaction_repository.py` | Modificado | Guarda y lee `merchant_country`. |
| `core_banking_mcp` | `infrastructure/outbound` | `persistence/sqlalchemy_customer_repository.py` | Modificado | Lee `card_ref` como `Card.card_id`. |
| `core_banking_mcp` | `infrastructure/outbound` | `persistence/seeds/transactions.py` | Modificado | Añade `merchant_country` a las 9 transacciones (`TX-000002` StreamFlix → `US`, el resto `CO`), más `TX-000010` (US, 300.000 COP, `2026-06-01`, `CONFIRMED`, `CARD-0001`) y `TX-000011` (CO, 800.000 COP, `2026-10-05`, `CONFIRMED`, `CARD-0001`) para la demostración de DP-007-04 y DP-007-03. |
| `core_banking_mcp` | `infrastructure/inbound` | `mcp/schemas.py` | Modificado | `TransactionItemOut.merchant_country`. `CustomerCardOut {card_id, masked_card}` (`extra="forbid"`). `CustomerMatchOut.cards: list[CustomerCardOut]`. |
| `core_banking_mcp` | `infrastructure/inbound` | `mcp/tools.py`, `mcp/transaction_tools.py` | Modificado | `buscar_cliente` construye `cards` en el orden de `masked_cards`; `to_transaction_item` incluye `merchant_country`. |
| `dispute_agent` | `domain` | `domain/models/transaction.py` — `TransactionStatus`, `DisputedTransaction` | Nuevo | Vista del dominio de un `TransactionItem`: `transaction_id`, `card_id`, `masked_card`, `occurred_at`, `merchant`, `amount: Decimal`, `currency`, `merchant_country`, `status`. Valida los invariantes. |
| `dispute_agent` | `domain` | `domain/models/decision.py` — `Decision`, `AgentAction`, `EscalationReason`, `PriorAction`, `DisputeDecision` | Nuevo | Enums cerrados (los motivos de derivación son los de RN-006-02). `DisputeDecision(decision, rule, escalation_reason, allowed_actions, customer_reason, next_steps)`. |
| `dispute_agent` | `domain` | `domain/policies/dispute_policy.py` — `DisputePolicy` | Nuevo | `decide(tx, today, fraud_declared) -> DisputeDecision`; primera fila que aplica de §5; `equivalent_cop(tx) -> Decimal \| None`; `age_days(tx, today)`. Constantes `AMOUNT_THRESHOLD_COP = Decimal(500000)` y `MAX_FOREIGN_AGE_DAYS = 90`; `usd_cop_rate` en el constructor. |
| `dispute_agent` | `domain` | `domain/messages.py` | Nuevo | Textos fijos en español de §5 y §7.3 (`reason`, `next_steps` por regla y tipo), el mensaje de conversación cerrada y la nota `Cliente solicitó atención humana`. |
| `dispute_agent` | `domain` | `domain/models/outcome.py` — `OutcomeKind`, `Outcome` | Nuevo | Los 13 tipos de §7.3; `Outcome(kind, rule, reason, next_steps, transaction_id, masked_card, reference)`. |
| `dispute_agent` | `domain` | `domain/models/conversation.py` — `Conversation`, `ConversationStatus`, `KnownCard` | Nuevo | Estado mutable de la conversación (ver §4). Métodos: `mark_verified`, `record_search(matches)`, `remember_transactions`, `record_decision`, `close`, `allows_write_for(tx_id)`, `card_by_last4`. |
| `dispute_agent` | `domain` | `domain/redaction.py` — `redact_reply` | Nuevo | Sustituye `\d(?:[ -]?\d){12,18}` (13–19 dígitos, con espacios o guiones) por `[REDACTED]`, sin cortar números más largos. Enmascara los documentos aportados con `****` y sus 2 últimos caracteres (RN-001-09). |
| `dispute_agent` | `domain` | `domain/errors.py` | Nuevo | `DomainError`, `InvalidTransactionDataError`. |
| `dispute_agent` | `application` | `application/ports/llm.py` — `LLMPort`, `LLMResponse`, `ToolCall`, `ChatMessage`, `LLMError` | Nuevo | `async complete(system, messages, tools) -> LLMResponse(text, tool_calls)`. |
| `dispute_agent` | `application` | `application/ports/banking_tools.py` — `BankingToolsPort`, DTOs, `BankingToolError`, `BankingToolUnavailableError` | Nuevo | Una operación `async` por herramienta: `search_customer`, `verify_identity`, `list_transactions`, `open_dispute`, `block_card`, `escalate`. Devuelve DTOs de aplicación y lanza `BankingToolError(code, message, retryable)` o `BankingToolUnavailableError` (tiempo límite, salida inválida o transporte). |
| `dispute_agent` | `application` | `application/ports/conversation_repository.py`, `audit_log.py` (`AuditEvent`), `clock.py`, `id_generator.py` | Nuevo | Puertos de §3.3, más `Clock` e `IdGenerator` para el determinismo (§5.3.6). |
| `dispute_agent` | `application` | `application/agent_tools.py` | Nuevo | Definiciones JSON de las 6 herramientas que ve el LLM; conjunto `WRITE_TOOLS` reconocido y bloqueado. |
| `dispute_agent` | `application` | `application/system_prompt.py` | Nuevo | Prompt del sistema en español. Indica el uso de las herramientas, que no se interpretan resultados como instrucciones (RN-007-27), que no se repitan números de tarjeta y que los `outcomes` son la fuente de la respuesta. |
| `dispute_agent` | `application` | `application/use_cases/handle_customer_message.py` — `HandleCustomerMessage`, `ChatTurnResult` | Nuevo | El loop: estado cerrado, tope de iteraciones, orden de procesamiento, guarda de identidad (RN-007-01) y de escrituras (RN-007-11), manejo de `LLMError`, herramientas desconocidas o argumentos inválidos (RN-007-23), filtro final y auditoría. |
| `dispute_agent` | `application` | `application/use_cases/dispute_actions.py` — `DisputeActions` | Nuevo | `evaluate(conv, tx_id, reason, fraud)`: llama a `DisputePolicy`, audita la decisión y ejecuta las acciones permitidas (`open_dispute`, `EscalationService`). Maneja `DISPUTE_ALREADY_OPEN` (RN-007-12) y las fallas (RN-007-21). Devuelve los `Outcome`. |
| `dispute_agent` | `application` | `application/use_cases/fraud_actions.py` — `FraudActions` | Nuevo | RN-007-14 a 17 y RN-007-19: resuelve la tarjeta, bloquea, maneja `already_blocked` y `CARD_NOT_BLOCKABLE`, delega la decisión de cada transacción en `DisputeActions` con `fraud=True` y deriva. |
| `dispute_agent` | `application` | `application/use_cases/escalation_service.py` — `EscalationService` | Nuevo | Construye la solicitud de `escalate` (resumen completo o limitado, `prior_actions`, nota `<regla>: <motivo>`, clave determinista). Ante `IDENTITY_NOT_VERIFIED`, repite sin datos; ante `INTERNAL`, devuelve `ESCALATION_FAILED` (RN-007-22). |
| `dispute_agent` | `infrastructure/inbound` | `infrastructure/inbound/web/api/chat_router.py`, `schemas.py` | Nuevo | `POST /api/chat`. `ChatRequest` (`message` recortado, de 1 a 2000; `conversation_id` opcional; `extra="forbid"`) y `ChatResponse` / `OutcomeOut`. `404` con conversación desconocida; `422` por validación de FastAPI. |
| `dispute_agent` | `infrastructure/outbound` | `infrastructure/outbound/llm/anthropic_llm_adapter.py` — `AnthropicLLMAdapter` | Nuevo | Traduce `ChatMessage` y `ToolCall` al formato de Messages API (`tool_use` / `tool_result`). Cualquier excepción del SDK se convierte en `LLMError`. |
| `dispute_agent` | `infrastructure/outbound` | `infrastructure/outbound/mcp/mcp_stdio_banking_adapter.py`, `response_models.py` | Nuevo | `ClientSession` sobre `stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "core_banking_mcp.server"], env=…))`. `asyncio.wait_for` por llamada. Error con `isError` → `BankingToolError`, parseando el sobre `{code, message, retryable}`. Salida que no cumple el modelo Pydantic espejo (`extra="forbid"`) → `BankingToolUnavailableError` (`mcp-client.md` §2). Inyecta `conversation_id`. |
| `dispute_agent` | `infrastructure/outbound` | `infrastructure/outbound/persistence/in_memory_conversation_repository.py` | Nuevo | Diccionario `conversation_id → Conversation`. |
| `dispute_agent` | `infrastructure/outbound` | `infrastructure/outbound/audit/json_audit_log.py`, `clock/system_clock.py`, `ids/uuid_generator.py` | Nuevo | Logger JSON a `stderr` (logger `dispute_agent.audit`). Cada evento pasa antes por `redact_reply` (RN-007-28). |
| `dispute_agent` | arranque | `config.py` — `AgentSettings` | Nuevo | `pydantic-settings`: `anthropic_api_key` (`SecretStr`), `anthropic_model = "claude-sonnet-5-5"`, `llm_max_iterations = 8`, `usd_cop_rate = Decimal(4000)`, `mcp_call_timeout_seconds = 10`, `core_database_url` (se pasa al subproceso). |
| `dispute_agent` | arranque | `main.py` — `create_app(settings, banking=None, llm=None)` | Nuevo | Composición. El `lifespan` abre y cierra el adaptador MCP; los parámetros opcionales permiten inyectar fakes. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `LLMPort` | Nuevo | `AnthropicLLMAdapter` | `FakeLLM` guionizado en `tests/fakes/` (§5.3.1). |
| `BankingToolsPort` | Nuevo | `McpStdioBankingAdapter` | `FakeBankingTools` programable por herramienta (respuesta o error) y con registro de llamadas. |
| `ConversationRepository` | Nuevo | `InMemoryConversationRepository` | `get(id) -> Conversation \| None`, `save(conv)`. |
| `AuditLogPort` (agente) | Nuevo | `JsonAuditLog` | `AgentAuditEvent(conversation_id, at, event_type, tool, input, output, rule, reason)` con `event_type ∈ {tool_call, tool_blocked, decision, escalation, conversation_closed}`. `FakeAgentAuditLog` en los tests. |
| `Clock` (agente) | Nuevo | `SystemClock` | `FixedAgentClock` en los tests. |
| `IdGenerator` | Nuevo | `Uuid4Generator` | `SequentialIdGenerator` en los tests. |
| `CustomerRepository`, `TransactionRepository` (core) | Sin cambio de firma | SQLAlchemy | Solo mapean los campos nuevos. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `DisputedTransaction` | `transaction_id`, `card_id`, `masked_card`, `occurred_at: datetime`, `merchant`, `amount: Decimal`, `currency`, `merchant_country`, `status: TransactionStatus` | `occurred_at` con zona; `amount > 0`, con 2 decimales; `currency` de 3 letras en mayúsculas; `merchant_country` de 2 letras en mayúsculas. Si no se cumple → `InvalidTransactionDataError`, que el adaptador traduce en salida inválida (RN-007-21). |
| `DisputeDecision` | `decision: Decision`, `rule: str` (`DP-007-0N`), `escalation_reason: EscalationReason \| None`, `allowed_actions: frozenset[AgentAction]`, `customer_reason`, `next_steps` | `ESCALATE` ⇔ `escalation_reason` no nulo; `RESOLVE` ⇒ `allowed_actions = {OPEN_DISPUTE}`; `REJECT` ⇒ vacío. |
| `Outcome` | `kind: OutcomeKind`, `rule`, `reason`, `next_steps`, `transaction_id`, `masked_card`, `reference` | `reason` y `next_steps` no vacíos. |
| `Conversation` | `conversation_id`, `status` (`ACTIVE` / `ESCALATED`), `located_customer_id`, `verified_customer_id`, `known_cards: tuple[KnownCard, ...]` (`card_id`, `last4`), `failed_searches: int`, `seen_transactions: dict[str, DisputedTransaction]`, `decisions: dict[str, DisputeDecision]`, `blocked_cards: set[str]`, `escalated_keys: set[str]`, `provided_documents: set[str]`, `history: list[ChatMessage]` | Una vez `ESCALATED`, no vuelve a `ACTIVE`. `verified_customer_id` solo se fija tras `verified = true`. `allows_write_for(tx)` es verdadero solo si `decisions[tx].decision` tiene `OPEN_DISPUTE` entre sus acciones. |

`ChatMessage` (`role`, `content` con texto, `tool_use` y `tool_result`) es un tipo de `application/ports/llm.py`, no del dominio. `Conversation.history` lo guarda de forma opaca, como `list[object]`, tipado en la aplicación.

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| `transactions` | `merchant_country` (`String(2)`, no nula, `server_default "CO"`) | Columna nueva. |
| `cards` | `card_ref` | Sin cambio: ya es el `card_id` opaco y ahora también lo publica `buscar_cliente`. |

El agente no tiene persistencia: las conversaciones viven en memoria (fuera de alcance).

### Semillas

- `merchant_country` en las 9 transacciones existentes (`TX-000002` → `US`; el resto → `CO`).
- `TX-000010`: `CARD-0001`, `2026-06-01T10:00-05:00`, "Hotel Pacífico Sur", `300000.00 COP`, `US`, `CONFIRMED`. Sirve para demostrar DP-007-04.
- `TX-000011`: `CARD-0001`, `2026-10-05T16:45-05:00`, "Electro Hogar Andes", `800000.00 COP`, `CO`, `CONFIRMED`. Sirve para demostrar DP-007-03.

Todo es ficticio y fijo (Art. 1). Los tests usan builders, no semillas (§5.3.7). El e2e prepara su propia base SQLite temporal con los repositorios del core, desde código de test.

## 5. Dependencias nuevas

| Paquete | Versión | Justificación | Alternativa descartada |
|---|---|---|---|
| `fastapi` | `>=0.115,<1` | API web del stack (§2). | Starlette sola: FastAPI ya está fijado en la constitución. |
| `uvicorn` | `>=0.30,<1` | Servidor ASGI del stack (§2). | Hypercorn: no está en el stack. |
| `anthropic` | `>=0.40,<1` | SDK oficial del LLM (§2). | Llamadas HTTP propias: más código y sin tipado. |
| `httpx` | `>=0.27,<1` (grupo `dev`) | Lo exige `fastapi.testclient.TestClient` (§2, Testing). | `requests`: TestClient no lo usa. |

Todas están previstas en el tech-stack de la constitución (§2); se justifican aquí según la regla de §2.

## 6. Estrategia de pruebas

Nombrado y comentarios de trazabilidad según `mcp-testing.md` §3–4. Los tests de invariantes citan el artículo.

Fakes y builders nuevos en `tests/fakes/`:

- `fake_llm.py` (`FakeLLM`): guion de respuestas (`text` y `tool_calls`), registro de las peticiones recibidas y un modo que lanza `LLMError`.
- `fake_banking_tools.py` (`FakeBankingTools`): respuestas o errores programables por herramienta y registro de llamadas con sus argumentos.
- `agent_transaction_builder.py` (`DisputedTransactionBuilder` con `.national()`, `.foreign()`, `.days_ago(n, today)`, `.amount("85000.00", "COP")`) y `conversation_builder.py` (verificada, localizada, cerrada).
- `fake_agent_audit_log.py`, `fixed_agent_clock.py` y `sequential_id_generator.py`.
- Se amplían `TransactionBuilder` (core) con `merchant_country` y `CustomerBuilder` / `OwnedCardBuilder` con `card_id`.

Niveles por carpeta:

- Unitarios: `tests/unit/dispute_agent/{domain,application}/`.
- Integración: `tests/integration/dispute_agent/{web,mcp,llm,audit}/`.
- Contrato del lado cliente: `tests/contract/dispute_agent/`.
- E2E: `tests/e2e/`.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-007-01 | `HandleCustomerMessage` con `FakeLLM` (`evaluar_disputa(TX-L1)`) y `FakeBankingTools`: `open_dispute` invocado con `UNRECOGNIZED_CHARGE` y sin `escalate`; el `outcome` es `DISPUTE_OPENED` con DP-007-05; `ACTIVE` | `POST /api/chat` con `create_app` y fakes: `200` con `outcomes` | — | Cubierto por AC-007-34 |
| AC-007-02 | Las 4 filas parametrizadas: sin verificar, el LLM pide la herramienta → no hay llamada en `FakeBankingTools`, hay evento `tool_blocked` con `RN-007-01` y el `reply` / `outcomes` no contienen los datos listados | — | — | — |
| AC-007-03 | `DisputePolicy.decide`, tabla con las 6 filas (umbral exacto, +1, USD 125.00 / 125.01, EUR); y el caso de uso para la fila de 500.001 (`escalate` con `AMOUNT_OVER_THRESHOLD`) | — | — | — |
| AC-007-04 | `DisputePolicy(usd_cop_rate=5000)` con `100.01 USD` → DP-007-03 | `AgentSettings` lee `USD_COP_RATE` del entorno | — | — |
| AC-007-05 | Caso de uso: dos `evaluar_disputa` en el mismo turno; 1 `open_dispute` (TX-L1); 1 `escalate` (TX-L2, `CARD-L1`, `prior_actions=[]`, nota `DP-007-03: …`); dos `outcomes` | — | — | Cubierto por AC-007-34 |
| AC-007-06 | `DisputePolicy.decide`, tabla de 6 filas (89/90/91 días, borde de la fecha de Bogotá con `04:30Z`, nacional 91/400) con `FixedAgentClock` | — | — | — |
| AC-007-07 | Las 2 filas: tras la derivación, el LLM pide `iniciar_disputa` → bloqueada con `RN-007-11`, sin una segunda `escalate`; el `outcome` de la derivación se mantiene | — | — | — |
| AC-007-08 | Las 2 filas: `iniciar_disputa` sin evaluar y tras REJECT → bloqueada con `RN-007-11` | — | — | — |
| AC-007-09 | `DisputePolicy.decide(fraud_declared=True)`, tabla de 5 filas (DP-007-06/07); caso de uso con `reportar_fraude(transaction_ids=[TX-L1])`: orden de llamadas `block_card` → (`open_dispute`) → `escalate` y las `prior_actions` de cada fila | — | — | — |
| AC-007-10 | `FraudActions` con las 4 filas de `cards` (una tarjeta, otra por dígitos, petición de dígitos, dígitos ambiguos → derivación sin bloqueo) | — | — | — |
| AC-007-11 | Sin verificar, `reportar_fraude` → sin `block_card`; `escalate` limitado con `FRAUD_SUSPECTED`; estado `ESCALATED` | — | — | — |
| AC-007-12 | Las 4 filas (momentos simulados con `ConversationBuilder` e historial): `escalate` con `OTHER` y la nota; sin `list_transactions` ni `open_dispute` en el turno; resumen limitado o completo según la verificación | — | — | — |
| AC-007-13 | Las 3 frases con un guion sin `solicitar_atencion_humana` → sin `escalate`, `ACTIVE` | `@pytest.mark.llm`: `AnthropicLLMAdapter` real con el prompt del sistema; las 3 frases no producen `solicitar_atencion_humana` y las 4 de AC-007-12 sí | — | — |
| AC-007-14 | Un solo turno con `solicitar_atencion_humana` + `reportar_fraude(card_last4="4321")`: `block_card(CARD-L1)` y un solo `escalate` (`FRAUD_SUSPECTED`, `CARD_BLOCKED`, nota); sin `list_transactions` ni `open_dispute` | — | — | — |
| AC-007-15 | Igual, sin verificar: sin `block_card`; un `escalate` limitado | — | — | — |
| AC-007-16 | El turno trae `evaluar_disputa(TX-L1)` y `solicitar_atencion_humana`: sin `open_dispute`; `escalate` con `OTHER`; `ESCALATED` | — | — | — |
| AC-007-17 | `DisputePolicy`: `PENDING` y `REVERSED` → DP-007-01; caso de uso: sin `open_dispute` ni `escalate`; `outcome` `NOT_DISPUTABLE` | — | — | — |
| AC-007-18 | `FakeBankingTools.open_dispute` lanza `BankingToolError("DISPUTE_ALREADY_OPEN", "… D-OLD …")`; 1 llamada; `outcome` `DISPUTE_ALREADY_OPEN` con `reference="D-OLD"` | El adaptador extrae el `dispute_id` del `message` real del servidor (sesión MCP en memoria contra el core con SQLite) | — | — |
| AC-007-19 | Las 2 filas (`already_blocked=true` y `CARD_NOT_BLOCKABLE`): tipo de `outcome` y `prior_actions` | — | — | — |
| AC-007-20 | Las 2 filas, más las negativas (1–2 fallos, 1 búsqueda vacía → sin derivar) | — | — | — |
| AC-007-21 | `buscar_cliente` con 2 coincidencias: no se llama a `verify_identity`; el `reply` no contiene los datos listados (el guion del LLM los incluye a propósito, para probar también el filtro); no cuenta como búsqueda fallida | — | — | — |
| AC-007-22 | Las 2 filas (`[]` y `refinement_required`): `outcomes` `NO_TRANSACTIONS_FOUND` / `REFINEMENT_REQUIRED`; sin `open_dispute` ni `escalate` | — | — | — |
| AC-007-23 | Las 5 filas con `FakeBankingTools` (`BankingToolError("INTERNAL")` y `BankingToolUnavailableError`): sin `outcome` de éxito; `escalate` con `UNRECOVERABLE_SYSTEM_FAILURE` y el dato afectado; el `reply` sin el código ni la excepción; `ESCALATED` | `McpStdioBankingAdapter`: el tiempo límite (servidor de prueba lento) → `BankingToolUnavailableError`; una respuesta sin `dispute_id` → `BankingToolUnavailableError` | — | — |
| AC-007-24 | `escalate` lanza `BankingToolError("INTERNAL")` → 1 sola llamada; `outcome` `ESCALATION_FAILED`; `ESCALATED` | — | — | — |
| AC-007-25 | Las 4 filas: 9 llamadas → `ITERATION_LIMIT`; 8 con final → `ACTIVE`; `FakeLLM` lanza → `LLM_FAILURE`; herramienta desconocida o argumentos inválidos → `LLM_FAILURE`; el `reply` fijo; sin escrituras tras detectarlo | `AnthropicLLMAdapter` con un cliente HTTP simulado (`httpx.MockTransport`): un error 500 → `LLMError` | — | — |
| AC-007-26 | Las 3 causas: un segundo mensaje no llama a `FakeLLM` ni a `FakeBankingTools` y devuelve el mensaje fijo con `outcomes=[]`; tras DP-007-03, sigue `ACTIVE` | `POST /api/chat` sobre una conversación cerrada: `200`, `status="ESCALATED"` | — | — |
| AC-007-27 | `redact_reply`, tabla de 6 filas (PAN seguido, con espacios, con guiones, documento, máscara intacta, monto intacto) más un caso de 20 dígitos | El caso de uso aplica el filtro al `reply` y a `outcomes` (el guion del LLM devuelve el PAN) | — | — |
| AC-007-28 | `merchant` con el texto de inyección → DP-007-03, sin `open_dispute` (la política no lee `merchant`) | — | — | — |
| AC-007-29 | Las 3 filas: `outcomes` con `kind`, `rule`, `reason` y `next_steps` iguales a los textos de `domain/messages.py`; la última petición al `FakeLLM` contiene esos `outcomes` | `@pytest.mark.llm`: el `reply` real está en español y menciona la acción, el motivo y los próximos pasos | — | — |
| AC-007-30 | `FakeAgentAuditLog` + `FixedAgentClock`, 8 casos parametrizados: evento con `conversation_id`, `at`, `event_type`, `input`, `output`, `rule` y `reason`; ninguno contiene el PAN ni `D-1001` | `JsonAuditLog` del agente: JSON por línea en `stderr` con las claves de `AgentAuditEvent` y la redacción aplicada | — | — |
| AC-007-31 | — | `TestClient(create_app(..., fakes))`: las 6 filas (nueva, existente, desconocida `404`, vacía `422`, 2001 caracteres `422`, `{}` / JSON inválido `422`); en los errores, `FakeLLM` sin llamadas | — | — |
| AC-007-32 | `SearchCustomers` sin cambios de dominio; `Card.card_id` de los builders | `buscar_cliente` vía sesión MCP con SQLite: `cards` en el orden de `masked_cards`, sin estado ni PAN; con `refinement_required` no hay clientes | Servidor: `CustomerMatchOut` publica `cards` con `additionalProperties: false`. Cliente: el modelo espejo del adaptador acepta la salida real y rechaza un `cards` con campos extra | — |
| AC-007-33 | `Transaction` rechaza `merchant_country` inválido (`"co"`, `"COL"`, `""`) | Las 3 herramientas vía sesión MCP con SQLite devuelven `merchant_country = "US"`; `SqlAlchemyTransactionRepository` lo guarda y lo lee | Servidor: `TransactionItemOut` con `merchant_country` y `additionalProperties: false`; snapshot del catálogo actualizado. Cliente: los modelos espejo aceptan la salida real de las 3 herramientas | — |
| AC-007-34 | — | — | — | `tests/e2e/test_chat_e2e.py`: base SQLite temporal preparada con los repositorios del core; `create_app` con el `McpStdioBankingAdapter` real (subproceso por stdio) y `FakeLLM`; 4 mensajes por `TestClient`. En la base quedan 1 disputa `OPEN` sobre `TX-L1` y 1 derivación `PENDING` con `AMOUNT_OVER_THRESHOLD` sobre `TX-L2` |

Adicionales:

- **Tabla de decisión (§5.3.3):** `test_dispute_policy.py` tiene una prueba parametrizada con una fila por cada DP-007-01…07, además de los bordes de AC-007-03, AC-007-06 y AC-007-09.
- **Casos de escalamiento (§5.3.4):** cada fila de la spec §8 tiene un test unitario del caso de uso: AC-007-03/05/09/10/11/12/14/20/23/24/25.
- **Invariantes (§5.3.5):**
  - Art. 7: AC-007-02, AC-007-11 y AC-007-15.
  - Decisiones no ejecutables: AC-007-07 y AC-007-08.
  - Límite del loop: AC-007-25.
- **Contrato en ambos lados (`mcp-testing.md` §1):** `tests/contract/dispute_agent/test_banking_client_contract.py` valida los modelos espejo del adaptador contra la salida real de las 6 herramientas (sesión MCP en memoria) y contra los sobres de error. También comprueba que rechazan campos extra.
- **Regresión del core:** las suites de 001–006 siguen en verde. Las afirmaciones de igualdad exacta de campos (`TransactionItem` y cliente de `buscar_cliente`) se actualizan para incluir los campos nuevos, sin ningún otro cambio de comportamiento.
- **Fronteras:** el hook `check_mcp_boundaries` impide importar `core_banking_mcp` desde `dispute_agent`. Un test unitario recorre `src/dispute_agent` y falla si algún módulo importa `core_banking_mcp` o `sqlalchemy`.

Cobertura: `pytest --cov` con `fail_under=80` global. En la verificación final, además, `coverage report --include="src/*/domain/*,src/*/application/*" --fail-under=90`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El LLM sortea la política (insistencia, inyección en `merchant`) y se abre una disputa indebida | Alto | El LLM no tiene acceso a las escrituras: solo las ejecuta la aplicación tras `DisputePolicy`. Las peticiones directas se bloquean y se auditan (AC-007-07, AC-007-08, AC-007-28). |
| Se exponen datos antes de verificar (p. ej. el LLM repite el nombre devuelto por `buscar_cliente`) | Alto | Guarda de identidad en el caso de uso. El resultado de `buscar_cliente` que recibe el LLM antes de verificar se reduce a `{matches: N}` (no se le pasan nombres, documentos ni tarjetas; el agente guarda `customer_id` y `cards` en `Conversation`). Además, el filtro de RN-007-26. Lo prueban AC-007-02 y AC-007-21. |
| El subproceso MCP muere o se cuelga | Alto | Tiempo límite por llamada → `BankingToolUnavailableError` → derivación (RN-007-21). El `lifespan` cierra el subproceso al apagar. Una prueba de integración cubre el tiempo límite. |
| Los tests asíncronos con un subproceso por stdio son inestables en Windows | Medio | Se reutiliza el patrón de `test_stdio_smoke.py` (ya verde en Windows), con `sys.executable` y un tiempo límite amplio solo en el e2e. |
| El cambio de `Transaction` o `Card` rompe builders y tests de 001–006 | Medio | Los campos nuevos van al final y con valor por defecto (`"CO"`, `None`). `models/tables.py`, `schemas.py`, `server.py`, `tests/fakes/*` y los `__init__.py` cuentan como archivos compartidos al calcular las oleadas. |
| Una base `data/core_banking.db` local de 001–006 no tiene la columna `merchant_country` | Bajo | `create_all` no altera tablas existentes: hay que borrar la base local, ignorada por git. Se documenta en el resumen del PR. |
| `.claude/rules/mcp-client.md` §3 describe una guarda que deja pasar herramientas tras la verificación, mientras que aquí las escrituras nunca las pide el LLM | Bajo | Es más estricto y compatible con la rule y con el Art. 5; no requiere enmienda. |
| La redacción de RN-007-26 se come números legítimos largos (p. ej. referencias de 13+ dígitos) | Bajo | Los `dispute_id` y `escalation_id` del core son `DSP-` / `ESC-` + 6 dígitos y los montos tienen menos de 13 dígitos. Es aceptable y lo exige la spec. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Las semillas nuevas (`TX-000010`, `TX-000011`, países) son ficticias y fijas; los tests usan builders y el e2e su propia base temporal. |
| Art. 2 — Spec-anchored | Cumple | Implementa la spec 0.1.0 aprobada. Los 34 AC están trazados en §6. Las specs 001, 003, 004 y 006 se actualizan en el mismo PR para reflejar los campos nuevos (§4.3.3). |
| Art. 3 — TDD | Cumple | Cada tarea empezará por su test. El dominio puro y los fakes (`FakeLLM`, `FakeBankingTools`) permiten el ciclo rojo-verde sin I/O. |
| Art. 4 — Arquitectura hexagonal | Cumple | `DisputePolicy`, `Conversation` y la redacción usan solo stdlib. FastAPI, Anthropic, MCP y Pydantic quedan en infraestructura. Cableado solo en `main.py` y `server.py`; lo refuerza el hook. |
| Art. 5 — El dominio decide | Cumple | Las decisiones las toma `DisputePolicy`. El LLM solo interpreta (herramientas de intención) y redacta; nunca ejecuta escrituras ni puede alterar `outcomes` (AC-007-07, AC-007-08, AC-007-28). |
| Art. 6 — Acciones vía MCP | Cumple | `dispute_agent` solo accede al core con `McpStdioBankingAdapter` (cliente MCP stdio); sin imports del core ni SQLAlchemy (hook y test de fronteras). |
| Art. 7 — Identificación antes que información | Cumple | La guarda de RN-007-01 bloquea antes de llegar al servidor, que valida de nuevo. El LLM no ve datos de `buscar_cliente` antes de verificar y la salida se filtra (AC-007-02, AC-007-21, AC-007-27). |
| Art. 8 — Auditoría | Cumple | Hay eventos de llamada a herramienta (incluidas las bloqueadas), de decisión y de derivación o cierre, con `conversation_id`, reloj inyectado, entrada, salida, regla y motivo, sin PAN ni documento (AC-007-30). |
| Art. 9 — Secretos | Cumple | `ANTHROPIC_API_KEY` solo por entorno (`SecretStr`); `.env.example` gana las claves sin valor. |
| Art. 10 — Ante la duda, escalar | Cumple | Las fallas de herramientas o del LLM, las salidas inválidas, el límite de iteraciones, la moneda sin tasa y la tarjeta ambigua en un fraude derivan por defecto (AC-007-03, 10, 23, 25). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
