# Tareas: Corregir los argumentos que el core rechaza en lugar de derivar el caso

| Campo | Valor |
|---|---|
| Feature | `010-invalid-input-correction` |
| Spec | [spec.md](./spec.md) — versión 0.1.1 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-19 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Abreviaturas de archivos de test nuevos: **U-IN** = `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`, **U-AUD** = `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py`.

---

## Tareas

### [x] T-010-01 — `BankingToolError.field` y builder `invalid_input`

- **Cubre:** habilita AC-010-01 a AC-010-12 (error con campo; plan §2, §3)
- **App / capa:** `dispute_agent` / `application` (puerto) + soporte de tests
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/ports/banking_tools.py`, `tests/fakes/banking_errors.py`, `tests/unit/dispute_agent/application/test_banking_tool_error.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_banking_tool_error.py::test_banking_tool_error__field_argument__is_kept_and_defaults_to_none`
- **Red:** `BankingToolError` no acepta `field` (`TypeError`) y `tests.fakes.banking_errors` no existe. El test comprueba que sin `field` el atributo es `None`, que con `field="date_to"` se conserva y que `invalid_input("date_to")` devuelve un error con `code = "INVALID_INPUT"`, `retryable = False` y ese campo.
- **Green:** parámetro opcional `field: str | None = None` en `BankingToolError.__init__` (atributo `field`); builder `invalid_input(field, message=None)` en `tests/fakes/banking_errors.py`.
- **Refactor:** —

### [x] T-010-02 — Contador de correcciones en `Conversation`

- **Cubre:** AC-010-06 (parte de dominio: el contador es del turno)
- **App / capa:** `dispute_agent` / `domain`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/domain/models/conversation.py`, `tests/unit/dispute_agent/domain/test_conversation.py`
- **Test primero:** `tests/unit/dispute_agent/domain/test_conversation.py::test_ac_010_06_conversation__register_invalid_input__counts_and_begin_turn_resets`
- **Red:** `Conversation` no tiene `turn_invalid_inputs` ni `register_invalid_input()`. El test espera que una conversación nueva tenga 0, que `register_invalid_input()` devuelva 1, 2 y 3 en llamadas sucesivas y que `begin_turn()` lo devuelva a 0.
- **Green:** atributo `turn_invalid_inputs: int = 0`, método `register_invalid_input() -> int` que incrementa y devuelve el valor, y reinicio en `begin_turn()`.
- **Refactor:** —

### [x] T-010-03 — Paso y texto fijo `INVALID_SEARCH`

