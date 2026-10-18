"""Configuración de `dispute_agent` (variables de entorno sin prefijo)."""

from decimal import Decimal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    llm_max_iterations: int = 8
    usd_cop_rate: Decimal = Decimal(4000)
    mcp_call_timeout_seconds: float = 10
    # Misma variable que lee el core: se pasa tal cual al subproceso MCP.
    core_database_url: str = Field(
        default="sqlite:///./data/core_banking.db",
        validation_alias=AliasChoices("CORE_DATABASE_URL", "core_database_url"),
    )
    core_seed_on_start: bool = Field(
        default=True,
        validation_alias=AliasChoices("CORE_SEED_ON_START", "core_seed_on_start"),
    )
