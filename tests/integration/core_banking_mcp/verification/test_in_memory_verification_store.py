from concurrent.futures import ThreadPoolExecutor

from core_banking_mcp.domain.models.identity import VerificationState
from core_banking_mcp.infrastructure.outbound.verification.in_memory_verification_store import (
    InMemoryConversationVerificationStore,
)


# Regla: RN-002-12 — la verificación pertenece a su conversation_id y no se traslada a otra.
# AC-002-13 · Art. 7
def test_ac_002_13_store_keeps_conversations_independent() -> None:
    """AC-002-13: guardar el estado de A no cambia el de B; get desconocida es vacío."""
    store = InMemoryConversationVerificationStore()
    state_a = VerificationState(verified_customer_id="C-A")

    assert store.get("conv-unknown") == VerificationState()

    store.save("conv-a", state_a)

    assert store.get("conv-a") is state_a
    assert store.get("conv-b") == VerificationState()


# Regla: RN-002-12 — cada conversación tiene su propio contador de intentos.
# AC-002-13 · Art. 7
def test_ac_002_13_store_save_replaces_previous_state() -> None:
    """AC-002-13: un save reemplaza al anterior y el contador no afecta a otra conversación."""
    store = InMemoryConversationVerificationStore()
    store.save("conv-a", VerificationState(failed_attempts=1))

    assert store.get("conv-b") == VerificationState()

    store.save("conv-a", VerificationState(failed_attempts=2))

    assert store.get("conv-a") == VerificationState(failed_attempts=2)
    assert store.get("conv-b") == VerificationState()


# Invariante: el almacén en memoria no pierde guardados concurrentes (riesgo del plan §7).
# AC-002-13 · Art. 7 (el estado de verificación por conversación debe ser fiable)
def test_ac_002_13_store_concurrent_saves_lose_none() -> None:
    """AC-002-13: hilos que guardan conversaciones distintas no pierden ninguna."""
    store = InMemoryConversationVerificationStore()
    ids = [f"conv-{i}" for i in range(200)]

    def save(i: int) -> None:
        store.save(ids[i], VerificationState(failed_attempts=i % 3))

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(save, range(len(ids))))

    for i, conv in enumerate(ids):
        assert store.get(conv) == VerificationState(failed_attempts=i % 3)
