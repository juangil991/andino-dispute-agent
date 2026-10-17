"""Verifica el esqueleto del proyecto (T-001-01)."""

import importlib


def test_core_banking_mcp_package_is_importable() -> None:
    """Habilita todos los AC de la feature 001: el paquete existe y se importa."""
    module = importlib.import_module("core_banking_mcp")
    assert module.__name__ == "core_banking_mcp"
