# Rules del proyecto

Convenciones concretas que complementan `docs/constitution.md`. Se cargan automáticamente según el frontmatter `paths:` de cada archivo.

**Precedencia:** `constitution.md` > `.claude/rules/` > `spec.md` > `plan.md` > `tasks.md` > código. Si una rule contradice la constitución, prevalece la constitución y la rule se corrige.

| Rule | Aplica a | Contenido |
|---|---|---|
| `mcp-tools.md` | Servidor MCP (`core_banking_mcp`) y contratos | Nombres, esquemas, errores, seguridad, auditoría de herramientas |
| `mcp-client.md` | Adaptador MCP del agente (`dispute_agent`) | Validación de respuestas, identidad, reintentos, auditoría |
| `mcp-testing.md` | `tests/contract`, `tests/e2e`, `tests/integration` | Cobertura por herramienta, nombrado y comentarios de trazabilidad |

Las fronteras entre capas y aplicaciones (Art. 4, Art. 6, §3.2) las impone el hook `.claude/hooks/check_mcp_boundaries.py`, no una rule.

## Cómo añadir una rule

1. Crear `.claude/rules/<tema>.md` con frontmatter `paths:` (globs) y reglas numeradas y cortas.
2. Cada regla cita el Artículo o § de la constitución que concreta.
3. No repetir lo que ya dice la constitución; si algo es verificable de forma automática, hacerlo un hook o un test.
4. Registrar la rule en la tabla de este archivo.
