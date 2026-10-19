# Plan: Ver la respuesta del agente palabra por palabra mientras se genera

| Campo | Valor |
|---|---|
| Feature | `009-streaming-agent-reply` |
| Versión | 0.1.1 |
| Estado | Aprobado |
| Fecha | 2026-10-18 |
| Spec | [spec.md](./spec.md) — versión 0.2.1 aprobada (las enmiendas PATCH 0.1.1 y 0.2.1 no cambian el diseño; la 0.2.1 sincroniza el formato del historial y la guarda de salida, ver §1) |
| Tareas | [tasks.md](./tasks.md) |

---

## 1. Resumen técnico

El turno se parte en dos fases dentro de `dispute_agent`, sin tocar `core_banking_mcp`:

1. **Decisión**: es el ciclo actual de `HandleCustomerMessage` (spec 007), extraído a un método `decide_turn` que devuelve el estado del turno (conversación, `outcomes` y si el ciclo terminó en `end_turn` o con un texto fijo) sin redactar ni guardar la respuesta. `handle()` (usado por `POST /api/chat`) llama a `decide_turn` y luego a `complete_turn`, y conserva exactamente su comportamiento: AC-007-* siguen verdes sin cambios.
2. **Redacción**: un caso de uso nuevo, `StreamCustomerMessage`, ejecuta `decide_turn` y, si corresponde (RN-009-03), llama a `LLMPort.stream(system, messages)`. Esa llamada no tiene herramientas. Va pasando los trozos de texto por un `IncrementalRedactor` de dominio, que solo libera **palabras completas ya filtradas** (RN-009-06/07). El caso de uso produce eventos de aplicación (`ReplyStarted`, `ReplyWord`, `ReplyEnded`, `ReplyInterrupted`) que el router convierte en Server-Sent Events.

Decisiones técnicas:

