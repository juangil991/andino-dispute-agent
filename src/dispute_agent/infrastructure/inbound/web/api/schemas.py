"""Esquemas HTTP de `POST /api/chat` (spec §7.3)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from dispute_agent.application.use_cases.handle_customer_message import ChatTurnResult
from dispute_agent.domain.models.outcome import Outcome


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class OutcomeOut(BaseModel):
    kind: str
    transaction_id: str | None
    masked_card: str | None
    rule: str
    reason: str
    next_steps: str
    reference: str | None

    @classmethod
    def from_outcome(cls, outcome: Outcome) -> "OutcomeOut":
        return cls(
            kind=outcome.kind.value,
            transaction_id=outcome.transaction_id,
            masked_card=outcome.masked_card,
            rule=outcome.rule,
            reason=outcome.reason,
            next_steps=outcome.next_steps,
            reference=outcome.reference,
        )


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    status: Literal["ACTIVE", "ESCALATED"]
    outcomes: list[OutcomeOut]

    @classmethod
    def from_result(cls, result: ChatTurnResult) -> "ChatResponse":
        status: Literal["ACTIVE", "ESCALATED"] = (
            "ESCALATED" if result.status.value == "ESCALATED" else "ACTIVE"
        )
        return cls(
            conversation_id=result.conversation_id,
            reply=result.reply,
            status=status,
            outcomes=[OutcomeOut.from_outcome(o) for o in result.outcomes],
        )
