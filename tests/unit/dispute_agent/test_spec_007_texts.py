"""Coherencia spec 007 <-> código: textos fijos de §7.4 y versión (Art. 2, §4.3.3)."""

import re
from pathlib import Path

from dispute_agent.domain.identification import IdentificationReply
from dispute_agent.domain.messages import IDENTIFICATION_REPLIES

_SPEC = Path(__file__).resolve().parents[3] / "specs" / "007-dispute-resolution-agent" / "spec.md"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section_7_4(spec: str) -> str:
    match = re.search(r"^### 7\.4 .*?(?=^## )", spec, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, "La spec 007 no tiene la sección 7.4"
    return match.group(0)


# Regla: RN-010-06 — el texto fijo INVALID_SEARCH de la spec 007 coincide con el código.
# AC-010-08 · Art. 2 (la spec es fuente de verdad)
def test_spec_007__invalid_search_text_and_version__match_code() -> None:
    """Spec 010 / AC-010-08 (Art. 2): §7.4 de la spec 007 recoge INVALID_SEARCH.

    La versión de la spec debe ser ≥ 0.4.0 (0.4.x).
    """
    spec = _SPEC.read_text(encoding="utf-8")
    expected = _normalize(IDENTIFICATION_REPLIES[IdentificationReply.INVALID_SEARCH])

    assert expected in _normalize(_section_7_4(spec))
    assert re.search(r"^\|\s*Versión\s*\|\s*0\.4\.\d+\s*\|", spec, flags=re.MULTILINE), (
        "La spec 007 debe estar en versión >= 0.4.0 (0.4.x)"
    )
