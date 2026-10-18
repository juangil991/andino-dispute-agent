"""Errores del dominio del agente."""


class DomainError(Exception):
    """Base de los errores del dominio de dispute_agent."""


class InvalidTransactionDataError(DomainError):
    """Los datos de una transacción devuelta por el core no cumplen sus invariantes."""


class InvalidDecisionError(DomainError):
    """Una DisputeDecision viola sus invariantes."""


class InvalidOutcomeError(DomainError):
    """Un Outcome viola sus invariantes."""