- **Cubre:** AC-010-08 (parte de dominio: selector y texto fijo)
- **App / capa:** `dispute_agent` / `domain`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/domain/identification.py`, `src/dispute_agent/domain/messages.py`, `tests/unit/dispute_agent/domain/test_identification.py`
- **Test primero:** `tests/unit/dispute_agent/domain/test_identification.py::test_ac_010_08_select_identification_reply__invalid_search_step__returns_fixed_text`
- **Red:** `IdentificationStep.INVALID_SEARCH` e `IdentificationReply.INVALID_SEARCH` no existen. El test espera que, con ese último paso del turno y la conversación `ACTIVE`, el selector devuelva `INVALID_SEARCH`; que `messages.IDENTIFICATION_REPLIES` tenga exactamente el texto de §7.4 de la spec 010; y que un paso posterior `LOCATED` en el mismo turno gane (último resultado, RN-007-41).
- **Green:** añadir el paso, la respuesta, la entrada en `_STEP_REPLIES` y el texto `Esos datos no son válidos. Revísalos e indícame tu número de documento, tu nombre completo o los últimos 4 dígitos de tu tarjeta.`
- **Refactor:** —

### [x] T-010-04 — El adaptador MCP extrae el campo inválido

- **Cubre:** AC-010-12 (niveles contrato e integración)
- **App / capa:** `dispute_agent` / `infrastructure/outbound`
- **Depende de:** T-010-01
- **Archivos:** `src/dispute_agent/infrastructure/outbound/mcp/mcp_stdio_banking_adapter.py`, `tests/contract/dispute_agent/test_banking_client_contract.py`, `tests/integration/dispute_agent/mcp/test_mcp_stdio_banking_adapter.py`
- **Test primero:** `tests/contract/dispute_agent/test_banking_client_contract.py::test_ac_010_12_to_tool_error__invalid_input_messages__extracts_field` (parametrizado con los seis mensajes reales del servidor: `Los datos de la solicitud no son válidos (campo: X).`, `…de verificación…`, `…de búsqueda…`, `…de la consulta…`, más un mensaje sin `(campo: …)` ⇒ `None`). Después, `tests/integration/dispute_agent/mcp/test_mcp_stdio_banking_adapter.py::test_ac_010_12_list_transactions__future_date_to__raises_invalid_input_with_field` contra el servidor real por stdio.
- **Red:** `_to_tool_error` no rellena `field`: el contrato recibe `None` y la integración también, aunque el servidor responde `INVALID_INPUT` con `(campo: date_to)`.
- **Green:** expresión regular `\(campo:\s*([^)\s]+)\)` aplicada al mensaje solo si `code == "INVALID_INPUT"`; el resultado va a `BankingToolError(field=…)`. Sin coincidencia ⇒ `None`.
- **Refactor:** definir la regex como constante de módulo junto a `_ALREADY_OPEN_ID`.

### [x] T-010-05 — Helper `describe_failure`

- **Cubre:** habilita AC-010-10 (texto de la nota y del motivo de cierre, RN-010-08)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/failure_detail.py`, `tests/unit/dispute_agent/application/test_failure_detail.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_failure_detail.py::test_ac_010_10_describe_failure__with_and_without_field__builds_text`
- **Red:** el módulo `dispute_agent.application.failure_detail` no existe. El test espera `describe_failure("consultar_transacciones", "INTERNAL", None) == "falla irrecuperable en consultar_transacciones (INTERNAL)"` y `describe_failure("iniciar_disputa", "INVALID_INPUT", "transaction_id") == "falla irrecuperable en iniciar_disputa (INVALID_INPUT, campo: transaction_id)"`.
- **Green:** función pura `describe_failure(tool: str, code: str, field: str | None = None) -> str`.
- **Refactor:** —

### [x] T-010-06 — `DisputeActions`: campo en el registro y la nota de la falla

- **Cubre:** AC-010-10 (fila de `iniciar_disputa`), AC-010-11 (fila de `iniciar_disputa`)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-01, T-010-05
- **Archivos:** `src/dispute_agent/application/use_cases/dispute_actions.py`, `tests/unit/dispute_agent/application/test_dispute_actions.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_dispute_actions.py::test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates`
- **Red:** con `open_dispute` lanzando `invalid_input("transaction_id")`, el `tool_call` auditado trae `{"error": "INVALID_INPUT"}` sin `field`, y la nota y el motivo de `conversation_closed` no lo mencionan. El test espera `{"error": "INVALID_INPUT", "field": "transaction_id"}`, la nota `RN-007-21: falla irrecuperable en iniciar_disputa (INVALID_INPUT, campo: transaction_id)` y que siga derivando con `UNRECOVERABLE_SYSTEM_FAILURE` y cerrando (AC-010-11).
- **Green:** pasar `error.field` a `_audit_open` y a `_fail`; construir nota y motivo con `describe_failure`. Con `INTERNAL` o tiempo límite el texto actual no cambia.
- **Refactor:** —

### [x] T-010-07 — `FraudActions`: campo en el registro y la nota de la falla

- **Cubre:** AC-010-10 (fila de `bloquear_tarjeta`), AC-010-11 (fila de `bloquear_tarjeta`)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-01, T-010-05
- **Archivos:** `src/dispute_agent/application/use_cases/fraud_actions.py`, `tests/unit/dispute_agent/application/test_fraud_actions.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_fraud_actions.py::test_ac_010_10_block_card__invalid_input_with_field__audits_field_and_still_escalates`
- **Red:** con `block_card` lanzando `invalid_input("card_id")`, el `tool_call` no trae `field` y la nota no lo menciona. El test espera `{"error": "INVALID_INPUT", "field": "card_id"}`, la nota con `(INVALID_INPUT, campo: card_id)`, derivación `UNRECOVERABLE_SYSTEM_FAILURE` con `card_id` y conversación cerrada.
- **Green:** `error.field` hasta `_audit_call` y `_fail`; nota y motivo con `describe_failure`.
- **Refactor:** —

