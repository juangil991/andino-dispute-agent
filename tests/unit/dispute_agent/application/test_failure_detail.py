from dispute_agent.application.failure_detail import describe_failure


# Regla: RN-010-08 — la nota y el motivo de cierre indican la herramienta, el código y el campo.
# AC-010-10 · Art. 10 (ante la duda, escalar)
def test_ac_010_10_describe_failure__with_and_without_field__builds_text() -> None:
    """AC-010-10: texto de la nota y del motivo de cierre (RN-010-08)."""
    assert (
        describe_failure("consultar_transacciones", "INTERNAL", None)
        == "falla irrecuperable en consultar_transacciones (INTERNAL)"
    )
    assert (
        describe_failure("iniciar_disputa", "INVALID_INPUT", "transaction_id")
        == "falla irrecuperable en iniciar_disputa (INVALID_INPUT, campo: transaction_id)"
    )
