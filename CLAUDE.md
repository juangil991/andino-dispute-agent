# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Fuente de verdad

`docs/constitution.md` es la fuente de verdad del proyecto y el documento de mayor jerarquía: misión, stack, arquitectura, contrato de herramientas MCP, flujo SDD y política de tests están definidos allí. Léela antes de cualquier tarea; si este archivo, una spec o el código la contradicen, prevalece la constitución. Este archivo no repite su contenido.

Las convenciones concretas (herramientas MCP, cliente MCP, tests de contrato) viven en `.claude/rules/` (índice en `.claude/rules/README.md`). Precedencia: constitución > rules > spec. Las fronteras entre capas las impone el hook `.claude/hooks/check_mcp_boundaries.py`; el hook `.claude/hooks/ac_coverage_gate.py` bloquea el PR de una feature sin veredicto `Cumple` vigente de `verify-ac-coverage`.

## Comandos

```
uv sync
uv run pytest                                          # suite completa
uv run pytest tests/unit/<ruta>/test_x.py::test_name   # un solo test
uv run pytest -m llm                                   # pruebas con Claude real (opcionales)
uv run playwright install chromium                     # una sola vez (pruebas de navegador)
uv run pytest -m browser                               # pruebas de navegador de la página de chat
uv run pytest --cov
uv run ruff check . ; uv run ruff format --check .
uv run mypy --strict src
```

## Entorno

- Windows 11; la shell principal es PowerShell (usar `;` o `&&` de pwsh 7, no sintaxis bash).
- `.mcp.json` configura el servidor MCP de GitHub, que requiere la variable de entorno `GITHUB_PERSONAL_ACCESS_TOKEN`.