### [x] T-010-08 — `_read_failure` audita la herramienta y el código antes de derivar

- **Cubre:** AC-010-10 (filas de `consultar_transacciones`)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-01, T-010-05
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_audit.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_escalations.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py::test_ac_010_10_read_failure__internal_or_timeout__audits_tool_call_before_escalation` (2 filas: `INTERNAL` y tiempo límite).
- **Red:** `_read_failure` no registra ningún `tool_call`: la secuencia de eventos del turno pasa de `llm_response` a `escalation`. El test espera, antes de `escalation` y `conversation_closed` (orden verificado), un `tool_call` con `tool = "consultar_transacciones"`, `rule = "RN-007-21"` y salida `{"error": "INTERNAL"}` (o `UNAVAILABLE`).
- **Green:** en `_read_failure`, emitir el `tool_call` con `_audit_call` y construir la nota y el motivo con `describe_failure`. Se ajustan, con referencia a RN-010-08, los tests existentes de los archivos listados que cuenten los eventos de una falla de lectura.
- **Refactor:** —

### [x] T-010-09 — Corrección de `consultar_transacciones` rechazada

- **Cubre:** AC-010-01, AC-010-03, AC-010-07 (fila de `consultar_transacciones`), AC-010-09
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-01, T-010-03, T-010-08
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `src/dispute_agent/domain/messages.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py::test_ac_010_01_handle_message__list_transactions_invalid_input__llm_corrects_and_continues` (4 filas: `date_to` futuro, rango > 90 días, `date_from` > `date_to`, `card_last4` de 2 dígitos). Luego `test_ac_010_03_handle_message__invalid_input__llm_gets_fixed_text_without_values`, `test_ac_010_07_handle_message__list_invalid_input__nothing_is_assumed` (en U-IN) y `test_ac_010_09_handle_message__invalid_input__audits_correctable_tool_call` (en U-AUD).
- **Red:** `INVALID_INPUT` de `consultar_transacciones` va a `_read_failure`: se invoca `escalate`, la conversación queda `ESCALATED` y el LLM recibe `system_unavailable`. Los tests esperan un `tool_result` `invalid_input` con el campo y `corrections_remaining = 1`, la 2.ª consulta normal, `ACTIVE` sin `escalate`, el texto fijo sin documento ni valores, `evaluar_disputa` ⇒ `transaction_not_listed` sin `outcomes` de lista vacía, y el `tool_call` de RN-010-07 con regla `RN-010-01`.
- **Green:** en `_dispatch`, un `BankingToolError` con `code == "INVALID_INPUT"` de `_ListArgs` va a `_invalid_input`, que llama a `conv.register_invalid_input()`, audita el `tool_call` (RN-010-07) y devuelve el resultado de §7.2 con el texto fijo de `messages` (función `invalid_input_message(tool, field)`). El camino de agotamiento queda para T-010-11; aquí solo se atiende hasta el 2.º rechazo.
- **Refactor:** extraer el armado del `ToolResult` de §7.2 a una función privada junto a `_error`.

### [x] T-010-10 — Corrección de `buscar_cliente` rechazada y texto `INVALID_SEARCH`

- **Cubre:** AC-010-02, AC-010-07 (filas de `buscar_cliente`), AC-010-08 (nivel unitario del agente)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-03, T-010-09
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py::test_ac_010_02_handle_message__search_invalid_input__llm_corrects_and_locates`. Luego `test_ac_010_07_handle_message__search_invalid_input__does_not_count_as_failed_search` (rechazadas + búsqueda sin coincidencias ⇒ `ACTIVE`) y `test_ac_010_08_handle_message__unverified_after_search_invalid_input__fixed_invalid_search_reply`.
- **Red:** `INVALID_INPUT` de `buscar_cliente` aún deriva (T-010-09 solo desvió `consultar_transacciones`): `ESCALATED` y `reply` de cierre. Los tests esperan el error `invalid_input` con el campo, la 2.ª búsqueda que localiza a la cliente, `failed_searches` sin cambios y, al terminar el turno sin verificar, el `reply` `INVALID_SEARCH` sin llamar al LLM para redactarlo.
- **Green:** extender el desvío de `_dispatch` a `_SearchArgs` y, en `_invalid_input`, llamar a `conv.record_identification(IdentificationStep.INVALID_SEARCH)` solo para `buscar_cliente`.
- **Refactor:** —

