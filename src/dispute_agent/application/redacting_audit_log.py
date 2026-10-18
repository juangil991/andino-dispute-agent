"""AuditLogPort que redacta PAN y documentos de todo evento antes de delegarlo (RN-007-28)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditLogPort
from dispute_agent.domain.redaction import redact_reply


@dataclass(frozen=True)
class RedactingAuditLog:
    """Aplica `redact_reply` a todos los textos del evento; no muta el original."""

    inner: AuditLogPort
    documents_for: Callable[[str], Iterable[str]]

    def record(self, event: AgentAuditEvent) -> None:
        documents = tuple(self.documents_for(event.conversation_id))
        self.inner.record(
            replace(
                event,
                tool=_text(event.tool, documents),
                input=_mapping(event.input, documents),
                output=_mapping(event.output, documents),
                rule=_text(event.rule, documents),
                reason=_text(event.reason, documents),
            )
        )


def _text(value: str | None, documents: tuple[str, ...]) -> str | None:
    return None if value is None else redact_reply(value, documents)


def _mapping(
    value: dict[str, object] | None, documents: tuple[str, ...]
) -> dict[str, object] | None:
    if value is None:
        return None
    return {key: _clean(item, documents) for key, item in value.items()}


def _clean(value: object, documents: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return redact_reply(value, documents)
    if isinstance(value, dict):
        return {key: _clean(item, documents) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item, documents) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean(item, documents) for item in value)
    return value
