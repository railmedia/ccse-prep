from __future__ import annotations

from app.settings import Settings


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "",
        "db_host": "postgres",
        "db_port": 5432,
        "db_name": "ccse",
        "db_user": "ccse",
        "db_password": "secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_password_is_percent_encoded() -> None:
    from sqlalchemy.engine import make_url

    settings = _settings(db_password="p@ss/word?x#y")
    url = make_url(settings.sqlalchemy_url)

    assert url.host == "postgres"
    assert url.database == "ccse"
    assert url.password == "p@ss/word?x#y"


def test_explicit_url_wins() -> None:
    settings = _settings(database_url="postgresql+asyncpg://x:y@example:5432/db")
    assert settings.sqlalchemy_url == "postgresql+asyncpg://x:y@example:5432/db"
