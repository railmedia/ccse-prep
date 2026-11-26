from functools import lru_cache
from urllib.parse import quote

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

    # Explicit override (CI, tests). When empty, the URL is assembled from the
    # discrete DB_* values so credentials are percent-encoded instead of being
    # pasted into a URL.
    database_url: str = ""
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ccse"
    db_user: str = "ccse"
    db_password: str = "ccse"
    db_pool_size: int = 5
    db_pool_max_overflow: int = 5

    # Edge / public surface, used for absolute links and docs.
    public_host: str = "ccse-prep.tudorache.me"
    cookie_secure: bool = False

    # Placeholder for Sprint 3; keeping it here means .env keys are typed.
    mistral_api_key: str = ""
    openai_api_key: str = ""

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        user = quote(self.db_user, safe="")
        password = quote(self.db_password, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
