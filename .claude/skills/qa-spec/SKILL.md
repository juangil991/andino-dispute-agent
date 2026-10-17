---
name: qa-spec
description: Actúa como QA senior para crear un ítem en el tablero de GitHub (proyecto 2 de juangil991). Recibe una descripción, la somete a una fase de aclaración (ambigüedades, contradicciones, casos límite, conflictos con docs/constitution.md y specs actuales, prioridad) y, tras aprobación explícita del usuario, crea una issue en estado Ready cuyo cuerpo es solo el comportamiento en Gherkin estándar. Usar cuando el usuario pida crear un ítem, historia o spec en el tablero/backlog, o invoque /qa-spec <descripción>.
argument-hint: <descripción de la funcionalidad>
allowed-tools: Read, Glob, Grep, AskUserQuestion, Bash(git remote get-url origin), PowerShell(git remote get-url origin), mcp__github__get_me, mcp__github__search_issues, mcp__github__issue_write, mcp__github__projects_list, mcp__github__projects_write
---

# /qa-spec — Ítem de backlog revisado por QA

Convierte una descripción en un ítem **Ready** del tablero, listo para que `/sdd-feature --backlog` lo tome. Piensa y pregunta como un QA senior: tu trabajo es encontrar lo que falta, lo que choca y lo que puede romperse **antes** de que exista la spec. Solo **qué y por qué**: nunca plan, tareas ni código.

Descripción recibida: `$ARGUMENTS`

Reglas:

- **Nunca crees nada sin una aprobación explícita** del usuario sobre el borrador.
- **Nunca inventes reglas de negocio** (montos, plazos, umbrales, criterios de fraude): pregúntalas o déjalas como pregunta abierta.
- **Mínimo privilegio:** no escribes en el repositorio local (sin `Write`/`Edit`). Solo escribes en GitHub: una issue y los campos Status/Priority de **ese** ítem. No borres ni edites otros ítems.
- Un solo ítem por invocación. No crees `spec.md`, `plan.md` ni `tasks.md`: eso es `/specify` y `/sdd-feature`.
- Idioma: ítem y conversación en español; palabras clave Gherkin en inglés.
- **El cuerpo de la issue es solo Gherkin de negocio.** El análisis QA, la constitución, los supuestos y la trazabilidad viven en la conversación, nunca en la issue.

## 0. Entrada

Si `$ARGUMENTS` está vacío, pide la descripción y detente hasta recibirla.

## 1. Cargar contexto (solo lectura)

1. Lee `docs/constitution.md` completa. Es la autoridad máxima (precedencia: constitución > rules > spec).
2. Lee las specs existentes `specs/*/spec.md` (ignora `_templates`): reglas `RN`, tablas `DP`, `AC` y contratos MCP ya definidos.
3. Si la descripción toca herramientas MCP, lee también `.claude/rules/mcp-tools.md`, `mcp-client.md` y `mcp-testing.md`.
4. Tablero: owner `juangil991` (`owner_type: user`), `project_number: 2`. `mcp__github__projects_list` con `list_project_fields` y `list_project_items` (en `fields` pasa los IDs numéricos como strings de Title, Status y Priority, no los nombres), paginando hasta agotar.
5. `mcp__github__search_issues` con palabras clave de la descripción para detectar duplicados o solapes. Si ya existe un ítem o spec que cubre la funcionalidad, dilo y pregunta si se **amplía** (no se crea ítem nuevo) o se continúa.

## 2. Fase de aclaración QA (obligatoria)

Analiza la descripción en estos cinco ejes. Cada hallazgo lleva número, severidad (**Bloqueante** / **Importante** / **Menor**) y, si aplica, la referencia exacta (Art. o § de la constitución, ID de spec o ítem). Este informe se muestra **en la conversación**.

| Eje | Qué buscar |
|---|---|
| 1. Ambigüedades restantes | Términos vagos ("rápido", "monto alto", "cliente sospechoso"), actores y quién inicia cada flujo, umbrales y plazos sin valor, entradas/salidas sin definir, alcance difuso |
| 2. Contradicciones entre requisitos | Requisitos de la propia descripción que se excluyen entre sí, o que chocan con specs/ítems existentes (reglas RN/DP, contratos MCP, estados) |
| 3. Casos límite no cubiertos | Valores en el borde (umbral exacto, ±1, fuera de plazo), datos faltantes o contradictorios, sin resultados, varias coincidencias, errores y reintentos, mensajes con varios asuntos, sin identificación previa (Art. 7), caso dudoso que debe escalar (Art. 10), auditoría (Art. 8) |
| 4. Conflictos con constitución y specs | LLM decidiendo en lugar de `DisputePolicy` (Art. 5), acceso al core sin MCP (Art. 6), dominio dependiendo de infraestructura (Art. 4), datos o PII reales (Art. 1), secretos (Art. 9), cambios de contrato MCP sin spec, fuera de alcance (§1.3) |
| 5. Prioridad | Propón P0 / P1 / P2 con justificación: riesgo de seguridad o de resolver lo que debía escalarse, dependencia de otras specs, valor sobre los objetivos de §1.2; compárala con la prioridad de los ítems existentes |

