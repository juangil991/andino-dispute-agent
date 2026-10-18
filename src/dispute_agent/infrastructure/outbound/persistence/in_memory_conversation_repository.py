"""Repositorio de conversaciones en memoria."""

from dispute_agent.domain.models.conversation import Conversation


class InMemoryConversationRepository:
    """Implementa `ConversationRepository`."""

    def __init__(self) -> None:
        self._items: dict[str, Conversation] = {}

    def get(self, conversation_id: str) -> Conversation | None:
        return self._items.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self._items[conversation.conversation_id] = conversation
