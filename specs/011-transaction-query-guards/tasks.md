# Tareas: Guardas en la consulta de transacciones: tarjeta propia, rango de 90 días y fecha actual

| Campo | Valor |
|---|---|
| Feature | `011-transaction-query-guards` |
| Spec | [spec.md](./spec.md) — versión 0.1.2 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-19 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Abreviaturas de archivos de test nuevos: **U-CG** = `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard.py`, **U-CGA** = `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard_audit.py`.

---

## Tareas

### [x] T-011-01 — Builder `not_found` para los tests

- **Cubre:** habilita AC-011-07, AC-011-08, AC-011-10 y AC-011-11 (error `NOT_FOUND` del core; plan §2)
- **App / capa:** `dispute_agent` / soporte de tests
- **Depende de:** —
- **Archivos:** `tests/fakes/banking_errors.py`, `tests/unit/dispute_agent/application/test_banking_tool_error.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_banking_tool_error.py::test_not_found_builder__returns_non_retryable_not_found_error`
- **Red:** `not_found` no existe en `tests.fakes.banking_errors` (`ImportError`). El test espera un `BankingToolError` con `code = "NOT_FOUND"`, `retryable = False` y `field = None`.
- **Green:** función `not_found(message=None)` en `tests/fakes/banking_errors.py`, junto a `invalid_input`.
- **Refactor:** —

### [x] T-011-02 — Textos fijos de `unknown_card` y `not_found`

- **Cubre:** AC-011-06 (parte de dominio: texto fijo, sin valores enviados)
- **App / capa:** `dispute_agent` / `domain`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/domain/messages.py`, `src/dispute_agent/domain/models/conversation.py`, `tests/unit/dispute_agent/domain/test_messages.py`
- **Test primero:** `tests/unit/dispute_agent/domain/test_messages.py::test_ac_011_06_unknown_card_message__lists_own_last4_only` y `::test_ac_011_07_not_found_card_message__is_fixed_text`
- **Red:** `messages.unknown_card_message` y `messages.NOT_FOUND_CARD_MESSAGE` no existen. El primer test espera que `unknown_card_message(("4321", "8765"))` sea exactamente el texto de §7.1 con `4321` y `8765`, y que con otra entrada no aparezca ningún otro dígito; el segundo, que la constante sea exactamente el texto de §7.2.
- **Green:** añadir la función y la constante con los textos de la spec; actualizar los docstrings de `Conversation.turn_invalid_inputs` y `register_invalid_input` (cuentan todas las correcciones del mensaje, RN-011-06). Sin cambio de comportamiento en `Conversation`.
- **Refactor:** —

### [x] T-011-03 — El LLM conoce el límite exacto del rango

- **Cubre:** AC-011-01
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/application/system_prompt.py`, `src/dispute_agent/application/agent_tools.py`, `tests/unit/dispute_agent/application/test_system_prompt.py`, `tests/unit/dispute_agent/application/test_agent_tools.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_agent_tools.py::test_ac_011_01_agent_tools__list_transactions_states_89_day_limit` y `tests/unit/dispute_agent/application/test_system_prompt.py::test_ac_011_01_decision_prompt__states_89_day_limit_and_default_date_from`
- **Red:** hoy la descripción de `consultar_transacciones` y la de `date_to` dicen «máximo 90 días» y el prompt «últimos 90 días». Los tests esperan «89 días» y «90 días contando ambos extremos» en ambas descripciones, `hoy - 89` en `build_decision_system(date(2026, 10, 19))` y que ningún texto contenga «últimos 90 días» sin esa precisión.
- **Green:** reescribir la regla 10 de `SYSTEM_PROMPT` y las descripciones de `agent_tools.py` con el texto de RN-011-01.
- **Refactor:** —

### [x] T-011-04 — La redacción lleva la fecha actual

- **Cubre:** AC-011-02
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-011-03
- **Archivos:** `src/dispute_agent/application/system_prompt.py`, `src/dispute_agent/application/use_cases/stream_customer_message.py`, `tests/unit/dispute_agent/application/test_drafting_prompt.py`, `tests/unit/dispute_agent/application/test_stream_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_decide_turn.py`
- **Test primero:** `tests/unit/dispute_agent/application/test_drafting_prompt.py::test_ac_011_02_build_drafting_system__includes_today`, `tests/unit/dispute_agent/application/test_stream_customer_message.py::test_ac_011_02_stream__drafting_prompt_includes_current_date` y `tests/unit/dispute_agent/application/test_handle_customer_message_decide_turn.py::test_ac_011_02_handle__decision_prompt_includes_current_date`
- **Red:** `build_drafting_system` no acepta `today` (`TypeError`) y el prompt de streaming no tiene `Fecha actual`. Con el reloj en `2026-10-19` el test de streaming espera `Fecha actual: 2026-10-19 (formato AAAA-MM-DD).` en el `system` que recibe `FakeLLM.stream`. El test sin streaming es de caracterización de RN-007-44 (ya verde) y fija la fila «sin streaming» de la spec.
- **Green:** `build_drafting_system(outcomes, today)` añade la línea de fecha; `StreamCustomerMessage` llama con `self._clock.today()`; actualizar los tests de `test_drafting_prompt.py` a la nueva firma.
- **Refactor:** reutilizar la línea de fecha de `build_decision_system` con una constante o función común en `system_prompt.py`.

