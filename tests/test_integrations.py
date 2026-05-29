import json

import pytest

from confer import integrations


@pytest.fixture
def env(tmp_path):
    return {
        "settings_path": tmp_path / ".claude" / "settings.json",
        "commands_dir": tmp_path / ".claude" / "commands",
        "confer_bin": "/usr/local/bin/confer",
    }


def test_install_fresh(env):
    actions = integrations.install(**env, dry_run=False)
    settings = json.loads(env["settings_path"].read_text())
    assert settings["hooks"]["Stop"] == [{
        "matcher": "",
        "hooks": [{"type": "command",
                   "command": "/usr/local/bin/confer hook stop"}],
    }]
    ups = settings["hooks"]["UserPromptSubmit"]
    assert ups == [{
        "hooks": [{"type": "command",
                   "command": "/usr/local/bin/confer hook prompt"}],
    }]
    assert "matcher" not in ups[0]  # UserPromptSubmit takes no matcher
    away = (env["commands_dir"] / "away.md").read_text()
    assert "/usr/local/bin/confer away" in away
    assert (env["commands_dir"] / "back.md").exists()
    assert any("add Stop hook" in a for a in actions)


def test_install_is_idempotent(env):
    integrations.install(**env, dry_run=False)
    actions = integrations.install(**env, dry_run=False)
    settings = json.loads(env["settings_path"].read_text())
    assert len(settings["hooks"]["Stop"]) == 1
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1
    assert any("already registered" in a for a in actions)


def test_install_merges_and_preserves_existing(env):
    env["settings_path"].parent.mkdir(parents=True)
    env["settings_path"].write_text(json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "other-tool"}]}]},
    }))
    integrations.install(**env, dry_run=False)
    settings = json.loads(env["settings_path"].read_text())
    assert settings["model"] == "opus"
    commands = [h["command"]
                for g in settings["hooks"]["Stop"] for h in g["hooks"]]
    assert "other-tool" in commands
    assert "/usr/local/bin/confer hook stop" in commands


def test_install_dry_run_writes_nothing(env):
    actions = integrations.install(**env, dry_run=True)
    assert not env["settings_path"].exists()
    assert not env["commands_dir"].exists()
    assert any("add Stop hook" in a for a in actions)


def test_install_empty_settings_file(env):
    env["settings_path"].parent.mkdir(parents=True)
    env["settings_path"].write_text("   \n")
    integrations.install(**env, dry_run=False)
    assert "Stop" in json.loads(env["settings_path"].read_text())["hooks"]


def test_install_corrupt_settings_raises(env):
    env["settings_path"].parent.mkdir(parents=True)
    env["settings_path"].write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        integrations.install(**env, dry_run=False)


def test_resolve_confer_bin_found(monkeypatch):
    monkeypatch.setattr(integrations.shutil, "which", lambda _: "/x/confer")
    assert integrations.resolve_confer_bin() == "/x/confer"


def test_resolve_confer_bin_fallback(monkeypatch):
    monkeypatch.setattr(integrations.shutil, "which", lambda _: None)
    assert integrations.resolve_confer_bin() == "confer"


def test_install_uses_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations, "claude_dir", lambda: tmp_path / ".claude")
    monkeypatch.setattr(integrations, "resolve_confer_bin", lambda: "confer")
    integrations.install(dry_run=False)
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".claude" / "commands" / "away.md").exists()
