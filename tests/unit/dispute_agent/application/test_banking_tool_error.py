"""Tests del error de negocio de las herramientas del core (campo inválido)."""

from tests.fakes.banking_errors import invalid_input

from dispute_agent.application.ports.banking_tools import BankingToolError


# Regla: RN-010-08 — el error conserva el campo inválido, que habilita el diagnóstico.
# AC-010-10 · Art. 10 (ante la duda, escalar)
def test_banking_tool_error__field_argument__is_kept_and_defaults_to_none() -> None:
    """AC-010-10: el error conserva el campo inválido; sin campo vale None."""
    without_field = BankingToolError("NOT_FOUND", "no existe", False)
    with_field = BankingToolError("INVALID_INPUT", "fecha inválida", False, field="date_to")
    built = invalid_input("date_to")

    assert without_field.field is None
    assert with_field.field == "date_to"
    assert built.code == "INVALID_INPUT"
    assert built.retryable is False
    assert built.field == "date_to"
