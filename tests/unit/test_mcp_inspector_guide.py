"""Guía de prueba manual con MCP Inspector (T-002-17)."""

from pathlib import Path

from core_banking_mcp.infrastructure.outbound.persistence.seeds.customers import (
    SEED_CUSTOMERS,
)

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "mcp-inspector.md"


# Soporte de tests: guía de prueba manual, fuera de la trazabilidad de AC — plan §1 y §5.
# Art. 1 (datos ficticios): las fechas citadas se leen de SEED_CUSTOMERS.
def test_mcp_inspector_guide_documents_command_and_seed_examples() -> None:
    """Soporte (plan §1/§5): la guía existe, da el comando y cita las semillas."""
    text = GUIDE.read_text(encoding="utf-8")

    assert "uv run mcp dev src/core_banking_mcp/server.py" in text
    assert "Node.js" in text
    assert "data/core_banking.db" in text
    assert "verificar_identidad" in text
    assert "buscar_cliente" in text
    # conversation_id es un argumento obligatorio de cada llamada (spec 002 §7).
    assert "mecanismo de identidad de conversación" not in text
    assert "reinicie la conexión entre casos" not in text
    assert "conversation_id" in text
    assert "obligatorio" in text
    for customer, _pans, identity in SEED_CUSTOMERS:
        if customer.customer_id in {"C-0001", "C-0002"}:
            assert customer.customer_id in text
            assert identity.birth_date.isoformat() in text
            assert identity.document_issue_date.isoformat() in text