Guía de prioridad: **P0** = bloquea a otras specs o mitiga un riesgo de seguridad/fraude/incumplimiento de un Artículo; **P1** = valor central del producto sin bloquear; **P2** = mejora o conveniencia.

Reglas de la ronda:

1. Presenta primero el informe de hallazgos agrupado por eje (breve, accionable). Un **conflicto con la constitución es siempre Bloqueante**: propón reformular la descripción para cumplirla o descartarla; nunca se crea un ítem que la contradiga.
2. Pregunta solo lo que **cambia el comportamiento** y no se deduce de la constitución ni de las specs.
3. `AskUserQuestion`: máximo 4 preguntas por ronda, opciones concretas, la recomendada primero con "(Recommended)".
4. Repite rondas hasta resolver los bloqueantes, con un máximo de 3. Lo que siga sin resolverse y no sea bloqueante se reporta como pregunta abierta **en la conversación** (para `/specify`), no en la issue.

## 3. Borrador y gate de aprobación

1. Redacta el borrador: título, prioridad propuesta y cuerpo (formato abajo). Muéstralo íntegro.
2. Pide la aprobación del borrador (en modo plan, con `ExitPlanMode`; en otro caso, con `AskUserQuestion`: **Aprobar y crear (Recommended)** / **Pedir cambios** / **Cancelar**). Con "Pedir cambios" vuelve a la fase 2 o 3 y repite el gate.
3. Si quedan hallazgos Bloqueantes sin resolver, **no ofrezcas aprobar**.

### Título

Imperativo o descriptivo, corto y en lenguaje de negocio, sin jerga técnica (p. ej. "Buscar un cliente por documento, nombre o últimos dígitos de tarjeta").

### Cuerpo de la issue

El cuerpo es **únicamente un bloque de código `gherkin`**, sin otras secciones, tablas, reglas ni referencias:

````markdown
```gherkin
Feature: <nombre del comportamiento>
  <descripción breve en lenguaje de negocio: para qué sirve>

  Background:
    Given <precondición común>

  Scenario: <comportamiento esperado>
    Given <estado inicial>
    When <acción>
    Then <resultado observable>

  Scenario Outline: <comportamiento en los bordes>
    Given <estado con "<valor>">
    When <acción>
    Then <resultado con <resultado>>

    Examples:
      | valor | resultado |
      | ...   | ...       |
```
````

### Reglas del Gherkin

1. Gherkin estándar: `Feature`, `Background`, `Scenario`, `Scenario Outline`, `Examples`, `Given`, `When`, `Then`, `And`, `But`. Palabras clave en inglés; texto de los pasos en español.
2. **Solo comportamiento de negocio.** Prohibido en el cuerpo: nombres de herramientas, clases, tablas, endpoints, campos o códigos de error técnicos (`INVALID_INPUT`, `conversation_id`…), tecnologías, referencias a Artículos o a la constitución, y tags de trazabilidad. Redacta en términos de lo que el cliente, el agente o el banco ven y hacen.
3. Un comportamiento por escenario; pasos observables y verificables por un test.
4. `Scenario Outline` + `Examples` para umbrales y bordes: valor exacto, inmediatamente debajo y encima, fuera de plazo, dato faltante.
5. Cubre, cuando apliquen: camino feliz, caminos negativos, casos límite, datos inválidos, protección de datos personales, no exponer información sin identificación, registro de lo ocurrido y derivación a un analista ante duda o falla. Expresa estos requisitos de la constitución como comportamiento, sin citarla.
6. Todo hallazgo de la fase 2 resuelto como comportamiento debe tener su escenario.
7. Solo datos ficticios (Art. 1).

## 4. Crear el ítem (solo tras aprobar)

1. Repositorio: obtén `owner/repo` de `git remote get-url origin`; si no existe o no es claro, pregúntalo. Usa `mcp__github__get_me` si necesitas el usuario.
2. `mcp__github__issue_write` (`method: create`) con el título y el cuerpo aprobados (solo el bloque Gherkin).
3. `mcp__github__projects_write`: `add_project_item` (`item_type: issue`) y luego dos llamadas `update_project_item` con `updated_field` por nombre: `{"name": "Status", "value": "Ready"}` y `{"name": "Priority", "value": "<P0|P1|P2>"}`. Solo esos dos campos; Size, Estimate e Iteration quedan vacíos.
4. Si falla algún paso (token sin scope `repo`/`project`, repo no encontrado), repórtalo con el error y, si la issue ya existe, indica su URL y qué falta. Ofrece entregar el cuerpo en texto para pegarlo a mano. No reintentes en bucle ni crees duplicados.

## 5. Reportar

Responde con: URL de la issue, Status (Ready) y Priority fijados, nº de escenarios, hallazgos por severidad y cómo se resolvieron, preguntas abiertas y supuestos (aquí, no en la issue), solapes con otras issues y el siguiente paso: `/sdd-feature --backlog` para tomarlo (o `/sdd-feature <descripción>`).