### [x] T-011-05 — Guarda de tarjeta propia y tope compartido

- **Cubre:** AC-011-03, AC-011-04, AC-011-05, AC-011-05b, AC-011-06, AC-011-08 (fila «tres tarjetas ajenas»), AC-011-09
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-011-01, T-011-02
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard.py`
- **Test primero:** U-CG: `test_ac_011_03_handle__foreign_card__core_not_called_and_unknown_card_returned`, `test_ac_011_04_handle__llm_corrects_card__query_proceeds`, `test_ac_011_05_handle__no_known_cards__request_reaches_core`, `test_ac_011_05b_handle__malformed_card_last4__reaches_core_and_invalid_input_applies` (parametrizado: 2 dígitos y 16 dígitos), `test_ac_011_06_handle__unknown_card_text_is_fixed_and_hides_sent_value`, `test_ac_011_08_handle__three_foreign_cards__escalates_with_rn_011_07` y `test_ac_011_09_handle__new_message_resets_correction_counter`
- **Red:** hoy la petición con `card_last4 = "4231"` llega al core. Los tests esperan que `FakeBankingTools` no registre ninguna llamada a `list_transactions`, que el `tool_result` sea `unknown_card` con `cards_last4 = ["4321", "8765"]` y `corrections_remaining` 1 y 0, que el 3.º rechazo llame a `escalate` con `INSUFFICIENT_OR_CONTRADICTORY_INFO`, resumen completo sin transacción ni tarjeta, la nota `RN-011-07: consultar_transacciones UNKNOWN_CARD tras 2 correcciones`, un único `ESCALATED` y estado `ESCALATED`; sin `known_cards` la petición sí llega al core; y un mensaje nuevo reinicia el contador.
- **Green:** en `_list_transactions`, tras la verificación y antes de leer las fechas, si hay `known_cards`, `args.card_last4` son exactamente 4 dígitos y ninguna coincide, llamar a `_card_rejection(conv, call, "UNKNOWN_CARD", outcomes)` nuevo: `register_invalid_input()`; con `> _MAX_CORRECTIONS` llama a `_derive_and_close` con `INSUFFICIENT_OR_CONTRADICTORY_INFO`, la regla `_CARD_CAP_RULE = "RN-011-07"` y el motivo `consultar_transacciones UNKNOWN_CARD tras 2 correcciones`; si no, devuelve el resultado `unknown_card` de §7.1 con `messages.unknown_card_message`. La auditoría del rechazo corregible llega en T-011-07.
- **Refactor:** extraer `_card_rejection_result(call_id, kind, cards_last4, remaining)` para que `unknown_card` y `not_found` compartan serialización.

### [x] T-011-06 — `NOT_FOUND` es un error de negocio con el mismo tope

- **Cubre:** AC-011-07, AC-011-08 (filas «tres `NOT_FOUND`» y mezcla), AC-011-11
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-011-05
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_escalations.py`
- **Test primero:** U-CG: `test_ac_011_07_handle__not_found_from_core__returned_to_llm_without_escalation`, `test_ac_011_08_handle__three_not_found_or_mixed__escalates_with_rn_011_07` (parametrizado: tres `NOT_FOUND`; `INVALID_INPUT` + tarjeta ajena + `NOT_FOUND`) y `test_ac_011_11_handle__other_failures_still_escalate_and_invalid_input_still_corrects` (parametrizado: `INTERNAL` y tiempo límite de `consultar_transacciones` derivan con `UNRECOVERABLE_SYSTEM_FAILURE`; `INVALID_INPUT` de `consultar_transacciones` devuelve `invalid_input`). En `test_handle_customer_message_escalations.py`: `test_ac_011_11_handle__not_found_in_write_tool_still_escalates` para `iniciar_disputa`.
- **Red:** hoy un `NOT_FOUND` de `consultar_transacciones` va a `_read_failure`: deriva con `UNRECOVERABLE_SYSTEM_FAILURE`. Los tests esperan `not_found` con `corrections_remaining = 1`, sin `escalate`, sin `outcomes` y estado `ACTIVE`; con el 3.º rechazo, la nota `RN-011-07: consultar_transacciones NOT_FOUND tras 2 correcciones`. Las filas de AC-011-11 son de caracterización y pasan desde el inicio: fijan que el desvío no se amplía a otros códigos ni herramientas.
- **Green:** en `_dispatch`, un `BankingToolError` con código `NOT_FOUND` de `_ListArgs` llama a `_card_rejection(conv, call, "NOT_FOUND", outcomes)`; el resultado usa `messages.NOT_FOUND_CARD_MESSAGE`. Sin cambios para `INTERNAL`, tiempo límite, otras herramientas ni `INVALID_INPUT`.
- **Refactor:** consolidar en `_dispatch` los dos desvíos (`INVALID_INPUT` y `NOT_FOUND`) en una sola condición legible.

