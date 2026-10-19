"""Filtro determinista de datos personales en las respuestas (RN-007-26)."""

import re
from collections.abc import Iterable

_PAN = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def mask_document(document: str) -> str:
    """Enmascara un documento: ``****`` + 2 últimos caracteres (RN-001-09)."""
    if len(document) <= 4:
        return "****"
    return "****" + document[-2:]


def redact_reply(text: str, documents: Iterable[str]) -> str:
    """Redacta secuencias de 13-19 dígitos y enmascara los documentos aportados."""
    result = _PAN.sub("[REDACTED]", text)
    for document in sorted({d for d in documents if d}, key=len, reverse=True):
        result = result.replace(document, mask_document(document))
    return result


_UNIT = re.compile(r"\s*\S+")
_PAN_TAIL = re.compile(r"\d(?:[ -]?\d)*[ -]?\Z")


def _tail_may_complete_match(text: str, documents: frozenset[str]) -> int | None:
    """Inicio del sufijo de ``text`` que aún podría formar parte de un texto a sustituir."""
    starts: list[int] = []
    pan = _PAN_TAIL.search(text)
    if pan:
        starts.append(pan.start())
    for index in range(len(text)):
        suffix = text[index:]
        if any(document.startswith(suffix) for document in documents):
            starts.append(index)
            break
    return min(starts) if starts else None


class IncrementalRedactor:
    """Libera la redacción por palabras completas y ya filtradas (RN-009-06/07/08).

    Retiene la cola mientras pueda extender una secuencia de dígitos de ``_PAN`` o ser
    prefijo de un documento aportado. Lo liberado pasa por ``redact_reply``.
    """

    def __init__(self, documents: Iterable[str] = ()) -> None:
        self._documents = frozenset(d for d in documents if d)
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        """Añade un trozo y devuelve los fragmentos que ya pueden enviarse."""
        text = self._buffer + chunk
        hold = len(text.rstrip())
        units = list(_UNIT.finditer(text))
        if units and not text[-1:].isspace():
            hold = units[-1].start()
        tail = _tail_may_complete_match(text, self._documents)
        if tail is not None:
            hold = min(hold, self._unit_start(units, tail))
        self._buffer = text[hold:]
        return self._split(text[:hold])

    def finish(self) -> list[str]:
        """Termina la redacción y libera todo lo retenido."""
        text, self._buffer = self._buffer, ""
        fragments = self._split(text)
        trailing = text[len(text.rstrip()) :]
        redacted = redact_reply(text, self._documents)
        if trailing and redacted.endswith(trailing):
            fragments.append(trailing)
        return fragments

    @staticmethod
    def _unit_start(units: list[re.Match[str]], index: int) -> int:
        for unit in units:
            if unit.start() <= index < unit.end():
                return unit.start()
        return index

    def _split(self, text: str) -> list[str]:
        return [m.group() for m in _UNIT.finditer(redact_reply(text, self._documents))]