- **Streaming HTTP sin dependencias**: `POST /api/chat/stream` devuelve un `StreamingResponse` de Starlette con `media_type="text/event-stream"`. Cada evento se escribe a mano: `event: <tipo>\ndata: <json>\n\n`. La validación (`422`) usa el mismo `ChatRequest`. La existencia de la conversación (`404`) se comprueba **antes** de crear la respuesta, con `StreamCustomerMessage.prepare(...)`, para que ambos errores salgan como HTTP y sin flujo (RN-009-01).
- **Llamada de redacción sin herramientas** (decisión del usuario): `LLMPort.stream(system, messages)` no recibe herramientas. Como la API de Anthropic rechaza un historial con bloques `tool_use`/`tool_result` sin herramientas declaradas, `AnthropicLLMAdapter.stream` **aplana** esos bloques a texto dentro de bloques `<datos_internos>…</datos_internos>` (`Consulta realizada: <nombre> <argumentos>` / `Resultado de <nombre> <argumentos>[ (error)]: <contenido>`). Se abandonó el formato `[herramienta …]`/`[resultado …]`: el modelo lo imitaba y lo escribía al cliente. Las marcas viven en `ports/llm.py` (`INTERNAL_DATA_OPEN`, `INTERNAL_DATA_CLOSE`, `INTERNAL_MARKERS`), `REPLY_DRAFTING_PROMPT` prohíbe imitarlas (RN-009-03) y `classify_draft_end` trata como inválido un texto que las contenga (RN-009-09 c, AC-009-31). No hay reintento de la redacción: las palabras ya se transmitieron, así que se interrumpe y se deriva (RN-009-10). No envía `tools` y usa `client.messages.stream(...)`. Emite `LLMTextDelta(text)` por cada delta y, al final, un `LLMStreamEnd(stop_reason, tool_calls)` con la razón de parada y cualquier bloque `tool_use` del mensaje final. Toda excepción del SDK se traduce a `LLMError` (sin detalles).
- **Instrucciones de redacción**: `REPLY_DRAFTING_PROMPT`, en `application/system_prompt.py`, pide redactar en español a partir de los `outcomes` del turno, sin afirmar acciones fuera de ellos y sin números completos (RN-009-03). El prompt final se compone con los `outcomes` del turno ya filtrados, en JSON. Los mensajes son el historial de la conversación, que tras el ciclo termina en un mensaje `user` (texto de la cliente o resultados de herramientas), así que la API acepta un turno nuevo del asistente.
- **Validez e interrupción** (RN-009-09): la función pura `classify_draft_end(end, text)`, en `application/loop_control.py`, devuelve `COMPLETE` o `INTERRUPTED` con causa `LLM_INVALID_OUTPUT`, con la misma tabla de RN-007-34/35 (cualquier razón distinta de `end_turn`, cualquier `tool_call` o texto vacío). `LLMError` ⇒ `LLM_ERROR`. Una excepción inesperada dentro de la redacción ⇒ `INTERNAL_ERROR`.
- **Espera de 30 s sin texto** (`LLM_TIMEOUT`): `StreamCustomerMessage` compite cada `anext()` del flujo del LLM contra `Sleeper.sleep(idle_timeout)`, con `asyncio.wait(..., FIRST_COMPLETED)`. `Sleeper` es un puerto nuevo (`AsyncioSleeper` en producción). En las pruebas, un `VirtualSleeper` con tiempo virtual hace que los bordes de 29 s y 30 s (AC-009-10) sean exactos y sin esperas reales. El `FakeLLM` usa ese mismo `VirtualSleeper` para sus demoras guionizadas. El valor sale de `AgentSettings.llm_stream_idle_timeout_seconds` (30 por defecto).
- **Interrupción** (RN-009-10): reutiliza la ruta de falla de `HandleCustomerMessage` (`_fail_turn`, expuesta como `fail_turn`) con `UNRECOVERABLE_SYSTEM_FAILURE`, `OutcomeKind.LLM_FAILURE` y regla `RN-009-10`. Así la derivación, el cierre, RN-007-22 y el texto fijo son los mismos de la spec 007.
- **Desconexión de la página** (RN-009-12): la fase de decisión corre con `asyncio.shield` en una tarea propia, de modo que si Starlette cancela el generador por desconexión, **nunca se cortan acciones a medias**. Si la cancelación (`asyncio.CancelledError`/`GeneratorExit`) llega durante la redacción, el caso de uso cierra el flujo del LLM, audita `reply_shown` con `CLIENT_DISCONNECTED`, guarda la conversación y no deriva. Si llega antes de la redacción, espera a que termine la decisión, guarda y audita igual, sin llamar al LLM.
- **Historial**: al terminar, se añade al historial el texto que vio la cliente. Es `reply` en `end`. En `interrupted` es el texto parcial enviado seguido del mensaje fijo. En una desconexión es solo el texto parcial enviado. Así el siguiente turno del LLM ve exactamente lo que se mostró.
- **Auditoría** (RN-009-11): nuevo tipo `reply_shown` en `AuditEventType`, con `output = {"result", "cause", "text", "outcomes": [{"kind", "rule"}]}`. La llamada de redacción emite además un `llm_response` (RN-007-36) con `input = {"call": "draft"}` y la regla `RN-009-03` o `RN-009-09`. Todo pasa por `RedactingAuditLog`, que ya aplica RN-007-26.
- **Página** (`chat.js`): `fetch` a `/api/chat/stream` y lectura del cuerpo con `response.body.getReader()` y `TextDecoder`, con un analizador SSE mínimo (`EventSource` no admite `POST`). La respuesta en curso se pinta en una burbuja de **borrador** situada **fuera** de la región viva (`#draft`, sin `aria-live`). Al llegar `end` o `interrupted`, la burbuja completa se mueve a `#conversation` (`role="log"`, `aria-live="polite"`), lo que produce un solo anuncio (RN-009-19). Con `matchMedia('(prefers-reduced-motion: reduce)')` el borrador no se muestra (RN-009-20). La espera de 60 s se rearma con cada `word` mediante `setTimeout`/`clearTimeout`, que controla `page.clock` (RN-009-22). El evento `offline` de `window` aborta el flujo en curso (RN-009-23). Un contador de intento (`currentAttempt`, que ya existe) descarta los eventos de flujos terminados o abandonados (RN-009-25).
- **Specs vivas**: las specs 007 y 008 reciben una fila en su historial que remite a la 009. La 008 además actualiza RN-008-01, RN-008-16 b, §7.1 y §7.2 (§4.3.3).

