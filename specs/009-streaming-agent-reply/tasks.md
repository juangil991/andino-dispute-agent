# Tareas: Ver la respuesta del agente palabra por palabra mientras se genera

| Campo | Valor |
|---|---|
| Feature | `009-streaming-agent-reply` |
| Spec | [spec.md](./spec.md) — versión 0.1.1 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-18 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

---

## Tareas

### [x] T-009-01 — Puerto `Sleeper` y `VirtualSleeper` de pruebas

- **Cubre:** habilita AC-009-01, AC-009-09, AC-009-10 (tiempo virtual determinista; plan §1)
- **App / capa:** `dispute_agent` / `application` (puerto) + soporte de tests
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/ports/sleeper.py`, `tests/fakes/virtual_sleeper.py`, `tests/unit/dispute_agent/application/test_virtual_sleeper.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_virtual_sleeper.py::test_virtual_sleeper__concurrent_sleeps__resolve_in_deadline_order`
- **Red:** el módulo `tests.fakes.virtual_sleeper` no existe. El test comprueba que dos esperas concurrentes (29 s y 30 s) se resuelven en orden de vencimiento, que `now` avanza a 29 y luego a 30 sin espera real (< 1 s de reloj de pared), y que una espera cancelada no avanza el tiempo.
- **Green:** `Sleeper` (`Protocol` con `async def sleep(seconds: float) -> None`). `VirtualSleeper` con tiempo virtual: cuando las tareas pendientes están bloqueadas (cede el control con `asyncio.sleep(0)` varias veces), resuelve la espera de menor vencimiento y actualiza `now`.
- **Refactor:** —

### [x] T-009-02 — `LLMPort.stream` y guion de streaming en `FakeLLM`

- **Cubre:** habilita AC-009-01 a AC-009-13 (plan §2, §3)
- **App / capa:** `dispute_agent` / `application` (puerto) + soporte de tests
- **Depende de:** T-009-01
- **Archivos:** `src/dispute_agent/application/ports/llm.py`, `tests/fakes/fake_llm.py`, `tests/unit/dispute_agent/application/test_fake_llm_stream.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_fake_llm_stream.py::test_fake_llm_stream__scripted_chunks__yields_deltas_then_end_with_virtual_delays`
- **Red:** `LLMTextDelta`, `LLMStreamEnd` y `FakeLLM.stream` no existen. El test guioniza los trozos `[(1, "Hola "), (2, "Ana.")]` con `end=LLMStreamEnd("end_turn", ())` y espera recibir dos `LLMTextDelta` y luego el `LLMStreamEnd`, con `VirtualSleeper.now == 3` al terminar. Una entrada `LLMError` debe lanzarse tras los trozos, una entrada `HANG` no debe terminar nunca, y `stream_requests` registra `system` y `messages`.
- **Green:** en `ports/llm.py`, los dataclasses `LLMTextDelta(text)` y `LLMStreamEnd(stop_reason, tool_calls)` y el método `LLMPort.stream(system, messages) -> AsyncIterator[LLMTextDelta | LLMStreamEnd]`. En `FakeLLM`, el parámetro opcional `stream_script: list[StreamScript]`, el parámetro `sleeper` y el centinela `HANG`. `complete` no cambia.
- **Refactor:** —

### [x] T-009-03 — `IncrementalRedactor`: palabras completas y filtro antes de liberar

- **Cubre:** AC-009-05, AC-009-06
- **App / capa:** `dispute_agent` / `domain`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/domain/redaction.py`, `tests/unit/dispute_agent/domain/test_incremental_redaction.py`
- **Test primero:** `tests/unit/dispute_agent/domain/test_incremental_redaction.py::test_ac_009_05_words_are_never_split_or_altered` (parametrizado con las 4 filas, en trozos de 3 caracteres). Además, `test_ac_009_06_filter_applies_before_each_word` (las 3 filas, en trozos de 2 caracteres) y `test_ac_009_06_any_chunking_matches_full_redaction` (propiedad: trozos de 1 a 7 caracteres, la concatenación es igual a `redact_reply(texto)` y ningún fragmento contiene 13 o más dígitos).
- **Red:** `IncrementalRedactor` no existe.
- **Green:** clase pura con `feed(chunk) -> list[str]` y `finish() -> list[str]`. Cada fragmento es el espacio en blanco previo más una palabra completa. La cola se retiene mientras pueda extender una coincidencia de `_PAN` (grupos de dígitos con espacios o guiones) o ser prefijo de un documento aportado. Lo liberado pasa por `redact_reply`. `redact_reply` no cambia.
- **Refactor:** extraer el predicado "puede completar una coincidencia" si queda complejo.

### [x] T-009-04 — Refactor de `HandleCustomerMessage`: `decide_turn`, `complete_turn` y `fail_turn`

