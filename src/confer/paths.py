import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# XDG_RUNTIME_DIR values we have already warned about falling back from. The
# daemon probes the same value every 15s for its whole lifetime (presence
# poll, cs7nkp4x), so without this the correct-but-non-fatal fallback warning
# floods the log (XDG Fallback Warning Floods The Daemon Log, wq4n7pxv). Keyed
# by value so a genuinely changing env still surfaces once each.
_warned_runtime_dirs: set[str] = set()


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
    if val and val not in _warned_runtime_dirs:
        _warned_runtime_dirs.add(val)
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


def presence_file() -> Path:
    """Workstation away-presence marker (Presence As A Workstation File,
    pf4nqkx7). Lives beside the socket in the runtime dir so it is per-user,
    shared across sessions, and cleared on reboot (reboot ⇒ present)."""
    return _xdg_runtime_dir() / "confer.presence"
