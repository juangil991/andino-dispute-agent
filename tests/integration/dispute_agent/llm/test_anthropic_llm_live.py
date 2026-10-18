"""Pruebas opcionales con Claude real (AC-007-13, AC-007-29). Se excluyen por defecto."""

import os

import pytest

from dispute_agent.application.agent_tools import LLM_TOOLS
from dispute_agent.application.ports.llm import ChatMessage, ToolCall, ToolResult
from dispute_agent.application.system_prompt import SYSTEM_PROMPT
from dispute_agent.infrastructure.outbound.llm.anthropic_llm_adapter import (
    AnthropicLLMAdapter,
)

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="Sin ANTHROPIC_API_KEY"),
]

_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
_HUMAN = [
    "quiero hablar con una persona",
    "pásame con un asesor humano",
    "prefiero que me atienda un analista",
    "quiero hablar con alguien del banco",
]
_NOT_HUMAN = [
    "no entiendo lo que me pide",
    "esto es muy lento",
    "no sé cuál es el cobro",
]


def _adapter() -> AnthropicLLMAdapter:
    return AnthropicLLMAdapter(api_key=os.environ["ANTHROPIC_API_KEY"], model=_MODEL)


# Regla: RN-007-18 — Cuando el cliente pide expresamente que lo atienda una persona (lo
# interpreta el LLM y lo indica al agente), el agente deriva **de inmediato**, en cualquier
# momento de la conversación, y cierra la conversación. En ese turno no invoca
# `consultar_transacciones` ni `iniciar_disputa`, aunque el mismo mensaje pida otras cosas.
# La derivación usa el motivo `OTHER` y la nota `Cliente solicitó atención humana`, con
# resumen completo (sin transacción ni tarjeta) si está verificado y limitado si no. Frases
# de frustración o de duda que no piden una persona no derivan por sí solas.
# AC-007-12 · Art. 10
async def test_ac_007_12_live__human_request_phrases__invoke_human_tool() -> None:
    """AC-007-12: las 4 frases que piden una persona invocan solicitar_atencion_humana."""
    adapter = _adapter()
    for phrase in _HUMAN:
        response = await adapter.complete(SYSTEM_PROMPT, (ChatMessage("user", phrase),), LLM_TOOLS)
        assert any(c.name == "solicitar_atencion_humana" for c in response.tool_calls), phrase


# Regla: RN-007-18 — Cuando el cliente pide expresamente que lo atienda una persona (lo
# interpreta el LLM y lo indica al agente), el agente deriva **de inmediato**, en cualquier
# momento de la conversación, y cierra la conversación. En ese turno no invoca
# `consultar_transacciones` ni `iniciar_disputa`, aunque el mismo mensaje pida otras cosas.
# La derivación usa el motivo `OTHER` y la nota `Cliente solicitó atención humana`, con
# resumen completo (sin transacción ni tarjeta) si está verificado y limitado si no. Frases
# de frustración o de duda que no piden una persona no derivan por sí solas.
# AC-007-13 · Art. 10
async def test_ac_007_13_live__non_human_phrases__do_not_invoke_human_tool() -> None:
    """AC-007-13: frases de duda o frustración no invocan solicitar_atencion_humana."""
    adapter = _adapter()
    for phrase in _NOT_HUMAN:
        response = await adapter.complete(SYSTEM_PROMPT, (ChatMessage("user", phrase),), LLM_TOOLS)
        assert all(c.name != "solicitar_atencion_humana" for c in response.tool_calls), phrase


# Regla: RN-007-25 — Cada respuesta de `POST /api/chat` incluye el texto redactado por el LLM
# (`reply`) y la lista estructurada `outcomes` con lo ocurrido en el turno (§7.3): por cada
# acción o decisión, su tipo, la transacción o tarjeta enmascarada, la regla aplicada, el
# motivo y los próximos pasos, ambos en español y con el texto fijo de §5 o de §7.3. El LLM
# recibe esos `outcomes` para redactar la respuesta, pero no puede alterarlos.
# AC-007-29 · Art. 10
async def test_ac_007_29_live__spanish_reply__mentions_reason_and_next_steps() -> None:
    """AC-007-29: el reply está en español y explica qué se hizo, por qué y próximos pasos."""
    outcomes = (
        '{"outcomes": [{"kind": "DISPUTE_OPENED", "rule": "DP-007-05",'
        ' "transaction_id": "TX-0001", "masked_card": "**** 4321", "reference": "D-0001",'
        ' "reason": "El cobro cumple las condiciones para abrir la disputa de inmediato.",'
        ' "next_steps": "Tu disputa quedó abierta; el banco la gestionará y te informará'
        ' el resultado."}]}'
    )
    history = (
        ChatMessage("user", "No reconozco un cobro de mi tarjeta, ¿qué hicieron?"),
        ChatMessage(
            "assistant",
            tool_calls=(ToolCall("toolu_1", "iniciar_disputa", {"transaction_id": "TX-0001"}),),
        ),
        ChatMessage("user", tool_results=(ToolResult("toolu_1", outcomes),)),
    )
    response = await _adapter().complete(SYSTEM_PROMPT, history, LLM_TOOLS)
    text = response.text.lower()
    assert text
    # Motivo: cumple las condiciones / abrir la disputa; próximos pasos: banco gestiona/informa.
    assert any(
        w in text for w in ("condiciones", "cumple", "inmediato", "abrir", "abrió", "abierta")
    )
    assert any(w in text for w in ("banco", "gestion", "informar", "resultado"))
    # Español: algún término funcional en español y sin marcadores típicos del inglés.
    assert any(w in text for w in (" tu ", " la ", " el ", " de ", " que "))
    assert not any(w in text for w in (" the ", " your ", " dispute "))