## 2. Componentes por capa

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `dispute_agent` | `domain` | `redaction.py` → `IncrementalRedactor` | Modificado | Clase pura: `feed(chunk) -> list[str]` y `finish() -> list[str]`. Libera fragmentos de una palabra completa con su espacio previo (RN-009-06). Retiene la cola mientras pueda formar parte de una secuencia de 13–19 dígitos (dígitos con espacios o guiones) o ser prefijo de un documento aportado, y aplica `redact_reply` a lo liberado. Invariante: `"".join(fragments) == redact_reply(full_text, documents)` (RN-009-07/08). `redact_reply` no cambia. |
| `dispute_agent` | `application` | `ports/llm.py` | Modificado | Añade `LLMTextDelta`, `LLMStreamEnd(stop_reason, tool_calls)` y `LLMPort.stream(system, messages) -> AsyncIterator[LLMTextDelta \| LLMStreamEnd]`. `complete` no cambia. |
| `dispute_agent` | `application` | `ports/sleeper.py` | Nuevo | Puerto `Sleeper` (`async def sleep(seconds: float) -> None`). |
| `dispute_agent` | `application` | `ports/audit_log.py` | Modificado | `AuditEventType` incorpora `"reply_shown"` (quinto tipo de evento, RN-009-11). |
| `dispute_agent` | `application` | `loop_control.py` | Modificado | Añade `DraftVerdict` y `classify_draft_end(end, text)` (RN-009-09 c); rechaza además textos con marcas de `INTERNAL_MARKERS` (AC-009-31). `classify_llm_response` no cambia. |
| `dispute_agent` | `application` | `system_prompt.py` | Modificado | Añade `REPLY_DRAFTING_PROMPT` y `build_drafting_system(outcomes)` (RN-009-03); la regla 5 prohíbe imitar `<datos_internos>` y escribir llamadas a herramientas. `SYSTEM_PROMPT` cambia en la spec 007 (RN-007-44). |
| `dispute_agent` | `application` | `use_cases/handle_customer_message.py` | Modificado | Refactor sin cambio de comportamiento: `decide_turn(conversation_id, message) -> TurnDecision` (conversación, `outcomes`, texto y `drafted: bool`, que indica si el ciclo terminó en `end_turn`), `complete_turn(decision, reply) -> ChatTurnResult` y `fail_turn(...)` público (hoy `_fail_turn`), con la regla como parámetro. `handle()` = `decide_turn` + `complete_turn`. |
| `dispute_agent` | `application` | `use_cases/stream_customer_message.py` | Nuevo | `StreamCustomerMessage`: `prepare(conversation_id)` (lanza `ConversationNotFoundError`) y `events(prepared, message) -> AsyncIterator[StreamEvent]`. Orden: `ReplyStarted` → decisión protegida con `shield` → redacción (o texto fijo, RN-009-04) → `ReplyWord`* → `ReplyEnded` \| `ReplyInterrupted`. Espera de inactividad con `Sleeper`, interrupción (RN-009-10), auditoría `reply_shown` + `llm_response` (RN-009-11), desconexión (RN-009-12) e historial. Eventos como dataclasses inmutables en el mismo módulo. |
| `dispute_agent` | `infrastructure/outbound` | `llm/anthropic_llm_adapter.py` | Modificado | `stream(system, messages)`: `client.messages.stream` sin `tools`, con historial aplanado (`_flatten_for_drafting`). Emite `LLMTextDelta` por delta de texto y `LLMStreamEnd` con `stop_reason` y `tool_use` finales. Excepciones ⇒ `LLMError`. |
| `dispute_agent` | `infrastructure/outbound` | `clock/asyncio_sleeper.py` | Nuevo | `AsyncioSleeper` (envuelve `asyncio.sleep`). |
| `dispute_agent` | `infrastructure/inbound` | `web/api/chat_stream_router.py` | Nuevo | `POST /api/chat/stream`: valida con `ChatRequest` (`422`), `prepare` (`404`) y `StreamingResponse` `text/event-stream` que serializa cada evento según spec §7.1. |
| `dispute_agent` | `infrastructure/inbound` | `web/api/schemas.py` | Modificado | `StreamStartOut`, `StreamWordOut`, `StreamEndOut` y `StreamInterruptedOut` (reutilizan `OutcomeOut`). |
| `dispute_agent` | `infrastructure/inbound` | `web/static/chat.js` | Modificado | Cliente de streaming: lector SSE, borrador fuera de la región viva, indicador hasta la primera palabra, marca `Incompleto`, aviso de derivación tras la última palabra, espera de 60 s por palabra, `offline`, movimiento reducido, descarte de eventos tardíos y `Reintentar` según RN-009-24. Deja de llamar a `/api/chat`. |
| `dispute_agent` | `infrastructure/inbound` | `web/static/index.html` | Modificado | Contenedor `#draft` (sin `aria-live`) entre `#conversation` y el indicador, dentro del mismo panel con desplazamiento. |
| `dispute_agent` | `infrastructure/inbound` | `web/static/styles.css` | Modificado | Estilo del borrador y de la marca `Incompleto`, sin desbordar el ancho (RN-008-19). |
| `dispute_agent` | — | `config.py` | Modificado | `llm_stream_idle_timeout_seconds: float = 30` (spec §7.3). |
| `dispute_agent` | — | `main.py` | Modificado | `_LazyAnthropicLLM.stream`, cableado de `StreamCustomerMessage` (con `AsyncioSleeper` inyectable) y del router nuevo. Parámetro opcional `sleeper` en `create_app` para pruebas. |
| — | — | `specs/007-dispute-resolution-agent/spec.md` | Modificado | Fila en el historial: la spec 009 añade `POST /api/chat/stream` y el evento `reply_shown` (amplía RN-007-28). |
| — | — | `specs/008-chat-web-page/spec.md` | Modificado | Versión 0.2.0: RN-008-01 y §7.1 (la página usa `POST /api/chat/stream`), RN-008-16 b (60 s desde la última palabra), §7.2 (`Incompleto`) y la fila de historial. |
| — | tests | `tests/fakes/fake_llm.py` | Modificado | Guion de streaming: `StreamScript(chunks=[(delay_s, text)…], end=LLMStreamEnd \| LLMError \| HANG)`. Las demoras usan el `VirtualSleeper`. `stream_requests` registra `system` y `messages`. |
| — | tests | `tests/fakes/virtual_sleeper.py` | Nuevo | Tiempo virtual determinista: resuelve las esperas por orden de vencimiento cuando todas las tareas están bloqueadas. Expone `now`. |
| — | tests | `tests/fakes/chat_stream_script.py` | Nuevo | App ASGI de prueba que envuelve la app real y responde `POST /api/chat/stream` con eventos guionizados, emitidos de forma progresiva (demoras y puertas `hold`/`release`) o con un cierre abrupto. El resto de rutas va a la app real. |
| — | tests | `tests/fakes/chat_api_script.py` | Modificado | Intercepta `**/api/chat/stream` y traduce cada respuesta JSON encolada a un cuerpo SSE completo (`start`, `word` por palabra de `reply`, `end`), o al código de error. Así los AC-008 conservan su semántica. |
| — | tests | `tests/e2e/web/conftest.py` | Modificado | El servidor en vivo sirve la app envuelta por `ChatStreamScript`. |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `LLMPort` | Modificado | `AnthropicLLMAdapter`, `_LazyAnthropicLLM` (main), `FakeLLM` (tests) | Nuevo método `stream`, sin herramientas. `complete` no cambia. |
| `Sleeper` | Nuevo | `AsyncioSleeper`, `VirtualSleeper` (tests) | Solo para la espera de inactividad de la redacción. No sustituye a `Clock` (marcas de tiempo). |
| `AuditLogPort` | Modificado | `JsonAuditLog` vía `RedactingAuditLog` | Nuevo tipo de evento `reply_shown`. Los adaptadores no cambian. |
| `BankingToolsPort` | Sin cambios | `McpStdioBankingAdapter` | La redacción no usa herramientas MCP. |
| `ConversationRepository` | Sin cambios | `InMemoryConversationRepository` | Compartido por ambos endpoints. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `IncrementalRedactor` | `documents: frozenset[str]`, búfer pendiente | Nunca libera parte de una palabra. Nunca libera texto que `redact_reply` sustituiría. La concatenación de todo lo liberado (`feed`* + `finish`) es igual a `redact_reply` del texto completo. |

