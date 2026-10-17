"""Configuración del servidor `core_banking_mcp` (variables `CORE_*`)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/core_banking.db"
    seed_on_start: bool = True
