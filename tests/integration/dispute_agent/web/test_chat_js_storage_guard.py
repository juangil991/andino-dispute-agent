"""Guarda estática: `chat.js` no usa almacenamiento del navegador.

Spec 008: AC-008-13.
"""

import re
from pathlib import Path

_CHAT_JS = (
    Path(__file__).resolve().parents[4]
    / "src/dispute_agent/infrastructure/inbound/web/static/chat.js"
)


# Regla: RN-008-12 — El estado de la conversación vive solo en memoria; no se guarda en
# localStorage, sessionStorage, IndexedDB ni cookies.
# AC-008-13 · Art. 7
def test_ac_008_13_chat_js__no_browser_storage_apis__none_used() -> None:
    """AC-008-13: `chat.js` no referencia ninguna API de almacenamiento del navegador."""
    source = _CHAT_JS.read_text(encoding="utf-8")

    forbidden = re.findall(r"localStorage|sessionStorage|indexedDB|document\s*\.\s*cookie", source)

    assert forbidden == []
