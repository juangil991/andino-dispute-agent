---
paths:
  - "src/dispute_agent/application/**"
  - "src/dispute_agent/domain/**"
  - "src/dispute_agent/infrastructure/outbound/llm/**"
---

# Convención de comportamiento del agente (`dispute_agent`)

Complementa `mcp-client.md` (adaptador MCP): aquí se fija cómo conversa, decide y escala el agente. La constitución fija el stack (loop propio con el SDK `anthropic`, sin frameworks de agentes, §2): donde un requisito hable de "hooks", se cumple con **guardas deterministas en código** dentro del loop, no con instrucciones de prompt.

## Ciclo agéntico

1. **La razón de parada manda** (§3.5): el loop continúa mientras el modelo termine con `stop_reason == "tool_use"` y termina con `end_turn`. Prohibido decidir con un número fijo de iteraciones o buscando palabras en el texto. `LLMPort` expone `stop_reason` en `LLMResponse`; una razón inesperada (`max_tokens`, `refusal`…) es salida inválida ⇒ Art. 10.
2. **El tope de iteraciones es solo una red de seguridad** configurable (§3.5), nunca el criterio de terminación normal. Al alcanzarlo se escala (Art. 10).
3. Cada `tool_use` recibe su `tool_result` en el mismo turno, también los bloqueados o fallidos; el historial nunca queda con un `tool_use` huérfano.

## Reglas de negocio garantizadas, no sugeridas

4. Las reglas de negocio críticas (identificación antes que información, Art. 7; el dominio decide, Art. 5; escalar ante la duda, Art. 10) se imponen con guardas previas a la ejecución de cada herramienta, en `application`. El prompt puede repetirlas, pero **nunca es el único mecanismo**.
5. Una guarda que bloquea devuelve un resultado de error estructurado (`blocked`) con la regla aplicada y la audita (Art. 8); no ejecuta la herramienta ni la ejecuta "a medias".
6. Toda regla nueva se prueba con un test que simula un LLM que la viola (`FakeLLM` pidiendo la herramienta prohibida) y comprueba que la guarda actúa.

## Ambigüedad

7. Si `buscar_cliente` devuelve varias coincidencias (`refinement_required`), el agente pide **otro identificador** y repite la búsqueda; nunca elige una coincidencia. El LLM no recibe los datos de las coincidencias, solo su número (RN-007-02).
8. Una búsqueda sin resultados no es un error: es un resultado vacío que el agente comunica y reintenta con otro dato, hasta el tope definido en la spec, tras el cual escala.

## Solicitudes con varias preocupaciones

9. El agente separa cada asunto del mensaje del cliente (p. ej. cargo desconocido + tarjeta perdida + duda de saldo), trata cada uno por su vía (disputa, fraude, escalamiento) y responde **una sola vez**, de forma unificada, cubriendo todos.
10. Un asunto que no puede resolverse o que se escala no impide resolver los demás; la respuesta indica el estado de cada uno.

## Escalamiento con criterio

11. Se escala solo cuando: el cliente lo pide, el monto supera el umbral, o la política no cubre el caso o no es concluyente (Art. 5, Art. 10). Lo decide `DisputePolicy` o una guarda, nunca el LLM por iniciativa propia.
12. No se escala lo que el agente puede resolver. Todo escalamiento declara su causa como un `EscalationReason` del dominio.
13. Tras escalar, la conversación se cierra y no se vuelven a invocar herramientas de escritura (RN-007-24).

## Handoff al analista

14. El analista **no tiene acceso a la conversación**: el resumen de `escalar_a_analista` debe bastarse solo. Contenido mínimo: cliente (identificador, nunca datos sensibles en claro), transacciones y montos implicados, acciones ya ejecutadas, causa del escalamiento y acción recomendada.
15. El resumen lo construye `EscalationService` a partir del estado de la conversación y de las decisiones del dominio, no lo redacta el LLM; un test verifica que cada campo mínimo está presente.
16. PII enmascarada en el resumen, igual que en logs y respuestas (Art. 1, Art. 8).

## Descripciones de herramientas del LLM

17. Cada herramienta expuesta al LLM en `agent_tools.py` describe **cuándo usarla y cuándo no**, y su relación con las demás. En particular: `buscar_cliente` solo localiza (no autentica); `verificar_identidad` autentica y exige haber localizado antes; qué hacer ante varias o ninguna coincidencia.
18. Las descripciones cambian junto con la spec; un cambio de contrato de herramienta actualiza descripción, esquema y test de catálogo en el mismo cambio (Art. 2).

## Errores de herramientas hacia el LLM

19. El agente distingue cuatro categorías: **transitorio** (reintentable con tope), **validación** (el LLM corrige argumentos), **negocio** (se comunica al cliente, no se reintenta) y **permisos** (bloqueo, no se reintenta). Reintenta solo con `retryable=true` (`mcp-client.md` 4).
20. Los errores irrecuperables escalan (Art. 10) y no se exponen al LLM con detalle interno.
