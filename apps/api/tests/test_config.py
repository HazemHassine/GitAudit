from maintainer_api.config import Settings


def test_incomplete_explicit_authentication_is_not_reported_as_configured() -> None:
    app = Settings(_env_file=None, github_auth_mode="app", github_app_id="123")
    token = Settings(_env_file=None, github_auth_mode="token", github_token=None)

    assert app.github_configured is False
    assert token.github_configured is False


def test_auto_mode_prefers_complete_github_app_over_token() -> None:
    settings = Settings(
        _env_file=None,
        github_auth_mode="auto",
        github_token="fallback-token",
        github_app_id="123",
        github_installation_id=456,
        github_app_private_key="private-key",
    )

    assert settings.github_configured is True
    assert settings.resolved_github_auth_mode == "app"


def test_openai_configuration_is_server_owned() -> None:
    missing = Settings(_env_file=None, openai_api_key=None)
    configured = Settings(_env_file=None, openai_api_key="test-key", openai_model="test-model")

    assert missing.openai_configured is False
    assert configured.openai_configured is True
    assert configured.openai_model == "test-model"


def test_empty_strings_coerced_to_none() -> None:
    settings = Settings(
        _env_file=None,
        github_installation_id="",
        github_app_id="",
        github_token="",
        openai_api_key="",
        jules_api_key="",
    )

    assert settings.github_installation_id is None
    assert settings.github_app_id is None
    assert settings.github_token is None
    assert settings.openai_api_key is None
    assert settings.jules_api_key is None
    assert settings.github_configured is False


def test_allowed_origins_defaults_and_parsing() -> None:
    defaults = Settings(_env_file=None)
    assert "http://localhost:3000" in defaults.allowed_origins
    assert "http://127.0.0.1:3000" in defaults.allowed_origins

    custom = Settings(_env_file=None, cors_origins="http://example.com , http://test.local ")
    assert custom.allowed_origins == ["http://example.com", "http://test.local"]
