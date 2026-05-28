import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def _xdg_state_home() -> Path:
    val = os.environ.get("XDG_STATE_HOME")
    if val:
        return Path(val)
    return Path.home() / ".local" / "state"


def _xdg_runtime_dir() -> Path:
    """Per the XDG Base Directory Specification: '$XDG_RUNTIME_DIR... must
    be created by the user and managed... If $XDG_RUNTIME_DIR is not set
    applications should fall back to a replacement directory.' We also
    fall back when it IS set but unusable (common on WSL2 without
    systemd-logind: the env var is exported but /run/user/<uid> never
    gets created)."""
    val = os.environ.get("XDG_RUNTIME_DIR")
    if val and os.path.isdir(val) and os.access(val, os.W_OK):
        return Path(val)
    if val:
        log.warning(
            "XDG_RUNTIME_DIR=%s is set but not a writable directory; "
            "falling back to %s/confer",
            val,
            _xdg_state_home(),
        )
    return _xdg_state_home() / "confer"


def socket_path() -> Path:
    return _xdg_runtime_dir() / "confer.sock"


def pid_file() -> Path:
    return _xdg_runtime_dir() / "confer.pid"


def log_file() -> Path:
    return _xdg_state_home() / "confer" / "daemon.log"