Los eventos del flujo (`ReplyStarted`, `ReplyWord`, `ReplyEnded`, `ReplyInterrupted`), `TurnDecision` y `DraftVerdict` son DTOs inmutables de `application`, no entidades de dominio. `Outcome`, `OutcomeKind` y `Conversation` no cambian: el `LLM_FAILURE` de la interrupción usa el `OutcomeKind` existente con la regla `RN-009-10`.

### Persistencia (`core_banking_mcp`)

No aplica: la feature no toca el core.

### Semillas

No aplica: no se necesitan datos nuevos. AC-009-14 usa las semillas existentes del core (clientes y tarjetas ficticios de las specs 001–007).

## 5. Dependencias nuevas

Ninguna. El streaming HTTP usa `StreamingResponse` de Starlette (incluido con FastAPI). El SDK `anthropic` ya ofrece `messages.stream`. En el navegador se usan `fetch` y `ReadableStream` nativos. Las pruebas usan Playwright, `httpx` y `pytest-asyncio`, que ya están en el grupo `dev`. Se descartaron `sse-starlette` (innecesario para un único endpoint) y `looptime` (el `VirtualSleeper` cubre el tiempo virtual que se necesita).

## 6. Estrategia de pruebas

Archivos nuevos (nombres orientativos; las tareas los fijan):

