"""Puerto de persistencia del estado de la conversación."""

from typing import Protocol

from dispute_agent.domain.models.conversation import Conversation


class ConversationRepository(Protocol):
    def get(self, conversation_id: str) -> Conversation | None: ...

    def save(self, conversation: Conversation) -> None: ...
