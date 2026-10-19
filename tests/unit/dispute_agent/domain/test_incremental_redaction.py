"""Redacción incremental por palabras completas (spec 009, AC-009-05 y AC-009-06)."""

import re

import pytest

from dispute_agent.domain.redaction import IncrementalRedactor, mask_document, redact_reply

_DOCUMENT = "D-1001"


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _stream(text: str, size: int, documents: frozenset[str] = frozenset()) -> list[str]:
    redactor = IncrementalRedactor(documents)
    fragments: list[str] = []
    for chunk in _chunks(text, size):
        fragments.extend(redactor.feed(chunk))
    fragments.extend(redactor.finish())
    return fragments


@pytest.mark.parametrize(
    "content",
    [
        "Tildes, ñandú y emojis 😀",
        "Línea 1\nLínea 2",
        "Mira " + "x" * 80,
        "<b>texto</b> con marcas de código",
    ],
)
# Regla: RN-009-06 — un fragmento es una palabra completa con su espacio previo; RN-009-08 — la
#   concatenación es exactamente el `reply`.
# AC-009-05 · Art. 7
def test_ac_009_05_words_are_never_split_or_altered(content: str) -> None:
    """AC-009-05: una palabra completa por fragmento; la concatenación es exacta."""
    fragments = _stream(content, 3)

    assert "".join(fragments) == content
    for fragment in fragments:
        assert re.fullmatch(r"\s*\S+", fragment), repr(fragment)
    assert len(fragments) == len(content.split())


@pytest.mark.parametrize(
    ("text", "forbidden", "reply"),
    [
        (
            "Tu tarjeta 4111 1111 1111 4321 fue bloqueada.",
            "4111",
            "Tu tarjeta [REDACTED] fue bloqueada.",
        ),
        (
            "Tu documento D-1001 está verificado.",
            "D-1001",
            "Tu documento " + mask_document(_DOCUMENT) + " está verificado.",
        ),
        (
            "Bloqueamos tu tarjeta **** 4321.",
            None,
            "Bloqueamos tu tarjeta **** 4321.",
        ),
    ],
)
# Regla: RN-009-07 — el filtro de RN-007-26 se aplica antes de liberar cada fragmento.
# AC-009-06 · Art. 7
def test_ac_009_06_filter_applies_before_each_word(
    text: str, forbidden: str | None, reply: str
) -> None:
    """AC-009-06: ningún fragmento contiene lo que el filtro sustituiría."""
    fragments = _stream(text, 2, frozenset({_DOCUMENT}))

    if forbidden is not None:
        assert all(forbidden not in fragment for fragment in fragments)
    assert "".join(fragments) == reply


@pytest.mark.parametrize("size", range(1, 8))
@pytest.mark.parametrize(
    "text",
    [
        "Tu tarjeta 4111 1111 1111 4321 fue bloqueada y 4111-1111-1111-4321 también.",
        "Doc D-1001 y D-1001. Número 1234567890123456 al final 4111 1111 1111 4321",
        "Cuenta 12 34 y monto 85.000 COP, ref 4111 1111 1111 ",
        "  espacios   múltiples\ty\nsaltos  ",
    ],
)
# Regla: RN-009-07 — el filtro se aplica antes de liberar cada fragmento; RN-009-08 — la
#   concatenación es exactamente el `reply`.
# AC-009-06 · Art. 7
def test_ac_009_06_any_chunking_matches_full_redaction(text: str, size: int) -> None:
    """AC-009-06: cualquier troceo equivale a ``redact_reply`` del texto completo."""
    documents = frozenset({_DOCUMENT})

    fragments = _stream(text, size, documents)

    assert "".join(fragments) == redact_reply(text, documents)
    assert all(not re.search(r"\d{13,}", fragment) for fragment in fragments)
