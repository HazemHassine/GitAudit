from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
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

    @field_validator(
        "github_installation_id",
        "github_app_id",
        "github_app_private_key_path",
        "github_app_slug",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @field_validator(
        "github_token",
        "github_app_private_key",
        "openai_api_key",
        "jules_api_key",
        "owner_password",
        "owner_session_secret",
        mode="before",
    )
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    auto_scan_on_startup: bool = True
    auto_scan_interval_minutes: int = 0
    scan_stale_after_minutes: int = 360
    max_concurrent_scans: int = Field(default=3, ge=1, le=10)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_model: str = "gpt-5.4-mini"
    jules_api_key: SecretStr | None = Field(default=None, repr=False)
    jules_source_repository: str = "HazemHassine/GitAudit"
    jules_starting_branch: str = "main"

    owner_password: SecretStr | None = Field(default=None, repr=False)
    owner_session_secret: SecretStr | None = Field(default=None, repr=False)
    owner_cookie_secure: bool = False
    audit_image: str = "gitaudit-checks:1"
    audit_install_network: str = "gitaudit-install"
    audit_install_proxy: str = "http://install-proxy:3128"
    audit_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    audit_daily_sessions: int = Field(default=80, ge=1, le=80)
    audit_jules_slots: int = Field(default=3, ge=1, le=3)
    audit_allow_workflow_edits: bool = False
    public_web_url: str = "http://localhost:3000"

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

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def jules_configured(self) -> bool:
        return bool(self.jules_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
