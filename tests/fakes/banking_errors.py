"""Builders de errores de herramientas del core para tests."""

from dispute_agent.application.ports.banking_tools import BankingToolError


def invalid_input(field: str, message: str | None = None) -> BankingToolError:
    """Error INVALID_INPUT no reintentable que señala el campo inválido."""
    return BankingToolError(
        code="INVALID_INPUT",
        message=message or f"Valor inválido en el campo {field}",
        retryable=False,
        field=field,
    )
