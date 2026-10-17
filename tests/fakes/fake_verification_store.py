"""Almacén de verificación en memoria, por conversación."""

from core_banking_mcp.domain.models.identity import VerificationState


class FakeVerificationStore:
    def __init__(self) -> None:
        self._states: dict[str, VerificationState] = {}

    def get(self, conversation_id: str) -> VerificationState:
        return self._states.get(conversation_id, VerificationState())

    def save(self, conversation_id: str, state: VerificationState) -> None:
        self._states[conversation_id] = state

    def with_verified(self, conversation_id: str, customer_id: str) -> "FakeVerificationStore":
        self._states[conversation_id] = VerificationState(verified_customer_id=customer_id)
        return self

    def with_failures(self, conversation_id: str, n: int) -> "FakeVerificationStore":
        self._states[conversation_id] = VerificationState(failed_attempts=n)
        return self