- **Cubre:** habilita AC-009-02, AC-009-03, AC-009-07, AC-009-09 (plan §2; sin cambio de comportamiento, §4.3.5)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_decide_turn.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_decide_turn.py::test_decide_turn__loop_ends_with_end_turn__returns_outcomes_without_saving_reply`
- **Red:** `decide_turn` no existe. El test espera un `TurnDecision` con `drafted=True`, los `outcomes` del turno, el texto del `end_turn` y la conversación sin el mensaje del asistente añadido. Otros dos tests: con `max_tokens` en el ciclo (`drafted=False`, texto fijo de `LLM_FAILURE`), y `fail_turn(conv, outcomes, rule="RN-009-10")`, que deriva, cierra y devuelve el texto fijo con un `LLM_FAILURE` de regla `RN-009-10`.
- **Green:** extraer `decide_turn` (carga, cierre previo de RN-007-24, ciclo y fallas) y `complete_turn` (filtro, historial, guardado y `outcomes` filtrados). `handle()` llama a ambos. `_fail_turn` pasa a ser público con la regla como parámetro.
- **Refactor:** la suite de AC-007 (`tests/unit/dispute_agent/application/test_handle_customer_message*.py`, `tests/integration/dispute_agent/web/test_chat_api.py`) debe seguir verde **sin modificar** ningún test existente.

### [x] T-009-05 — `classify_draft_end`: validez de la redacción

- **Cubre:** AC-009-09, AC-009-11 (RN-009-09 c)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-02
- **Archivos:** `src/dispute_agent/application/loop_control.py`, `tests/unit/dispute_agent/application/test_draft_classification.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_draft_classification.py::test_ac_009_09_draft_end_is_complete_only_with_end_turn_text_and_no_tools` (parametrizado: `end_turn` con texto ⇒ `COMPLETE`; `end_turn` con `"   "`, `max_tokens`, `refusal`, `pause_turn`, `stop_sequence`, `None`, otro valor y `end_turn` con un `tool_call` ⇒ `INTERRUPTED`/`LLM_INVALID_OUTPUT`)
- **Red:** `classify_draft_end` y `DraftVerdict` no existen.
- **Green:** función pura `classify_draft_end(end: LLMStreamEnd, text: str) -> DraftVerdict` (`complete: bool`, `cause: str | None`). `classify_llm_response` no cambia.
- **Refactor:** —

### [x] T-009-06 — Instrucciones de redacción

- **Cubre:** AC-009-03, AC-009-04 (RN-009-03)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/system_prompt.py`, `tests/unit/dispute_agent/application/test_drafting_prompt.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_drafting_prompt.py::test_ac_009_04_drafting_prompt_forbids_claiming_actions_outside_outcomes`
- **Red:** `REPLY_DRAFTING_PROMPT` y `build_drafting_system` no existen. El test exige que el prompt pida responder en español a partir de los `outcomes`, sin afirmar acciones que no figuren en ellos y sin números completos. También exige que `build_drafting_system(outcomes)` incluya el JSON de los `outcomes` recibidos (`kind`, `rule`, `reason`, `next_steps`, `masked_card`, `reference`).
- **Green:** constante y función en `system_prompt.py`. `SYSTEM_PROMPT` no cambia.
- **Refactor:** —

### [x] T-009-07 — `StreamCustomerMessage`: decisión primero y redacción palabra por palabra

- **Cubre:** AC-009-01, AC-009-02, AC-009-03, AC-009-04, AC-009-05
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-02, T-009-03, T-009-04, T-009-05, T-009-06
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `src/dispute_agent/application/ports/audit_log.py`, `tests/unit/dispute_agent/application/test_stream_customer_message.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message.py::test_ac_009_01_reply_streams_word_by_word`. Además: `test_ac_009_02_no_text_is_sent_while_the_loop_runs`, `test_ac_009_03_decisions_and_actions_happen_before_first_word`, `test_ac_009_04_draft_text_never_triggers_actions` y `test_ac_009_05_stream_concatenation_equals_reply`.
- **Red:** `StreamCustomerMessage` no existe.
- **Green:** `prepare(conversation_id)` (propaga `ConversationNotFoundError`) y `events(prepared, message)`, que emite `ReplyStarted`, ejecuta `decide_turn` y, si `drafted`, hace una sola llamada `llm.stream(build_drafting_system(outcomes), historial)`. Pasa cada delta por `IncrementalRedactor`, emite `ReplyWord` por fragmento y, al terminar `COMPLETE` (`classify_draft_end`), emite `ReplyEnded(reply, status, outcomes)` y llama a `complete_turn`. `AuditEventType` incorpora `"reply_shown"`, y se registra un `reply_shown` básico (`COMPLETE`, texto, `outcomes` con `kind`/`rule`).
- **Refactor:** eventos como dataclasses inmutables en el mismo módulo.

### [x] T-009-08 — Respuestas fijas sin redacción

- **Cubre:** AC-009-07
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-07
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_fixed.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_fixed.py::test_ac_009_07_fixed_replies_are_sent_whole_without_drafting` (parametrizado: límite de 8 llamadas, `max_tokens` en el ciclo y conversación cerrada)
- **Red:** el caso de uso hace la llamada `stream` o emite `ReplyWord` cuando `drafted=False`.
- **Green:** con `drafted=False`, emitir solo `ReplyEnded` con el texto fijo, sin llamar a `stream`.
- **Refactor:** —

### [x] T-009-09 — Interrupción de la redacción: fallas del LLM y falla interna

- **Cubre:** AC-009-09, AC-009-11 (caso de escalamiento de spec §8)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-08
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_interruptions.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_interruptions.py::test_ac_009_09_interrupted_draft_escalates_and_closes` (las 5 filas: `LLMError`, `HANG` 30 s, `max_tokens`, `tool_call` `bloquear_tarjeta` y una excepción inesperada). Además, `test_ac_009_11_invalid_draft_without_words_escalates` (3 filas).
- **Red:** el caso de uso no emite `ReplyInterrupted` ni deriva.
- **Green:** competir cada `anext()` contra `sleeper.sleep(idle_timeout)` (`LLM_TIMEOUT`). `LLMError` ⇒ `LLM_ERROR`, veredicto inválido ⇒ `LLM_INVALID_OUTPUT` y cualquier otra excepción ⇒ `INTERNAL_ERROR`. Ante una interrupción, se cierra el flujo del LLM, se llama a `fail_turn(..., rule="RN-009-10")` y se emite `ReplyInterrupted(reply=texto fijo, status=ESCALATED, outcomes)`. No se ejecuta ninguna herramienta pedida en la redacción. El historial recibe el texto parcial y el texto fijo.
- **Refactor:** —

