"""Builder de Conversation en estados típicos para tests del agente."""

from dispute_agent.domain.models.conversation import Conversation, KnownCard


class ConversationBuilder:
    def __init__(self) -> None:
        self._conversation = Conversation(conversation_id="conv-0001")

    def conversation_id(self, conversation_id: str) -> "ConversationBuilder":
        self._conversation.conversation_id = conversation_id
        return self

    def located(self, customer_id: str, cards: tuple[KnownCard, ...] = ()) -> "ConversationBuilder":
        self._conversation.located_customer_id = customer_id
        self._conversation.known_cards = cards
        return self

    def verified(
        self, customer_id: str, cards: tuple[KnownCard, ...] = ()
    ) -> "ConversationBuilder":
        self.located(customer_id, cards)
        self._conversation.mark_verified(customer_id)
        return self

    def closed(self) -> "ConversationBuilder":
        self._conversation.close()
        return self

    def with_documents(self, *documents: str) -> "ConversationBuilder":
        self._conversation.provided_documents.update(documents)
        return self

    def build(self) -> Conversation:
        return self._conversation
