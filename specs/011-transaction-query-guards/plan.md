# Plan: Guardas en la consulta de transacciones: tarjeta propia, rango de 90 días y fecha actual

| Campo | Valor |
|---|---|
| Feature | `011-transaction-query-guards` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-19 |
| Spec | [spec.md](./spec.md) — versión 0.1.2 aprobada |
| Tareas | [tasks.md](./tasks.md) |

---

## 1. Resumen técnico

Todo el cambio vive en `dispute_agent/application` y `domain/messages.py`; el core y el adaptador MCP no cambian.

- **Textos (RN-011-01, RN-011-02).** `agent_tools.py` y `SYSTEM_PROMPT` pasan a decir «`date_to` como máximo 89 días después de `date_from` (90 días contando ambos extremos)» y «sin fechas, `date_from = hoy - 89`». `build_drafting_system(outcomes, today)` añade la línea `Fecha actual: …`, igual que `build_decision_system`; `StreamCustomerMessage` le pasa `self._clock.today()`. La ruta sin streaming no tiene prompt de redacción aparte: usa el de decisión, que ya lleva la fecha (RN-007-44). Se verifica con un test, sin código nuevo.
- **Guarda y `NOT_FOUND` (RN-011-03 a RN-011-09).** En `HandleCustomerMessage`, `_list_transactions` comprueba, tras la verificación y antes de leer las fechas, que `card_last4` esté entre las `known_cards` de la clienta (solo si hay alguna). Si no, devuelve el rechazo `unknown_card` sin llamar al core. En `_dispatch`, un `BankingToolError` con código `NOT_FOUND` de `_ListArgs` pasa a ese mismo camino con `not_found`. El camino nuevo, `_card_rejection`, reutiliza el contador `Conversation.turn_invalid_inputs` (`register_invalid_input()`) y el tope `_MAX_CORRECTIONS` de la spec 010, por lo que el contador es compartido (RN-011-06) sin cambios de dominio. Con el 3.er rechazo llama a `_derive_and_close` con la regla `RN-011-07` y el motivo `INSUFFICIENT_OR_CONTRADICTORY_INFO`.
- **Docs.** Se actualizan en el mismo cambio la spec 007 (RN-007-21 y RN-007-44), la spec 010 (RN-010-03) y `docs/DECISIONES.md`.

Decisiones técnicas sin consulta (default convencional):

- El contador no cambia de nombre (`turn_invalid_inputs`) para no tocar los tests de la spec 010; su docstring pasa a decir que cuenta todas las correcciones del mensaje.
- El orden en `_list_transactions` es: identidad verificada → guarda de tarjeta → formato de fechas → core. La guarda va antes de las fechas porque no necesita llamar al core ni depende de ellas; `invalid_date` sigue sin contar como corrección, como hoy.
- El tipo del 3.er rechazo (`UNKNOWN_CARD` o `NOT_FOUND`) lo da el rechazo que llega tercero. Si el tercero es un `INVALID_INPUT`, manda RN-010-04 (spec 010) sin cambios.
- La entrada auditada de la guarda es `{"fields": [...]}` (nombres de argumentos), no el valor, para cumplir RN-011-09; la de `NOT_FOUND` usa `_safe` como cualquier lectura.

