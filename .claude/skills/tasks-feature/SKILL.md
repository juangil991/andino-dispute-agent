---
name: tasks-feature
description: Crea la lista de tareas de una feature (specs/NNN-feature-name/tasks.md) a partir de specs/_templates/tasks.md, solo cuando su plan.md está Aprobado. Usar cuando el usuario pida desglosar una feature en tareas, crear o actualizar un tasks.md, pasar a la fase Tasks, o invoque /tasks-feature <NNN o slug>.
argument-hint: <NNN o NNN-feature-name>
---

# /tasks-feature — Fase 3 del flujo SDD

Genera el `tasks.md` de una feature con plan aprobado (constitución §4.2, fase "Tasks"). Solo traduce el plan en pasos TDD ordenados y trazables: nunca añade comportamiento ni diseño, ni escribe código o tests.

Feature recibida: `$ARGUMENTS`

## 1. Cargar contexto

1. Lee `docs/constitution.md` completa, con atención a §3.2 y §3.6 (capas y carpetas), §5 (política de tests) y §5.5 (Definition of Done).
2. Resuelve la feature a partir de `$ARGUMENTS` (número `NNN` o slug completo). Si está vacío o no coincide, lista las features de `specs/` con el estado de su spec y su plan y pregunta cuál desglosar; detente hasta recibir la respuesta.
3. Lee `specs/NNN-feature-name/spec.md`, `specs/NNN-feature-name/plan.md` y `specs/_templates/tasks.md`.
4. Explora `src/` y `tests/` (incluido `tests/fakes/`) para reutilizar fakes, builders y módulos existentes en lugar de planificar duplicados.

## 2. Gate de entrada (bloqueante)

- La spec debe estar `Aprobada` y el plan `Aprobado`. Si no, informa el estado actual, recuerda que la aprobación la da el usuario y **detente sin crear nada**.
- El campo Spec del plan debe referenciar la versión vigente de la spec. Si no coincide, el plan está desactualizado: detente y propone actualizarlo con `/plan-feature`.
- Si ya existe `tasks.md`, pregunta si se **actualiza** o se aborta. Al actualizar: conserva los estados `[x]` y `[~]`, no renumeres las tareas existentes y añade las nuevas con los IDs siguientes.

## 3. Desglosar

Orden de las tareas, de adentro hacia afuera:

| # | Bloque | Contenido típico |
|---|---|---|
| 1 | Soporte de tests | Fakes de puertos, builders, `Clock` y `FakeLLM` en `tests/fakes/` |
| 2 | `domain` | Entidades, value objects, errores, `DisputePolicy` (un test parametrizado por fila `DP-`) |
| 3 | `application` | Puertos y casos de uso, probados con fakes |
| 4 | Contratos MCP | Esquemas de herramientas en `tests/contract/`, ambos lados |
| 5 | `infrastructure/outbound` | SQLAlchemy, cliente MCP, Anthropic, auditoría |
| 6 | `infrastructure/inbound` | Herramientas FastMCP, routers FastAPI, estáticos |
| 7 | Cableado y datos | `main.py` / `server.py`, `config.py`, semillas ficticias |
| 8 | End-to-end | Chat → agente → MCP stdio → SQLite con `FakeLLM` |
| 9 | Verificación final | Suite completa con cobertura, lint, formato y tipado (§5.5) |

Omite los bloques que el plan no toque.

Reglas:

- **No añadas componentes, dependencias ni comportamiento** que no estén en el plan. Si falta algo para desglosar, detente y vuelve a `/plan-feature` (o a `/specify` si es comportamiento).
- **Una tarea = un ciclo Red → Green → Refactor** (§5.1): un test, o un grupo parametrizado, más el código mínimo, normalmente sobre un componente de una sola capa.
- Cada tarea rellena todos los campos de la plantilla:
  - **Cubre:** AC de la spec. Las tareas de soporte (fakes, builders, semillas, cableado) indican las tareas o AC que habilitan.
  - **App / capa:** según §3.2.
  - **Depende de:** solo tareas anteriores; sin ciclos. Declara **todas** las dependencias reales: las tareas sin dependencia entre sí se ejecutarán en paralelo.
  - **Archivos:** rutas completas de todo archivo que la tarea crea o modifica (código, tests, fakes, `__init__.py`, configuración). El orquestador las usa para no ejecutar en paralelo tareas que tocan el mismo archivo.
  - **Test primero:** ruta real según §5.2 y §3.6, con nombre `test_ac_NNN_XX_<descripcion>` cuando verifique un AC (§4.3.2).
  - **Red:** qué debe fallar y por qué motivo.
  - **Green:** el cambio mínimo para pasar.
  - **Refactor:** mejoras previstas, o "—".
- Respeta la estrategia de pruebas del plan: cada nivel asignado a un AC tiene al menos una tarea.
- Incluye las tareas de los casos de escalamiento (§5.3.4) y de las invariantes que el plan prevea (Art. 7, límite de iteraciones, decisiones no ejecutables).
- La última tarea es la verificación: `uv run pytest --cov`, `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.

## 4. Redactar las tareas

1. Crea `specs/NNN-feature-name/tasks.md` copiando la estructura de la plantilla y sustituye todos los placeholders `<...>` y `NNN`.
2. Cabecera: versiones exactas de la spec y del plan aprobados, y fecha de hoy.
3. IDs `T-NNN-XX` consecutivos desde `01`; todas las tareas nuevas en `[ ]`.
4. Matriz de trazabilidad con una fila por AC de la spec, sus tareas y sus tests.
5. Elimina los comentarios `<!-- -->` de la plantilla en el resultado final.
6. No modifiques `spec.md` ni `plan.md`.

## 5. Validar

1. El conjunto de AC de la matriz es **exactamente** el de la spec (ni faltan ni sobran).
2. Toda fila `DP-` y todo caso de escalamiento de la spec tiene al menos una tarea.
3. Toda tarea tiene test primero y archivos, y sus dependencias apuntan solo a tareas anteriores.
4. Si una tarea usa un archivo que crea otra, depende de ella.
5. No quedan placeholders `<...>`.

Si algo falla, corrígelo antes de reportar. No escribas código ni tests.

## 6. Reportar

Responde con: ruta de las tareas, número de tareas por app y capa, AC cubiertos sobre el total, primera tarea a ejecutar y el siguiente paso (fase "Implement": aprobar las tareas y ejecutar `/sdd-feature NNN`, que las implementa con TDD en paralelo o en cadena según sus dependencias).
