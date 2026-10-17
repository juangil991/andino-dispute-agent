---
name: specify
description: Crea la spec de una feature (specs/NNN-feature-name/spec.md) a partir de specs/_templates/spec.md, con una fase obligatoria de clarificación con el usuario cuyas respuestas quedan registradas en la spec. Usar cuando el usuario pida especificar una feature, crear o actualizar una spec, o invoque /specify <descripción>.
argument-hint: <descripción de la feature>
---

# /specify — Fase 1 del flujo SDD

Genera el `spec.md` de una feature (constitución §4.2, fase "Specify"). Solo **qué y por qué**: nunca plan, tareas ni código.

Descripción de la feature recibida: `$ARGUMENTS`

## 1. Cargar contexto

1. Lee `docs/constitution.md` completa. Es la autoridad máxima: si algo de la descripción la contradice, señálalo al usuario antes de seguir.
2. Lee `specs/_templates/spec.md`.
3. Revisa las specs existentes en `specs/*/spec.md` para evitar solapes y reutilizar reglas, contratos MCP e IDs ya definidos.
4. Si `$ARGUMENTS` está vacío, pide al usuario la descripción de la feature y detente hasta recibirla.

## 2. Identificar la feature

- Número: siguiente `NNN` libre de tres dígitos en `specs/` (ignorando `_templates`).
- Slug: kebab-case, en inglés, 2–4 palabras (p. ej. `001-customer-identification`).
- Si ya existe una spec que cubre la feature, pregunta si se **actualiza** esa spec (spec viva: subir versión y añadir fila en el historial) o se crea una nueva.

## 3. Clarificación (obligatoria)

Antes de redactar, detecta ambigüedades recorriendo esta lista:

| Categoría | Qué buscar |
|---|---|
| Alcance | Qué entra y qué queda fuera de la feature |
| Actores | Cliente, agente, analista; quién inicia cada flujo |
| Reglas de negocio | Umbrales de monto, plazos, tipos de transacción, estados |
| Decisión | Qué condiciones llevan a RESOLVE / REJECT / ESCALATE en `DisputePolicy` |
| Herramientas MCP | Entradas, salidas, sin resultados, coincidencias múltiples, errores y reintentos |
| Identidad | Qué datos localizan y cuáles verifican al cliente |
| Escalamiento | Cuándo se escala y qué lleva el resumen estructurado |
| Datos | Datos semilla ficticios necesarios para los criterios de aceptación |
| Casos límite | Valores en el borde, datos faltantes o contradictorios, mensajes con varios asuntos |

Reglas:

- Pregunta solo lo que **cambia el comportamiento** y no puede deducirse de la constitución ni de specs previas.
- **Nunca inventes reglas de negocio** (montos, plazos, criterios de fraude): pregúntalas.
- Usa `AskUserQuestion`: máximo 4 preguntas por ronda, opciones concretas y la recomendada primero con "(Recommended)".
- Repite rondas hasta que no queden ambigüedades bloqueantes, con un máximo de 3 rondas. Lo que siga sin resolverse va a la sección "Preguntas abiertas".
- Registra **cada** pregunta y respuesta en la sección "Clarificaciones" de la spec (fecha, pregunta, respuesta, secciones afectadas).

## 4. Redactar la spec

1. Crea `specs/NNN-feature-name/spec.md` copiando la estructura de la plantilla y sustituye todos los placeholders `<...>` y `NNN`.
2. IDs: `HU-NNN-XX`, `RN-NNN-XX`, `DP-NNN-XX`, `AC-NNN-XX`, consecutivos desde `01`.
3. Criterios de aceptación en Given/When/Then, observables y verificables por un test; cada regla de negocio y cada fila de la tabla de decisión cubierta por al menos un AC.
4. Las secciones que no apliquen se marcan "No aplica"; no se eliminan.
5. Cada respuesta de la clarificación debe reflejarse en las secciones que afecta.
6. Elimina los comentarios `<!-- -->` de la plantilla en el resultado final.

## 5. Validar

Recorre el gate de salida de la plantilla y marca lo que se cumple. Estado de la spec:

- `Borrador` si quedan preguntas abiertas.
- `En revisión` si no quedan.
- **Nunca** `Aprobada`: la aprobación la da el usuario.

No crees `plan.md`, `tasks.md` ni código.

## 6. Reportar

Responde con: ruta de la spec, número de HU / RN / AC creados, preguntas abiertas restantes y el siguiente paso (aprobar la spec y ejecutar `/plan-feature NNN` para pasar a la fase "Plan").