## 2. Componentes por capa

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `dispute_agent` | `domain` | `messages.py` | Modificado | `unknown_card_message(cards_last4)` y `NOT_FOUND_CARD_MESSAGE`: textos fijos de §7.1 y §7.2 de la spec. |
| `dispute_agent` | `domain` | `models/conversation.py` (`Conversation`) | Modificado | Solo el docstring de `register_invalid_input` y de `turn_invalid_inputs` (cuenta todas las correcciones del mensaje). Sin cambio de comportamiento. |
| `dispute_agent` | `application` | `system_prompt.py` | Modificado | Regla 10 de `SYSTEM_PROMPT` con el límite de 89 días y `hoy - 89` (RN-011-01); `build_drafting_system(outcomes, today)` añade `Fecha actual: AAAA-MM-DD (formato AAAA-MM-DD).` (RN-011-02). |
| `dispute_agent` | `application` | `agent_tools.py` | Modificado | Descripción de `consultar_transacciones` y de `date_to` con «máximo 89 días después de `date_from` (90 días contando ambos extremos)» (RN-011-01). |
| `dispute_agent` | `application` | `use_cases/stream_customer_message.py` | Modificado | Línea 122: `build_drafting_system(outcomes, self._clock.today())`. |
| `dispute_agent` | `application` | `use_cases/handle_customer_message.py` | Modificado | (a) Guarda de tarjeta en `_list_transactions` (RN-011-03). (b) `_dispatch` desvía `NOT_FOUND` de `_ListArgs` a `_card_rejection` (RN-011-05). (c) `_card_rejection(conv, call, kind, outcomes)` nuevo: cuenta, audita (RN-011-09), devuelve `unknown_card`/`not_found` o deriva con `RN-011-07` (RN-011-06, RN-011-07). (d) Constantes `_UNKNOWN_CARD_RULE = "RN-011-03"`, `_NOT_FOUND_RULE = "RN-011-05"`, `_CARD_CAP_RULE = "RN-011-07"`. (e) `_card_rejection_result(...)` para serializar §7.1 y §7.2. |
| `dispute_agent` | `infrastructure/outbound` | `mcp/mcp_stdio_banking_adapter.py` | Sin cambios | `NOT_FOUND` ya llega como `BankingToolError(code="NOT_FOUND")`. |
| `core_banking_mcp` | — | — | Sin cambios | Contratos y validaciones del servidor intactos (spec §2). |
| — | docs | `specs/007-dispute-resolution-agent/spec.md` | Modificado | Versión 0.4.1: RN-007-21 (el `NOT_FOUND` de `consultar_transacciones` no deriva; spec 011) y RN-007-44 (límite de 89 días y `hoy - 89`), más la fila del historial. |
| — | docs | `specs/010-invalid-input-correction/spec.md` | Modificado | RN-010-03: el contador también cuenta los rechazos de la spec 011 (RN-011-06); versión y fila del historial. |
| — | docs | `docs/DECISIONES.md` | Modificado | Una fila para la guarda de tarjeta y `NOT_FOUND` como error de negocio, con referencia a RN-011-03/05/06. |
| — | tests | `tests/fakes/banking_errors.py` | Modificado | Builder `not_found()` que devuelve `BankingToolError("NOT_FOUND", …, retryable=False)`, junto al `invalid_input` existente (§5.3.7). |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `BankingToolsPort` | Sin cambios | `McpStdioBankingAdapter` | El puerto no cambia; `NOT_FOUND` ya forma parte de su contrato de errores. |
| `AuditLogPort` | Sin cambios | `JsonAuditLog` | Se reutiliza el tipo `tool_call` (RN-007-28). |
| `LLMPort` | Sin cambios | `AnthropicLLMAdapter` | `unknown_card` y `not_found` viajan como `ToolResult` de error, como `invalid_input` y `blocked`. |
| `Clock` | Sin cambios | `SystemClock`, `FixedAgentClock` | `StreamCustomerMessage` ya lo recibe. |

## 4. Modelo de datos

### Dominio

Sin entidades nuevas. `Conversation.known_cards` (`KnownCard.last4`) y `turn_invalid_inputs` ya existen; el último se reinicia en `begin_turn()` (RN-011-06, AC-011-09).

### Persistencia (`core_banking_mcp`)

No aplica. El core no cambia.

### Semillas

No se necesitan semillas nuevas. Los tests unitarios usan `ConversationBuilder`, `FakeBankingTools` y los builders existentes. El e2e (AC-011-12) usa la clienta verificada del seed con tarjetas `4321` y `8765`, y pide primero `4231` (dígitos intercambiados) y después `4321`.

## 5. Dependencias nuevas

Ninguna.

## 6. Estrategia de pruebas

