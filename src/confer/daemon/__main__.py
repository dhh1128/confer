import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

from confer.config import Settings
from confer.daemon.core import Daemon
from confer.daemon.transport import DiscordTransport
from confer.paths import log_file, pid_file, socket_path
from confer.protocol import Status, StatusResult, decode, encode

log = logging.getLogger("confer.daemon")


def _configure_logging() -> None:
    log_path = log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def _run_daemon() -> None:
    settings = Settings.load()
    transport = DiscordTransport(
        token=settings.discord_bot_token, user_id=settings.confer_user_id
    )
    daemon = Daemon(transport=transport)
    await daemon.serve(socket_path(), pid_file())


def _cmd_run() -> int:
    _configure_logging()
    asyncio.run(_run_daemon())
    return 0


def _read_live_pid(pid_path) -> int | None:
    """Return the PID from the file only if it identifies a live
    confer-daemon process; None otherwise. Guards against stale PID files
    (after kill -9, OOM, system reboot) where PID reuse could otherwise
    cause us to signal an unrelated process."""
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        return None
    try:
        cmdline = (
            Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", errors="replace"
            )
        )
    except FileNotFoundError:
        return None
    if "confer-daemon" not in cmdline:
        return None
    return pid


def _cmd_stop() -> int:
    pf = pid_file()
    pid = _read_live_pid(pf)
    if pid is None:
        if pf.exists():
            print(
                f"Stale PID file at {pf} (no live confer-daemon process); "
                "removing."
            )
            with suppress(FileNotFoundError):
                pf.unlink()
            return 0
        print(f"No daemon PID file at {pf}; nothing to stop.", file=sys.stderr)
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"No process with pid {pid}; removing stale PID file.")
        with suppress(FileNotFoundError):
            pf.unlink()
        return 0
    for _ in range(50):
        time.sleep(0.1)
        if not pf.exists():
            print(f"Daemon (pid {pid}) stopped.")
            return 0
    print(f"Daemon (pid {pid}) did not exit within 5s.", file=sys.stderr)
    return 1


async def _query_status() -> StatusResult | None:
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path()))
    except OSError:
        return None
    try:
        writer.write(encode(Status(request_id="status")))
        await writer.drain()
        line = await reader.readline()
        if not line:
            return None
        msg = decode(line)
        if not isinstance(msg, StatusResult):
            return None
        return msg
    finally:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


def _format_uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _print_status(pid: int, result: StatusResult) -> None:
    print("confer daemon")
    print(f"  PID: {pid}")
    print(f"  Uptime: {_format_uptime(result.uptime_seconds)}")
    print(f"  Gateway: {result.gateway_state}")
    print(f"  Clients ({len(result.clients)}):")
    for c in result.clients:
        print(f"    {c}")
    lf = log_file()
    if not lf.exists():
        return
    print()
    print(f"Recent log tail ({lf}):")
    for line in lf.read_text().splitlines()[-20:]:
        print(f"  {line}")


def _cmd_status() -> int:
    pf = pid_file()
    pid = _read_live_pid(pf)
    if pid is None:
        if pf.exists():
            print(
                f"Stale PID file at {pf} (no live confer-daemon process); "
                "daemon is not running."
            )
            return 0
        print(f"No daemon running (no PID file at {pf}).")
        return 0
    result = asyncio.run(_query_status())
    if result is None:
        print(
            f"Daemon (pid {pid}) did not respond to status query.",
            file=sys.stderr,
        )
        return 1
    _print_status(pid, result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="confer-daemon")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("stop", help="Stop a running daemon.")
    sub.add_parser("status", help="Show running daemon status.")
    args = parser.parse_args(argv)
    if args.cmd is None:
        return _cmd_run()
    if args.cmd == "stop":
        return _cmd_stop()
    return _cmd_status()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