- `tests/unit/dispute_agent/domain/test_incremental_redaction.py`
- `tests/unit/dispute_agent/application/test_stream_customer_message.py` (y, si crece, `_interruptions.py` y `_audit.py`)
- `tests/unit/dispute_agent/application/test_draft_classification.py`
- `tests/integration/dispute_agent/web/test_chat_stream_api.py` (`TestClient`, lectura del flujo SSE)
- `tests/integration/dispute_agent/llm/test_anthropic_stream_adapter.py` (`httpx.MockTransport` que sirve el SSE de Anthropic)
- `tests/e2e/test_chat_stream_e2e.py` (servidor MCP real por stdio, `FakeLLM`)
- `tests/e2e/web/test_chat_page_streaming.py` y afines (Playwright, `ChatStreamScript`, `page.clock`)

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-009-01 | `StreamCustomerMessage` con `FakeLLM` en trozos y `VirtualSleeper`: orden y contenido de eventos, `" disputa"` emitido antes del 3.er trozo, una sola llamada `stream` sin herramientas | `POST /api/chat/stream`: `200`, `text/event-stream`, formato SSE de §7.1 | — | — |
| AC-009-02 | Ciclo de 3 llamadas con texto en `tool_use`/`end_turn`: ningún evento entre `start` y el primer `word` y ningún fragmento con ese texto | — | — | — |
| AC-009-03 | Orden de registros en `FakeAgentAuditLog` y llamadas a `FakeBankingTools` frente a `stream_requests`; `outcomes` iguales a los de `handle()` en el mismo guion | — | — | — |
| AC-009-04 | Redacción que afirma acciones: no hay llamadas a herramientas después, `outcomes` vacío y `reply_shown` `COMPLETE` con el texto | — | — | — |
| AC-009-05 | `IncrementalRedactor` parametrizado con las 4 filas, en trozos de 3 caracteres: una palabra por fragmento y concatenación exacta; y `StreamCustomerMessage` con una fila | — | — | — |
| AC-009-06 | `IncrementalRedactor` parametrizado con las 3 filas, en trozos de 2 caracteres: ningún fragmento con lo prohibido y `reply` filtrado | — | — | — |
| AC-009-07 | Tres filas (límite de 8, `max_tokens` en el ciclo, conversación cerrada): sin `stream`, `start` + `end` con el texto fijo | — | — | — |
| AC-009-08 | — | Tres filas: `422`/`404` sin flujo y sin llamadas al `FakeLLM` | — | — |
| AC-009-09 | Cinco filas de interrupción: no hay más `word`, `interrupted` con el texto fijo, `outcomes` con `DISPUTE_OPENED` + `LLM_FAILURE` (`RN-009-10`), una derivación, cierre y `reply_shown` con la causa y `"Abrimos tu"`; `bloquear_tarjeta` no se invoca | — | — | — |
| AC-009-10 | Bordes de 29 s y 30 s con `VirtualSleeper`; espera configurada en 10 s | `AgentSettings` lee `LLM_STREAM_IDLE_TIMEOUT_SECONDS` (30 por defecto) | — | — |
| AC-009-11 | Tres filas sin palabras enviadas: `interrupted` y derivación | — | — | — |
| AC-009-12 | Dos filas con `FixedAgentClock`: `reply_shown` (resultado, causa, texto, `outcomes`) y `llm_response` de la redacción (`RN-009-03`/`RN-009-09`); con `RedactingAuditLog` real, sin `4111111111114321` ni `D-1001` | — | — | — |
| AC-009-13 | Cancelar el generador tras dos palabras: sin nuevas llamadas al LLM ni derivación, `reply_shown` `CLIENT_DISCONNECTED` y siguiente mensaje atendido; cancelar durante la decisión no corta las acciones | — | — | — |
| AC-009-14 | — | — | — | `create_app` con MCP real por stdio y `FakeLLM`: entrada de la redacción sin resultados de transacciones ni datos de las semillas, y fragmentos sin `****` ni datos personales |
| AC-009-15 | — | — | — | Navegador: la burbuja crece palabra a palabra y al final queda exacta; única petición a `/api/chat/stream` |
| AC-009-16 | — | — | — | Navegador: indicador visible sin borrador hasta la primera palabra |
| AC-009-17 | — | — | — | Navegador: 5 filas como texto plano, sin elementos inyectados ni diálogos, sin desplazamiento horizontal |
| AC-009-18 | — | — | — | Navegador: texto enmascarado exacto y sin campos de `outcomes` |
| AC-009-19 | — | — | — | Navegador: sin peticiones nuevas a mitad de respuesta; foco en la caja al terminar |
| AC-009-20 | — | — | — | Navegador: aviso de derivación y botón solo tras la última palabra |
| AC-009-21 | — | — | — | Navegador: `Incompleto`, burbuja fija, aviso y cierre |
| AC-009-22 | — | — | — | Navegador: `MutationObserver` sobre las regiones `aria-live`: ninguna mutación mientras llegan palabras y una sola inserción completa con prefijo `Agente` al final |
| AC-009-23 | — | — | — | Navegador con `reduced_motion="reduce"`: indicador sin palabras y burbuja completa al final |
| AC-009-24 | — | — | — | Navegador: saludo, mensaje de la cliente, respuesta fija y aviso completos de una vez |
| AC-009-25 | — | — | — | Navegador con `page.clock`: filas de 59, 60 y 61 s |
| AC-009-26 | — | — | — | Navegador con `page.clock`: 4 palabras cada 50 s sin aviso; 60 s sin palabras ⇒ `No enviado` |
| AC-009-27 | — | — | — | Navegador con `context.set_offline(True)` a mitad de flujo: aviso, `Incompleto`, sin `No enviado` y reintento con la misma petición |
| AC-009-28 | — | — | — | Navegador: flujo cortado, evento inválido, `503` y `404` |
| AC-009-29 | — | — | — | Navegador: recargar y conversación nueva con eventos tardíos sin residuos; petición siguiente sin `conversation_id` |
| AC-009-30 | — | — | — | Navegador: sin datos de la cuenta y única petición a `/api/chat/stream` |
| AC-009-31 | `test_draft_classification`/`test_loop_control.py::test_classify_draft_end__internal_markup_in_text__invalid` (2 filas) y `test_stream_customer_message_interruptions.py::test_ac_009_31_draft_with_internal_markup_escalates` (`interrupted`, `LLM_INVALID_OUTPUT`, derivación única); `test_drafting_prompt.py::test_drafting_prompt__forbids_tool_call_text` | — | `test_anthropic_stream_adapter.py::test_stream__flattened_history_without_tools__yields_deltas_and_stop_reason` (sin `[herramienta`/`[resultado`; bloques `<datos_internos>`) | — |

