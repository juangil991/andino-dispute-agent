"""Errores de dominio de core_banking_mcp."""


class DomainError(Exception):
    """Base de los errores de dominio."""


class InvalidInputError(DomainError):
    """Entrada inválida: indica el campo y el motivo."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason
