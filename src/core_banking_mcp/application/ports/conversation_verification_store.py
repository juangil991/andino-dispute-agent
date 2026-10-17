"""Puerto de salida: estado de verificación por conversación (RN-002-13)."""

from typing import Protocol

from core_banking_mcp.domain.models.identity import VerificationState


class ConversationVerificationStore(Protocol):
    def get(self, conversation_id: str) -> VerificationState:
        """Estado de la conversación; vacío si es desconocida."""
        ...

    def save(self, conversation_id: str, state: VerificationState) -> None:
        """Conserva el estado de la conversación."""
        ...