### [x] T-009-10 — Espera máxima configurable de la redacción

- **Cubre:** AC-009-10
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-09
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_timeout.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_timeout.py::test_ac_009_10_idle_timeout_borders` (filas 29 s ⇒ termina completa, sin derivación; 30 s ⇒ `LLM_TIMEOUT` a los 30 s virtuales). Además, `test_ac_009_10_idle_timeout_is_configurable` (10 s).
- **Red:** el borde de 30 s o el valor configurado no se respetan (p. ej., la espera se mide desde el inicio y no desde el último texto).
- **Green:** reiniciar la espera con cada delta recibido. El valor `idle_timeout_seconds` se inyecta en el constructor.
- **Refactor:** —

### [x] T-009-11 — Auditoría `reply_shown` y `llm_response` de la redacción

- **Cubre:** AC-009-12
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-10
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_audit.py`, `tests/unit/dispute_agent/application/test_stream_customer_message.py`
- **Añadido tras el bloqueo de T-009-11:** el `llm_response` de la redacción necesita el `stop_reason`, así que se emite al terminar el flujo y queda entre `stream` y `reply_shown`. La aserción de `test_ac_009_03_decisions_and_actions_happen_before_first_word` (línea 315) prohibía cualquier auditoría ahí. Se ajusta para que solo admita `audit:llm_response` y `audit:reply_shown` tras `stream`, sin cambiar su intención: las auditorías de decisión y de herramientas ocurren antes de la redacción.
- **Añadido tras T-009-09 (spec §8):** la nota de la derivación por interrupción lleva la causa (`LLM_ERROR`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT` o `INTERNAL_ERROR`), sin detalles internos ni texto del LLM. Para ello `fail_turn` admite una nota opcional y se hace público `clean_outcome` (hoy `_clean_outcome`, importado como privado por `StreamCustomerMessage`). Se verifica en `test_stream_customer_message_audit.py` con la nota recibida por `FakeBankingTools.escalar_a_analista`.
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_audit.py::test_ac_009_12_reply_shown_is_audited_masked` (filas `COMPLETE`/`RN-009-03` e `INTERRUPTED`/`LLM_INVALID_OUTPUT`/`RN-009-09`, con `FixedAgentClock` y `RedactingAuditLog` real sobre `FakeAgentAuditLog`)
- **Red:** falta la causa, la marca de tiempo, el `llm_response` de la redacción (`input={"call": "draft"}`) o el registro contiene `4111111111114321`/`D-1001`.
- **Green:** completar `reply_shown` (`result`, `cause`, `text`, `outcomes`) y emitir `llm_response` de la redacción con `stop_reason`, la decisión (`REPLY`/`ESCALATE`), las herramientas pedidas y la regla `RN-009-03` o `RN-009-09`.
- **Refactor:** —

### [x] T-009-12 — Desconexión de la página sin cortar acciones

- **Cubre:** AC-009-13
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-11
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_disconnect.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_disconnect.py::test_ac_009_13_disconnect_during_draft_stops_without_escalating`. Además, `test_ac_009_13_disconnect_during_decision_does_not_cut_actions` (cancelar mientras `FakeBankingTools` ejecuta `iniciar_disputa`: la disputa termina, se guarda y no se llama a `stream`).
- **Red:** cancelar el consumidor (`aclose()`/`CancelledError`) corta la decisión, o tras la desconexión se vuelve a llamar al LLM o se deriva.
- **Green:** decisión en una tarea propia con `asyncio.shield`. En `finally`, ante un cierre sin evento final: cerrar el flujo del LLM, auditar `reply_shown` `CLIENT_DISCONNECTED`, añadir al historial el texto parcial enviado y guardar sin derivar. El siguiente mensaje a la misma conversación se atiende normalmente.
- **Refactor:** —

### [x] T-009-13 — `AnthropicLLMAdapter.stream` con historial aplanado

- **Cubre:** habilita AC-009-01, AC-009-09 en producción (plan §1, decisión "aplanar")
- **App / capa:** `dispute_agent` / `infrastructure/outbound`
- **Depende de:** T-009-02
- **Archivos:** `src/dispute_agent/infrastructure/outbound/llm/anthropic_llm_adapter.py`, `tests/integration/dispute_agent/llm/test_anthropic_stream_adapter.py`, `tests/integration/dispute_agent/llm/test_anthropic_llm_live.py`
- **Test primero:** `tests/integration/dispute_agent/llm/test_anthropic_stream_adapter.py::test_stream__flattened_history_without_tools__yields_deltas_and_stop_reason` (`httpx.MockTransport` que sirve un SSE de la Messages API)
- **Red:** `stream` no existe. El test comprueba que la petición no lleva `tools`, que los bloques `tool_use`/`tool_result` del historial viajan como texto (`[herramienta …]`/`[resultado …]`), que se emiten los deltas y luego un `LLMStreamEnd` con `stop_reason`, y que el `tool_use` final se mapea a `tool_calls`. Otro test: un error HTTP o un corte del SSE ⇒ `LLMError` sin detalles.
- **Green:** `client.messages.stream(model, max_tokens, system, messages=_flatten_for_drafting(...))` y la traducción de eventos. Prueba opcional `@pytest.mark.llm` en `test_anthropic_llm_live.py` que redacta en streaming con Claude real.
- **Refactor:** compartir la serialización de texto con `_serialize_message`.

### [x] T-009-14 — `AsyncioSleeper`

- **Cubre:** habilita AC-009-10 en producción
- **App / capa:** `dispute_agent` / `infrastructure/outbound`
- **Depende de:** T-009-01
- **Archivos:** `src/dispute_agent/infrastructure/outbound/clock/asyncio_sleeper.py`, `tests/integration/dispute_agent/clock/test_asyncio_sleeper.py`
- **Test primero:** `tests/integration/dispute_agent/clock/test_asyncio_sleeper.py::test_asyncio_sleeper__short_sleep__waits_and_is_cancellable`
- **Red:** `AsyncioSleeper` no existe.
- **Green:** clase que delega en `asyncio.sleep`.
- **Refactor:** —

### [x] T-009-15 — Configuración `llm_stream_idle_timeout_seconds`

- **Cubre:** AC-009-10 (integración, spec §7.3)
- **App / capa:** `dispute_agent` / cableado (`config.py`)
- **Depende de:** —
- **Archivos:** `src/dispute_agent/config.py`, `tests/integration/dispute_agent/web/test_agent_settings.py`
- **Test primero:** `tests/integration/dispute_agent/web/test_agent_settings.py::test_ac_009_10_stream_idle_timeout_defaults_to_30_and_reads_env`
- **Red:** `AgentSettings` no tiene el campo.
- **Green:** `llm_stream_idle_timeout_seconds: float = 30`, leído de `LLM_STREAM_IDLE_TIMEOUT_SECONDS`.
- **Refactor:** —

### [x] T-009-16 — Router `POST /api/chat/stream` y cableado

- **Cubre:** AC-009-01, AC-009-08 (y el contrato de spec §7.1)
- **App / capa:** `dispute_agent` / `infrastructure/inbound` + cableado (`main.py`)
- **Depende de:** T-009-12, T-009-13, T-009-14, T-009-15
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/api/chat_stream_router.py`, `src/dispute_agent/infrastructure/inbound/web/api/schemas.py`, `src/dispute_agent/main.py`, `tests/integration/dispute_agent/web/test_chat_stream_api.py`
- **Test primero:** `tests/integration/dispute_agent/web/test_chat_stream_api.py::test_ac_009_01_stream_endpoint_emits_sse_events` (`TestClient` con `FakeLLM` en streaming y `VirtualSleeper`: `200`, `text/event-stream`, eventos `start`/`word`/`end` con los campos de §7.1). Además, `test_ac_009_08_invalid_input_fails_before_streaming` (filas `422`, `422`, `404`, sin llamadas al LLM) y una regresión de que `POST /api/chat` no cambia (AC-007-31).
- **Red:** la ruta no existe (`404`/`405`).
- **Green:** router con `ChatRequest`, `prepare` ⇒ `404` y `StreamingResponse` que serializa `event:`/`data:` con los esquemas `Stream*Out`. En `main.py`: `_LazyAnthropicLLM.stream`, `StreamCustomerMessage` con `AsyncioSleeper` (parámetro opcional `sleeper` en `create_app`) y `settings.llm_stream_idle_timeout_seconds`, e `include_router`.
- **Refactor:** —

### [x] T-009-17 — Arnés de navegador: `ChatApiScript` con SSE y `ChatStreamScript` progresivo

- **Cubre:** habilita AC-009-15 a AC-009-30 y conserva AC-008-* (plan §2, riesgos "page.route" y "pruebas de la 008")
- **App / capa:** soporte de tests (navegador)
- **Depende de:** —
- **Archivos:** `tests/fakes/chat_api_script.py`, `tests/fakes/chat_stream_script.py`, `tests/e2e/web/conftest.py`, `tests/e2e/web/test_chat_page_harness.py`
- **Test primero:** `tests/e2e/web/test_chat_page_harness.py::test_chat_stream_script__scripted_events__arrive_progressively` (desde la página, un `fetch` a `/api/chat/stream` lee `start` antes de que se libere el primer `word`). Además, `test_chat_api_script__json_reply__is_translated_to_sse_on_stream_route`.
- **Red:** `ChatStreamScript` no existe y `ChatApiScript` no intercepta `**/api/chat/stream`.
- **Green:** `ChatStreamScript`, una app ASGI que envuelve la app real y responde `POST /api/chat/stream` con eventos encolados por prueba (demoras, `hold`/`release`, cierre abrupto, evento inválido, código de error). Las demás rutas van a la app real. `ChatApiScript` intercepta **también** `**/api/chat/stream` y traduce cada JSON encolado a SSE (`start`, un `word` por palabra de `reply`, `end`), o devuelve el código de error tal cual. El servidor en vivo de `conftest.py` sirve la app envuelta. Los AC-008 siguen verdes sin cambios.
- **Refactor:** —

### [x] T-009-18 — Página: respuesta palabra por palabra desde `/api/chat/stream`

- **Cubre:** AC-009-15, AC-009-16, AC-009-17, AC-009-18, AC-009-24, AC-009-30
- **App / capa:** `dispute_agent` / `infrastructure/inbound` (estáticos)
- **Depende de:** T-009-16, T-009-17
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_streaming.py`, `tests/e2e/web/test_chat_page_messaging.py`, `tests/e2e/web/test_chat_page_failures.py`, `tests/e2e/web/test_chat_page_language.py`
- **Test primero:** `tests/e2e/web/test_chat_page_streaming.py::test_ac_009_15_reply_appears_word_by_word`. Además: `test_ac_009_16_typing_indicator_until_first_word`, `test_ac_009_17_streamed_content_is_plain_and_exact` (5 filas), `test_ac_009_18_masked_data_shown_as_received`, `test_ac_009_24_only_drafted_reply_streams` y `test_ac_009_30_no_account_data_without_identity`.
- **Red:** la página sigue llamando a `/api/chat` y pinta la respuesta de una vez.
- **Green:** `fetch` a `/api/chat/stream`, lector SSE con `getReader()` y `TextDecoder`, y burbuja borrador en `#draft` (fuera de la región viva) a la que se añaden fragmentos con `textContent`. El indicador se ve hasta la primera palabra. En `end`, el texto pasa a ser `reply` y la burbuja se mueve a `#conversation`. Los AC-008 que comprueban la URL de la petición pasan a `/api/chat/stream` (enmienda de RN-008-01).
- **Refactor:** aislar el analizador SSE en una función pura de `chat.js`.

### [x] T-009-19 — Página: bloqueo de envío, derivación al final e interrupción

- **Cubre:** AC-009-19, AC-009-20, AC-009-21
- **App / capa:** `dispute_agent` / `infrastructure/inbound` (estáticos)
- **Depende de:** T-009-18
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_streaming_closing.py`
- **Test primero:** `tests/e2e/web/test_chat_page_streaming_closing.py::test_ac_009_19_cannot_send_while_reply_streams`. Además, `test_ac_009_20_escalation_notice_after_last_word` y `test_ac_009_21_interrupted_reply_is_marked_incomplete`.
- **Red:** se puede enviar a mitad de la respuesta, el aviso aparece antes de la última palabra o no existe la marca `Incompleto`.
- **Green:** `pending` hasta el evento final. El foco vuelve a la caja tras `end` `ACTIVE`. El aviso de derivación se pinta al llegar `end` `ESCALATED`. Con `interrupted`: marca `Incompleto` en el borrador, burbuja fija completa, aviso y cierre.
- **Refactor:** —

### [x] T-009-20 — Página: lector de pantalla y movimiento reducido

- **Cubre:** AC-009-22, AC-009-23
- **App / capa:** `dispute_agent` / `infrastructure/inbound` (estáticos)
- **Depende de:** T-009-19
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_streaming_accessibility.py`
- **Test primero:** `tests/e2e/web/test_chat_page_streaming_accessibility.py::test_ac_009_22_screen_reader_announces_reply_once` (un `MutationObserver` registra las mutaciones de las regiones `aria-live`). Además, `test_ac_009_23_reduced_motion_shows_reply_at_end` (contexto con `reduced_motion="reduce"`).
- **Red:** hay mutaciones en la región viva por palabra, o con movimiento reducido las palabras se muestran.
- **Green:** asegurar que `#draft` no está dentro de ninguna región viva y que la burbuja se inserta completa una sola vez. Con `matchMedia('(prefers-reduced-motion: reduce)')`, el borrador queda oculto y el indicador se mantiene hasta el final.
- **Refactor:** —

### [x] T-009-21 — Página: espera por palabra, sin conexión y fallas del flujo

- **Cubre:** AC-009-25, AC-009-26, AC-009-27, AC-009-28
- **App / capa:** `dispute_agent` / `infrastructure/inbound` (estáticos)
- **Depende de:** T-009-20
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `tests/e2e/web/test_chat_page_streaming_failures.py`
- **Test primero:** `tests/e2e/web/test_chat_page_streaming_failures.py::test_ac_009_25_wait_without_new_words` (filas 59, 60 y 61 s con `page.clock`). Además: `test_ac_009_26_each_word_restarts_wait`, `test_ac_009_27_connection_lost_while_streaming` y `test_ac_009_28_stream_fails_before_finishing` (flujo cortado, evento inválido, `503`, `404`).
- **Red:** el temporizador no se reinicia por palabra, la página no reacciona a `offline` a mitad del flujo, o el texto parcial no se marca `Incompleto` y el mensaje de la cliente sí se marca `No enviado`.
- **Green:** rearmar el `setTimeout` de 60 s en cada `word`. Escuchar `offline` y abortar con el `AbortController`. Clasificar un flujo cortado o un evento inválido como "servicio no disponible". Aplicar RN-009-24 al borrador y al mensaje de la cliente. `Reintentar` reenvía la misma petición.
- **Refactor:** —

### [x] T-009-22 — Página: sin texto residual al recargar o empezar de nuevo

- **Cubre:** AC-009-29
- **App / capa:** `dispute_agent` / `infrastructure/inbound` (estáticos)
- **Depende de:** T-009-21
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `tests/e2e/web/test_chat_page_streaming_reset.py`
- **Test primero:** `tests/e2e/web/test_chat_page_streaming_reset.py::test_ac_009_29_no_residual_words_after_reload_or_new_conversation` (filas: recargar; `interrupted` seguido de `word` tardíos y luego `Iniciar una conversación nueva`)
- **Red:** aparecen palabras del flujo anterior tras empezar de nuevo.
- **Green:** ignorar los eventos de flujos terminados o abandonados (`currentAttempt`), abortar el flujo en `startNewConversation` y vaciar `#draft`.
- **Refactor:** —

### [x] T-009-23 — E2E con el servidor MCP real: sin datos antes de verificar

- **Cubre:** AC-009-14
- **App / capa:** `dispute_agent` / end-to-end
- **Depende de:** T-009-16
- **Archivos:** `tests/e2e/test_chat_stream_e2e.py`
- **Test primero:** `tests/e2e/test_chat_stream_e2e.py::test_ac_009_14_unverified_stream_has_no_account_data`
- **Red:** falla si la entrada de la redacción o los fragmentos contienen resultados de transacciones, `****` o datos de clientes de las semillas. Si el comportamiento ya cumple, el test debe verse fallar primero con una aserción invertida temporal, que se documenta en el resultado de la tarea.
- **Green:** `create_app` con el servidor MCP real por stdio (como `tests/e2e/test_chat_e2e.py`), `FakeLLM` (ciclo que pide el documento + redacción) y `TestClient` sobre `/api/chat/stream`. Si falta algo en producción, se corrige en el componente responsable.
- **Refactor:** —

### [x] T-009-24 — Specs vivas: enmiendas a 007 y 008

- **Cubre:** Art. 2 / §4.3.3 (plan §2: specs 007 y 008)
- **App / capa:** documentación de specs
- **Depende de:** T-009-18
- **Archivos:** `specs/007-dispute-resolution-agent/spec.md`, `specs/008-chat-web-page/spec.md`
- **Test primero:** `tests/e2e/web/test_chat_page_messaging.py` (regresión: los AC-008 actualizados a `/api/chat/stream` siguen verdes con la spec enmendada)
- **Red:** — (tarea documental, sin código de producción: alinea la spec viva con el comportamiento de T-009-18)
- **Green:** en la 008 (versión 0.2.0): RN-008-01 y §7.1 (la página usa `POST /api/chat/stream`, spec 009), RN-008-16 b (60 s desde la última palabra, RN-009-22), §7.2 (`Incompleto`) y la fila de historial. En la 007: fila de historial (`POST /api/chat/stream` y evento `reply_shown`, que amplía RN-007-28, spec 009). Sin otros cambios de comportamiento.
- **Refactor:** —

### [x] T-009-26 — Derivación por interrupción protegida frente a la desconexión

- **Cubre:** AC-009-13 (RN-009-12, Art. 10; riesgo alto del plan §7). Tarea añadida tras T-009-12, que dejó sin proteger la derivación de `_interrupt`.
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-009-12
- **Archivos:** `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_disconnect.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_stream_customer_message_disconnect.py::test_ac_009_13_disconnect_during_interruption_escalation_does_not_cut_it`
- **Red:** si la cliente se desconecta (cancelación o `aclose()`) mientras `_interrupt` espera a `escalar_a_analista` tras una falla de la redacción, la derivación se corta a medias: la conversación no queda cerrada o el turno no queda guardado.
- **Green:** `fail_turn` y el guardado de la interrupción corren en una tarea propia esperada con `asyncio.shield`, igual que la decisión. Ante una cancelación se espera a que termine y luego se re-lanza. La conversación queda derivada, cerrada y guardada.
- **Refactor:** compartir con `_decide_shielded` el patrón de "esperar la tarea aunque se cancele al consumidor".

### [x] T-009-27 — Spec 008: alinear la URL en RN-008-15 y en los AC

- **Cubre:** Art. 2 / §4.3.4 (la divergencia entre spec y código es un defecto). Tarea añadida tras T-009-24, que dejó `POST /api/chat` en RN-008-15 y en los textos de varios AC mientras los tests verifican `POST /api/chat/stream`.
- **App / capa:** documentación de specs
- **Depende de:** T-009-24
- **Archivos:** `specs/008-chat-web-page/spec.md`
- **Test primero:** `tests/e2e/web/test_chat_page_messaging.py` (regresión: los AC-008 siguen verdes; solo cambia el texto de la spec)
- **Red:** — (tarea documental)
- **Green:** en la spec 008 sustituir `POST /api/chat` por `POST /api/chat/stream` en RN-008-15 y en los AC-008-01, -02, -03, -06, -10, -16 y -20 (peticiones de la página), sin cambiar su semántica. Se conservan `POST /api/chat` en el contexto del §1, en AC-008-25 (comprueba que el contrato de `POST /api/chat` sigue vigente, AC-007-31) y en el historial de clarificaciones del §9. Fila nueva en el historial de cambios (0.2.1, PATCH).
- **Refactor:** —

### [x] T-009-28 — Comentarios de trazabilidad pendientes en los tests

- **Cubre:** `mcp-testing.md` §4 y constitución §4.3.2 (trazabilidad de tests a RN y AC). Tarea añadida antes del cierre: los tests de T-009-01, T-009-03, T-009-04 y T-009-06 no llevan el comentario `Regla:` / `AC-009-XX · Art. N`, y el de T-009-01 cita `RN-009-14` en lugar de `RN-009-09`.
- **App / capa:** soporte de tests (solo comentarios y docstrings)
- **Depende de:** T-009-01, T-009-03, T-009-04, T-009-06
- **Archivos:** `tests/unit/dispute_agent/application/test_virtual_sleeper.py`, `tests/unit/dispute_agent/domain/test_incremental_redaction.py`, `tests/unit/dispute_agent/application/test_drafting_prompt.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_decide_turn.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_virtual_sleeper.py` (los mismos tests, sin cambio de comportamiento)
- **Red:** — (solo comentarios: ningún test cambia lo que verifica)
- **Green:** añadir sobre cada test el comentario `# Regla: RN-009-XX — <enunciado corto>` y `# AC-009-XX · Art. N`, con la regla y el AC que el test realmente verifica: `RN-009-09`/`AC-009-10` para el sleeper virtual, `RN-009-06/07/08` y `AC-009-05/06` para el redactor incremental, `RN-009-03` y `AC-009-03/04` para el prompt de redacción, y `RN-009-02/03` y los AC de T-009-04 (`AC-009-02/03/07/09`) para `decide_turn`/`fail_turn`.
- **Refactor:** —

### [x] T-009-25 — Verificación final

- **Cubre:** Definition of Done (§5.5)
- **App / capa:** —
- **Depende de:** T-009-01, T-009-02, T-009-03, T-009-04, T-009-05, T-009-06, T-009-07, T-009-08, T-009-09, T-009-10, T-009-11, T-009-12, T-009-13, T-009-14, T-009-15, T-009-16, T-009-17, T-009-18, T-009-19, T-009-20, T-009-21, T-009-22, T-009-23, T-009-24, T-009-26, T-009-27, T-009-28
- **Archivos:** — (solo lectura)
- **Test primero:** `uv run pytest --cov`
- **Red:** —
- **Green:** `uv run pytest --cov` (cobertura ≥ 90 % en `domain` + `application` y ≥ 80 % global), `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`, todo sin errores.
- **Refactor:** —

### [x] T-009-29 — Correcciones de la auditoría de AC (H-01 a H-04 y H-06)

- **Cubre:** hallazgos H-01, H-02, H-03, H-04 y H-06 del primer informe de `verify-ac-coverage 009` (trazabilidad de tests; spec enmendada a 0.1.1 por decisión del usuario). Tarea añadida tras la auditoría.
- **App / capa:** soporte de tests (solo comentarios, docstrings y `ids=` de parametrizados)
- **Depende de:** T-009-28
- **Archivos:** `tests/unit/dispute_agent/application/test_stream_customer_message.py`, `tests/unit/dispute_agent/application/test_stream_customer_message_audit.py`, `tests/unit/dispute_agent/application/test_drafting_prompt.py`, `tests/unit/dispute_agent/application/test_fake_llm_stream.py`, `tests/unit/dispute_agent/application/test_virtual_sleeper.py`, `tests/integration/dispute_agent/web/test_chat_stream_api.py`, `tests/e2e/web/test_chat_page_harness.py`, `tests/e2e/web/test_chat_page_streaming_failures.py`, `tests/e2e/web/test_chat_page_streaming_reset.py`
- **Test primero:** los mismos tests existentes, sin cambio de lo que verifican.
- **Red:** — (solo comentarios, docstrings e `ids=`)
- **Green:** H-01 (líneas `Regla:` y `AC-` que faltan), H-02 (citar el AC cuyo `Cubre:` incluye la RN), H-03 (los tests de soporte citan `Soporte de tests`), H-04 (documentar en el test de AC-009-29 que el `interrupted` sin `outcomes` es válido según spec §7.1 v0.1.1) y H-06 (`ids=` legibles).
- **Refactor:** —
- **No incluida (H-05, Menor):** renombrar los tests de integración y e2e al patrón `test_<tool>__<condition>__<expected_outcome>`. Los tests `test_ac_NNN_XX_*` siguen la convención de `tasks-feature`, de la constitución §4.3.2 y de la spec 008 ya auditada; se deja como decisión del usuario.

### [x] T-009-30 — Renombrar los tests de integración y e2e al patrón de la rule (H-05)

- **Cubre:** hallazgo H-05 de `verify-ac-coverage 009` (`mcp-testing.md` §3: `test_<tool>__<condition>__<expected_outcome>`). Decisión del usuario: renombrar.
- **App / capa:** soporte de tests (solo nombres de funciones de test y docstring)
- **Depende de:** T-009-29
- **Archivos:** `tests/integration/dispute_agent/web/test_chat_stream_api.py`, `tests/integration/dispute_agent/web/test_agent_settings.py`, `tests/integration/dispute_agent/llm/test_anthropic_llm_live.py`, `tests/e2e/test_chat_stream_e2e.py`, `tests/e2e/web/test_chat_page_streaming.py`, `tests/e2e/web/test_chat_page_streaming_accessibility.py`, `tests/e2e/web/test_chat_page_streaming_closing.py`, `tests/e2e/web/test_chat_page_streaming_failures.py`, `tests/e2e/web/test_chat_page_streaming_reset.py`
- **Test primero:** los mismos tests, con nombre nuevo y sin cambio de lo que verifican.
- **Red:** — (solo nombres)
- **Green:** renombrar cada test `test_ac_009_NN_*` de esos archivos al patrón de la rule (el AC sigue citado en el comentario `# AC-009-NN`), alinear el docstring de `test_chat_stream_api.py` que dice AC-009-01 en el test de `interrupted`, y actualizar la matriz de trazabilidad de este archivo con los nombres nuevos.
- **Refactor:** —

## Seguimiento durante la implementación

Resuelto:

- Trazabilidad de los tests de T-009-01, 03, 04 y 06 (`Regla:` / `AC-009-XX · Art. N`, y `RN-009-14` → `RN-009-09`): resuelto en T-009-28.
- `_clean_outcome` privado importado por `StreamCustomerMessage`: se hizo público (`clean_outcome`) en T-009-11. `repo` e `ids` se cablearon en T-009-16.
- Los 2 errores de `mypy --strict` en `src/dispute_agent/main.py` (desde T-009-02): resueltos en T-009-16.
- Nota de la derivación con la causa (spec §8): T-009-11. Derivación de la interrupción protegida frente a la desconexión: T-009-26. URL de la página en la spec 008: T-009-24 y T-009-27.

Desviaciones a constar en el informe de cierre:

- T-009-17: el subagente escribió código y tests en el mismo paso y no ejecutó el Red por separado (desviación del Art. 3). Las pruebas de T-009-18 en adelante ejercen ese arnés y lo validan de forma indirecta.
- T-009-21: el subagente escribió el Green antes del Red, lo detectó, revirtió `chat.js` y obtuvo el Red real antes de continuar (sin desviación final).
- T-009-08, T-009-19, T-009-20, T-009-21, T-009-22 y T-009-23: algunos tests pasaron a la primera porque el comportamiento ya estaba cubierto por tareas anteriores. En esos casos el Red se provocó con mutaciones temporales de producción, documentadas por cada subagente, y se restauró el código.
- T-009-11 necesitó ampliar sus archivos para ajustar una aserción de T-009-07 que contradecía RN-009-11 (el `llm_response` de la redacción queda entre `stream` y `reply_shown`).
- Punto a confirmar: las respuestas fijas sin redacción (RN-009-04) no registran `reply_shown`, porque RN-009-11 lo liga al fin de una redacción.

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-009-01 | T-009-07, T-009-16 | `test_ac_009_01_reply_streams_word_by_word`, `test_chat_stream__valid_input__emits_start_word_and_end_events` |
| AC-009-02 | T-009-07 | `test_ac_009_02_no_text_is_sent_while_the_loop_runs` |
| AC-009-03 | T-009-07 | `test_ac_009_03_decisions_and_actions_happen_before_first_word` |
| AC-009-04 | T-009-06, T-009-07 | `test_ac_009_04_drafting_prompt_forbids_claiming_actions_outside_outcomes`, `test_ac_009_04_draft_text_never_triggers_actions` |
| AC-009-05 | T-009-03, T-009-07 | `test_ac_009_05_words_are_never_split_or_altered`, `test_ac_009_05_stream_concatenation_equals_reply` |
| AC-009-06 | T-009-03 | `test_ac_009_06_filter_applies_before_each_word`, `test_ac_009_06_any_chunking_matches_full_redaction` |
| AC-009-07 | T-009-08 | `test_ac_009_07_fixed_replies_are_sent_whole_without_drafting` |
| AC-009-08 | T-009-16 | `test_chat_stream__invalid_input__fails_before_streaming` |
| AC-009-09 | T-009-05, T-009-09 | `test_ac_009_09_draft_end_is_complete_only_with_end_turn_text_and_no_tools`, `test_ac_009_09_interrupted_draft_escalates_and_closes`, `test_chat_stream__draft_cut__emits_interrupted_event` |
| AC-009-10 | T-009-10, T-009-15 | `test_ac_009_10_idle_timeout_borders`, `test_ac_009_10_idle_timeout_is_configurable`, `test_agent_settings__stream_idle_timeout__defaults_to_30_and_reads_env` |
| AC-009-11 | T-009-05, T-009-09 | `test_ac_009_11_invalid_draft_without_words_escalates` |
| AC-009-12 | T-009-11 | `test_ac_009_12_reply_shown_is_audited_masked` |
| AC-009-13 | T-009-12, T-009-26 | `test_ac_009_13_disconnect_during_draft_stops_without_escalating`, `test_ac_009_13_disconnect_during_decision_does_not_cut_actions`, `test_ac_009_13_disconnect_during_interruption_escalation_does_not_cut_it` |
| AC-009-14 | T-009-23 | `test_chat_stream__unverified_customer__has_no_account_data` |
| AC-009-15 | T-009-18 | `test_chat_page__reply_streams__appears_word_by_word` |
| AC-009-16 | T-009-18 | `test_chat_page__before_first_word__shows_typing_indicator` |
| AC-009-17 | T-009-18 | `test_chat_page__streamed_content__is_plain_text_and_exact` |
| AC-009-18 | T-009-18 | `test_chat_page__masked_data_in_stream__is_shown_as_received` |
| AC-009-19 | T-009-19 | `test_chat_page__reply_streaming__blocks_sending` |
| AC-009-20 | T-009-19 | `test_chat_page__escalated_reply_ends__shows_notice_after_last_word` |
| AC-009-21 | T-009-19 | `test_chat_page__reply_interrupted__is_marked_incomplete`, `test_chat_page__interrupted_without_words__shows_only_reply_and_notice` |
| AC-009-22 | T-009-20 | `test_chat_page__reply_streams__screen_reader_announces_once` |
| AC-009-23 | T-009-20 | `test_chat_page__reduced_motion__shows_reply_at_end` |
| AC-009-24 | T-009-18 | `test_chat_page__reply_types__only_drafted_reply_streams` |
| AC-009-25 | T-009-21 | `test_chat_page__waiting_without_new_words__shows_delay_notice` |
| AC-009-26 | T-009-21 | `test_chat_page__each_word_arrives__restarts_the_wait`, `test_chat_page__no_new_words_for_60s__shows_delay_notice_and_marks_incomplete` |
| AC-009-27 | T-009-21 | `test_chat_page__connection_lost_while_streaming__marks_reply_incomplete` |
| AC-009-28 | T-009-21 | `test_chat_page__stream_fails_before_finishing__shows_error`, `test_chat_page__http_503_before_streaming__shows_error`, `test_chat_page__http_404_before_streaming__closes_conversation` |
| AC-009-29 | T-009-22 | `test_chat_page__reload_or_new_conversation_mid_stream__leaves_no_residual_words`, `test_chat_page__words_arrive_after_end__are_ignored` |
| AC-009-30 | T-009-18 | `test_chat_page__no_verified_identity__shows_no_account_data` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde (auditoría `verify-ac-coverage`: Cumple, 30/30 AC y 26/26 RN).
- [x] Umbrales de cobertura cumplidos (total 97,12 %; `domain` + `application` de ambas apps ≥ 95 %).
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado (spec 009 en 0.1.1; specs 007 en 0.2.1 y 008 en 0.2.1).
- [x] Sin secretos ni datos reales.