**Regresión obligatoria**: AC-007-* (`POST /api/chat` y ciclo) y AC-008-* siguen verdes. Los AC-008 que comprueban la URL de la petición (`/api/chat`) se actualizan a `/api/chat/stream` junto con la enmienda de RN-008-01. Su semántica se conserva gracias a `ChatApiScript`, que traduce el JSON guionizado a SSE.

**Tabla `DP-`**: no aplica (spec §5). **Escalamiento** (spec §8): lo cubren AC-009-09 y AC-009-11. **Invariantes**: Art. 7 en AC-009-14 y AC-009-30. El texto no ejecuta acciones (Art. 5) en AC-009-04 y AC-009-09 (fila de la petición de herramienta). La llamada de redacción queda fuera del tope de iteraciones en AC-009-07 y AC-009-01 (una sola llamada `stream`).

Todos los tests llevan el comentario de trazabilidad (`Regla: RN-009-XX …` / `AC-009-XX · Art. N`). No usan el LLM real ni el reloj real: `FakeLLM`, `FixedAgentClock`, `VirtualSleeper` y `page.clock`.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Si la página se desconecta, Starlette cancela el generador **durante la fase de decisión** y una acción (disputa, bloqueo, derivación) queda a medias. | Alto | La decisión corre en una tarea propia con `asyncio.shield`. Ante la cancelación, el caso de uso espera a que termine, guarda y audita. Un test unitario cancela durante la decisión (AC-009-13). |
| El filtro por fragmentos deja pasar un número de tarjeta repartido entre palabras o trozos (Art. 7). | Alto | `IncrementalRedactor` retiene mientras la cola pueda completar una coincidencia. Lo prueban tests parametrizados (AC-009-06) y una propiedad por trozos de 1 a N caracteres que exige `"".join(fragmentos) == redact_reply(texto)` y que ningún fragmento contenga 13 o más dígitos seguidos. |
| `page.route` de Playwright no entrega cuerpos de forma progresiva, así que no se puede probar "palabra por palabra" con el arnés de la 008. | Alto | `ChatStreamScript` es una app ASGI de prueba que emite eventos progresivos desde el servidor en vivo. `ChatApiScript` sigue sirviendo los AC-008, que no necesitan progresión. |
| Al cambiar la página a `/api/chat/stream` se rompen las pruebas de navegador de la 008, que interceptan `**/api/chat`. | Alto | `ChatApiScript` pasa a interceptar `**/api/chat/stream` y traduce el JSON a SSE. La migración es una tarea propia, previa a cambiar `chat.js`. La suite completa corre tras cada oleada. |
| `context.set_offline` no corta en Chromium un `fetch` en curso, y la página se queda esperando. | Medio | `chat.js` escucha el evento `offline` de `window` y aborta el flujo con su `AbortController`. La prueba lo verifica (AC-009-27). |
| Pruebas de tiempo inestables (bordes de 29/30 s y 59/60 s). | Medio | `VirtualSleeper` en el agente y `page.clock` en el navegador, sin esperas reales. Los bordes se verifican en tiempo virtual. |
| El aplanado del historial pierde contexto y el LLM redacta peor. | Medio | El aplanado conserva el nombre de la herramienta, sus argumentos y su resultado en texto, en bloques `<datos_internos>` que el modelo no imita, y una guarda de salida rechaza el texto que los reproduzca. Las instrucciones de redacción incluyen los `outcomes` del turno. La calidad real se valora con una prueba opcional `@pytest.mark.llm`, que no bloquea. |
| El refactor de `HandleCustomerMessage` cambia sin querer el comportamiento de `POST /api/chat`. | Medio | Refactor sin cambio de comportamiento (§4.3.5): los tests AC-007-* existentes deben seguir verdes sin modificarse, y es la primera tarea de la cadena del agente. |
| Una llamada extra al LLM por mensaje aumenta el coste y la latencia. | Bajo | Aceptado en la clarificación de la spec. Solo ocurre cuando el ciclo termina con `end_turn`. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | No se añaden datos. Las pruebas usan builders y las semillas ficticias existentes. |
| Art. 2 — Spec-anchored | Cumple | Spec 009 aprobada y trazada. Las enmiendas a las specs 007 y 008 (RN-008-01, RN-008-16 b, §7.1, §7.2, historial) van en el mismo PR. |
| Art. 3 — TDD | Cumple | Cada tarea empieza por su test (Red → Green → Refactor). El refactor de `HandleCustomerMessage` se protege con los tests existentes. |
| Art. 4 — Arquitectura hexagonal | Cumple | `IncrementalRedactor` es dominio puro (solo `re`). Los eventos y el caso de uso viven en `application`. SSE y SDK solo en `infrastructure`. Cableado solo en `main.py`. `Sleeper` es un puerto nuevo. |
| Art. 5 — El dominio decide | Cumple | La redacción empieza después de que `DisputePolicy` y las guardas actúan. No tiene herramientas, y su texto nunca se interpreta para ejecutar acciones (RN-009-05). Una petición de herramienta en la redacción interrumpe sin ejecutarla. |
| Art. 6 — Acciones vía MCP | Cumple | Sin cambios: toda acción sigue en la fase de decisión vía `BankingToolsPort`. La redacción no toca el core. |
| Art. 7 — Identificación antes que información | Cumple | La redacción solo recibe el historial, que ya está protegido por las guardas de 007. El filtro incremental impide mostrar datos sin enmascarar en cualquier fragmento. Lo prueban AC-009-06, AC-009-14 y AC-009-30. |
| Art. 8 — Auditoría | Cumple | Nuevo evento `reply_shown` (resultado, causa, texto filtrado, `outcomes`) y `llm_response` de la redacción, con `conversation_id` y el reloj inyectado. Todo pasa por `RedactingAuditLog`. |
| Art. 9 — Secretos | Cumple | Sin credenciales nuevas. La espera de inactividad es configuración no secreta en `AgentSettings`. |
| Art. 10 — Ante la duda, escalar | Cumple | Toda interrupción de la redacción (error, 30 s sin texto, salida inválida, falla interna) deriva con `UNRECOVERABLE_SYSTEM_FAILURE` y cierra. La desconexión no deriva porque las decisiones ya se tomaron (RN-009-12, decisión de la spec). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
