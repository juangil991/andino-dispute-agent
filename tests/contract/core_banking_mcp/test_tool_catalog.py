"""Snapshot del catálogo de herramientas del servidor `core_banking_mcp` (specs 001 y 002 §7)."""

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from core_banking_mcp.config import CoreSettings
from core_banking_mcp.infrastructure.inbound.mcp.schemas import (
    BloquearTarjetaOut,
    BuscarClienteOut,
    ConsultarTransaccionesOut,
    EscalarAnalistaOut,
    IniciarDisputaOut,
    VerificarIdentidadOut,
)
from core_banking_mcp.server import build_server


def _list_tools() -> list[Tool]:
    server = build_server(CoreSettings(database_url="sqlite://", seed_on_start=False))

    async def run() -> list[Tool]:
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return (await session.list_tools()).tools

    return anyio.run(run)


# Regla: RN-002-01 — la solicitud aporta customer_id, birth_date y document_issue_date (parte de
#   RN-002-01 que verifica este snapshot: los campos de entrada del catálogo); el catálogo expone
#   solo las herramientas declaradas en spec §7.
# AC-002-01 · Art. 7 (mínima exposición)
def test_ac_002_01_catalog_exposes_buscar_cliente_and_verificar_identidad() -> None:
    """AC-002-01: list_tools devuelve solo buscar_cliente y verificar_identidad con sus esquemas."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "escalar_a_analista",
        "iniciar_disputa",
        "verificar_identidad",
    ]
    buscar, verificar = tools["buscar_cliente"], tools["verificar_identidad"]

    assert set(buscar.inputSchema["properties"]) == {
        "conversation_id",
        "document",
        "full_name",
        "card_last4",
    }
    assert not buscar.inputSchema.get("required")
    assert "bligatorio" in buscar.inputSchema["properties"]["conversation_id"]["description"]

    assert buscar.outputSchema is not None
    expected = BuscarClienteOut.model_json_schema()
    assert buscar.outputSchema["properties"] == expected["properties"]
    assert buscar.outputSchema["$defs"]["CustomerMatchOut"]["additionalProperties"] is False

    assert set(verificar.inputSchema["properties"]) == {
        "conversation_id",
        "customer_id",
        "birth_date",
        "document_issue_date",
    }
    assert not verificar.inputSchema.get("required")
    assert "bligatorio" in verificar.inputSchema["properties"]["conversation_id"]["description"]

    assert verificar.outputSchema is not None
    expected_out = VerificarIdentidadOut.model_json_schema()
    assert verificar.outputSchema["properties"] == expected_out["properties"]
    assert verificar.outputSchema["additionalProperties"] is False


# Regla: RN-003-12 — cada transacción devuelta contiene solo: `transaction_id`, `occurred_at`,
#   `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card` (parte de RN-003-12 que
#   verifica este snapshot: los campos del esquema de salida, sin campos extra); el catálogo
#   expone solo las herramientas declaradas en spec §7.
# AC-003-14 · Art. 7 (mínima exposición)
def test_ac_003_14_catalog_exposes_consultar_transacciones_with_spec_schemas() -> None:
    """AC-003-14: list_tools incluye consultar_transacciones con esquemas de la spec 003 §7."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "escalar_a_analista",
        "iniciar_disputa",
        "verificar_identidad",
    ]
    consultar = tools["consultar_transacciones"]

    properties = consultar.inputSchema["properties"]
    assert set(properties) == {"conversation_id", "card_last4", "date_from", "date_to"}
    assert not consultar.inputSchema.get("required")
    assert all(properties[name].get("description") for name in properties)
    assert "bligatorio" in properties["conversation_id"]["description"]

    assert consultar.outputSchema is not None
    expected = ConsultarTransaccionesOut.model_json_schema()
    assert consultar.outputSchema["properties"] == expected["properties"]
    assert consultar.outputSchema["additionalProperties"] is False
    assert consultar.outputSchema["$defs"]["TransactionItemOut"]["additionalProperties"] is False


