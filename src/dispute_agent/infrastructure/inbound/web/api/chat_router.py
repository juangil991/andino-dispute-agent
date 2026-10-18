"""Router `POST /api/chat` (spec §7.3)."""

from fastapi import APIRouter, HTTPException

from dispute_agent.application.use_cases.handle_customer_message import (
    ConversationNotFoundError,
    HandleCustomerMessage,
)
from dispute_agent.infrastructure.inbound.web.api.schemas import ChatRequest, ChatResponse


def build_chat_router(handle_message: HandleCustomerMessage) -> APIRouter:
    router = APIRouter()

    @router.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        try:
            result = await handle_message.handle(request.conversation_id, request.message)
        except ConversationNotFoundError:
            raise HTTPException(status_code=404, detail="Conversación no encontrada.") from None
        return ChatResponse.from_result(result)

    return router