Archivos nuevos: `tests/unit/dispute_agent/application/test_handle_customer_message_card_guard.py` (**U-CG**: AC-011-03 a AC-011-09 y AC-011-11) y `…/test_handle_customer_message_card_guard_audit.py` (**U-CGA**: AC-011-10). Se amplían `test_system_prompt.py`, `test_agent_tools.py`, `test_drafting_prompt.py` y `test_stream_customer_message.py`. Los tests citan el AC y la RN en el nombre o la docstring (`mcp-testing.md`).

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-011-01 | `test_agent_tools.py` y `test_system_prompt.py`: la descripción de `consultar_transacciones` y de `date_to` contiene «89 días» y «90 días contando ambos extremos»; `SYSTEM_PROMPT` y `build_decision_system(date(2026, 10, 19))` también, con `hoy - 89`; ningún texto contiene «últimos 90 días» sin la precisión. | — | — | — |
| AC-011-02 | `test_drafting_prompt.py`: `build_drafting_system([], date(2026, 10, 19))` contiene `Fecha actual: 2026-10-19 (formato AAAA-MM-DD).`. `test_stream_customer_message.py`: con el reloj en `2026-10-19`, el `system` que recibe `FakeLLM.stream` lleva esa línea (fila «en streaming»). `test_handle_customer_message_decide_turn.py`: el `system` de la llamada de decisión lleva la fecha (fila «sin streaming»; el comportamiento existe desde RN-007-44). | — | — | — |
| AC-011-03 | U-CG: verificada con tarjetas `4321` y `8765`; `FakeLLM` pide `4231`. `FakeBankingTools` no registra ninguna llamada a `list_transactions`; el `tool_result` es `unknown_card` con `cards_last4 = ["4321", "8765"]` y `corrections_remaining = 1`; estado `ACTIVE`, sin `escalate` ni `outcomes`. | — | — | — |
| AC-011-04 | U-CG: tras el rechazo, `FakeLLM` pide `4321` con un rango de 90 días inclusive; la consulta se atiende y las transacciones quedan en `seen_transactions`. | — | — | — |
| AC-011-05 | U-CG: sin `known_cards`, la petición llega al core (`FakeBankingTools` registra la llamada) y no hay `unknown_card`. | — | — | — |
| AC-011-05b | U-CG: con `known_cards` y `card_last4` de 2 dígitos o de 16 dígitos, la petición llega al core (`FakeBankingTools` programa `INVALID_INPUT`) y el LLM recibe `invalid_input`, no `unknown_card`. Los tests existentes de AC-010-01 (`short_card`) y AC-007-30 (PAN completo) siguen verdes sin cambios. | — | — | — |
| AC-011-06 | U-CG: `card_last4 = "9999"`; el contenido enviado al LLM es exactamente el texto fijo de §7.1, sin `9999`. | — | — | — |
| AC-011-07 | U-CG: `FakeBankingTools` programa `NOT_FOUND`; el LLM recibe `not_found` con `corrections_remaining = 1`; no hay `escalate`, ni `outcomes` de derivación, `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED`; `ACTIVE`. | — | — | — |
| AC-011-08 | U-CG: 3 filas parametrizadas (3 tarjetas ajenas; 3 `NOT_FOUND`; `INVALID_INPUT` + tarjeta ajena + `NOT_FOUND`); los dos primeros vuelven al LLM (`corrections_remaining` 1 y 0), el 3.º llama a `escalate` con `INSUFFICIENT_OR_CONTRADICTORY_INFO`, resumen completo sin transacción ni tarjeta, la nota `RN-011-07…`, un único `ESCALATED` y estado `ESCALATED`. | — | — | — |
| AC-011-09 | U-CG: tras 2 rechazos, un mensaje nuevo (`begin_turn`) reinicia el contador y el siguiente rechazo es la 1.ª corrección. | — | — | — |
| AC-011-10 | U-CGA: filas «tarjeta ajena, 1.º» y «`NOT_FOUND`, 2.º»: `tool_call` con `conversation_id`, marca del reloj, `tool`, entrada filtrada, salida `{error, correction, of}`, regla `RN-011-03`/`RN-011-05` y motivo fijo; la entrada de la guarda no contiene los 4 dígitos pedidos. | — | — | — |
| AC-011-11 | U-CG y `test_handle_customer_message_escalations.py`: `INTERNAL` y tiempo límite de `consultar_transacciones` derivan con `UNRECOVERABLE_SYSTEM_FAILURE` (AC-007-23 sigue verde); `NOT_FOUND` de `iniciar_disputa` deriva (`test_dispute_actions.py`); `INVALID_INPUT` de `consultar_transacciones` sigue devolviéndose como `invalid_input` (AC-010-01 sigue verde). | — | — | — |
| AC-011-12 | — | `test_mcp_stdio_banking_adapter.py`: con el servidor real, `consultar_transacciones` con una tarjeta que la clienta no tiene lanza `BankingToolError` con `code = "NOT_FOUND"` y `retryable = False` (base del test del agente). | — | `tests/e2e/test_chat_e2e.py`: chat → agente → servidor MCP real por stdio con `FakeLLM` que pide `4231` y luego `4321`; el servidor no recibe la 1.ª petición (se observa en la auditoría), la 2.ª devuelve transacciones, la conversación sigue `ACTIVE`, no hay derivación y la auditoría trae el `tool_call` de RN-011-09. |

Casos de escalamiento de §8 de la spec: el 3.er rechazo se prueba en AC-011-08; `INTERNAL`, tiempo límite y respuesta fuera de esquema, en AC-011-11. Invariante del Art. 7: `consultar_transacciones` sin verificar sigue bloqueada antes de la guarda (se mantiene el test de AC-007-44…); la guarda no devuelve datos ajenos (AC-011-06). Tope de iteraciones: no cambia; las 2 correcciones caben en las 8 llamadas (AC-011-08 consume 3 pedidos de herramienta más la respuesta de cierre).

