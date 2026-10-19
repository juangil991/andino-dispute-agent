"""Router `POST /api/chat/stream` (spec 009 §7.1): respuesta como flujo de eventos SSE."""

from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dispute_agent.application.use_cases.handle_customer_message import ConversationNotFoundError
from dispute_agent.application.use_cases.stream_customer_message import (
    ReplyEnded,
    ReplyInterrupted,
    ReplyStarted,
    ReplyWord,
    StreamCustomerMessage,
    StreamEvent,
)
from dispute_agent.infrastructure.inbound.web.api.schemas import (
    ChatRequest,
    OutcomeOut,
    StreamEndOut,
    StreamInterruptedOut,
    StreamStartOut,
    StreamWordOut,
)

_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _frame(name: str, payload: BaseModel) -> str:
    return f"event: {name}\ndata: {payload.model_dump_json()}\n\n"


def _serialize(event: StreamEvent) -> str:
    if isinstance(event, ReplyStarted):
        return _frame("start", StreamStartOut(conversation_id=event.conversation_id))
    if isinstance(event, ReplyWord):
        return _frame("word", StreamWordOut(text=event.text))
    outcomes = [OutcomeOut.from_outcome(o) for o in event.outcomes]
    if isinstance(event, ReplyEnded):
        status: Literal["ACTIVE", "ESCALATED"] = (
            "ESCALATED" if event.status.value == "ESCALATED" else "ACTIVE"
        )
        return _frame(
            "end",
            StreamEndOut(
                conversation_id=event.conversation_id,
                reply=event.reply,
                status=status,
                outcomes=outcomes,
            ),
        )
    assert isinstance(event, ReplyInterrupted)
    return _frame(
        "interrupted",
        StreamInterruptedOut(
            conversation_id=event.conversation_id, reply=event.reply, outcomes=outcomes
        ),
    )


def build_chat_stream_router(stream_message: StreamCustomerMessage) -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat/stream")
    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        try:
            prepared = stream_message.prepare(request.conversation_id)
        except ConversationNotFoundError:
            raise HTTPException(status_code=404, detail="Conversación no encontrada.") from None

        async def body() -> AsyncIterator[str]:
            # RN-009-12: sin capturar CancelledError/GeneratorExit; la desconexión se propaga.
            async for event in stream_message.events(prepared, request.message):
                yield _serialize(event)

        return StreamingResponse(body(), media_type="text/event-stream", headers=_HEADERS)

    return router
