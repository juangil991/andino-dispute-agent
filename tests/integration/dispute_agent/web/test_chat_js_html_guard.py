"""Guarda estática: `chat.js` no usa APIs que interpreten texto como HTML (spec 008)."""

from pathlib import Path

import pytest

import dispute_agent

_CHAT_JS = (
    Path(dispute_agent.__file__).parent
    / "infrastructure"
    / "inbound"
    / "web"
    / "static"
    / "chat.js"
)


# Regla: RN-008-09 — ningún texto se interpreta como HTML ni se ejecuta.
# AC-008-07 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    "api",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("],
)
def test_ac_008_07_chat_js__no_html_injection_apis__none_used(api: str) -> None:
    """AC-008-07: `chat.js` no contiene APIs de inyección de HTML ni de evaluación de código."""
    assert api not in _CHAT_JS.read_text(encoding="utf-8")
