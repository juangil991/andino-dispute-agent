"""Errores de la capa de aplicación."""


class CoreUnavailableError(Exception):
    """Falla no recuperable del core bancario (RN-001-13)."""
