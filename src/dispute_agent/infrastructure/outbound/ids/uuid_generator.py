"""Generador de ids de conversación basado en uuid4."""

import uuid


class Uuid4Generator:
    """Implementa `IdGenerator`: id hexadecimal de 32 caracteres."""

    def new_conversation_id(self) -> str:
        return uuid.uuid4().hex
