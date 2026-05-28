import pytest
from pydantic import ValidationError

from confer.config import Settings


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token-xyz")
    monkeypatch.setenv("CONFER_USER_ID", "123456789012345678")
    settings = Settings(_env_file=None)
    assert settings.discord_bot_token == "test-token-xyz"
    assert settings.confer_user_id == 123456789012345678


def test_config_raises_on_missing_required_var(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("CONFER_USER_ID", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
