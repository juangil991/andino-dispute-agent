"""Errores de la capa de aplicación."""


class CoreUnavailableError(Exception):
    """Falla no recuperable del core bancario (RN-001-13)."""


class IdentityNotVerifiedError(Exception):
    """La conversación no tiene identidad verificada para el cliente."""


class CardNotFoundError(Exception):
    """El cliente no tiene ninguna tarjeta con esos últimos 4 dígitos."""