### [x] T-010-11 — Tope de 2 correcciones y derivación al 3.er rechazo

- **Cubre:** AC-010-04, AC-010-05, AC-010-06
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-02, T-010-10
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py::test_ac_010_04_handle_message__third_invalid_input_in_list__escalates_insufficient_info`. Luego `test_ac_010_05_handle_message__third_invalid_input_in_search_unverified__limited_summary_and_closed_reply` y `test_ac_010_06_handle_message__shared_cap_and_reset_per_message__third_escalates_new_message_resets`.
- **Red:** el 3.er `INVALID_INPUT` del mensaje sigue devolviéndose al LLM (o el contador no se reinicia entre mensajes): no se invoca `escalate`. Los tests esperan `escalate` con `INSUFFICIENT_OR_CONTRADICTORY_INFO` y la nota `RN-010-04: <herramienta> INVALID_INPUT (campo: <campo>) tras 2 correcciones`, resumen completo sin transacción (verificada) o limitado (no verificada), un único `outcome` `ESCALATED` con regla `RN-010-04`, estado `ESCALATED`, `reply` de cierre en el caso sin verificar, contador combinado entre ambas herramientas y reinicio con un mensaje nuevo.
- **Green:** en `_invalid_input`, si `register_invalid_input()` devuelve más de 2, llamar a la rutina de derivación y cierre de `_read_failure` generalizada con motivo `INSUFFICIENT_OR_CONTRADICTORY_INFO`, regla `RN-010-04` y esa nota; devolver el mismo resultado de cierre `system_unavailable`.
- **Refactor:** unificar `_read_failure` y el camino de agotamiento en un único método parametrizado.

### [x] T-010-12 — Lo que no cambia sigue igual (caracterización)

- **Cubre:** AC-010-11
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-11
- **Archivos:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py::test_ac_010_11_handle_message__unchanged_failures__still_escalate_or_ask_dates` (filas: `iniciar_disputa` y `bloquear_tarjeta` con `INVALID_INPUT` ⇒ `UNRECOVERABLE_SYSTEM_FAILURE` y cierre, sin consumir el contador; `consultar_transacciones` con `INTERNAL` ⇒ deriva; `verificar_identidad` con `INVALID_INPUT` ⇒ `INVALID_DATES` sin derivar).
- **Red:** es una prueba de caracterización de comportamiento ya vigente; no introduce código de producción. Debe pasar desde el inicio y falla si T-010-09/10/11 ampliaron el desvío más allá de `consultar_transacciones` y `buscar_cliente`.
- **Green:** sin cambio de producción. Si alguna fila falla, el desvío de `_dispatch` es demasiado amplio y se corrige allí.
- **Refactor:** —

### [x] T-010-13 — `INVALID_SEARCH` por la API del chat

- **Cubre:** AC-010-08 (nivel de integración)
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-010-10
- **Archivos:** `tests/integration/dispute_agent/web/test_chat_identification_api.py`
- **Test primero:** `tests/integration/dispute_agent/web/test_chat_identification_api.py::test_ac_010_08_post_chat__search_invalid_input_unverified__replies_invalid_search_text`
- **Red:** prueba de integración sobre comportamiento ya implementado (sin código de producción propio). Con `FakeLLM` y core falso que responde `INVALID_INPUT` a `buscar_cliente`, `POST /api/chat` debe devolver `200`, `status = "ACTIVE"`, el `reply` `INVALID_SEARCH` y `outcomes = []`; falla si el texto fijo no llega por HTTP.
- **Green:** sin cambio de producción.
- **Refactor:** —

