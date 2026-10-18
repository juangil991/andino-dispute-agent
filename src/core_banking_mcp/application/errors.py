"""Errores de la capa de aplicación."""


class CoreUnavailableError(Exception):
    """Falla no recuperable del core bancario (RN-001-13)."""


class IdentityNotVerifiedError(Exception):
    """La conversación no tiene identidad verificada para el cliente."""


class CardNotFoundError(Exception):
    """El cliente no tiene ninguna tarjeta con esos últimos 4 dígitos."""


class TransactionNotFoundError(Exception):
    """La transacción no existe o no pertenece al cliente."""


class TransactionNotDisputableError(Exception):
    """La transacción no se puede disputar en su estado actual."""


class DisputeAlreadyOpenError(Exception):
    """Ya existe una disputa abierta para la transacción."""

    def __init__(self, dispute_id: str) -> None:
        super().__init__(dispute_id)
        self.dispute_id = dispute_id
