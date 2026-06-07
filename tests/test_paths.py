from pathlib import Path

from confer import paths


def test_socket_path_uses_xdg_runtime_dir_when_writable(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert paths.socket_path() == runtime / "confer.sock"


def test_socket_path_falls_back_when_xdg_runtime_dir_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert paths.socket_path() == tmp_path / "state" / "confer" / "confer.sock"


def test_socket_path_falls_back_when_xdg_runtime_dir_does_not_exist(
    monkeypatch, tmp_path, caplog
):
    """Common on WSL2 without systemd-logind: env var is exported by
    /etc/profile.d/ but /run/user/<uid> is never actually created."""
    import logging

    nonexistent = tmp_path / "run-user-99999"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(nonexistent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with caplog.at_level(logging.WARNING, logger="confer.paths"):
        result = paths.socket_path()
    assert result == tmp_path / "state" / "confer" / "confer.sock"
    assert any(
        "XDG_RUNTIME_DIR" in r.getMessage() and "falling back" in r.getMessage()
        for r in caplog.records
    )


def test_socket_path_falls_back_when_xdg_runtime_dir_not_writable(
    monkeypatch, tmp_path
):
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o500)  # readable but not writable
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    try:
        assert paths.socket_path() == tmp_path / "state" / "confer" / "confer.sock"
    finally:
        runtime.chmod(0o700)  # restore so pytest cleanup can rmtree it


def test_pid_file_uses_xdg_runtime_dir_when_writable(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert paths.pid_file() == runtime / "confer.pid"


def test_presence_file_uses_xdg_runtime_dir_when_writable(tmp_path, monkeypatch):
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    assert paths.presence_file() == runtime / "confer.presence"


def test_log_file_uses_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert paths.log_file() == tmp_path / "state" / "confer" / "daemon.log"


def test_state_home_falls_back_to_home_when_unset(monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    expected = Path.home() / ".local" / "state" / "confer" / "daemon.log"
    assert paths.log_file() == expected


def test_runtime_dir_falls_back_to_state_home_when_unset(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    expected = Path.home() / ".local" / "state" / "confer" / "confer.sock"
    assert paths.socket_path() == expected


def test_xdg_fallback_warning_emitted_once_per_value(monkeypatch, tmp_path, caplog):
    """The fallback warning is correct but non-fatal; on WSL2 the same
    unwritable XDG_RUNTIME_DIR is probed every 15s for the daemon's whole life
    (wq4n7pxv). It must warn AT MOST ONCE per distinct value, not per call."""
    import logging

    nonexistent = tmp_path / "run-user-dedup"  # unique per test → fresh value
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(nonexistent))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with caplog.at_level(logging.WARNING, logger="confer.paths"):
        paths.socket_path()
        paths.pid_file()
        paths.presence_file()
    warnings = [
        r for r in caplog.records if "XDG_RUNTIME_DIR" in r.getMessage()
    ]
    assert len(warnings) == 1
