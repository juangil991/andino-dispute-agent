"""HandleCustomerMessage: loop de tool use, identificación, guardas y resultados del turno."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from dispute_agent.application.agent_tools import LLM_TOOLS, WRITE_TOOLS
from dispute_agent.application.failure_detail import describe_failure
from dispute_agent.application.loop_control import LoopStep, LoopVerdict, classify_llm_response
from dispute_agent.application.ports.audit_log import AgentAuditEvent, AuditEventType, AuditLogPort
from dispute_agent.application.ports.banking_tools import (
    BankingToolError,
    BankingToolsPort,
    BankingToolUnavailableError,
    TransactionPage,
)
from dispute_agent.application.ports.clock import Clock
from dispute_agent.application.ports.conversation_repository import ConversationRepository
from dispute_agent.application.ports.id_generator import IdGenerator
from dispute_agent.application.ports.llm import (
    ChatMessage,
    LLMError,
    LLMPort,
    LLMResponse,
    ToolCall,
    ToolResult,
)
from dispute_agent.application.system_prompt import build_decision_system
from dispute_agent.application.use_cases.dispute_actions import DisputeActions
from dispute_agent.application.use_cases.escalation_service import EscalationService
from dispute_agent.application.use_cases.fraud_actions import FraudActions
from dispute_agent.domain import messages
from dispute_agent.domain.identification import (
    IdentificationReply,
    IdentificationStep,
    select_identification_reply,
)
from dispute_agent.domain.models.conversation import Conversation, ConversationStatus, KnownCard
from dispute_agent.domain.models.decision import EscalationReason
from dispute_agent.domain.models.outcome import Outcome, OutcomeKind
from dispute_agent.domain.models.transaction import DisputedTransaction
from dispute_agent.domain.redaction import redact_reply

_DEFAULT_REASON = "UNRECOGNIZED_CHARGE"
# Códigos de motivo que acepta `evaluar_disputa` (espejo de application/agent_tools.py).
_DISPUTE_REASONS = frozenset(
    {"UNRECOGNIZED_CHARGE", "DUPLICATE_CHARGE", "INCORRECT_AMOUNT", "NOT_RECEIVED", "OTHER"}
)
_UNVERIFIED_RULE = "RN-007-01"
_UNVERIFIED_TURN_RULE = "RN-007-37"
_REMINDERS = frozenset({IdentificationReply.REMINDER_LOCATE, IdentificationReply.REMINDER_VERIFY})
_SEARCH_RULE = "RN-007-02"
_VERIFY_RULE = "RN-007-03"
_NO_MATCH_RULE = "RN-007-05"
_NO_TRANSACTIONS_RULE = "RN-007-13"
_VERIFICATION_FAILED_RULE = "RN-007-04"
_UNEVALUATED_WRITE_RULE = "RN-007-11"
_SYSTEM_DECIDES_RULE = "Art. 5"
_HUMAN_TOOL = "solicitar_atencion_humana"
_HUMAN_RULE = "RN-007-18"
_HUMAN_FRAUD_RULE = "RN-007-19"
_FRAUD_TOOL = "reportar_fraude"
_CARD_RULE = "RN-007-15"
_FAILURE_RULE = "RN-007-21"
_LLM_RULE = "RN-007-23"
_UNAVAILABLE_CODE = "UNAVAILABLE"
_INVALID_INPUT_RULE = "RN-010-01"
_MAX_CORRECTIONS = 2  # RN-010-03
_CAP_RULE = "RN-010-04"
_UNKNOWN_CARD_RULE = "RN-011-03"
_NOT_FOUND_RULE = "RN-011-05"
_CARD_CAP_RULE = "RN-011-07"
# Motivo fijo por regla para el evento `llm_response` (RN-007-36); nunca incluye texto del LLM.
_LLM_RESPONSE_REASONS = {
    "RN-007-32": "la razón de parada del LLM decide si continuar o responder",
    "RN-007-34": "razón de parada inesperada del LLM",
    "RN-007-35": "respuesta del LLM incoherente o vacía",
    _LLM_RULE: "límite de llamadas al LLM superado",
}
_READ_TOOLS = frozenset({"buscar_cliente", "verificar_identidad", "consultar_transacciones"})
_INTENT_TOOLS = frozenset({"evaluar_disputa", "reportar_fraude", "solicitar_atencion_humana"})
_ALLOWED_ARGUMENTS: dict[str, frozenset[str]] = {
    "buscar_cliente": frozenset({"document", "full_name", "card_last4"}),
    "verificar_identidad": frozenset({"birth_date", "document_issue_date"}),
    "consultar_transacciones": frozenset({"card_last4", "date_from", "date_to"}),
    "evaluar_disputa": frozenset({"transaction_id", "reason"}),
    "reportar_fraude": frozenset({"card_last4", "transaction_ids"}),
    "solicitar_atencion_humana": frozenset(),
}


class ConversationNotFoundError(Exception):
    """El `conversation_id` recibido no existe."""


class IterationLimitExceeded(Exception):  # noqa: N818 - nombre fijado por tasks.md T-007-14
    """El LLM superó el máximo de llamadas por mensaje (RN-007-23); lo captura T-007-15."""


class LLMOutputError(Exception):
    """Salida inválida del LLM (RN-007-23, RN-007-34, RN-007-35); `rule` indica la regla."""

    def __init__(self, message: str, rule: str = _LLM_RULE) -> None:
        super().__init__(message)
        self.rule = rule


@dataclass(frozen=True)
class ChatTurnResult:
    """Resultado de un turno: respuesta filtrada, estado y outcomes."""

    conversation_id: str
    reply: str
    status: ConversationStatus
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class TurnDecision:
    """Estado del turno tras el ciclo: sin la respuesta redactada ni guardada.

    `drafted` es `True` si el ciclo terminó en `end_turn` (`text` es el borrador); si no, `text`
    es un texto fijo. `closed` marca una conversación ya cerrada (RN-007-24): no se guarda nada.
    """

    conversation: Conversation
    outcomes: tuple[Outcome, ...]
    text: str
    drafted: bool
    closed: bool = False


@dataclass(frozen=True)
class _SearchArgs:
    document: str | None
    full_name: str | None
    card_last4: str | None


@dataclass(frozen=True)
class _VerifyArgs:
    birth_date: str
    document_issue_date: str


@dataclass(frozen=True)
class _ListArgs:
    card_last4: str
    date_from: str | None
    date_to: str | None


@dataclass(frozen=True)
class _EvaluateArgs:
    transaction_id: str
    reason: str


@dataclass(frozen=True)
class _FraudArgs:
    card_last4: str | None
    transaction_ids: tuple[str, ...] | None


_Parsed = _SearchArgs | _VerifyArgs | _ListArgs | _EvaluateArgs | _FraudArgs | None


class HandleCustomerMessage:
    """Atiende un mensaje del cliente ejecutando el loop con el LLM."""

    def __init__(
        self,
        llm: LLMPort,
        banking: BankingToolsPort,
        repo: ConversationRepository,
        dispute_actions: DisputeActions,
        fraud_actions: FraudActions,
        escalation: EscalationService,
        audit: AuditLogPort,
        clock: Clock,
        ids: IdGenerator,
        max_iterations: int,
    ) -> None:
        self._llm = llm
        self._banking = banking
        self._repo = repo
        self._dispute_actions = dispute_actions
        self._fraud_actions = fraud_actions
        self._escalation = escalation
        self._audit_log = audit
        self._clock = clock
        self._ids = ids
        self._max_iterations = max_iterations

    async def handle(self, conversation_id: str | None, message: str) -> ChatTurnResult:
        decision = await self.decide_turn(conversation_id, message)
        return self.complete_turn(decision, decision.text)

    async def decide_turn(self, conversation_id: str | None, message: str) -> TurnDecision:
        """Carga, cierre previo (RN-007-24), ciclo y fallas; no redacta ni guarda la respuesta.

        `drafted` indica que el ciclo terminó en `end_turn`; si no, `text` es un texto fijo.
        """
        conv = self._load(conversation_id)
        if conv.status is ConversationStatus.ESCALATED:
            # RN-007-24: cerrada; ni LLM ni herramientas, y la conversación no cambia.
            return TurnDecision(
                conv, (), messages.CONVERSATION_CLOSED_MESSAGE, drafted=False, closed=True
            )
        conv.begin_turn()  # RN-007-41: el rastro de identificación es por turno
        conv.history.append(ChatMessage("user", text=message))
        outcomes: list[Outcome] = []
        try:
            text = await self._run_loop(conv, outcomes)
            drafted = True
        except IterationLimitExceeded:
            drafted = False
            text = await self.fail_turn(
                conv,
                outcomes,
                EscalationReason.INCONCLUSIVE_RULES,
                OutcomeKind.ITERATION_LIMIT,
                "límite de llamadas al LLM superado",
                _LLM_RULE,
            )
        except (LLMError, LLMOutputError) as error:
            drafted = False
            text = await self.fail_turn(
                conv,
                outcomes,
                rule=error.rule if isinstance(error, LLMOutputError) else _LLM_RULE,
            )
        if drafted and conv.verified_customer_id is None:
            text = self._identification_reply(conv, outcomes)
            drafted = False
        return TurnDecision(conv, tuple(outcomes), text, drafted=drafted)

    def _identification_reply(self, conv: Conversation, outcomes: Sequence[Outcome]) -> str:
        """RN-007-38: sin verificar, el reply es un texto fijo de §7.4 (el del LLM se descarta)."""
        last_kind = outcomes[-1].kind if outcomes else None
        reply = select_identification_reply(conv, last_kind)
        if reply in _REMINDERS:
            # RN-007-42: solo nombres de herramientas; nunca texto ni argumentos · Art. 8
            self._audit(
                conv,
                "identification_required",
                tool=None,
                input={"requested_tools": list(conv.turn_blocked_tools)},
                output={"reply": reply.value},
                rule=_UNVERIFIED_TURN_RULE,
                reason="solicitud rechazada por falta de identificación",
            )
        return messages.IDENTIFICATION_REPLIES[reply]

    def complete_turn(self, decision: TurnDecision, reply: str) -> ChatTurnResult:
        """Filtra (RN-007-26), registra en el historial, guarda y limpia los `outcomes`."""
        conv = decision.conversation
        if decision.closed:
            return ChatTurnResult(conv.conversation_id, reply, conv.status, ())
        reply = redact_reply(reply, conv.provided_documents)
        conv.history.append(ChatMessage("assistant", text=reply))
        self._repo.save(conv)
        cleaned = tuple(clean_outcome(conv, outcome) for outcome in decision.outcomes)
        return ChatTurnResult(conv.conversation_id, reply, conv.status, cleaned)

    async def fail_turn(
        self,
        conv: Conversation,
        outcomes: list[Outcome],
        reason: EscalationReason = EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE,
        kind: OutcomeKind = OutcomeKind.LLM_FAILURE,
        why: str = "falla o salida inválida del LLM",
        rule: str = _LLM_RULE,
        note: str | None = None,
    ) -> str:
        """RN-007-23/34/35: deriva, cierra y responde con el texto fijo, sin llamar al LLM.

        `note` (opcional) sustituye la nota de la derivación; sin ella se usa la habitual.
        """
        failure = Outcome(
            kind=kind,
            rule=rule,
            reason=messages.OUTCOME_REASONS[kind],
            next_steps=messages.OUTCOME_NEXT_STEPS[kind],
        )
        if conv.status is ConversationStatus.ESCALATED:
            # Ya derivada en este turno: no se duplica la derivación.
            outcomes.append(failure)
        else:
            escalated = await self._escalation.escalate(conv, reason, rule, note=note)
            self._close(conv, "llm", rule, why)
            if escalated.kind is OutcomeKind.ESCALATION_FAILED:
                outcomes.extend([failure, escalated])
                failure = escalated
            else:
                failure = replace(failure, reference=escalated.reference)
                outcomes.append(failure)
        return f"{failure.reason} {failure.next_steps}"

    def _load(self, conversation_id: str | None) -> Conversation:
        if conversation_id is None:
            return Conversation(conversation_id=self._ids.new_conversation_id())
        conv = self._repo.get(conversation_id)
        if conv is None:
            raise ConversationNotFoundError(conversation_id)
        return conv

    async def _run_loop(self, conv: Conversation, outcomes: list[Outcome]) -> str:
        for iteration in range(1, self._max_iterations + 1):
            history = tuple(m for m in conv.history if isinstance(m, ChatMessage))
            system = build_decision_system(self._clock.today())
            response = await self._llm.complete(system, history, LLM_TOOLS)
            reply = self._decide(conv, response, iteration)
            if reply is not None:
                return reply
            parsed = [(call, _parse(call)) for call in response.tool_calls]
            conv.history.append(ChatMessage("assistant", response.text, response.tool_calls))
            if any(call.name == _HUMAN_TOOL for call, _ in parsed):
                results = await self._human_request(conv, parsed, outcomes)
            else:
                results = [await self._dispatch(conv, c, args, outcomes) for c, args in parsed]
            conv.history.append(ChatMessage("user", tool_results=tuple(results)))
        raise IterationLimitExceeded(self._max_iterations)

    def _decide(self, conv: Conversation, response: LLMResponse, iteration: int) -> str | None:
        """RN-007-32/34/35: decide por la razón de parada, antes de parsear o ejecutar nada.

        Devuelve el texto a enviar al cliente, o `None` si el loop debe continuar.
        """
        verdict = classify_llm_response(response)
        capped = verdict.step is LoopStep.CONTINUE and iteration == self._max_iterations
        self._audit_llm_response(conv, response, verdict, iteration, capped)
        if verdict.step is LoopStep.ESCALATE:
            raise LLMOutputError(verdict.why, rule=verdict.rule)
        if verdict.step is LoopStep.REPLY:
            return response.text
        if capped:
            # No se ejecuta ninguna acción pendiente de la última respuesta (RN-007-23).
            raise IterationLimitExceeded(iteration)
        return None

    def _audit_llm_response(
        self,
        conv: Conversation,
        response: LLMResponse,
        verdict: LoopVerdict,
        iteration: int,
        capped: bool,
    ) -> None:
        """RN-007-36: registra cómo terminó la respuesta, sin su texto ni argumentos."""
        rule = _LLM_RULE if capped else verdict.rule
        self._audit(
            conv,
            "llm_response",
            tool=None,
            input={"call": iteration},
            output={
                "stop_reason": response.stop_reason,
                "decision": LoopStep.ESCALATE.value if capped else verdict.step.value,
                "tool_call_count": len(response.tool_calls),
                "tool_calls": [call.name for call in response.tool_calls],
            },
            rule=rule,
            reason=_LLM_RESPONSE_REASONS[rule],
        )

    async def _human_request(
        self,
        conv: Conversation,
        parsed: Sequence[tuple[ToolCall, _Parsed]],
        outcomes: list[Outcome],
    ) -> list[ToolResult]:
        """RN-007-18: deriva de inmediato y descarta el resto de peticiones del lote."""
        if conv.status is ConversationStatus.ESCALATED:
            return [
                _error(call.id, "conversation_closed", "La conversación ya fue derivada.")
                for call, _ in parsed
            ]
        fraud = next((args for _, args in parsed if isinstance(args, _FraudArgs)), None)
        if fraud is None:
            produced = [
                await self._escalation.escalate(
                    conv, EscalationReason.OTHER, _HUMAN_RULE, note=messages.HUMAN_REQUEST_NOTE
                )
            ]
            self._close(conv, _HUMAN_TOOL, _HUMAN_RULE, "el cliente pidió atención humana")
        else:
            produced = await self._human_and_fraud(conv, fraud)
        outcomes.extend(produced)
        payload = _outcomes_payload(conv, produced)
        results: list[ToolResult] = []
        for call, _ in parsed:
            if call.name in (_HUMAN_TOOL, _FRAUD_TOOL):
                results.append(_ok(call.id, {"outcomes": payload}))
            else:
                results.append(
                    _error(call.id, "not_executed", "No ejecutada: se solicitó atención humana.")
                )
        return results

    async def _human_and_fraud(self, conv: Conversation, fraud: _FraudArgs) -> list[Outcome]:
        """RN-007-19: bloquea si procede, deriva una sola vez y cierra la conversación."""
        result = await self._fraud_actions.report(
            conv, fraud.card_last4, None, human_note=messages.HUMAN_REQUEST_NOTE
        )
        produced = list(result.outcomes)
        if result.needs_card_digits:
            # Se pidió atención inmediata: no se pregunta, se deriva sin bloquear (RN-007-15).
            produced.append(
                await self._escalation.escalate(
                    conv,
                    EscalationReason.FRAUD_SUSPECTED,
                    _CARD_RULE,
                    note=messages.HUMAN_REQUEST_NOTE,
                )
            )
        if conv.status is ConversationStatus.ACTIVE:
            self._close(conv, _FRAUD_TOOL, _HUMAN_FRAUD_RULE, "persona y fraude en el mismo turno")
        return produced

    async def _dispatch(
        self,
        conv: Conversation,
        call: ToolCall,
        args: _Parsed,
        outcomes: list[Outcome],
    ) -> ToolResult:
        if conv.status is ConversationStatus.ESCALATED:
            return _error(call.id, "conversation_closed", "La conversación ya fue derivada.")
        if call.name in WRITE_TOOLS:
            return self._block_write(conv, call)
        if isinstance(args, (_ListArgs, _SearchArgs, _VerifyArgs)):
            try:
                return await self._read(conv, call, args, outcomes)
            except (BankingToolError, BankingToolUnavailableError) as error:
                if isinstance(error, BankingToolError):
                    # Rechazos corregibles: INVALID_INPUT (RN-010-01) y NOT_FOUND (RN-011-05)
                    if error.code == "INVALID_INPUT" and isinstance(args, (_ListArgs, _SearchArgs)):
                        return await self._invalid_input(conv, call, error, outcomes)
                    if error.code == "NOT_FOUND" and isinstance(args, _ListArgs):
                        return await self._card_rejection(conv, call, "NOT_FOUND", outcomes)
                return await self._read_failure(conv, call, error, outcomes)
        if isinstance(args, _EvaluateArgs):
            return await self._evaluate_dispute(conv, call, args, outcomes)
        if isinstance(args, _FraudArgs):
            return await self._report_fraud(conv, call.id, args, outcomes)
        return _error(call.id, "not_available", "Herramienta no disponible.")

    # -- Escrituras bloqueadas -------------------------------------------------------------

    def _block_write(self, conv: Conversation, call: ToolCall) -> ToolResult:
        """Las escrituras nunca las ejecuta el LLM (RN-007-01, RN-007-11, Art. 5)."""
        if conv.verified_customer_id is None:
            rule = _UNVERIFIED_RULE
            message = (
                "Primero debe verificarse la identidad del cliente. Las decisiones y las "
                "acciones las toma el sistema, no tú."
            )
        else:
            rule = (
                _UNEVALUATED_WRITE_RULE if call.name == "iniciar_disputa" else _SYSTEM_DECIDES_RULE
            )
            message = (
                "Las decisiones y las acciones las toma el sistema, no tú. Comunica lo que "
                "el cliente quiere con evaluar_disputa, reportar_fraude o "
                "solicitar_atencion_humana."
            )
        return self._blocked(conv, call, rule, message)

    def _blocked(self, conv: Conversation, call: ToolCall, rule: str, message: str) -> ToolResult:
        # RN-007-37: rastro de herramientas bloqueadas del turno · Art. 7
        conv.turn_blocked_tools.append(call.name)
        self._audit(
            conv,
            "tool_blocked",
            tool=call.name,
            input=_safe(conv, call.arguments),
            output={"blocked": True},
            rule=rule,
            reason=message,
        )
        return _error(call.id, "blocked", message)

    # -- Lecturas MCP ------------------------------------------------------------------------

    async def _read(
        self,
        conv: Conversation,
        call: ToolCall,
        args: _ListArgs | _SearchArgs | _VerifyArgs,
        outcomes: list[Outcome],
    ) -> ToolResult:
        if isinstance(args, _ListArgs):
            return await self._list_transactions(conv, call, args, outcomes)
        if isinstance(args, _SearchArgs):
            return await self._search_customer(conv, call.id, args, outcomes)
        return await self._verify_identity(conv, call.id, args, outcomes)

    async def _invalid_input(
        self,
        conv: Conversation,
        call: ToolCall,
        error: BankingToolError,
        outcomes: list[Outcome],
    ) -> ToolResult:
        """RN-010-01: el rechazo vuelve al LLM para corregir; no deriva ni da nada por hecho."""
        number = conv.register_invalid_input()
        if number > _MAX_CORRECTIONS:
            # RN-010-04: el 3.er rechazo del mensaje no se corrige; deriva y cierra
            detail = "" if error.field is None else f" (campo: {error.field})"
            why = f"{call.name} INVALID_INPUT{detail} tras {_MAX_CORRECTIONS} correcciones"
            return await self._derive_and_close(
                conv,
                call,
                outcomes,
                EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO,
                _CAP_RULE,
                why,
            )
        if call.name == "buscar_cliente":
            conv.record_identification(IdentificationStep.INVALID_SEARCH)  # RN-010-06
        # RN-010-07: rastro de cada rechazo corregible · Art. 8
        self._audit_call(
            conv,
            call.name,
            _safe(conv, call.arguments),
            {
                "error": "INVALID_INPUT",
                "field": error.field,
                "correction": number,
                "of": _MAX_CORRECTIONS,
            },
            _INVALID_INPUT_RULE,
            "argumentos rechazados por el core; se devuelven al LLM para corregirlos",
        )
        return _invalid_input_result(call.id, call.name, error.field, _MAX_CORRECTIONS - number)

    async def _card_rejection(
        self,
        conv: Conversation,
        call: ToolCall,
        kind: Literal["UNKNOWN_CARD", "NOT_FOUND"],
        outcomes: list[Outcome],
    ) -> ToolResult:
        """RN-011-03/05/06/07: rechazo de tarjeta corregible; el 3.º del mensaje deriva y cierra."""
        number = conv.register_invalid_input()
        if number > _MAX_CORRECTIONS:
            return await self._derive_and_close(
                conv,
                call,
                outcomes,
                EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO,
                _CARD_CAP_RULE,
                f"{call.name} {kind} tras {_MAX_CORRECTIONS} correcciones",
            )
        # RN-011-09: rastro de cada rechazo corregible, sin los 4 dígitos pedidos · Art. 8
        if kind == "UNKNOWN_CARD":
            tool_input: dict[str, object] = {"fields": sorted(call.arguments)}
            rule, reason = (
                _UNKNOWN_CARD_RULE,
                "la tarjeta no es de la clienta; se devuelve al LLM para corregirla",
            )
        else:
            tool_input = _safe(conv, call.arguments)
            rule, reason = (
                _NOT_FOUND_RULE,
                "tarjeta no encontrada por el core; se devuelve al LLM para que la clienta "
                "revise los dígitos",
            )
        self._audit_call(
            conv,
            call.name,
            tool_input,
            {"error": kind, "correction": number, "of": _MAX_CORRECTIONS},
            rule,
            reason,
        )
        cards_last4 = tuple(card.last4 for card in conv.known_cards)
        return _card_rejection_result(call.id, kind, cards_last4, _MAX_CORRECTIONS - number)

    async def _read_failure(
        self,
        conv: Conversation,
        call: ToolCall,
        error: BankingToolError | BankingToolUnavailableError,
        outcomes: list[Outcome],
    ) -> ToolResult:
        """RN-007-21: falla de una lectura; deriva, cierra y no filtra el error al LLM."""
        code = error.code if isinstance(error, BankingToolError) else _UNAVAILABLE_CODE
        field = error.field if isinstance(error, BankingToolError) else None
        why = describe_failure(call.name, code, field)
        # RN-010-08: rastro de la herramienta y el código antes de derivar · Art. 8
        failure_output: dict[str, object] = {"error": code}
        if code == "INVALID_INPUT":
            failure_output["field"] = field
        self._audit_call(
            conv,
            call.name,
            {"fields": sorted(call.arguments)},
            failure_output,
            _FAILURE_RULE,
            why,
        )
        return await self._derive_and_close(
            conv, call, outcomes, EscalationReason.UNRECOVERABLE_SYSTEM_FAILURE, _FAILURE_RULE, why
        )

    async def _derive_and_close(
        self,
        conv: Conversation,
        call: ToolCall,
        outcomes: list[Outcome],
        reason: EscalationReason,
        rule: str,
        why: str,
    ) -> ToolResult:
        """Deriva, cierra y devuelve al LLM el resultado fijo `system_unavailable` (RN-007-21)."""
        outcome = await self._escalation.escalate(conv, reason, rule, note=f"{rule}: {why}")
        outcomes.append(outcome)
        self._close(conv, call.name, rule, why)
        content = json.dumps(
            {
                "error": "system_unavailable",
                "message": "Sistema no disponible: el caso fue derivado a un analista.",
                "outcomes": _outcomes_payload(conv, [outcome]),
            },
            ensure_ascii=False,
        )
        return ToolResult(call.id, content, is_error=True)

    async def _list_transactions(
        self, conv: Conversation, call: ToolCall, args: _ListArgs, outcomes: list[Outcome]
    ) -> ToolResult:
        """RN-007-01: exige verificación; RN-007-13: lista vacía o refinamiento son outcomes."""
        if conv.verified_customer_id is None:
            return self._blocked(
                conv,
                call,
                _UNVERIFIED_RULE,
                "Primero debe verificarse la identidad del cliente con verificar_identidad.",
            )
        last4 = args.card_last4
        if (
            conv.known_cards
            and last4 is not None
            and len(last4) == 4
            and last4.isascii()
            and last4.isdigit()
            and not conv.card_by_last4(last4)
        ):
            # RN-011-03: 4 dígitos que no son de la clienta no llegan al core;
            # un valor mal formado sí llega y el core responde INVALID_INPUT (spec 010)
            return await self._card_rejection(conv, call, "UNKNOWN_CARD", outcomes)
        try:
            date_from = date.fromisoformat(args.date_from or "")
            date_to = date.fromisoformat(args.date_to or "")
        except ValueError:
            return _error(call.id, "invalid_date", "Las fechas deben tener formato AAAA-MM-DD.")
        page = await self._banking.list_transactions(
            conv.conversation_id, args.card_last4, date_from, date_to
        )
        conv.remember_transactions(page.transactions)
        payload: dict[str, object] = {
            "transactions": [_transaction_dict(tx, conv) for tx in page.transactions],
            "refinement_required": page.refinement_required,
        }
        self._audit_call(
            conv,
            "consultar_transacciones",
            {"card_last4": args.card_last4, "date_from": args.date_from, "date_to": args.date_to},
            {
                "transactions": len(page.transactions),
                "refinement_required": page.refinement_required,
            },
            _UNVERIFIED_RULE,
            f"consulta de transacciones: {len(page.transactions)} resultado(s)",
        )
        kind = _empty_page_kind(page)
        if kind is not None:
            outcome = Outcome(
                kind=kind,
                rule=_NO_TRANSACTIONS_RULE,
                reason=messages.OUTCOME_REASONS[kind],
                next_steps=messages.OUTCOME_NEXT_STEPS[kind],
            )
            outcomes.append(outcome)
            payload["outcomes"] = _outcomes_payload(conv, [outcome])
        return _ok(call.id, payload)

    async def _search_customer(
        self, conv: Conversation, call_id: str, args: _SearchArgs, outcomes: list[Outcome]
    ) -> ToolResult:
        """RN-007-02: el LLM solo recibe el número de coincidencias, nunca sus datos."""
        if args.document:
            conv.provided_documents.add(args.document)
        found = await self._banking.search_customer(
            conv.conversation_id, args.document, args.full_name, args.card_last4
        )
        matches = len(found.customers)
        conv.record_search(matches, found.refinement_required)
        located = matches == 1 and not found.refinement_required
        if located:
            step = IdentificationStep.LOCATED
        elif matches == 0 and not found.refinement_required:
            step = IdentificationStep.NOT_FOUND
        else:
            step = IdentificationStep.MORE_DATA_NEEDED
        conv.record_identification(step)  # RN-007-41: rastro del turno para el texto fijo
        if located:
            match = found.customers[0]
            conv.located_customer_id = match.customer_id
            conv.known_cards = tuple(
                KnownCard(card.card_id, card.masked_card[-4:]) for card in match.cards
            )
        payload: dict[str, object] = {
            "matches": matches,
            "refinement_required": found.refinement_required,
        }
        self._audit_call(
            conv,
            "buscar_cliente",
            _safe(conv, {k: v for k, v in vars(args).items() if v is not None}),
            dict(payload),
            _SEARCH_RULE,
            f"búsqueda de cliente: {matches} coincidencia(s)",
        )
        if matches == 0 and not found.refinement_required and conv.failed_searches >= 2:
            outcome = await self._escalate_and_close(
                conv,
                EscalationReason.INSUFFICIENT_OR_CONTRADICTORY_INFO,
                _NO_MATCH_RULE,
                "buscar_cliente",
                "cliente no localizado tras 2 búsquedas",
            )
            outcomes.append(outcome)
            payload["outcomes"] = _outcomes_payload(conv, [outcome])
        return _ok(call_id, payload)

    async def _verify_identity(
        self, conv: Conversation, call_id: str, args: _VerifyArgs, outcomes: list[Outcome]
    ) -> ToolResult:
        """RN-007-03: inyecta el customer_id localizado; el LLM no lo conoce."""
        customer_id = conv.located_customer_id
        if customer_id is None:
            return _error(
                call_id,
                "customer_not_located",
                "Primero identifica al cliente con buscar_cliente.",
            )
        try:
            birth_date = date.fromisoformat(args.birth_date)
            issue_date = date.fromisoformat(args.document_issue_date)
        except ValueError:
            # RN-007-40: sin llamar al core ni gastar intento
            conv.record_identification(IdentificationStep.INVALID_DATES)
            return _error(call_id, "invalid_date", "Las fechas deben tener formato AAAA-MM-DD.")
        try:
            result = await self._banking.verify_identity(
                conv.conversation_id, customer_id, birth_date, issue_date
            )
        except BankingToolError as error:
            if error.code != "INVALID_INPUT":
                raise
            # RN-007-40: el core rechazó las fechas; se pide de nuevo sin derivar
            conv.record_identification(IdentificationStep.INVALID_DATES)
            return _error(call_id, "invalid_date", "Las fechas deben tener formato AAAA-MM-DD.")
        payload: dict[str, object]
        if result.verified:
            conv.mark_verified(customer_id)
            payload = {"verified": True, "cards": [f"**** {c.last4}" for c in conv.known_cards]}
        else:
            payload = {"verified": False, "attempts_remaining": result.attempts_remaining}
            conv.record_identification(IdentificationStep.WRONG_DATES, result.attempts_remaining)
        self._audit_call(
            conv,
            "verificar_identidad",
            {"fields": ["birth_date", "document_issue_date"]},
            {"verified": result.verified, "attempts_remaining": result.attempts_remaining},
            _VERIFY_RULE,
            "verificación de identidad " + ("exitosa" if result.verified else "fallida"),
        )
        if result.escalation_required:
            outcome = await self._escalate_and_close(
                conv,
                EscalationReason.IDENTITY_VERIFICATION_FAILED,
                _VERIFICATION_FAILED_RULE,
                "verificar_identidad",
                "intentos de verificación agotados",
            )
            outcomes.append(outcome)
            payload["outcomes"] = _outcomes_payload(conv, [outcome])
        return _ok(call_id, payload)

    async def _escalate_and_close(
        self, conv: Conversation, reason: EscalationReason, rule: str, tool: str, why: str
    ) -> Outcome:
        """Deriva con resumen sin datos del cliente y cierra la conversación (RN-007-24)."""
        outcome = await self._escalation.escalate(conv, reason, rule)
        self._close(conv, tool, rule, why)
        return outcome

    def _close(self, conv: Conversation, tool: str, rule: str, why: str) -> None:
        """Cierra la conversación y audita `conversation_closed` (RN-007-24)."""
        conv.close()
        self._audit(
            conv,
            "conversation_closed",
            tool=tool,
            input={"tool": tool},
            output={"status": conv.status.value},
            rule=rule,
            reason=why,
        )

    def _audit_call(
        self,
        conv: Conversation,
        tool: str,
        tool_input: dict[str, object],
        tool_output: dict[str, object],
        rule: str,
        reason: str,
    ) -> None:
        self._audit(
            conv,
            "tool_call",
            tool=tool,
            input=tool_input,
            output=tool_output,
            rule=rule,
            reason=reason,
        )

    def _audit(
        self,
        conv: Conversation,
        event_type: AuditEventType,
        *,
        tool: str | None,
        input: dict[str, object],
        output: dict[str, object],
        rule: str,
        reason: str,
    ) -> None:
        """Punto único de emisión de eventos de auditoría del turno (RN-007-28)."""
        self._audit_log.record(
            AgentAuditEvent(
                conversation_id=conv.conversation_id,
                at=self._clock.now(),
                event_type=event_type,
                tool=tool,
                input=input,
                output=output,
                rule=rule,
                reason=reason,
            )
        )

    # -- Intenciones --------------------------------------------------------------------------

    async def _evaluate_dispute(
        self, conv: Conversation, call: ToolCall, args: _EvaluateArgs, outcomes: list[Outcome]
    ) -> ToolResult:
        call_id = call.id
        if conv.verified_customer_id is None:
            # RN-007-01, RN-007-37: sin verificación no se evalúa nada · Art. 7
            return self._blocked(
                conv,
                call,
                _UNVERIFIED_RULE,
                "Primero debe verificarse la identidad del cliente con verificar_identidad.",
            )
        if args.transaction_id not in conv.seen_transactions:
            return _ok(
                call_id,
                {
                    "result": "transaction_not_listed",
                    "message": (
                        "Esa transacción no está entre las consultadas; "
                        "llama ahora a consultar_transacciones con la tarjeta del cliente "
                        "(rango por defecto: hoy - 89 a hoy) y vuelve a evaluar."
                    ),
                },
            )
        if args.transaction_id in conv.decisions:
            return _ok(
                call_id,
                {
                    "result": "already_evaluated",
                    "message": "Esa transacción ya fue evaluada en esta conversación.",
                },
            )
        produced = await self._dispute_actions.evaluate(conv, args.transaction_id, args.reason)
        outcomes.extend(produced)
        return _ok(call_id, {"outcomes": _outcomes_payload(conv, produced)})

    async def _report_fraud(
        self, conv: Conversation, call_id: str, args: _FraudArgs, outcomes: list[Outcome]
    ) -> ToolResult:
        """RN-007-14…17: bloqueo y derivación por fraude; el LLM solo declara la sospecha."""
        result = await self._fraud_actions.report(conv, args.card_last4, args.transaction_ids)
        if result.needs_card_digits:
            return _ok(
                call_id,
                {
                    "result": "needs_card_digits",
                    "message": "Pide al cliente los últimos 4 dígitos de la tarjeta afectada.",
                },
            )
        outcomes.extend(result.outcomes)
        return _ok(call_id, {"outcomes": _outcomes_payload(conv, result.outcomes)})


# -- Validación de argumentos -----------------------------------------------------------------


def _text_arg(arguments: Mapping[str, object], key: str, required: bool) -> str | None:
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LLMOutputError(f"argumento inválido: {key}")
    return value


def _parse(call: ToolCall) -> _Parsed:
    """Valida nombre y argumentos antes de ejecutar nada (RN-007-23)."""
    known = _READ_TOOLS | _INTENT_TOOLS | WRITE_TOOLS
    if call.name not in known:
        raise LLMOutputError(f"herramienta desconocida: {call.name}")
    allowed = _ALLOWED_ARGUMENTS.get(call.name)
    if allowed is not None and not set(call.arguments) <= allowed:
        raise LLMOutputError(f"argumentos no admitidos en {call.name}")
    if call.name == "buscar_cliente":
        search = _SearchArgs(
            _text_arg(call.arguments, "document", False),
            _text_arg(call.arguments, "full_name", False),
            _text_arg(call.arguments, "card_last4", False),
        )
        if not (search.document or search.full_name or search.card_last4):
            raise LLMOutputError("buscar_cliente exige al menos un dato de búsqueda")
        return search
    if call.name == "consultar_transacciones":
        return _ListArgs(
            str(_text_arg(call.arguments, "card_last4", True)),
            _text_arg(call.arguments, "date_from", False),
            _text_arg(call.arguments, "date_to", False),
        )
    if call.name == "verificar_identidad":
        return _VerifyArgs(
            str(_text_arg(call.arguments, "birth_date", True)),
            str(_text_arg(call.arguments, "document_issue_date", True)),
        )
    if call.name == "evaluar_disputa":
        transaction_id = _text_arg(call.arguments, "transaction_id", True)
        assert transaction_id is not None
        reason = call.arguments.get("reason", _DEFAULT_REASON)
        if not isinstance(reason, str) or reason not in _DISPUTE_REASONS:
            reason = _DEFAULT_REASON
        return _EvaluateArgs(transaction_id, reason)
    if call.name == _FRAUD_TOOL:
        ids = call.arguments.get("transaction_ids")
        if ids is not None and not (
            isinstance(ids, list) and all(isinstance(item, str) and item.strip() for item in ids)
        ):
            raise LLMOutputError("argumento inválido: transaction_ids")
        return _FraudArgs(
            _text_arg(call.arguments, "card_last4", False),
            tuple(ids) if ids is not None else None,
        )
    return None


# -- Serialización ----------------------------------------------------------------------------


def _ok(call_id: str, payload: Mapping[str, object]) -> ToolResult:
    return ToolResult(call_id, json.dumps(payload, ensure_ascii=False))


def _error(call_id: str, code: str, message: str) -> ToolResult:
    content = json.dumps({"error": code, "message": message}, ensure_ascii=False)
    return ToolResult(call_id, content, is_error=True)


def _invalid_input_result(call_id: str, tool: str, field: str | None, remaining: int) -> ToolResult:
    """Resultado de error de validación hacia el LLM (spec 010 §7.2)."""
    content = json.dumps(
        {
            "error": "invalid_input",
            "field": field,
            "corrections_remaining": remaining,
            "message": messages.invalid_input_message(tool, field),
        },
        ensure_ascii=False,
    )
    return ToolResult(call_id, content, is_error=True)


def _card_rejection_result(
    call_id: str,
    kind: Literal["UNKNOWN_CARD", "NOT_FOUND"],
    cards_last4: tuple[str, ...],
    remaining: int,
) -> ToolResult:
    """Resultado de error de tarjeta hacia el LLM (spec 011 §7.1 y §7.2)."""
    payload: dict[str, object]
    if kind == "UNKNOWN_CARD":
        payload = {
            "error": "unknown_card",
            "cards_last4": list(cards_last4),
            "corrections_remaining": remaining,
            "message": messages.unknown_card_message(cards_last4),
        }
    else:
        payload = {
            "error": "not_found",
            "corrections_remaining": remaining,
            "message": messages.NOT_FOUND_CARD_MESSAGE,
        }
    return ToolResult(call_id, json.dumps(payload, ensure_ascii=False), is_error=True)


def _safe(conv: Conversation, data: Mapping[str, object]) -> dict[str, object]:
    """Copia los argumentos para auditoría pasando los textos por el filtro (RN-007-28)."""
    return {
        key: redact_reply(value, conv.provided_documents) if isinstance(value, str) else value
        for key, value in data.items()
    }


def _clean(conv: Conversation, text: str | None) -> str | None:
    return None if text is None else redact_reply(text, conv.provided_documents)


def clean_outcome(conv: Conversation, outcome: Outcome) -> Outcome:
    """Aplica el filtro de RN-007-26 a todos los textos del outcome."""
    return replace(
        outcome,
        rule=str(_clean(conv, outcome.rule)),
        reason=str(_clean(conv, outcome.reason)),
        next_steps=str(_clean(conv, outcome.next_steps)),
        transaction_id=_clean(conv, outcome.transaction_id),
        masked_card=_clean(conv, outcome.masked_card),
        reference=_clean(conv, outcome.reference),
    )


def _outcomes_payload(
    conv: Conversation, outcomes: Sequence[Outcome]
) -> list[dict[str, str | None]]:
    return [_outcome_dict(clean_outcome(conv, outcome)) for outcome in outcomes]


def _empty_page_kind(page: TransactionPage) -> OutcomeKind | None:
    if page.refinement_required:
        return OutcomeKind.REFINEMENT_REQUIRED
    if not page.transactions:
        return OutcomeKind.NO_TRANSACTIONS_FOUND
    return None


def _transaction_dict(tx: DisputedTransaction, conv: Conversation) -> dict[str, str | None]:
    """Transacción para el LLM: sin `card_id` (solo la tarjeta enmascarada)."""
    return {
        "transaction_id": tx.transaction_id,
        "occurred_at": tx.occurred_at.isoformat(),
        "merchant": _clean(conv, tx.merchant),
        "amount": str(tx.amount),
        "currency": tx.currency,
        "merchant_country": tx.merchant_country,
        "status": tx.status.value,
        "masked_card": _clean(conv, tx.masked_card),
    }


def _outcome_dict(outcome: Outcome) -> dict[str, str | None]:
    return {
        "kind": outcome.kind.value,
        "rule": outcome.rule,
        "reason": outcome.reason,
        "next_steps": outcome.next_steps,
        "transaction_id": outcome.transaction_id,
        "masked_card": outcome.masked_card,
        "reference": outcome.reference,
    }