Regresión obligada: `uv run pytest tests/unit/dispute_agent tests/integration/dispute_agent tests/e2e`. Los tests de las specs 007 a 010 deben seguir verdes sin cambios, salvo los que fijaban `NOT_FOUND` de `consultar_transacciones` como derivación o el texto «90 días»; esos se ajustan en la misma tarea, con referencia a la RN, porque la spec 011 los enmienda. Si un test existente fija una `known_cards` distinta de la `card_last4` que pide, se corrige el dato del test (builder), no la guarda.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Tests existentes arman una clienta con `known_cards` y piden otra `card_last4`; la guarda nueva los rompería. | Medio | Se revisan con `grep` antes de implementar; se corrige el dato en el builder. La guarda solo actúa si hay `known_cards` (AC-011-05), lo que limita el impacto. |
| La guarda revela tarjetas al LLM. | Medio | Solo son los últimos 4 dígitos de las tarjetas de la propia clienta, que el LLM ya recibe en `verified` (`**** last4`); el texto es fijo (RN-011-04) y no incluye el valor pedido (AC-011-06). |
| Cambiar `_dispatch` altera el camino de `NOT_FOUND` que otros tests ya tratan como derivación. | Medio | El desvío se limita a `_ListArgs` y a código `NOT_FOUND`; `buscar_cliente`, `iniciar_disputa` y `bloquear_tarjeta` no cambian (AC-011-11). |
| El LLM no corrige y agota las 2 correcciones por una tarjeta que la clienta no tiene. | Bajo | Es el comportamiento especificado (RN-011-07): se deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO` en vez de bucle, y el mensaje de la guarda lista las tarjetas válidas para que el LLM pregunte. |
| El LLM sigue pidiendo rangos de 91 días pese al texto nuevo. | Bajo | El rechazo sigue siendo `INVALID_INPUT` corregible (spec 010); el texto fija el cómputo. No se valida en el agente (fuera de alcance). |
| La nota de la derivación mezcla tipos (`UNKNOWN_CARD`/`NOT_FOUND`/`INVALID_INPUT`) según qué rechazo llega tercero. | Bajo | Está especificado (AC-011-08, fila 3). Cada rechazo previo queda en su propio `tool_call`. |
| `build_drafting_system` cambia de firma y otros llamadores o tests se rompen. | Bajo | Hay un solo llamador en `src` (`stream_customer_message.py:122`) y los tests de `test_drafting_prompt.py`, que se actualizan en la misma tarea. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Los tests usan builders y las semillas existentes (ficticias); `4231`, `4321`, `8765` y `9999` son dígitos de prueba. |
| Art. 2 — Spec-anchored | Cumple | Spec 011 aprobada antes del plan; las specs 007 y 010 se actualizan en el mismo cambio. |
| Art. 3 — TDD | Cumple | Cada tarea empieza por su test; el de AC-011-03 reproduce el incidente (`4231`) y debe fallar antes de tocar `_list_transactions`. |
| Art. 4 — Arquitectura hexagonal | Cumple | Sin dependencias nuevas hacia `infrastructure`; los textos fijos viven en `domain/messages.py`; el cableado no cambia (`main.py` sin tocar). |
| Art. 5 — El dominio decide | Cumple | Ninguna decisión de disputa cambia; la guarda y el desvío de `NOT_FOUND` son guardas de `application`, no decisiones del LLM. |
| Art. 6 — Acciones vía MCP | Cumple | El agente sigue llamando solo a herramientas MCP; la guarda evita una llamada, no accede al core. |
| Art. 7 — Identificación antes que información | Cumple | La guarda va después de la comprobación de identidad verificada; solo expone los últimos 4 dígitos de las tarjetas de la propia clienta. |
| Art. 8 — Auditoría | Cumple | Cada rechazo corregible deja un `tool_call` con regla y motivo (RN-011-09); la derivación conserva `escalation` y `conversation_closed`. |
| Art. 9 — Secretos | N.A. | No se añaden credenciales ni configuración; el tope de 2 es la constante de la spec 010. |
| Art. 10 — Ante la duda, escalar | Cumple | Al agotar las 2 correcciones se deriva y se cierra; `INTERNAL`, tiempo límite y respuesta fuera de esquema siguen derivando (RN-011-10). |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
