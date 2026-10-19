"""Texto de una falla irrecuperable de herramienta (RN-010-08)."""


def describe_failure(tool: str, code: str, field: str | None = None) -> str:
    """Describe la falla para la nota de escalamiento y el motivo de cierre."""
    detail = code if field is None else f"{code}, campo: {field}"
    return f"falla irrecuperable en {tool} ({detail})"