### [x] T-010-14 — Fecha futura con el servidor real (e2e)

- **Cubre:** AC-010-12 (nivel e2e)
- **App / capa:** `dispute_agent` y `core_banking_mcp` / end-to-end
- **Depende de:** T-010-04, T-010-09
- **Archivos:** `tests/e2e/test_chat_e2e.py`
- **Test primero:** `tests/e2e/test_chat_e2e.py::test_ac_010_12_chat__future_date_to_with_real_server__llm_corrects_and_conversation_stays_active`
- **Red:** reproduce el incidente `ESC-000010` de extremo a extremo (sin código de producción propio): con una cliente verificada y el `FakeLLM` pidiendo `consultar_transacciones` con `date_to = 2099-01-01` y luego con una fecha válida, antes de T-010-04/09 la conversación terminaba `ESCALATED`. Debe comprobar: la 2.ª consulta devuelve transacciones, el estado sigue `ACTIVE`, no hay derivación y la auditoría trae el `tool_call` de RN-010-07 con `field = "date_to"`.
- **Green:** sin cambio de producción.
- **Refactor:** —

### [x] T-010-15 — Spec 007 a 0.4.0 y `DECISIONES.md`

- **Cubre:** habilita AC-010-01 a AC-010-12 (coherencia spec ↔ código; Art. 2, §4.3.3)
- **App / capa:** documentación + `dispute_agent` / `domain` (prueba de coherencia)
- **Depende de:** T-010-03, T-010-11
- **Archivos:** `specs/007-dispute-resolution-agent/spec.md`, `docs/DECISIONES.md`, `tests/unit/dispute_agent/test_spec_007_texts.py`
- **Test primero:** `tests/unit/dispute_agent/test_spec_007_texts.py::test_spec_007__invalid_search_text_and_version__match_code`
- **Red:** la spec 007 está en 0.3.3 y su §7.4 no tiene la fila `INVALID_SEARCH`. El test espera que el texto de `messages.IDENTIFICATION_REPLIES[INVALID_SEARCH]` aparezca literal en el §7.4 de la spec 007 y que su versión sea `0.4.0`.
- **Green:** actualizar la spec 007 según plan §2 (RN-007-21 con la excepción de `consultar_transacciones` y `buscar_cliente` y referencia a la spec 010, RN-007-28, RN-007-38 paso 2, fila de §7.4, fila de §8, fila de historial 0.4.0) y añadir la fila en `docs/DECISIONES.md`. Sin cambio de código.
- **Refactor:** —

### [x] T-010-16 — Verificación final

- **Cubre:** todos los AC (cierre; constitución §5.5)
- **App / capa:** ambas
- **Depende de:** T-010-01, T-010-02, T-010-03, T-010-04, T-010-05, T-010-06, T-010-07, T-010-08, T-010-09, T-010-10, T-010-11, T-010-12, T-010-13, T-010-14, T-010-15
- **Archivos:** — (solo ejecuta comandos)
- **Test primero:** `uv run pytest --cov` (suite completa con umbrales de §5.4)
- **Red:** —
- **Green:** `uv run pytest --cov`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src` sin errores; cobertura de `domain` y `application` ≥ 90 % y global ≥ 80 %. La regresión de las specs 007 y 009 pasa sin modificar sus AC.
- **Refactor:** —

### [x] T-010-17 — Hallazgos H-01, H-03, H-04, H-06 y H-09 en los tests del agente (auditoría 5.5)

- **Cubre:** AC-010-04, AC-010-05, AC-010-07, AC-010-08, AC-010-11
- **App / capa:** `dispute_agent` / `application` (solo tests)
- **Depende de:** T-010-16
- **Archivos:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py`
- **Test primero:** `test_ac_010_07_handle_message__search_invalid_input_then_evaluate__customer_stays_unlocated` (H-01: `buscar_cliente` rechazada y luego `evaluar_disputa(TX-L1)`; `located_customer_id` y `verified_customer_id` siguen en `None`). `test_ac_010_07_handle_message__two_invalid_inputs_then_no_match__stays_active` (H-03: `invalid_input`, `invalid_input`, `_NO_MATCH`; `failed_searches == 1`, `ACTIVE`, sin `escalate`). Se refuerzan los existentes de AC-010-08 (H-04: `failed_searches == 0` y sin intento descontado), AC-010-04 y AC-010-05 (H-09: contenido del resumen completo y limitado según `escalation_service.py`, y `outcome` `ESCALATED` sin transacción) y se corrige la cita de AC-010-11 (H-06: `Regla: RN-010-09`).
- **Red:** son afirmaciones de comportamiento ya implementado (sin código de producción). Cada test nuevo o reforzado debe fallar si se rompe a propósito el comportamiento que verifica (por ejemplo, contar el rechazo como búsqueda fallida) y se revierte.
- **Green:** sin cambio de producción.
- **Refactor:** —

