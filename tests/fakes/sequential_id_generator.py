"""Generador de identificadores secuenciales y deterministas."""


class SequentialIdGenerator:
    def __init__(self, prefix: str = "conv") -> None:
        self._prefix = prefix
        self._counter = 0

    def new_conversation_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:04d}"
