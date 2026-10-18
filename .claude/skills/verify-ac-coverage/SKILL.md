---
name: verify-ac-coverage
description: "Audita, en solo lectura, la trazabilidad entre la spec en curso (specs/NNN-*/spec.md) y los tests. Verifica que cada AC, fila de ejemplos, RN, fila DP- y caso de escalamiento tenga al menos un test, y que cada test cite una RN y un AC que existan, sean coherentes entre sí y correspondan a lo que el test realmente verifica. Opera en dos fases: la primera auditoría es completa y emite el veredicto; si es No cumple, la siguiente solo verifica que las correcciones sugeridas se hicieron y termina en Cumple. Usar cuando el usuario pida verificar la cobertura de criterios de aceptación, revisar la trazabilidad de los tests, validar que los tests correspondan a las reglas de negocio, o invoque /verify-ac-coverage [NNN]."
argument-hint: "[NNN o NNN-feature-name]"
model: claude-sonnet-5-5
context: fork
allowed-tools: Read, Glob, Grep
---

# /verify-ac-coverage — Auditoría de trazabilidad spec ↔ tests

Comprueba que la trazabilidad exigida por la constitución (§4.3.2, §4.3.6, §5.3) y por `.claude/rules/mcp-testing.md` (§3–§5) sea **completa** (todo lo de la spec tiene test) y **verdadera** (cada test verifica de verdad la regla y el AC que cita).

Feature recibida: `$ARGUMENTS`

La skill opera en **dos fases** (ver §0):

- **Fase 1 — auditoría completa** (primera ejecución): aplica V1–V10 y emite el veredicto con todos los hallazgos, cada uno con ID `H-NN`.
- **Fase 2 — verificación de correcciones** (si la fase 1 dio `No cumple`): solo comprueba que los hallazgos `H-NN` de la fase 1 se corrigieron. No re-audita ni abre hallazgos nuevos; termina en `Cumple` cuando todos están resueltos.

Reglas de la auditoría:

- **Solo lectura.** No editas, creas ni borras archivos; no ejecutas tests ni comandos. Tu única salida es el informe final.
- **No inventes ni reinterpretes reglas de negocio**: la spec es la fuente del comportamiento. Si una RN o un AC es ambiguo o contradictorio, repórtalo como hallazgo de spec; no lo resuelvas tú.
- Todo hallazgo lleva `archivo:línea` y el ID de la verificación (`V1`…`V10`).
- Corres en un contexto aislado y no puedes preguntar al usuario: si te falta un dato, termina explicando qué necesitas.

## 1. Resolver la spec

1. Si `$ARGUMENTS` es un `NNN` o un slug, usa `specs/NNN-*/spec.md`.
2. Si está vacío, lee `.git/HEAD`; si apunta a `refs/heads/feature/NNN-*`, usa ese `NNN`.
3. Si no se resuelve o no existe la carpeta, lista las `specs/*/spec.md` con su campo **Estado** y termina pidiendo el `NNN`.

## 1b. Determinar la fase

Con el `NNN` resuelto, lee con `Read` `.claude/state/ac-coverage/NNN.json` (lo escribe el hook `ac_coverage_gate.py` tras cada ejecución; campos `verdict`, `phase`, `report`, `baseline_report`, `checked_at`).

- No existe, `verdict` es `Cumple`, o no se puede leer ⇒ **Fase 1**: sigue §2–§6 completos.
- `verdict` es `No cumple` ⇒ **Fase 2**: la línea base es `baseline_report` si existe, si no `report` (el informe de la fase 1). Si el `spec.md` es posterior a `checked_at` no hay forma de comprobarlo con `Read`; en ese caso, ante la duda, haz Fase 1.

Anuncia en la primera línea del informe qué fase ejecutas.

## 1c. Fase 2 — verificación de correcciones

Solo si la fase es 2. Omite §2–§5 y §6 (el informe de fase 1 sigue siendo la referencia).

1. Extrae de la línea base cada hallazgo `H-NN` con su `archivo:línea`, `V#` y corrección sugerida. Si un hallazgo no tiene ID, numéralos en el orden del informe.
2. Para cada uno, relee **solo** lo necesario (el test o la spec afectados, con `Read`/`Grep`; las líneas pudieron moverse, busca por nombre de test o ID) y decide:
   - `Resuelto`: la corrección sugerida, u otra equivalente, hace que la verificación `V#` original se cumpla (mismos criterios que en fase 1, incluida la correspondencia semántica V8).
   - `No resuelto`: el defecto persiste o la corrección es insuficiente; indica qué falta.
3. **No** ejecutes de nuevo V1–V10 sobre el resto de la feature ni reportes hallazgos nuevos. Única excepción: si la corrección de un hallazgo rompe de forma directa algo del mismo punto (p. ej. el test corregido ya no verifica su AC), márcalo `No resuelto` explicando la regresión.
4. Veredicto: `Cumple` si todos están `Resuelto`; `No cumple` solo si queda alguno `No resuelto`.
5. Informe de fase 2, en español y en este orden:
   1. `Veredicto: Cumple` o `Veredicto: No cumple`, con el conteo `Resuelto` / `No resuelto`.
   2. Tabla:

      | Hallazgo | V# | Estado | Evidencia (`archivo:línea`) |
      |---|---|---|---|

   3. Si hay `No resuelto`: qué falta exactamente en cada uno. **Siguiente paso**: corregirlos y volver a ejecutar la skill (repite fase 2 sobre la misma línea base).
   4. Si todo está `Resuelto`: indica que la feature queda aprobada y puede ofrecerse el PR (§4.3).

