from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from confer.config import Settings, default_config_path


def test_default_config_path_is_xdg_conformant():
    assert default_config_path() == Path.home() / ".config" / "confer" / "config.toml"


def test_load_from_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "test-token"\nconfer_user_id = 123456789012345678\n')
    s = Settings.load(cfg)
    assert s.discord_bot_token == "test-token"
    assert s.confer_user_id == 123456789012345678


def test_load_uses_default_path_when_none_given(monkeypatch, tmp_path):
    default = tmp_path / "config.toml"
    default.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')
    monkeypatch.setattr("confer.config.default_config_path", lambda: default)
    s = Settings.load()
    assert s.discord_bot_token == "x"


def test_load_raises_with_helpful_message_when_file_missing(tmp_path):
    missing = tmp_path / "absent.toml"
    with pytest.raises(FileNotFoundError) as exc_info:
        Settings.load(missing)
    msg = str(exc_info.value)
    assert str(missing) in msg
    assert "config.toml.example" in msg


def test_load_raises_clear_error_on_missing_required_key(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("confer_user_id = 1\n")
    with pytest.raises(ValueError, match="discord_bot_token"):
        Settings.load(cfg)


def test_loose_perms_emits_warning(tmp_path, caplog):
    import logging
    import os

    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')
    os.chmod(cfg, 0o644)  # group/other readable
    with caplog.at_level(logging.WARNING, logger="confer.config"):
        Settings.load(cfg)
    assert any(
        "loose permissions" in record.getMessage() for record in caplog.records
    )


def test_perms_check_swallows_stat_failures(tmp_path, caplog, monkeypatch):
    """If stat() can't read the file (permission, symlink loop, etc.), the
    perms check must silently skip — it's best-effort, not a gate."""
    import logging

    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')

    def raise_oserror(self):
        raise OSError("stat blocked")

    monkeypatch.setattr("pathlib.Path.stat", raise_oserror)

    with caplog.at_level(logging.WARNING, logger="confer.config"):
        # Should not raise
        Settings.load(cfg)
    assert not any(
        "loose permissions" in record.getMessage() for record in caplog.records
    )


def test_tight_perms_do_not_emit_warning(tmp_path, caplog):
    import logging
    import os

    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')
    os.chmod(cfg, 0o600)
    with caplog.at_level(logging.WARNING, logger="confer.config"):
        Settings.load(cfg)
    assert not any(
        "loose permissions" in record.getMessage() for record in caplog.records
    )


def test_settings_is_frozen(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')
    s = Settings.load(cfg)
    with pytest.raises(FrozenInstanceError):
        s.discord_bot_token = "changed"  # type: ignore[misc]


def test_re_ping_every_seconds_defaults_to_900(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('discord_bot_token = "x"\nconfer_user_id = 1\n')
    s = Settings.load(cfg)
    assert s.re_ping_every_seconds == 900


def test_re_ping_every_seconds_can_be_overridden(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'discord_bot_token = "x"\n'
        "confer_user_id = 1\n"
        "[ask]\n"
        "re_ping_every_seconds = 300\n"
    )
    s = Settings.load(cfg)
    assert s.re_ping_every_seconds == 300


def test_re_ping_every_seconds_must_be_positive(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'discord_bot_token = "x"\n'
        "confer_user_id = 1\n"
        "[ask]\n"
        "re_ping_every_seconds = 0\n"
    )
    with pytest.raises(ValueError, match="re_ping_every_seconds"):
        Settings.load(cfg)
