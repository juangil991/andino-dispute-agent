"""StreamCustomerMessage: decide el turno primero y transmite la redacción palabra por palabra."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any

from dispute_agent.application.loop_control import classify_draft_end
from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditLogPort
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.ports.conversation_repository import ConversationRepository
from dispute_agent.application.ports.id_generator import IdGenerator
from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMPort,
    LLMStreamEnd,
    LLMTextDelta,
)
from dispute_agent.application.ports.sleeper import Sleeper
from dispute_agent.application.system_prompt import build_drafting_system
from dispute_agent.application.use_cases.handle_customer_message import (
    ChatTurnResult,
    ConversationNotFoundError,
    HandleCustomerMessage,
    TurnDecision,
    clean_outcome,
)
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus
from dispute_agent.domain.models.outcome import Outcome
from dispute_agent.domain.redaction import IncrementalRedactor, redact_reply

_REPLY_SHOWN_RULE = "RN-009-03"
_DRAFT_INVALID_RULE = "RN-009-09"
_DISCONNECT_RULE = "RN-009-12"


@dataclass(frozen=True)
class PreparedTurn:
    """Turno aceptado: la conversación existe (o se creó) y su id ya se conoce."""

    conversation_id: str


@dataclass(frozen=True)
class ReplyStarted:
    conversation_id: str


@dataclass(frozen=True)
class ReplyWord:
    text: str


@dataclass(frozen=True)
class ReplyEnded:
    conversation_id: str
    reply: str
    status: ConversationStatus
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class ReplyInterrupted:
    conversation_id: str
    reply: str
    status: ConversationStatus
    outcomes: tuple[Outcome, ...]


StreamEvent = ReplyStarted | ReplyWord | ReplyEnded | ReplyInterrupted


class StreamCustomerMessage:
    """Atiende un mensaje emitiendo eventos: `start`, `word`* y `end`/`interrupted`."""

    def __init__(
        self,
        handler: HandleCustomerMessage,
        llm: LLMPort,
        sleeper: Sleeper,
        audit: AuditLogPort,
        clock: Clock,
        idle_timeout_seconds: float,
        repo: ConversationRepository,
        ids: IdGenerator,
    ) -> None:
        self._handler = handler
        self._llm = llm
        self._sleeper = sleeper  # lo usan T-009-09/10 (espera máxima sin texto)
        self._audit = audit
        self._clock = clock
        self._idle_timeout_seconds = idle_timeout_seconds
        self._repo = repo
        self._ids = ids

    def prepare(self, conversation_id: str | None) -> PreparedTurn:
        """Carga o crea la conversación: `ReplyStarted` lleva el id antes del ciclo."""
        if conversation_id is None:
            conv = Conversation(conversation_id=self._ids.new_conversation_id())
            self._repo.save(conv)
            return PreparedTurn(conv.conversation_id)
        if self._repo.get(conversation_id) is None:
            raise ConversationNotFoundError(conversation_id)
        return PreparedTurn(conversation_id)

    async def events(self, prepared: PreparedTurn, message: str) -> AsyncIterator[StreamEvent]:
        yield ReplyStarted(prepared.conversation_id)
        decision = await self._decide_shielded(prepared.conversation_id, message)
        if not decision.drafted:
            # Texto fijo, sin redacción (RN-009-04); el detalle lo cubre T-009-08.
            yield _ended(self._handler.complete_turn(decision, decision.text))
            return
        conv = decision.conversation
        outcomes = tuple(clean_outcome(conv, outcome) for outcome in decision.outcomes)
        history = tuple(m for m in conv.history if isinstance(m, ChatMessage))
        redactor = IncrementalRedactor(conv.provided_documents)
        sent: list[str] = []
        end: LLMStreamEnd | None = None
        cause: str | None = None
        settled = False  # el turno ya se guardó: una desconexión posterior no cambia nada
        iterator = self._llm.stream(
            build_drafting_system(outcomes, self._clock.today()), history
        ).__aiter__()
        try:
            try:
                while (item := await self._next_item(iterator)) is not None:
                    if isinstance(item, LLMTextDelta):
                        for fragment in redactor.feed(item.text):
                            sent.append(fragment)
                            yield ReplyWord(fragment)
                    else:
                        end = item
            except _IdleTimeoutError:
                cause = "LLM_TIMEOUT"
            except LLMError:
                cause = "LLM_ERROR"
            except Exception:  # RN-009-09 (d): cualquier falla interna se trata como interrupción
                cause = "INTERNAL_ERROR"
            if cause is None and end is not None and _may_complete(end):
                tail = redactor.finish()
                if "".join([*sent, *tail]).strip():  # un texto en blanco no se envía (AC-009-11)
                    for fragment in tail:
                        sent.append(fragment)
                        yield ReplyWord(fragment)
            text = "".join(sent)
            if cause is None and (end is None or not classify_draft_end(end, text).complete):
                cause = "LLM_INVALID_OUTPUT"
            self._audit_draft_response(conv.conversation_id, end, complete=cause is None)
            if cause is not None:
                await _close(iterator)
                # La derivación corre protegida: una desconexión no la corta a medias, así que
                # desde aquí el turno se considera resuelto (no hay `_disconnect` que sumar).
                settled = True
                yield await self._interrupt_shielded(decision, text, cause)
                return
            result = self._handler.complete_turn(decision, text)
            settled = True
            self._record_reply_shown(result, "COMPLETE", None, result.reply)
            yield _ended(result)
        except (asyncio.CancelledError, GeneratorExit):
            # RN-009-12: la página cerró la conexión antes del evento final. Se cierra el flujo
            # del LLM y se guarda lo ya enviado, sin derivar ni volver a llamar al LLM.
            if not settled:
                await _close(iterator)
                self._disconnect(decision, "".join(sent))
            raise

    async def _decide_shielded(self, conversation_id: str, message: str) -> TurnDecision:
        """Decide el turno en una tarea propia: una desconexión no corta acciones a medias."""
        task = asyncio.ensure_future(self._handler.decide_turn(conversation_id, message))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await _wait_done(task)
            if task.cancelled() or task.exception() is not None:
                raise
            self._disconnect(task.result(), "")
            raise

    async def _interrupt_shielded(
        self, decision: TurnDecision, partial: str, cause: str
    ) -> ReplyInterrupted:
        """Deriva por interrupción en una tarea propia: la desconexión no la corta (RN-009-12)."""
        task = asyncio.ensure_future(self._interrupt(decision, partial, cause))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # La derivación ya empezó: se espera a que cierre y guarde, con su único
            # `reply_shown` (causa original), y recién entonces se re-lanza la cancelación.
            await _wait_done(task)
            if not task.cancelled() and task.exception() is not None:
                task.exception()  # evita el aviso de excepción no recuperada
            raise

    def _disconnect(self, decision: TurnDecision, partial: str) -> None:
        """RN-009-12: guarda lo ya hecho y audita `INTERRUPTED`/`CLIENT_DISCONNECTED`."""
        conv = decision.conversation
        if not decision.closed:
            if not decision.drafted:
                self._handler.complete_turn(decision, decision.text)  # texto fijo ya decidido
            else:
                if partial:
                    conv.history.append(ChatMessage("assistant", text=partial))
                self._repo.save(conv)
        outcomes = tuple(clean_outcome(conv, outcome) for outcome in decision.outcomes)
        self._audit.record(
            AgentAuditEvent(
                conversation_id=conv.conversation_id,
                at=self._clock.now(),
                event_type="reply_shown",
                output={
                    "result": "INTERRUPTED",
                    "cause": "CLIENT_DISCONNECTED",
                    "text": redact_reply(partial, conv.provided_documents),
                    "outcomes": [{"kind": o.kind.value, "rule": o.rule} for o in outcomes],
                },
                rule=_DISCONNECT_RULE,
                reason="la cliente se desconectó antes del evento final; no se deriva",
            )
        )

    async def _next_item(
        self, iterator: AsyncIterator[LLMTextDelta | LLMStreamEnd]
    ) -> LLMTextDelta | LLMStreamEnd | None:
        """Siguiente elemento del flujo, o `None` al terminar; compite contra la espera máxima."""
        # La espera se arma antes que la lectura: en el borde exacto (el texto llega justo al
        # cumplirse la espera máxima) gana la espera, como exige AC-009-10.
        sleep_task = asyncio.ensure_future(self._sleeper.sleep(self._idle_timeout_seconds))
        next_task = asyncio.ensure_future(anext(iterator))
        try:
            await asyncio.wait({next_task, sleep_task}, return_when=asyncio.FIRST_COMPLETED)
            if not next_task.done():
                raise _IdleTimeoutError
            try:
                return next_task.result()
            except StopAsyncIteration:
                return None
        finally:
            pending = [t for t in (next_task, sleep_task) if not t.done()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if sleep_task.done() and not sleep_task.cancelled():
                sleep_task.exception()  # evita el aviso de excepción no recuperada

    async def _interrupt(
        self, decision: TurnDecision, partial: str, cause: str
    ) -> ReplyInterrupted:
        """RN-009-10: deriva una vez, cierra y deja en el historial lo que vio la cliente."""
        conv = decision.conversation
        outcomes = list(decision.outcomes)
        fixed = await self._handler.fail_turn(
            conv, outcomes, rule=_INTERRUPTION_RULE, note=f"{_INTERRUPTION_RULE}: {cause}"
        )
        if partial:
            conv.history.append(ChatMessage("assistant", text=partial))
        result = self._handler.complete_turn(replace(decision, outcomes=tuple(outcomes)), fixed)
        self._record_reply_shown(result, "INTERRUPTED", cause, partial)
        return ReplyInterrupted(
            result.conversation_id, result.reply, result.status, result.outcomes
        )

    def _audit_draft_response(
        self, conversation_id: str, end: LLMStreamEnd | None, *, complete: bool
    ) -> None:
        """RN-009-11 / RN-007-36: cómo terminó la redacción, sin su texto ni argumentos."""
        calls = end.tool_calls if end is not None else ()
        self._audit.record(
            AgentAuditEvent(
                conversation_id=conversation_id,
                at=self._clock.now(),
                event_type="llm_response",
                input={"call": "draft"},
                output={
                    "stop_reason": end.stop_reason if end is not None else None,
                    "decision": "REPLY" if complete else "ESCALATE",
                    "tool_call_count": len(calls),
                    "tool_calls": [call.name for call in calls],
                },
                rule=_REPLY_SHOWN_RULE if complete else _DRAFT_INVALID_RULE,
                reason=(
                    "redacción completa: termina con end_turn y texto válido"
                    if complete
                    else "redacción incompleta o inválida: se interrumpe y se deriva"
                ),
            )
        )

    def _record_reply_shown(
        self, result: ChatTurnResult, outcome: str, cause: str | None, text: str
    ) -> None:
        """RN-009-11: texto enviado y `kind`/`rule` de cada outcome, para revisión humana."""
        self._audit.record(
            AgentAuditEvent(
                conversation_id=result.conversation_id,
                at=self._clock.now(),
                event_type="reply_shown",
                output={
                    "result": outcome,
                    "cause": cause,
                    "text": text,
                    "outcomes": [{"kind": o.kind.value, "rule": o.rule} for o in result.outcomes],
                },
                rule=_REPLY_SHOWN_RULE if cause is None else _INTERRUPTION_RULE,
                reason=(
                    "respuesta redactada completa enviada a la cliente"
                    if cause is None
                    else "redacción interrumpida; texto enviado antes de la falla"
                ),
            )
        )


class _IdleTimeoutError(Exception):
    """El LLM no entregó texto nuevo durante la espera máxima (RN-009-09)."""


_INTERRUPTION_RULE = "RN-009-10"


def _may_complete(end: LLMStreamEnd) -> bool:
    return end.stop_reason == "end_turn" and not end.tool_calls


async def _wait_done(task: "asyncio.Future[Any]") -> None:
    """Espera a que la tarea termine aunque lleguen más cancelaciones al consumidor."""
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            continue


async def _close(iterator: AsyncIterator[LLMTextDelta | LLMStreamEnd]) -> None:
    """Cierra el flujo del LLM si lo permite (generador asíncrono)."""
    aclose = getattr(iterator, "aclose", None)
    if aclose is not None:
        await aclose()


def _ended(result: ChatTurnResult) -> ReplyEnded:
    return ReplyEnded(result.conversation_id, result.reply, result.status, result.outcomes)
