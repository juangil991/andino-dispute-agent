from datetime import timedelta

from dispute_agent.domain.models.conversation import Conversation
from dispute_agent.infrastructure.outbound.clock.system_clock import SystemClock
from dispute_agent.infrastructure.outbound.ids.uuid_generator import Uuid4Generator
from dispute_agent.infrastructure.outbound.persistence.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)


# Soporte de tests: reloj del sistema con zona y fecha de Bogotá · Art. 3
def test_system_clock__now_and_today__bogota() -> None:
    """now() lleva zona y today() es la fecha en UTC-5."""
    clock = SystemClock()

    now = clock.now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=-5)
    assert clock.today() == now.date()


# Soporte de tests: generador de ids · Art. 3
def test_uuid4_generator__ids__unique_hex32() -> None:
    """Ids hex de 32 caracteres y únicos."""
    generator = Uuid4Generator()

    ids = {generator.new_conversation_id() for _ in range(5)}

    assert len(ids) == 5
    assert all(len(i) == 32 and int(i, 16) >= 0 for i in ids)


# Soporte de tests: repositorio en memoria · Art. 3
def test_in_memory_conversation_repository__get_and_save__roundtrip() -> None:
    """get devuelve None si no existe y lo guardado después."""
    repo = InMemoryConversationRepository()
    conversation = Conversation(conversation_id="abc")

    assert repo.get("abc") is None
    repo.save(conversation)

    assert repo.get("abc") is conversation
