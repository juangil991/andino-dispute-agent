"""Verifica el esqueleto del proyecto (T-001-01)."""

import importlib
import tomllib
from pathlib import Path


# Soporte de tests: el paquete es importable, fuera de la trazabilidad de AC · Art. 4
def test_core_banking_mcp_package_is_importable() -> None:
    """Habilita todos los AC de la feature 001: el paquete existe y se importa."""
    module = importlib.import_module("core_banking_mcp")
    assert module.__name__ == "core_banking_mcp"


# Soporte de tests: el extra `cli` de mcp habilita MCP Inspector, fuera de la trazabilidad de AC
# Plan 002 §5 · Art. 2 (stack)
def test_mcp_cli_extra_is_declared() -> None:
    """Soporte (plan 002 §5): `pyproject.toml` declara `mcp[cli]>=1.13,<2`."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "mcp[cli]>=1.13,<2" in data["project"]["dependencies"]
