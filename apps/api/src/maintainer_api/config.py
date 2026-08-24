from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OSS Maintainer API"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://maintainer:maintainer@localhost:5433/maintainer"
    github_api_url: AnyHttpUrl = AnyHttpUrl("https://api.github.com")
    github_auth_mode: str = "auto"
    github_token: SecretStr | None = Field(default=None, repr=False)
    github_app_id: str | None = None
    github_app_private_key: SecretStr | None = Field(default=None, repr=False)
    github_app_private_key_path: str | None = None
    github_installation_id: int | None = None
    github_app_slug: str | None = None
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    auto_scan_on_startup: bool = True
    auto_scan_interval_minutes: int = 0
    scan_stale_after_minutes: int = 360
    max_concurrent_scans: int = Field(default=3, ge=1, le=10)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_github_auth_mode(self) -> str:
        app_ready = bool(
            self.github_app_id
            and self.github_installation_id
            and (self.github_app_private_key or self.github_app_private_key_path)
        )
        if self.github_auth_mode == "app":
            return "app" if app_ready else "unconfigured"
        if self.github_auth_mode == "token":
            return "token" if self.github_token else "unconfigured"
        if self.github_auth_mode == "auto":
            if app_ready:
                return "app"
            if self.github_token:
                return "token"
        return "unconfigured"

    @property
    def github_configured(self) -> bool:
        return self.resolved_github_auth_mode != "unconfigured"

    @property
    def github_app_install_url(self) -> str | None:
        if not self.github_app_slug:
            return None
        return f"https://github.com/apps/{self.github_app_slug}/installations/new"


@lru_cache
def get_settings() -> Settings:
    return Settings()