## 2. Cargar contexto (solo fase 1)

1. `docs/constitution.md`: §4.3 (trazabilidad), §5.2 (niveles), §5.3 (reglas específicas), §5.4 (aserciones significativas).
2. `.claude/rules/mcp-testing.md` (nombrado, comentario de trazabilidad, invariantes).
3. `specs/NNN-feature-name/spec.md` y, si existen, su `plan.md` (estrategia de pruebas: nivel esperado por AC) y `tasks.md` (archivos de test previstos por tarea).

## 3. Inventario de la spec

Construye estas tablas antes de mirar los tests:

| Elemento | Origen en la spec | Qué extraer |
|---|---|---|
| Reglas de negocio | §4 | ID `RN-NNN-XX` y enunciado |
| Criterios de aceptación | §6 | ID `AC-NNN-XX`, línea `Cubre:` (HU y RN), Given/When/Then y cada fila de su tabla de ejemplos |
| Tabla de decisión | §5 | Cada fila `DP-` (o "No aplica") |
| Contrato MCP | §7 | Herramientas y códigos de error |
| Escalamiento | §8 | Cada condición que debe escalar |

## 4. Inventario de tests

1. Con `Grep`, localiza en `tests/` todos los `def test_` y `async def test_`, y todas las menciones de `AC-NNN-` y `RN-NNN-` de la feature.
2. Para cada test que cite IDs de la feature (o que esté en un archivo que los cite), lee con `Read`:
   - el docstring y el bloque de comentarios inmediatamente superior (`# Regla: …`, `# AC-… · Art. N`);
   - el decorador `@pytest.mark.parametrize` con sus filas e `ids=`;
   - el cuerpo completo (Arrange / Act / Assert) y los fakes o builders de `tests/fakes/` que use, si hace falta para entender los datos.
3. Registra también los tests de esos archivos **sin** IDs: son candidatos a huérfanos.

## 5. Verificaciones

| # | Verificación | Severidad |
|---|---|---|
| V1 | Cada AC tiene al menos un test que lo cita. | Bloqueante |
| V2 | Cada fila de la tabla de ejemplos de un AC está cubierta por un caso parametrizado o un test propio con esos mismos valores. | Bloqueante |
| V3 | Cada RN está cubierta por al menos un test; cada fila `DP-` tiene caso parametrizado (§5.3.3); cada caso de escalamiento tiene test (§5.3.4). | Bloqueante |
| V4 | Cada test lleva línea `Regla:` y línea `AC-` (rule §4). Los tests de invariantes pueden citar el Artículo en lugar de una RN (rule §5). | Bloqueante |
| V5 | Los IDs citados existen en la spec: ni de otra feature, ni inexistentes, ni con formato inválido. | Bloqueante |
| V6 | La RN citada figura en la línea `Cubre:` del AC citado. | Mayor |
| V7 | El enunciado tras `Regla: RN-…` es fiel al de la spec (no describe otra regla). | Mayor |
| V8 | **Correspondencia semántica**: el test verifica efectivamente la RN y el AC que cita: el Arrange reproduce el Given, el Act ejecuta el When y las aserciones comprueban el Then (valores, banderas, códigos de error, ausencia de datos). Un test sin aserciones significativas o que verifica otra cosa no cuenta como cobertura (§5.4). | Mayor |
| V9 | En `tests/contract`, `tests/integration` y `tests/e2e`, el nombre sigue `test_<tool>__<condition>__<expected_outcome>` y los parametrizados tienen `ids=` legibles (rule §3). | Menor |
| V10 | El nivel del test (unit / integration / contract / e2e) coincide con la estrategia de pruebas del `plan.md`. | Menor |

Criterios:

- Un test que falla V5 o V8 **no** cuenta para la cobertura de V1–V3.
- En V8, contrasta los valores concretos: si el AC dice `D-1001` y `masked_document = "****01"`, el test debe usar datos equivalentes y afirmar ese resultado, no uno parecido.
- Si un test cubre una RN que su comentario no cita, señálalo como sugerencia (añadir la cita), no como cobertura faltante.

## 6. Informe (fase 1)

Tu respuesta final es el informe, en español, con este orden:

1. **Veredicto**: `Cumple` o `No cumple` (cualquier hallazgo Bloqueante o Mayor ⇒ `No cumple`), con el conteo de hallazgos por severidad.
2. **Matriz de AC**:

   | AC | Filas cubiertas / total | Tests (`archivo:línea`) | Estado |
   |---|---|---|---|

3. **Matriz de RN** (y de `DP-` y escalamiento si aplican):

   | RN | Tests (`archivo:línea`) | Estado |
   |---|---|---|

4. **Hallazgos**, agrupados por severidad. Para cada uno: ID estable `H-01`, `H-02`… (la fase 2 los usa como lista de comprobación), `archivo:línea`, `V#`, qué cita o qué falta, qué debería citar o verificar según la spec, y una corrección concreta y verificable.
5. **Tests huérfanos**: sin IDs o con IDs inexistentes.
6. **Hallazgos de spec** (ambigüedades o contradicciones detectadas), si los hay.
7. **Siguiente paso**: si el veredicto es `No cumple`, corregir los tests (p. ej. con el subagente `task-implementer`) o, si el defecto está en la spec, actualizarla primero con `/specify` (§4.3.3, §4.3.4); después volver a ejecutar la skill, que hará solo la verificación de correcciones (fase 2). Si es `Cumple`, la feature queda aprobada.
