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
