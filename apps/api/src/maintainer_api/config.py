from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OSS Maintainer API"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://maintainer:maintainer@localhost:5433/maintainer"
    github_api_url: AnyHttpUrl = AnyHttpUrl("https://api.github.com")
    github_token: str | None = Field(default=None, repr=False)
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
