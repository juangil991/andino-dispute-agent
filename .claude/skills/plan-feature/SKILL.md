---
name: plan-feature
description: Crea el plan técnico de una feature (specs/NNN-feature-name/plan.md) a partir de specs/_templates/plan.md, solo cuando su spec.md está Aprobada. Usar cuando el usuario pida planificar una feature, crear o actualizar un plan.md, pasar a la fase Plan, o invoque /plan-feature <NNN o slug>.
argument-hint: <NNN o NNN-feature-name>
---

# /plan-feature — Fase 2 del flujo SDD

Genera el `plan.md` de una feature con spec aprobada (constitución §4.2, fase "Plan"). Solo **cómo**: nunca redefine comportamiento, ni crea tareas ni código.

Feature recibida: `$ARGUMENTS`

## 1. Cargar contexto

1. Lee `docs/constitution.md` completa, con atención a §2 (stack), §3 (capas, puertos, estructura de carpetas) y §5 (política de tests). Es la autoridad máxima.
2. Resuelve la feature a partir de `$ARGUMENTS` (número `NNN` o slug completo). Si está vacío o no coincide con ninguna carpeta, lista las `specs/*/spec.md` con su estado y pregunta cuál planificar; detente hasta recibir la respuesta.
3. Lee `specs/NNN-feature-name/spec.md` y `specs/_templates/plan.md`.
4. Lee los `plan.md` de otras features para reutilizar componentes, puertos, tablas y semillas ya planificados y evitar duplicados o contradicciones.
5. Explora `src/` y `tests/` para marcar cada componente como Nuevo o Modificado con base en el código real.

## 2. Gate de entrada (bloqueante)

- El campo **Estado** de la spec debe ser `Aprobada`. Si no lo es, informa el estado actual, recuerda que la aprobación la da el usuario y **detente sin crear nada**.
- Si la spec tiene preguntas abiertas sin resolver o su gate de salida está incompleto, señálalo y detente.
- Si ya existe `plan.md`, pregunta si se **actualiza** (subir versión y referenciar la versión vigente de la spec) o se aborta.

## 3. Diseñar el plan

| Sección del plan | Reglas |
|---|---|
| Componentes por capa | Ubicados en la capa y carpeta correctas (§3.2, §3.6). Dependencias hacia adentro. Nada compartido entre `dispute_agent` y `core_banking_mcp` salvo los contratos MCP. Cableado solo en `main.py` / `server.py`. |
| Puertos y adaptadores | Los de §3.3, o nuevos con justificación. |
| Modelo de datos | El dominio no usa SQLAlchemy ni Pydantic (§3.2.4). Semillas ficticias y reproducibles (Art. 1) que cubran los AC. |
| Dependencias nuevas | Solo si el stack de §2 no lo resuelve; cada una con justificación y alternativa descartada. Si no hay, "Ninguna". |
| Estrategia de pruebas | **Cada AC** de la spec con al menos un nivel (§5.2). Cada fila `DP-` con test parametrizado (§5.3.3). Cada caso de escalamiento con test (§5.3.4). Invariantes de Art. 7 y límite de iteraciones cuando apliquen. `FakeLLM`, `Clock` inyectado y builders en `tests/fakes/`. |
| Riesgos | Impacto y mitigación concretos. |
| Cumplimiento | Los 10 artículos con `Cumple` o `N.A.` y una justificación concreta; nunca `Cumple` sin motivo. |

Reglas:

- **No cambies ni añadas comportamiento.** Si la spec es ambigua, contradictoria o le falta algo necesario para planificar, detente y propone corregir la spec primero con `/specify` (§4.3.3). No lo resuelvas en el plan.
- **Nunca inventes reglas de negocio**: pertenecen a la spec.
- Las decisiones técnicas con varias opciones razonables (p. ej. dos diseños de adaptador, estructura de tablas) se consultan con `AskUserQuestion`: máximo 4 preguntas por ronda, opciones concretas y la recomendada primero con "(Recommended)". Las triviales o con un default convencional se deciden y se mencionan en el resumen técnico.

## 4. Redactar el plan

1. Crea `specs/NNN-feature-name/plan.md` copiando la estructura de la plantilla y sustituye todos los placeholders `<...>` y `NNN`.
2. Cabecera: versión `0.1.0` (o incremento semver si se actualiza), fecha de hoy y, en el campo Spec, la versión aprobada exacta de la spec.
3. Las secciones que no apliquen se marcan "No aplica"; no se eliminan.
4. Elimina los comentarios `<!-- -->` de la plantilla en el resultado final.
5. No modifiques `spec.md`.

## 5. Validar

1. Comprueba que el conjunto de AC de la estrategia de pruebas es **exactamente** el conjunto de AC de la spec (ni faltan ni sobran).
2. Comprueba que no quedan placeholders `<...>`.
3. Recorre el gate de salida de la plantilla y marca lo que se cumple. Estado del plan:
   - `Borrador` si algún punto del gate (salvo la aprobación) no se cumple.
   - `En revisión` si se cumplen todos.
   - **Nunca** `Aprobado`: la aprobación la da el usuario.

No crees `tasks.md` ni código.

## 6. Reportar

Responde con: ruta del plan, número de componentes nuevos / modificados, dependencias nuevas, AC cubiertos sobre el total, riesgos de impacto alto, artículos marcados N.A. y el siguiente paso (aprobar el plan y ejecutar `/tasks-feature NNN` para pasar a la fase "Tasks").