### [x] T-011-07 — Auditoría de cada rechazo corregible

- **Cubre:** AC-011-10
- **App / capa:** `dispute_agent` / `application`
- **Depende de:** T-011-06
- **Archivos:** `src/dispute_agent/application/use_cases/handle_customer_message.py`, `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard_audit.py`
- **Test primero:** U-CGA: `test_ac_011_10_audit__foreign_card_first_rejection__tool_call_rn_011_03` y `test_ac_011_10_audit__not_found_second_rejection__tool_call_rn_011_05`
- **Red:** `_card_rejection` no registra ningún `tool_call`. Los tests esperan un registro con `conversation_id`, marca de tiempo del reloj, `tool = "consultar_transacciones"`, la salida `{"error": "UNKNOWN_CARD", "correction": 1, "of": 2}` o `{"error": "NOT_FOUND", "correction": 2, "of": 2}`, `rule = "RN-011-03"` o `"RN-011-05"` y el motivo fijo de §7.3; la entrada de la guarda es `{"fields": [...]}` sin los 4 dígitos pedidos.
- **Green:** en `_card_rejection`, antes de devolver el resultado, `_audit_call(...)` con las constantes `_UNKNOWN_CARD_RULE`, `_NOT_FOUND_RULE` y los motivos de §7.3; entrada `{"fields": sorted(call.arguments)}` para la guarda y `_safe(conv, call.arguments)` para `NOT_FOUND`.
- **Refactor:** —

### [x] T-011-08 — El servidor real responde `NOT_FOUND` a una tarjeta ajena

- **Cubre:** AC-011-12 (nivel de integración)
- **App / capa:** `dispute_agent` / `infrastructure/outbound`
- **Depende de:** —
- **Archivos:** `tests/integration/dispute_agent/mcp/test_mcp_stdio_banking_adapter.py`
- **Test primero:** `tests/integration/dispute_agent/mcp/test_mcp_stdio_banking_adapter.py::test_ac_011_12_list_transactions__card_not_owned__raises_not_found_non_retryable`
- **Red:** es un test de caracterización del contrato que sustenta la guarda: con el servidor real por stdio y una clienta verificada, `consultar_transacciones` con una tarjeta que no tiene debe lanzar `BankingToolError` con `code = "NOT_FOUND"` y `retryable = False`. Se espera verde desde el inicio; falla si el servidor o el adaptador cambian ese contrato.
- **Green:** sin cambio de código de producción (el adaptador ya propaga `NOT_FOUND`, plan §2).
- **Refactor:** —

### [x] T-011-09 — Tarjeta equivocada con el servidor real (e2e)

- **Cubre:** AC-011-12 (nivel e2e)
- **App / capa:** `dispute_agent` / e2e
- **Depende de:** T-011-07, T-011-08
- **Archivos:** `tests/e2e/test_chat_e2e.py`
- **Test primero:** `tests/e2e/test_chat_e2e.py::test_ac_011_12_chat__wrong_card_digits_with_real_server__guard_blocks_then_llm_corrects`
- **Red:** chat → agente → servidor MCP real por stdio, con la clienta del seed (tarjetas `4321` y `8765`) y un `FakeLLM` que pide primero `4231` y luego `4321`. Sin la guarda, el servidor recibiría `4231` y el agente derivaría; el test espera que el servidor no reciba la 1.ª petición (se comprueba en la auditoría), que la 2.ª devuelva transacciones, que la conversación siga `ACTIVE`, que no haya derivación y que la auditoría traiga el `tool_call` de RN-011-09. Verifica el comportamiento de T-011-05 a T-011-07 de punta a punta.
- **Green:** sin cambio de código de producción si T-011-05 a T-011-07 están bien; si el e2e revela un desajuste, se corrige en la tarea que lo causó.
- **Refactor:** reutilizar el helper de arranque del chat e2e que ya usan AC-007-34 y AC-010-12.

