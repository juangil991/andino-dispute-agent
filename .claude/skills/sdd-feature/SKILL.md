---
name: sdd-feature
description: Orquesta el flujo SDD completo de una feature: crea la spec y, tras cada aprobación del usuario, el plan y las tareas; luego implementa las tareas con subagentes task-implementer (independientes en paralelo, dependientes en cadena). Usar cuando el usuario pida el flujo completo o de punta a punta de una feature, retomar una feature a medias, o invoque /sdd-feature <descripción o NNN>.
argument-hint: <descripción de la feature | NNN para retomar>
---

# /sdd-feature — Flujo SDD completo

Encadena las cuatro fases de la constitución §4.2 con un gate de aprobación humana entre cada una. Las fases 1–3 delegan en las skills `specify`, `plan-feature` y `tasks-feature`; la fase 4 delega cada tarea en el subagente `task-implementer`.

Entrada recibida: `$ARGUMENTS`

Reglas del orquestador:

- **Nunca apruebes nada sin una respuesta explícita del usuario** en `AskUserQuestion`.
- No escribes código de producción ni tests: eso lo hacen los subagentes.
- Eres el **único** que edita `tasks.md` y los campos Estado de `spec.md` y `plan.md`.
- Informa al usuario en una línea al empezar cada fase y cada oleada.

## 0. Empezar o retomar

Lee `docs/constitution.md`. Luego:

- Si `$ARGUMENTS` es un `NNN` o un slug de `specs/`, detecta la fase por los artefactos:

  | Situación | Fase |
  |---|---|
  | `spec.md` no está `Aprobada` | 1 (revisión / aprobación) |
  | `plan.md` ausente o no `Aprobado` | 2 |
  | `tasks.md` ausente | 3 |
  | `tasks.md` con tareas `[ ]` o `[~]` | 4 (las `[~]` huérfanas vuelven a `[ ]`) |
  | Todas `[x]` | 5 (cierre) |

- Si es una descripción, empieza en la fase 1.
- Si está vacío, pide la descripción o el `NNN` y detente.

## Gate de aprobación (común a las fases 1–3)

Al terminar cada fase, resume el artefacto (ruta, contenido clave, puntos que requieren atención) y pregunta con `AskUserQuestion`:

- **Aprobar (Recommended)** → aplica la aprobación de la fase y continúa.
- **Pedir cambios** → recoge los cambios (en la nota o en texto libre), vuelve a invocar la skill de la fase en modo actualización y repite el gate.
- **Detener** → termina indicando cómo retomar: `/sdd-feature NNN`.

## 1. Specify

1. Invoca la skill `specify` con la descripción.
2. Si la spec queda en `Borrador` (preguntas abiertas), no ofrezcas aprobar: resuelve las preguntas con el usuario y vuelve a invocar `specify`.
3. Gate. Al aprobar: Estado → `Aprobada`, marca la casilla de estado del gate de salida y añade fila en el historial de cambios.

## 2. Plan

1. Invoca la skill `plan-feature` con `NNN`.
2. Gate. Al aprobar: Estado → `Aprobado` y marca la casilla del gate de salida.
3. Si `plan-feature` detecta que falta algo en la spec, vuelve a la fase 1.

## 3. Tasks

1. Invoca la skill `tasks-feature` con `NNN`.
2. Antes del gate, calcula y muestra las oleadas (§4.1) para que el usuario vea qué se ejecutará en paralelo.
3. Gate. Aprobar significa autorizar la implementación.

## 4. Implement

### 4.1 Calcular oleadas

1. Parsea `tasks.md`: por tarea, ID, estado, **Depende de**, **Archivos** y **Test primero**.
2. Valida el grafo: sin ciclos, sin IDs inexistentes y todas las tareas con Archivos. Si falla, detente y propone corregirlo con `tasks-feature`.
3. Una tarea es **ejecutable** si está `[ ]` y todas sus dependencias están `[x]`.
4. Oleada = tareas ejecutables, en orden de ID, que no comparten archivos entre sí. Una tarea que comparte un archivo con otra ya elegida espera a la oleada siguiente. Se consideran siempre compartidos: `pyproject.toml`, `uv.lock`, cualquier `__init__.py`, `conftest.py`, `tests/fakes/*`, `config.py`, `main.py`, `server.py`.
5. Máximo **4** tareas por oleada.

### 4.2 Ejecutar una oleada

1. Marca las tareas de la oleada `[~]` en `tasks.md`.
2. Lanza un `Agent` con `subagent_type: "task-implementer"` por tarea, **todos en un mismo mensaje** para que corran en paralelo. Prompt de cada uno:
   - Ruta de la feature (`specs/NNN-feature-name/`).
   - ID y bloque completo de la tarea, copiado de `tasks.md`.
   - Lista exacta de archivos permitidos.
3. Al recibir cada resultado:
   - `DONE` → ejecuta tú `uv run pytest <test primero de la tarea>`; si pasa, márcala `[x]`; si no, trátala como `FAILED`.
   - `BLOCKED` o `FAILED` → vuelve a `[ ]`, anota el motivo bajo la tarea (`- **Bloqueo:** <motivo>`) y excluye a todos sus dependientes (directos y transitivos) del resto de la ejecución. Las ramas independientes siguen.
   - `BLOCKED: divergencia spec/plan` → **detén toda la implementación** al terminar la oleada y pregunta al usuario si volver a la fase 1 o 2 (§4.3.4).
4. Tras la oleada, ejecuta la suite completa `uv run pytest`. Si algo que antes pasaba ahora falla, detente y muestra la salida.
5. Recalcula y ejecuta la siguiente oleada hasta que no queden tareas ejecutables. Las cadenas de dependencias se resuelven solas, oleada a oleada.

## 5. Cierre

1. Si la última tarea es la de verificación final y sus dependencias están `[x]`, ejecútala tú: `uv run pytest --cov`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --strict src`.
2. Marca el checklist "Cierre de la feature" de `tasks.md` **solo** con lo que realmente pasó.
3. Reporta: tareas terminadas / bloqueadas / no ejecutadas (con motivo), cobertura obtenida, fallos con su salida y, si queda trabajo, cómo retomar (`/sdd-feature NNN`).
