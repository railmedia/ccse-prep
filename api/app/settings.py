from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field is overridable as CCSE_<FIELD>."""

    model_config = SettingsConfigDict(
        env_prefix="CCSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://ccse:ccse@localhost:5432/ccse"
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5

    # Edge / public surface, used for absolute links and docs.
    public_host: str = "ccse-prep.tudorache.me"
    cookie_secure: bool = False

    # Placeholder for Sprint 3; keeping it here means .env keys are typed.
    mistral_api_key: str = ""
    openai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
