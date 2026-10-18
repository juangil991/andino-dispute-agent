"""Fronteras de dispute_agent (Art. 6) y dependencias del esqueleto (plan §2, §6)."""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT_SRC = ROOT / "src" / "dispute_agent"
FORBIDDEN = ("core_banking_mcp", "sqlalchemy")

PACKAGES = [
    "domain",
    "domain/models",
    "domain/policies",
    "application",
    "application/ports",
    "application/use_cases",
    "infrastructure",
    "infrastructure/inbound",
    "infrastructure/inbound/web",
    "infrastructure/inbound/web/api",
    "infrastructure/outbound",
    "infrastructure/outbound/llm",
    "infrastructure/outbound/mcp",
    "infrastructure/outbound/persistence",
    "infrastructure/outbound/audit",
    "infrastructure/outbound/clock",
    "infrastructure/outbound/ids",
]


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def test_dispute_agent_modules_do_not_import_core_or_sqlalchemy() -> None:
    """Invariante: Art. 6 / plan §6 Fronteras.

    dispute_agent no importa core_banking_mcp ni sqlalchemy, y cada carpeta
    de plan §2 existe como paquete.
    """
    missing = [p for p in PACKAGES if not (AGENT_SRC / p / "__init__.py").is_file()]
    assert not missing, f"paquetes sin __init__.py: {missing}"

    offenders = [
        f"{path.relative_to(ROOT)}: {module}"
        for path in AGENT_SRC.rglob("*.py")
        for module in _imported_modules(path)
        if _is_forbidden(module)
    ]
    assert not offenders, offenders


def test_agent_dependencies_declared() -> None:
    """Soporte T-007-01: dependencias del agente declaradas en pyproject."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = " ".join(data["project"]["dependencies"]).lower()
    dev = " ".join(data["dependency-groups"]["dev"]).lower()
    for name in ("fastapi", "uvicorn", "anthropic"):
        assert name in deps, name
    assert "httpx" in dev