# Regla: RN-004-12 — la respuesta contiene solo `dispute_id`, `status`, `opened_at`, `reason` y
#   `transaction` (parte de RN-004-12 que verifica este snapshot: los campos del esquema de salida).
# Regla: RN-004-13 — la entrada y salida de la herramienta no exponen datos sensibles (parte que
#   verifica este snapshot: salida cerrada con `additionalProperties: false`; entrada con sus 4
#   campos documentados y el `enum` de `reason`); el catálogo expone solo las herramientas
#   declaradas en spec §7.
# AC-004-15 · Art. 7 (mínima exposición)
def test_ac_004_15_catalog_exposes_iniciar_disputa_with_spec_schemas() -> None:
    """AC-004-15: list_tools incluye iniciar_disputa con los esquemas de la spec 004 §7."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "escalar_a_analista",
        "iniciar_disputa",
        "verificar_identidad",
    ]
    disputa = tools["iniciar_disputa"]

    properties = disputa.inputSchema["properties"]
    assert set(properties) == {"conversation_id", "transaction_id", "reason", "idempotency_key"}
    assert not disputa.inputSchema.get("required")
    assert all(properties[name].get("description") for name in properties)
    assert "bligatorio" in properties["conversation_id"]["description"]
    assert properties["reason"]["enum"] == [
        "UNRECOGNIZED_CHARGE",
        "DUPLICATE_CHARGE",
        "INCORRECT_AMOUNT",
        "NOT_RECEIVED",
        "OTHER",
    ]

    assert disputa.outputSchema is not None
    expected = IniciarDisputaOut.model_json_schema()
    assert disputa.outputSchema["properties"] == expected["properties"]
    assert disputa.outputSchema["additionalProperties"] is False
    assert disputa.outputSchema["$defs"]["TransactionItemOut"]["additionalProperties"] is False


# Regla: RN-005-10 — La respuesta exitosa contiene **solo** `card_id`, `masked_card` (`**** `
#   seguido de los 4 últimos dígitos, RN-001-09), `status` (`BLOCKED`), `blocked_at`, `reason` y
#   `already_blocked`. (Parte que verifica este snapshot: los campos del esquema de salida.)
# Regla: RN-005-11 — La respuesta nunca contiene el número completo de ninguna tarjeta, el
#   documento del cliente ni su nombre, ni datos de otros clientes. (Parte que verifica este
#   snapshot: salida cerrada con `additionalProperties: false`; entrada con sus 4 campos
#   documentados y el `enum` de `reason`); el catálogo expone solo las herramientas declaradas
#   en spec §7.
# AC-005-13 · Art. 7 (mínima exposición)
def test_ac_005_13_catalog_exposes_bloquear_tarjeta_with_spec_schemas() -> None:
    """AC-005-13: list_tools incluye bloquear_tarjeta con los esquemas de la spec 005 §7."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "escalar_a_analista",
        "iniciar_disputa",
        "verificar_identidad",
    ]
    bloquear = tools["bloquear_tarjeta"]

    properties = bloquear.inputSchema["properties"]
    assert set(properties) == {"conversation_id", "card_id", "reason", "idempotency_key"}
    assert not bloquear.inputSchema.get("required")
    assert all(properties[name].get("description") for name in properties)
    assert "bligatorio" in properties["conversation_id"]["description"]
    assert properties["reason"]["enum"] == ["FRAUD_SUSPECTED", "LOST_OR_STOLEN"]

    assert bloquear.outputSchema is not None
    expected = BloquearTarjetaOut.model_json_schema()
    assert bloquear.outputSchema["properties"] == expected["properties"]
    assert bloquear.outputSchema["additionalProperties"] is False


# Regla: RN-006-12 — La respuesta exitosa contiene **solo** `escalation_id`, `status`,
#   `escalated_at`, `reason` y `summary`. `summary` contiene **solo** `conversation_id`,
#   `identity_verified`, `customer_id`, `transaction` (con exactamente los campos de
#   `TransactionItem` de la spec 003, RN-003-12, o `null`), `card` (con exactamente `card_id` y
#   `masked_card`, `**** ` seguido de los 4 últimos dígitos, RN-001-09, o `null`), `prior_actions`,
#   `dispute_id` y `note`. (Parte que verifica este snapshot: los campos de los esquemas de salida y
#   de entrada.)
# Regla: RN-006-13 — La respuesta nunca contiene el número completo de ninguna tarjeta, el documento
#   del cliente ni su nombre, ni datos de otros clientes. (Parte que verifica este snapshot:
#   esquemas de salida cerrados con `additionalProperties: false`; el catálogo expone solo las
#   herramientas declaradas en spec §7.)
# AC-006-18 · Art. 7 (mínima exposición)
def test_ac_006_18_catalog_exposes_escalar_a_analista_with_spec_schemas() -> None:  # noqa: E501
    """AC-006-18: list_tools incluye escalar_a_analista con los esquemas de la spec 006 §7."""
    tools = {t.name: t for t in _list_tools()}
    assert sorted(tools) == [
        "bloquear_tarjeta",
        "buscar_cliente",
        "consultar_transacciones",
        "escalar_a_analista",
        "iniciar_disputa",
        "verificar_identidad",
    ]
    escalar = tools["escalar_a_analista"]

    properties = escalar.inputSchema["properties"]
    assert set(properties) == {
        "conversation_id",
        "reason",
        "idempotency_key",
        "transaction_id",
        "card_id",
        "prior_actions",
        "dispute_id",
        "note",
    }
    assert not escalar.inputSchema.get("required")
    assert all(properties[name].get("description") for name in properties)
    assert "bligatorio" in properties["conversation_id"]["description"]
    assert properties["reason"]["enum"] == [
        "FRAUD_SUSPECTED",
        "AMOUNT_OVER_THRESHOLD",
        "INSUFFICIENT_OR_CONTRADICTORY_INFO",
        "INCONCLUSIVE_RULES",
        "UNRECOVERABLE_SYSTEM_FAILURE",
        "IDENTITY_VERIFICATION_FAILED",
        "OTHER",
    ]
    prior_actions = properties["prior_actions"]
    items = prior_actions.get("items") or next(
        option["items"] for option in prior_actions["anyOf"] if "items" in option
    )
    assert items["enum"] == ["DISPUTE_OPENED", "CARD_BLOCKED"]

    assert escalar.outputSchema is not None
    expected = EscalarAnalistaOut.model_json_schema()
    assert escalar.outputSchema["properties"] == expected["properties"]
    assert escalar.outputSchema["$defs"] == expected["$defs"]
    assert escalar.outputSchema["additionalProperties"] is False
    assert all(d["additionalProperties"] is False for d in escalar.outputSchema["$defs"].values())