### [x] T-010-18 — Hallazgo H-05 en los tests de falla de herramienta (auditoría 5.5)

- **Bloqueo (resuelto):** el subagente halló que el `tool_call` de la falla de `iniciar_disputa` emitía la regla `DP-007-05` y no `RN-007-21` (RN-010-08). Decisión del usuario: alinear el código con la spec. La afirmación de regla pasa a T-010-20.

- **Cubre:** AC-010-10
- **App / capa:** `dispute_agent` / `application` (solo tests)
- **Depende de:** T-010-16
- **Archivos:** `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py`, `tests/unit/dispute_agent/application/test_dispute_actions.py`
- **Test primero:** se refuerza `test_ac_010_10_read_failure__internal_or_timeout__audits_tool_call_before_escalation`: además del `tool_call`, afirma la nota del `escalate` y el `reason` de `conversation_closed` (`falla irrecuperable en consultar_transacciones (INTERNAL)`; para el tiempo límite, el código `UNAVAILABLE`). Se refuerza `test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates`: afirma `rule == "RN-007-21"` y el orden `tool_call` → `escalation` → `conversation_closed`.
- **Red:** afirmaciones sobre comportamiento ya implementado; cada una debe fallar si se rompe a propósito la nota, la regla o el orden de eventos, y se revierte.
- **Green:** sin cambio de producción.
- **Refactor:** —

### [x] T-010-19 — Hallazgos H-02, H-07 y H-08: citas de trazabilidad en los tests (auditoría 5.5)

- **Cubre:** AC-010-06, AC-010-08, AC-010-10, AC-010-12
- **App / capa:** `dispute_agent` / tests de dominio, aplicación, contrato e integración (solo comentarios y docstrings)
- **Depende de:** T-010-16
- **Archivos:** `tests/unit/dispute_agent/domain/test_conversation.py`, `tests/unit/dispute_agent/domain/test_identification.py`, `tests/unit/dispute_agent/application/test_failure_detail.py`, `tests/unit/dispute_agent/application/test_banking_tool_error.py`, `tests/unit/dispute_agent/test_spec_007_texts.py`, `tests/contract/dispute_agent/test_banking_client_contract.py`, `tests/integration/dispute_agent/mcp/test_mcp_stdio_banking_adapter.py`
- **Test primero:** no aplica test nuevo: es solo trazabilidad (`mcp-testing.md`). La comprobación es que los tests citados siguen pasando y que cada uno cita una RN y un AC coherentes: `test_conversation.py` (AC-010-06 · `Regla: RN-010-03`), `test_identification.py` (AC-010-08 · `Regla: RN-010-06`), `test_failure_detail.py` (AC-010-10 · `Regla: RN-010-08`), `test_banking_tool_error.py` (AC-010-10 · `Regla: RN-010-08`), `test_spec_007_texts.py` (AC-010-08 · `Regla: RN-010-06`), contrato e integración (AC-010-12 · `Regla: RN-010-01`).
- **Red:** —
- **Green:** añadir o corregir las líneas `Regla:` y `AC-… · Art. N` indicadas, sin cambiar el comportamiento de ningún test.
- **Refactor:** —

### [x] T-010-20 — El `tool_call` de la falla de `iniciar_disputa` lleva la regla `RN-007-21` (divergencia de T-010-18)

