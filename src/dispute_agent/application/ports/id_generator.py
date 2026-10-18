"""Puerto del generador de identificadores de conversación."""

from typing import Protocol


class IdGenerator(Protocol):
    def new_conversation_id(self) -> str: ...
