"""Almacén en memoria del estado de verificación por conversación (RN-002-12/13)."""

import threading

from core_banking_mcp.domain.models.identity import VerificationState


class InMemoryConversationVerificationStore:
    def __init__(self) -> None:
        self._states: dict[str, VerificationState] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> VerificationState:
        with self._lock:
            return self._states.get(conversation_id, VerificationState())

    def save(self, conversation_id: str, state: VerificationState) -> None:
        with self._lock:
            self._states[conversation_id] = state
