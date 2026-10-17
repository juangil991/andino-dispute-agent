# Spec: <Nombre de la feature>

<!-- Qué y por qué. Nada de cómo: eso va en plan.md. Ver constitución §4. -->

| Campo | Valor |
|---|---|
| Feature | `NNN-feature-name` |
| Versión | 0.1.0 |
| Estado | Borrador \| En revisión \| Aprobada |
| Fecha | AAAA-MM-DD |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

<!-- Situación actual, a quién afecta y por qué hay que resolverlo ahora. -->

<...>

## 2. Objetivos

- <Objetivo verificable 1>
- <Objetivo verificable 2>

### Fuera de alcance

- <Lo que esta feature explícitamente no cubre>

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-NNN-01 | <rol> | <acción> | <beneficio> |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-NNN-01 | <regla expresada de forma verificable> | <...> |

## 5. Tabla de decisión de `DisputePolicy`

<!-- Solo si la feature afecta decisiones de disputa (constitución Art. 5 y §4.3.6). Cada fila tendrá al menos un test. Si no aplica, escribir "No aplica". -->

| ID regla | Condiciones | Decisión | Acciones permitidas | Motivo comunicado |
|---|---|---|---|---|
| DP-NNN-01 | <condición 1 ∧ condición 2> | RESOLVE \| REJECT \| ESCALATE | <herramientas MCP habilitadas> | <...> |

## 6. Criterios de aceptación

<!-- Un ID único por criterio (constitución §4.3.2). Los tests lo citan en su nombre o docstring. -->

### AC-NNN-01 — <título corto>

Cubre: HU-NNN-01, RN-NNN-01

- **Given** <estado inicial>
- **When** <acción>
- **Then** <resultado observable>

### AC-NNN-02 — <título corto>

Cubre: <...>

- **Given** <...>
- **When** <...>
- **Then** <...>

## 7. Contratos de herramientas MCP

<!-- Una subsección por herramienta creada o modificada (constitución §3.4). Si no aplica, escribir "No aplica". -->

### `<nombre_herramienta>`

- **Propósito:** <...>
- **Cuándo usarla / cuándo no:** <criterio que evita confusión con otras herramientas>
- **Precondiciones:** <p. ej. identidad verificada (Art. 7)>

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| <campo> | <tipo> | Sí \| No | <...> |

**Salida**

| Campo | Tipo | Descripción |
|---|---|---|
| <campo> | <tipo> | <...> |

<!-- Indicar qué devuelve cuando no hay resultados (no es un error) o hay varias coincidencias. -->

**Errores**

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| <CODIGO> | transitorio \| validación \| negocio \| permisos | Sí \| No | <...> |

## 8. Casos de escalamiento

<!-- Situaciones que terminan en escalar_a_analista (constitución Art. 10). -->

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| <...> | <...> | <cliente, transacciones, decisión, evidencia...> |

## 9. Clarificaciones

<!-- Preguntas resueltas durante la especificación. Toda respuesta debe reflejarse en las secciones afectadas. -->

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| AAAA-MM-DD | <...> | <...> | <§4 RN-NNN-01, §6 AC-NNN-02> |

## 10. Preguntas abiertas

<!-- La spec no puede aprobarse con preguntas abiertas. -->

- [ ] <pregunta> — Responsable: <...>

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | AAAA-MM-DD | Versión inicial | <...> |

---

## Gate de salida

- [ ] No quedan preguntas abiertas.
- [ ] Cada clarificación está reflejada en las secciones afectadas.
- [ ] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [ ] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [ ] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [ ] Estado cambiado a **Aprobada**.