### [x] T-011-10 — Specs 007 y 010 y `DECISIONES.md` coherentes con la 011

- **Cubre:** habilita todos los AC (Art. 2: la spec refleja el comportamiento implementado)
- **App / capa:** docs
- **Depende de:** T-011-07
- **Archivos:** `specs/007-dispute-resolution-agent/spec.md`, `specs/010-invalid-input-correction/spec.md`, `docs/DECISIONES.md`
- **Test primero:** no aplica (documentación, sin código). Verificación: `grep` de `spec 011` / `RN-011` en los tres archivos y suite completa en verde (T-011-11).
- **Red:** hoy RN-007-21 de la spec 007 no exceptúa el `NOT_FOUND` de `consultar_transacciones` y RN-007-44 dice «últimos 90 días»; RN-010-03 de la spec 010 no menciona los rechazos de la spec 011; `DECISIONES.md` no recoge la guarda.
- **Green:** spec 007 a 0.4.1: RN-007-21 añade que el `NOT_FOUND` de `consultar_transacciones` no es falla (spec 011, RN-011-05/06/07) y RN-007-44 cita el límite de 89 días y `hoy - 89`, más la fila del historial. Spec 010: RN-010-03 aclara que el contador incluye los rechazos de la spec 011 (versión y fila del historial). `DECISIONES.md`: una fila `011 — Guardas de consulta de transacciones` con referencia a RN-011-03/05/06.
- **Refactor:** —

### [x] T-011-11 — Verificación final

- **Cubre:** todos los AC (Definition of Done, §5.5)
- **App / capa:** `dispute_agent` / verificación
- **Depende de:** T-011-04, T-011-09, T-011-10
- **Archivos:** — (solo ejecuta comandos; no modifica archivos)
- **Test primero:** suite completa: `uv run pytest --cov`
- **Red:** si algún test, el lint, el formato o el tipado falla, se corrige en la tarea que lo causó.
- **Green:** `uv run pytest --cov` cumple los umbrales (≥ 90 % en `domain` y `application`, ≥ 80 % global); `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src` sin errores.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-011-01 | T-011-03 | `test_ac_011_01_agent_tools__list_transactions_states_89_day_limit`, `test_ac_011_01_decision_prompt__states_89_day_limit_and_default_date_from` |
| AC-011-02 | T-011-04 | `test_ac_011_02_build_drafting_system__includes_today`, `test_ac_011_02_stream__drafting_prompt_includes_current_date`, `test_ac_011_02_handle__decision_prompt_includes_current_date` |
| AC-011-03 | T-011-05 | `test_ac_011_03_handle__foreign_card__core_not_called_and_unknown_card_returned` |
| AC-011-04 | T-011-05 | `test_ac_011_04_handle__llm_corrects_card__query_proceeds` |
| AC-011-05 | T-011-05 | `test_ac_011_05_handle__no_known_cards__request_reaches_core` |
| AC-011-05b | T-011-05 | `test_ac_011_05b_handle__malformed_card_last4__reaches_core_and_invalid_input_applies` |
| AC-011-06 | T-011-02, T-011-05 | `test_ac_011_06_unknown_card_message__lists_own_last4_only`, `test_ac_011_06_handle__unknown_card_text_is_fixed_and_hides_sent_value` |
| AC-011-07 | T-011-01, T-011-02, T-011-06 | `test_ac_011_07_not_found_card_message__is_fixed_text`, `test_ac_011_07_handle__not_found_from_core__returned_to_llm_without_escalation` |
| AC-011-08 | T-011-05, T-011-06 | `test_ac_011_08_handle__three_foreign_cards__escalates_with_rn_011_07`, `test_ac_011_08_handle__three_not_found_or_mixed__escalates_with_rn_011_07` |
| AC-011-09 | T-011-05 | `test_ac_011_09_handle__new_message_resets_correction_counter` |
| AC-011-10 | T-011-07 | `test_ac_011_10_audit__foreign_card_first_rejection__tool_call_rn_011_03`, `test_ac_011_10_audit__not_found_second_rejection__tool_call_rn_011_05` |
| AC-011-11 | T-011-06 | `test_ac_011_11_handle__other_failures_still_escalate_and_invalid_input_still_corrects`, `test_ac_011_11_handle__not_found_in_write_tool_still_escalates` |
| AC-011-12 | T-011-08, T-011-09 | `test_ac_011_12_list_transactions__card_not_owned__raises_not_found_non_retryable`, `test_ac_011_12_chat__wrong_card_digits_with_real_server__guard_blocks_then_llm_corrects` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
