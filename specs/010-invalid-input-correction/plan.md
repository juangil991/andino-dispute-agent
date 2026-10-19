# Plan: Corregir los argumentos que el core rechaza en lugar de derivar el caso

| Campo | Valor |
|---|---|
| Feature | `010-invalid-input-correction` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-19 |
| Spec | [spec.md](./spec.md) — versión 0.1.1 aprobada |
| Tareas | [tasks.md](./tasks.md) |

---

## 1. Resumen técnico

El cambio vive casi entero en `dispute_agent/application`. El adaptador MCP extrae el campo inválido del mensaje del servidor (`(campo: X)`) y lo expone en `BankingToolError.field`. En `HandleCustomerMessage._dispatch`, un `BankingToolError` con código `INVALID_INPUT` de una lectura con argumentos del LLM (`consultar_transacciones`, `buscar_cliente`) deja de ir a `_read_failure`: pasa a un camino nuevo, `_invalid_input`, que cuenta el rechazo en la conversación, audita, y devuelve al LLM el error de validación fijo (§7.2 de la spec) o, con el 3.er rechazo del mensaje, deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO` y cierra. El contador de correcciones es estado del turno en `Conversation` (se reinicia en `begin_turn`, igual que el rastro de identificación).

Mientras la cliente no está verificada, un `INVALID_INPUT` de `buscar_cliente` registra un paso nuevo de identificación (`INVALID_SEARCH`) cuyo texto fijo elige el selector existente (RN-007-38). Para el hueco de diagnóstico, `_read_failure` audita un `tool_call` antes de derivar, y las derivaciones por falla de `iniciar_disputa` y `bloquear_tarjeta` incorporan el campo al registro y a la nota, con un helper compartido que construye el texto.

Decisiones técnicas sin consulta (default convencional):

- El campo se extrae en el adaptador con una expresión regular sobre el mensaje, igual que `_ALREADY_OPEN_ID` ya extrae el `dispute_id` de `DISPUTE_ALREADY_OPEN`. El servidor no cambia (fuera de alcance) y el puerto sigue sin depender de MCP.
- El 3.er rechazo reutiliza la ruta de cierre de RN-007-21 (mismo resultado `system_unavailable` hacia el LLM), parametrizada por motivo, regla y nota.
- La spec 007 se actualiza a 0.4.0 como un componente más, con el precedente del plan 009.

## 2. Componentes por capa

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `dispute_agent` | `domain` | `models/conversation.py` (`Conversation`) | Modificado | Atributo `turn_invalid_inputs: int = 0` (correcciones usadas en el mensaje), puesto a 0 en `begin_turn()`; método `register_invalid_input()` que lo incrementa y devuelve el nuevo valor. |
| `dispute_agent` | `domain` | `identification.py` | Modificado | `IdentificationStep.INVALID_SEARCH`, `IdentificationReply.INVALID_SEARCH` y su entrada en `_STEP_REPLIES` (RN-010-06). |
| `dispute_agent` | `domain` | `messages.py` | Modificado | Texto fijo `INVALID_SEARCH` en `IDENTIFICATION_REPLIES` (§7.4) y el texto fijo del error hacia el LLM (§7.2). |
| `dispute_agent` | `application` | `ports/banking_tools.py` (`BankingToolError`) | Modificado | Atributo opcional `field: str \| None = None`; el resto del contrato del puerto no cambia. |
| `dispute_agent` | `application` | `failure_detail.py` | Nuevo | `describe_failure(tool, code, field)` → `"falla irrecuperable en <tool> (<code>[, campo: <campo>])"`. Lo usan `HandleCustomerMessage`, `DisputeActions` y `FraudActions` para la nota y el motivo de cierre (RN-010-08). |
| `dispute_agent` | `application` | `use_cases/handle_customer_message.py` | Modificado | `_dispatch` desvía `INVALID_INPUT` de `_ListArgs`/`_SearchArgs` a `_invalid_input` (RN-010-01…05, 07); `_read_failure` se generaliza (motivo, regla y nota) para servir también al 3.er rechazo (RN-010-04) y audita un `tool_call` antes de derivar (RN-010-08); constantes del tope (2) y reglas `RN-010-0x`. |
| `dispute_agent` | `application` | `use_cases/dispute_actions.py` | Modificado | `_audit_open` y `_fail` incluyen el campo si el error es `INVALID_INPUT` (RN-010-08); sigue derivando con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-010-09). |
| `dispute_agent` | `application` | `use_cases/fraud_actions.py` | Modificado | `_audit_call` y `_fail` incluyen el campo si el error es `INVALID_INPUT` (RN-010-08); sin cambio de decisión. |
| `dispute_agent` | `infrastructure/outbound` | `mcp/mcp_stdio_banking_adapter.py` | Modificado | `_to_tool_error` extrae el campo de `(campo: X)` en `INVALID_INPUT` y lo pasa a `BankingToolError`. Sin coincidencia ⇒ `field = None`. |
| `core_banking_mcp` | — | — | Sin cambios | Contratos y validaciones del servidor intactos (spec §2, fuera de alcance). |
| — | docs | `specs/007-dispute-resolution-agent/spec.md` | Modificado | Versión 0.4.0: RN-007-21 (la excepción alcanza a `consultar_transacciones` y `buscar_cliente` según la spec 010), RN-007-28 (el `tool_call` de la falla lleva campo), RN-007-38 (paso 2 con `INVALID_SEARCH`), §7.4 (fila `INVALID_SEARCH`), §8 (fila de la spec 010) y la fila de historial. |
| — | docs | `docs/DECISIONES.md` | Modificado | Una fila para la corrección de `INVALID_INPUT` y el tope de 2, con referencia a RN-010-01/03. |
| — | tests | `tests/fakes/banking_errors.py` | Nuevo | Builder `invalid_input(field, message=None)` que devuelve un `BankingToolError("INVALID_INPUT", …, retryable=False, field=…)`; evita repetir el literal en los tests (§5.3.7). |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| `BankingToolsPort` | Sin cambios de firma | `McpStdioBankingAdapter` | El puerto no cambia. Cambia el tipo de error (`BankingToolError.field`), que ya forma parte del contrato de errores del puerto. |
| `AuditLogPort` | Sin cambios | `JsonAuditLog` | Se reutiliza el tipo de evento `tool_call` (RN-007-28); no hay tipo nuevo. |
| `LLMPort` | Sin cambios | `AnthropicLLMAdapter` | El error de validación viaja como `ToolResult` de error, como ya hacen `invalid_date` y `blocked`. |
| `ConversationRepository` | Sin cambios | En memoria | El contador es un campo más de `Conversation`; se guarda con el objeto. |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| `Conversation` | `turn_invalid_inputs: int` | Vale 0 al empezar cada turno (`begin_turn`). Solo crece con `register_invalid_input()`. Nunca negativo. Pertenece al turno: no cruza mensajes (RN-010-03). |
| `IdentificationStep` | `INVALID_SEARCH` | Último paso de identificación del turno, como los demás (RN-007-41). |
| `IdentificationReply` | `INVALID_SEARCH` | Texto fijo de §7.4; el selector lo devuelve cuando el último paso es `INVALID_SEARCH`. |

### Persistencia (`core_banking_mcp`)

No aplica. El core no cambia.

### Semillas

No se necesitan semillas nuevas. Los tests unitarios usan builders (`conversation_builder`, `agent_transaction_builder`) y `FakeBankingTools`. El e2e (AC-010-12) usa las semillas existentes del core con una cliente verificada y pide `date_to` posterior a hoy con una fecha lejana fija (`2099-01-01`), para que el rechazo no dependa del reloj del servidor.

## 5. Dependencias nuevas

Ninguna.

## 6. Estrategia de pruebas

Archivos nuevos (los existentes de `handle_customer_message` ya son largos, por eso se separan por tema): `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input.py` (**U-IN**) y `tests/unit/dispute_agent/application/test_handle_customer_message_invalid_input_audit.py` (**U-AUD**). Los test citan el AC y la RN en el nombre o la docstring (`mcp-testing.md`).

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-010-01 | U-IN: 4 filas parametrizadas (`date_to` futuro, rango > 90 días, `date_from` > `date_to`, `card_last4` de 2 dígitos); `FakeBankingTools` programa `INVALID_INPUT` y luego una página; `FakeLLM` corrige. Comprueba el `tool_result` `invalid_input` con el campo, la 2.ª consulta normal, `ACTIVE` y ninguna llamada a `escalate`. | — | — | — |
| AC-010-02 | U-IN: `buscar_cliente` con `INVALID_INPUT` (`card_last4`) y luego una coincidencia; la cliente queda localizada y no hay derivación. | — | — | — |
| AC-010-03 | U-IN: error del servidor con el documento en el mensaje; el contenido enviado al LLM es exactamente el texto fijo de §7.2, sin ese documento ni valores. | — | — | — |
| AC-010-04 | U-IN: 3 `INVALID_INPUT` seguidos de `consultar_transacciones`; las 2 primeras vuelven al LLM (`corrections_remaining` 1 y 0), la 3.ª llama a `escalate` con `INSUFFICIENT_OR_CONTRADICTORY_INFO`, resumen completo sin transacción, nota `RN-010-04…`, un único `outcome` `ESCALATED` y estado `ESCALATED`. | — | — | — |
| AC-010-05 | U-IN: 3 `INVALID_INPUT` de `buscar_cliente` sin verificar; resumen limitado, nota `RN-010-04 … (campo: document)` y `reply` de cierre `ESCALATED` de §7.4. | — | — | — |
| AC-010-06 | U-IN: contador combinado (`buscar_cliente` + `consultar_transacciones` + una tercera) deriva con el 3.º; y, tras 2 rechazos, un mensaje nuevo reinicia el contador (el siguiente es la 1.ª corrección). Prueba de dominio en `test_conversation.py` para `register_invalid_input` y el reinicio de `begin_turn`. | — | — | — |
| AC-010-07 | U-IN: tras un `INVALID_INPUT`, `evaluar_disputa` responde `transaction_not_listed` y no hay `NO_TRANSACTIONS_FOUND`/`REFINEMENT_REQUIRED`; la cliente sigue sin localizar; dos rechazos más una búsqueda sin coincidencias no llegan a RN-007-05. | — | — | — |
| AC-010-08 | U-IN: turno sin verificar que termina tras `INVALID_INPUT` de `buscar_cliente` ⇒ `reply` `INVALID_SEARCH` sin llamar al LLM para redactar; sin búsqueda fallida ni intento. `test_identification.py`: el selector devuelve `INVALID_SEARCH` y el último paso del turno manda sobre uno anterior. | `test_chat_identification_api.py`: `POST /api/chat` con `FakeLLM` y core falso devuelve el texto fijo. | — | — |
| AC-010-09 | U-AUD: registro `tool_call` con `conversation_id`, marca del reloj, `tool`, entrada filtrada (RN-007-26), salida `{"error","field","correction","of"}`, regla `RN-010-01` y el motivo fijo; sin texto del servidor ni documentos. | — | — | — |
| AC-010-10 | U-AUD: `consultar_transacciones` con `INTERNAL` y con tiempo límite ⇒ `tool_call` antes de `escalation` y `conversation_closed` (orden verificado), salida sin campo. `test_dispute_actions.py` y `test_fraud_actions.py`: `INVALID_INPUT` con campo ⇒ salida con campo y nota/motivo de cierre con herramienta, código y campo. | — | — | — |
| AC-010-11 | U-IN y las pruebas de `dispute_actions`/`fraud_actions`: `INVALID_INPUT` de `iniciar_disputa` y de `bloquear_tarjeta` deriva con `UNRECOVERABLE_SYSTEM_FAILURE` sin pasar por el contador; `consultar_transacciones` con `INTERNAL` deriva (AC-007-23 sigue verde); `verificar_identidad` con `INVALID_INPUT` sigue en `INVALID_DATES` (AC-007-49 sigue verde). | — | — | — |
| AC-010-12 | — | `test_mcp_stdio_banking_adapter.py`: con el servidor real, `consultar_transacciones` con `date_to = 2099-01-01` lanza `BankingToolError` con `code = "INVALID_INPUT"`, `retryable = False` y `field = "date_to"`. | `test_banking_client_contract.py`: `_to_tool_error` produce `field` para los sobres con `(campo: X)` de los seis mensajes del servidor y `None` si el mensaje no lo trae. | `tests/e2e/test_chat_e2e.py`: chat → agente → servidor MCP real por stdio con `FakeLLM` que pide la fecha futura y luego una válida; la 2.ª consulta devuelve transacciones, la conversación sigue `ACTIVE`, no hay derivación y la auditoría trae el `tool_call` con `date_to`. |

Casos de escalamiento de §8 de la spec: la fila del 3.er rechazo se prueba en AC-010-04 y AC-010-05; la de `iniciar_disputa`/`bloquear_tarjeta`, en AC-010-10 y AC-010-11. Invariante del Art. 7: `buscar_cliente` es una de las cuatro cosas permitidas sin verificar (RN-007-37), y `consultar_transacciones` sin verificar sigue bloqueada antes de llegar al core (se mantiene la prueba existente de AC-007-44…). Tope de iteraciones: no cambia; se verifica que las 2 correcciones caben en las 8 llamadas (AC-010-04 consume 3 pedidos de herramienta + la respuesta de cierre).

Regresión obligada: `uv run pytest tests/unit/dispute_agent tests/integration/dispute_agent tests/e2e` debe pasar sin cambios en los tests de las specs 007 y 009; cualquier cambio exigido en uno de ellos indica una contradicción con la spec 007 y se resuelve en la spec primero.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El campo se extrae del texto del servidor (`(campo: X)`); un cambio de redacción lo dejaría en `None` sin romper nada, pero perdería el diagnóstico. | Medio | La regex vive en un solo lugar y un test de contrato recorre los seis mensajes reales del servidor; con `field = None` la corrección y el tope siguen funcionando (spec §7.2). |
| Un bucle de correcciones consume llamadas al LLM y alarga el turno. | Medio | Tope de 2 por mensaje (RN-010-03), dentro del tope de 8 llamadas (RN-007-23), que sigue siendo la red de seguridad. El contador se reinicia por mensaje, pero cada mensaje lo inicia la cliente. |
| El LLM recibe más información del core de la que debe (valores de la cliente, texto interno). | Alto | El mensaje hacia el LLM es fijo y sin valores (RN-010-02); AC-010-03 lo comprueba con un mensaje del servidor que contiene el documento. El `field` solo es un nombre de argumento. |
| Un `INVALID_INPUT` tratado como no-resultado podría dejar estado a medias (p. ej. cliente "localizada" o transacciones "vistas"). | Alto | El rechazo lanza antes de actualizar el estado en `_list_transactions` y `_search_customer`; AC-010-07 lo verifica. `provided_documents` sí se actualiza antes de la llamada (es solo para enmascarar), y no cambia nada observable. |
| El texto fijo `INVALID_SEARCH` añade otra rama al selector de RN-007-38. | Bajo | Una sola entrada en `_STEP_REPLIES` y su test en `test_identification.py`; sin lógica nueva en el selector. |
| El 3.er rechazo no emite un `tool_call` propio (RN-010-07 cubre solo los corregibles); su rastro es `escalation` + `conversation_closed`. | Bajo | `conversation_closed` y la nota incluyen herramienta, código y campo (RN-010-04, RN-010-08). Si se quisiera un `tool_call` también ahí, es un cambio de spec. |
| Cambiar `_read_failure` puede alterar los registros de RN-007-21 que ya verifican tests de la 007. | Medio | La generalización conserva por defecto motivo, regla y nota actuales; solo se añade el `tool_call` previo, y los tests existentes que cuentan eventos se ajustan en la misma tarea con referencia a RN-010-08. |
| El e2e depende de la fecha del servidor. | Bajo | Se usa `2099-01-01`, que es posterior a hoy con cualquier reloj razonable. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | Los tests usan los builders y las semillas existentes (ficticias); el documento `1020304050` de AC-010-03 es un dato de prueba, no real. |
| Art. 2 — Spec-anchored | Cumple | Spec 010 aprobada antes del plan; la spec 007 se actualiza a 0.4.0 en el mismo cambio. |
| Art. 3 — TDD | Cumple | Cada tarea empieza por su test; la prueba de AC-010-01 reproduce el incidente y debe fallar antes de tocar `_dispatch`. |
| Art. 4 — Arquitectura hexagonal | Cumple | El contador es dominio sin dependencias; `field` es un campo del error del puerto y la regex vive en el adaptador; el cableado no cambia (`main.py` sin tocar). |
| Art. 5 — El dominio decide | Cumple | Ninguna decisión de disputa cambia; la derivación al agotar el tope es una guarda en `application`, no una decisión del LLM. |
| Art. 6 — Acciones vía MCP | Cumple | El agente sigue llamando solo a herramientas MCP; no se añade acceso al core ni validación que lo sustituya. |
| Art. 7 — Identificación antes que información | Cumple | La guarda de RN-007-37 no cambia: `consultar_transacciones` sin verificar sigue bloqueada y `buscar_cliente` sigue permitida; `INVALID_SEARCH` es un texto fijo sin datos de cuenta. |
| Art. 8 — Auditoría | Cumple | Cada `INVALID_INPUT` corregible y cada falla que deriva dejan un `tool_call` con herramienta, código y campo; las derivaciones conservan `escalation` y `conversation_closed`. |
| Art. 9 — Secretos | N.A. | No se añaden credenciales ni configuración; el tope de 2 es una constante de la regla (RN-010-03), no un secreto. |
| Art. 10 — Ante la duda, escalar | Cumple | Al agotar las correcciones se deriva y se cierra; `INTERNAL`, tiempo límite y respuesta fuera de esquema, y los `INVALID_INPUT` de escrituras, siguen derivando. |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
