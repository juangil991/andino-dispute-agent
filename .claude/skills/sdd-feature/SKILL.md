---
name: sdd-feature
description: Orquesta el flujo SDD completo de una feature: crea la spec y, tras cada aprobación del usuario, el plan y las tareas; luego implementa las tareas con subagentes task-implementer (independientes en paralelo, dependientes en cadena). Crea la rama de la feature tras la spec y, al cerrar, ofrece abrir un pull request. Usar cuando el usuario pida el flujo completo o de punta a punta de una feature, retomar una feature a medias, o invoque /sdd-feature <descripción o NNN>. Con `--backlog` toma la siguiente spec por prioridad del tablero de GitHub (estado Ready).
argument-hint: <descripción de la feature | NNN para retomar | --backlog>
model: claude-opus-5-5
allowed-tools: Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, Skill, Bash(git status:*), Bash(git branch:*), Bash(git switch:*), Bash(git fetch origin main), Bash(git add:*), Bash(git commit:*), Bash(git push -u origin feature/*), Bash(uv run pytest:*), Bash(uv run ruff:*), Bash(uv run mypy:*), PowerShell(git status:*), PowerShell(git branch:*), PowerShell(git switch:*), PowerShell(git fetch origin main), PowerShell(git add:*), PowerShell(git commit:*), PowerShell(git push -u origin feature/*), PowerShell(uv run pytest:*), PowerShell(uv run ruff:*), PowerShell(uv run mypy:*), mcp__github__create_pull_request, mcp__github__projects_list, mcp__github__projects_write
---

# /sdd-feature — Flujo SDD completo

Encadena las cuatro fases de la constitución §4.2 con un gate de aprobación humana entre cada una. Las fases 1–3 delegan en las skills `specify`, `plan-feature` y `tasks-feature`; la fase 4 delega cada tarea en el subagente `task-implementer`.

Entrada recibida: `$ARGUMENTS`

Reglas del orquestador:

- **Nunca apruebes nada sin una respuesta explícita del usuario** en `AskUserQuestion`.
- No escribes código de producción ni tests: eso lo hacen los subagentes.
- Eres el **único** que edita `tasks.md` y los campos Estado de `spec.md` y `plan.md`.
- Informa al usuario en una línea al empezar cada fase y cada oleada.
- Eres el **único** que ejecuta operaciones git (rama, commit, push, PR); los subagentes no.
- **Nunca hagas push ni abras un PR** sin respuesta explícita en `AskUserQuestion`.

## Mínimo privilegio

Usa solo los permisos que la tarea en curso necesita (`allowed-tools` del frontmatter):

- **Escritura** solo en `specs/NNN-feature-name/`. Nunca en `src/`, `tests/`, `docs/constitution.md` ni `.claude/`.
- **Git** limitado a: ver estado, `git fetch origin main`, crear o cambiar a `feature/NNN-*`, `add`/`commit` de los archivos de la feature y push de esa rama. Prohibido: force-push, reset, rebase, borrar ramas, push a `main` y merge de PRs.
- **GitHub**: `create_pull_request` solo tras confirmación del usuario; lectura del proyecto 2 de `juangil991` (`projects_list`); y `projects_write` **solo para el campo Status del ítem tomado**. Nunca crear ni borrar ítems ni editar otros campos.
- **Subagentes**: pásales únicamente la ruta de la feature, su tarea y sus archivos permitidos.
- Si una acción requiere un permiso fuera de esta lista, pídelo al usuario; no lo amplíes por tu cuenta.

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

  Antes de continuar, comprueba la rama (`git branch --show-current`): si no es `feature/NNN-feature-name`, haz `git switch` a ella o créala (ver "Rama de la feature").
- Si es `--backlog`, ejecuta "Tomar del backlog"; su resultado es la descripción de entrada de la fase 1.
- Si es una descripción, empieza en la fase 1.
- Si está vacío, pide la descripción, el `NNN` o `--backlog` y detente.

## Tomar del backlog

Tablero: owner `juangil991` (`owner_type: user`), `project_number: 2`. Campos: Status (Backlog, Ready, In progress, In review, Done) y Priority (P0, P1, P2).

1. `mcp__github__projects_list` con `method: list_project_items`, `query: "status:Ready"` y `field_names: ["Status", "Priority", "Title"]`; pagina hasta agotar.
2. Ordena por Priority (P0 → P1 → P2; sin Priority al final); desempata por orden del tablero.
3. Si no hay ítems en Ready, informa y detente sugiriendo mover ítems de Backlog a Ready.
4. Muestra el ítem elegido y los 2–3 siguientes, y confirma con `AskUserQuestion`: **Tomar este (Recommended)** / **Elegir otro** / **Cancelar**.
5. Al confirmar, `projects_write` → Status = **In progress** (solo ese campo, solo ese ítem).
6. Entrada de la fase 1: título y cuerpo del ítem (si es una issue, cita `#N` en la spec); si es un borrador sin cuerpo útil, solo el título. `specify` mantiene su clarificación obligatoria.
7. Una sola spec por invocación. Si falla la API (permisos, token con scope `project`), repórtalo y ofrece recibir la descripción a mano.

## Gate de aprobación (común a las fases 1–3)

Al terminar cada fase, resume el artefacto (ruta, contenido clave, puntos que requieren atención) y pregunta con `AskUserQuestion`:

- **Aprobar (Recommended)** → aplica la aprobación de la fase y continúa.
- **Pedir cambios** → recoge los cambios (en la nota o en texto libre), vuelve a invocar la skill de la fase en modo actualización y repite el gate.
- **Detener** → termina indicando cómo retomar: `/sdd-feature NNN`.

## 1. Specify

1. Invoca la skill `specify` con la descripción.
2. Si la spec queda en `Borrador` (preguntas abiertas), no ofrezcas aprobar: resuelve las preguntas con el usuario y vuelve a invocar `specify`.
3. Gate. Al aprobar: Estado → `Aprobada`, marca la casilla de estado del gate de salida y añade fila en el historial de cambios.

### Rama de la feature

Se ejecuta en cuanto existe `specs/NNN-feature-name/` (tras `specify`), antes del gate de la spec, para que spec, plan y tareas queden en ella.

1. Nombre: `feature/NNN-feature-name` (carpeta de la spec).
2. Si `git status` muestra cambios ajenos a `specs/NNN-*/`, avisa al usuario antes de crear la rama.
3. Si la rama ya existe, `git switch feature/NNN-feature-name` sin tocarla. Si no existe, actualiza main primero: `git fetch origin main` y crea la rama desde la punta remota con `git switch -c feature/NNN-feature-name origin/main` (también si estás en `HEAD` desacoplado). El fetch no modifica el árbol de trabajo. Si el fetch falla (sin remoto o sin red), repórtalo y detente sin crear la rama desde una base desactualizada.
4. Informa la rama en una línea.

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
3. Reporta: tareas terminadas / bloqueadas / no ejecutadas (con motivo), cobertura obtenida, veredicto de la auditoría de AC (5.5) con su conteo de hallazgos, fallos con su salida y, si queda trabajo, cómo retomar (`/sdd-feature NNN`). Si se creó el PR (fase 6), incluye rama y URL.

## 5.5 Auditoría de cobertura de AC

1. Si todas las tareas están `[x]`, invoca la skill `verify-ac-coverage` con `NNN` antes de cualquier pregunta sobre el PR.
2. `Cumple` → continúa a la fase 6.
3. `No cumple` → muestra los hallazgos Bloqueantes y Mayores y **no ofrezcas el PR**. Pregunta con `AskUserQuestion`: **Corregir (Recommended)** (vuelve a la fase 4 con tareas para los hallazgos; si el defecto está en la spec, a la fase 1) / **Solo commit local** / **Detener**. Tras corregir, vuelve a invocar `verify-ac-coverage`: la segunda ejecución es la fase 2 y solo verifica que los hallazgos `H-NN` de la primera se corrigieron (no abre hallazgos nuevos).

## 6. Pull request

1. El PR exige un veredicto `Cumple` de 5.5 posterior al último cambio en `tests/` o en la spec; lo impone el hook `.claude/hooks/ac_coverage_gate.py`, que bloquea la pregunta y la creación del PR. Si hay tareas bloqueadas o fallidas, menciónalo en la pregunta; no abras el PR en silencio.
2. Pregunta con `AskUserQuestion`:
   - **Crear PR (Recommended)**
   - **Solo commit local**
   - **No hacer nada**
3. Si elige PR:
   1. Muestra `git status` y haz commit solo de los archivos de la feature (mensaje `feat(NNN): <título de la spec>`).
   2. `git push -u origin feature/NNN-feature-name`.
   3. Crea el PR contra `main` con `mcp__github__create_pull_request` (alternativa: `gh pr create`). Título = título de la spec; cuerpo = resumen de la spec, tareas hechas/bloqueadas, cobertura, veredicto de `verify-ac-coverage` y resultado de ruff/mypy; añade `Closes #N` si la spec viene de una issue del backlog.
   4. Si la spec vino del backlog, `projects_write` → Status = **In review**.
   5. Devuelve la URL del PR.
4. Si no hay remoto `origin` o el push falla, repórtalo y detente sin forzar nada.
5. Si eligió "Solo commit local" o "No hacer nada", o el flujo se detuvo antes, el ítem del backlog sigue en **In progress**: avísalo y recuerda `/sdd-feature NNN` para retomar. No muevas a Done (lo hace el merge o el usuario).
6. Al terminar, sugiere `/sdd-feature --backlog` para la siguiente spec.
