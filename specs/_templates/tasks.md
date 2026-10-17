# Tareas: <Nombre de la feature>

<!-- Tareas pequeñas y ordenadas. Cada una empieza por su test (constitución §5.1). -->

| Campo | Valor |
|---|---|
| Feature | `NNN-feature-name` |
| Spec | [spec.md](./spec.md) — versión <x.y.z> |
| Plan | [plan.md](./plan.md) — versión <x.y.z> |
| Fecha | AAAA-MM-DD |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

---

## Tareas

### [ ] T-NNN-01 — <título corto>

- **Cubre:** AC-NNN-01
- **App / capa:** `<dispute_agent | core_banking_mcp>` / `<domain | application | infrastructure/inbound | infrastructure/outbound>`
- **Depende de:** —
- **Archivos:** <rutas completas que la tarea crea o modifica>
- **Test primero:** `tests/<unit|integration|contract|e2e>/<app>/<ruta>/test_<x>.py::test_ac_NNN_01_<descripcion>`
- **Red:** <qué debe fallar y por qué>
- **Green:** <cambio mínimo para pasar>
- **Refactor:** <mejoras previstas, o "—">

### [ ] T-NNN-02 — <título corto>

- **Cubre:** <...>
- **App / capa:** <...>
- **Depende de:** T-NNN-01
- **Archivos:** <...>
- **Test primero:** <...>
- **Red:** <...>
- **Green:** <...>
- **Refactor:** <...>

## Matriz de trazabilidad

<!-- Todo AC de la spec debe aparecer al menos una vez. -->

| AC | Tareas | Tests |
|---|---|---|
| AC-NNN-01 | T-NNN-01 | `test_ac_NNN_01_<descripcion>` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [ ] Todos los AC trazados a tests en verde.
- [ ] Umbrales de cobertura cumplidos.
- [ ] Lint, formato y tipado sin errores.
- [ ] Spec actualizada al comportamiento implementado.
- [ ] Sin secretos ni datos reales.