- **Cubre:** AC-010-10 (fila de `iniciar_disputa`)
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-010-18
- **Archivos:** `src/dispute_agent/application/use_cases/dispute_actions.py`, `tests/unit/dispute_agent/application/test_dispute_actions.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_audit.py` (su `test_dispute_actions__open_dispute__audits_tool_call[error]` afirma la regla `DP-007-05` en la falla; se alinea con RN-010-08)
- **Test primero:** se completa `test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates` con `assert call.rule == "RN-007-21"` tras la afirmación de `call.output`, y se añade `test_ac_010_10_open_dispute__timeout__audits_tool_call_with_failure_rule` para el tiempo límite (`{"error": "UNAVAILABLE"}`, regla `RN-007-21`). Se comprueba que el éxito y `DISPUTE_ALREADY_OPEN` siguen emitiendo la regla de la decisión.
- **Red:** el `tool_call` de ambas fallas trae `DP-007-05` (`assert 'DP-007-05' == 'RN-007-21'`).
- **Green:** en `_audit_open`, usar `RN-007-21` como regla cuando la salida es una falla (`error` en la salida); sin cambio para el éxito ni `DISPUTE_ALREADY_OPEN`. Los tests existentes que afirmen la regla de la decisión en una falla se actualizan con referencia a RN-010-08.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-010-01 | T-010-09 | `test_ac_010_01_handle_message__list_transactions_invalid_input__llm_corrects_and_continues` |
| AC-010-02 | T-010-10 | `test_ac_010_02_handle_message__search_invalid_input__llm_corrects_and_locates` |
| AC-010-03 | T-010-09 | `test_ac_010_03_handle_message__invalid_input__llm_gets_fixed_text_without_values` |
| AC-010-04 | T-010-11 | `test_ac_010_04_handle_message__third_invalid_input_in_list__escalates_insufficient_info` |
| AC-010-05 | T-010-11 | `test_ac_010_05_handle_message__third_invalid_input_in_search_unverified__limited_summary_and_closed_reply` |
| AC-010-06 | T-010-02, T-010-11 | `test_ac_010_06_conversation__register_invalid_input__counts_and_begin_turn_resets`, `test_ac_010_06_handle_message__shared_cap_and_reset_per_message__third_escalates_new_message_resets` |
| AC-010-07 | T-010-09, T-010-10 | `test_ac_010_07_handle_message__list_invalid_input__nothing_is_assumed`, `test_ac_010_07_handle_message__search_invalid_input__does_not_count_as_failed_search` |
| AC-010-08 | T-010-03, T-010-10, T-010-13 | `test_ac_010_08_select_identification_reply__invalid_search_step__returns_fixed_text`, `test_ac_010_08_handle_message__unverified_after_search_invalid_input__fixed_invalid_search_reply`, `test_ac_010_08_post_chat__search_invalid_input_unverified__replies_invalid_search_text` |
| AC-010-09 | T-010-09 | `test_ac_010_09_handle_message__invalid_input__audits_correctable_tool_call` |
| AC-010-10 | T-010-05, T-010-06, T-010-07, T-010-08 | `test_ac_010_10_describe_failure__with_and_without_field__builds_text`, `test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates`, `test_ac_010_10_block_card__invalid_input_with_field__audits_field_and_still_escalates`, `test_ac_010_10_read_failure__internal_or_timeout__audits_tool_call_before_escalation` |
| AC-010-11 | T-010-06, T-010-07, T-010-12 | `test_ac_010_10_open_dispute__invalid_input_with_field__audits_field_and_still_escalates`, `test_ac_010_10_block_card__invalid_input_with_field__audits_field_and_still_escalates`, `test_ac_010_11_handle_message__unchanged_failures__still_escalate_or_ask_dates` |
| AC-010-12 | T-010-04, T-010-14 | `test_ac_010_12_to_tool_error__invalid_input_messages__extracts_field`, `test_ac_010_12_list_transactions__future_date_to__raises_invalid_input_with_field`, `test_ac_010_12_chat__future_date_to_with_real_server__llm_corrects_and_conversation_stays_active` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
