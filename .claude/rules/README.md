# Rules del proyecto

Convenciones concretas que complementan `docs/constitution.md`. Se cargan automáticamente según el frontmatter `paths:` de cada archivo.

**Precedencia:** `constitution.md` > `.claude/rules/` > `spec.md` > `plan.md` > `tasks.md` > código. Si una rule contradice la constitución, prevalece la constitución y la rule se corrige.

| Rule | Aplica a | Contenido |
|---|---|---|
| `mcp-tools.md` | Servidor MCP (`core_banking_mcp`) y contratos | Nombres, esquemas, errores, seguridad, auditoría de herramientas |
| `mcp-client.md` | Adaptador MCP del agente (`dispute_agent`) | Validación de respuestas, identidad, reintentos, auditoría |
| `agent-behavior.md` | Agente (`dispute_agent`: application, domain, adaptador LLM) | Ciclo agéntico, guardas, ambigüedad, multi-asunto, escalamiento y handoff |
| `mcp-testing.md` | `tests/contract`, `tests/e2e`, `tests/integration` | Cobertura por herramienta, nombrado y comentarios de trazabilidad |

Las fronteras entre capas y aplicaciones (Art. 4, Art. 6, §3.2) las impone el hook `.claude/hooks/check_mcp_boundaries.py`, no una rule. La auditoría de trazabilidad antes del PR (§4.3) la impone `.claude/hooks/ac_coverage_gate.py`: sin veredicto `Cumple` vigente de `verify-ac-coverage` no se ofrece ni se crea el PR. La skill opera en dos fases: la primera auditoría es completa; si da `No cumple`, la siguiente solo verifica que se corrigieron los hallazgos `H-NN` del primer informe.

## Cómo añadir una rule

1. Crear `.claude/rules/<tema>.md` con frontmatter `paths:` (globs) y reglas numeradas y cortas.
2. Cada regla cita el Artículo o § de la constitución que concreta.
3. No repetir lo que ya dice la constitución; si algo es verificable de forma automática, hacerlo un hook o un test.
4. Registrar la rule en la tabla de este archivo.
