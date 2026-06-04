"""Tests for the scheduled-away activation notice (cs7nkp4x / nd7nkp4x)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from confer import presence as presence_mod
from confer.daemon.core import (
    Daemon,
    _activation_notice_text,
    _newly_fired_activations,
)
from confer.presence import PendingAway


@pytest.fixture
def presence_path(tmp_path, monkeypatch):
    p = tmp_path / "confer.presence"
    # Patch where presence reads AND where core.read_presence reads (same fn).
    monkeypatch.setattr(presence_mod, "presence_file", lambda: p)
    return p


def _daemon_with_clock(now_holder):
    transport = MagicMock()
    transport.notify = AsyncMock(return_value="sent at 2026-01-01T00:00:00+00:00")
    return Daemon(transport=transport, wall_clock=lambda: now_holder["t"])


# ─── pure helper ────────────────────────────────────────────────────────────

def test_newly_fired_only_returns_due_and_unannounced():
    pending = (
        PendingAway(at=100.0, note="a"),
        PendingAway(at=200.0, note="b"),
        PendingAway(at=300.0, note="c"),
    )
    announced = {100.0}  # already announced the first
    fired = _newly_fired_activations(pending, announced, now=250.0)
    # 200 is due and unannounced; 100 already announced; 300 not due yet.
    assert [p.at for p in fired] == [200.0]


def test_activation_notice_text_with_and_without_note():
    assert _activation_notice_text("standup") == "confer: Now in away mode — standup"
    assert _activation_notice_text(None) == "confer: Now in away mode"


# ─── watcher one-pass behavior ──────────────────────────────────────────────

async def test_check_activations_dms_on_fire(presence_path):
    now = {"t": 50.0}
    daemon = _daemon_with_clock(now)
    presence_mod.schedule_away(at=100.0, note="standup")

    # Before fire: no DM.
    await daemon._check_activations_once()
    daemon._transport.notify.assert_not_called()

    # After fire: exactly one DM with the note.
    now["t"] = 100.0
    await daemon._check_activations_once()
    daemon._transport.notify.assert_awaited_once()
    body = daemon._transport.notify.await_args.args[0]
    assert "Now in away mode" in body and "standup" in body


async def test_check_activations_is_at_most_once(presence_path):
    now = {"t": 100.0}
    daemon = _daemon_with_clock(now)
    presence_mod.schedule_away(at=100.0)
    await daemon._check_activations_once()
    now["t"] = 200.0
    await daemon._check_activations_once()  # same entry, must not re-DM
    daemon._transport.notify.assert_awaited_once()


async def test_check_activations_no_pending_is_noop(presence_path):
    daemon = _daemon_with_clock({"t": 100.0})
    # No presence file at all.
    await daemon._check_activations_once()
    daemon._transport.notify.assert_not_called()


async def test_presence_watch_loop_runs_then_sleeps(presence_path):
    """One iteration of the poll loop: it checks activations (DMs the fired
    entry) then awaits its sleep — which we use to cancel the loop."""
    import asyncio

    now = {"t": 100.0}
    transport = MagicMock()
    transport.notify = AsyncMock(return_value="sent at ...")

    async def sleep_then_stop(_seconds):
        raise asyncio.CancelledError  # break out after the first check

    daemon = Daemon(
        transport=transport,
        wall_clock=lambda: now["t"],
        sleep=sleep_then_stop,
    )
    presence_mod.schedule_away(at=100.0, note="mtg")
    with pytest.raises(asyncio.CancelledError):
        await daemon._presence_watch_loop()
    transport.notify.assert_awaited_once()


async def test_presence_watch_loop_swallows_check_errors(presence_path, monkeypatch):
    """A failure inside _check_activations_once must not kill the loop; it is
    suppressed and the loop proceeds to its sleep (best-effort, nd7nkp4x)."""
    import asyncio

    transport = MagicMock()
    transport.notify = AsyncMock()
    daemon = Daemon(transport=transport, wall_clock=lambda: 0.0)

    async def boom():
        raise RuntimeError("read blew up")

    async def sleep_then_stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(daemon, "_check_activations_once", boom)
    monkeypatch.setattr(daemon, "_sleep", sleep_then_stop)
    with pytest.raises(asyncio.CancelledError):
        await daemon._presence_watch_loop()  # must not raise RuntimeError


async def test_check_activations_announces_each_distinct_entry(presence_path):
    now = {"t": 100.0}
    daemon = _daemon_with_clock(now)
    presence_mod.schedule_away(at=100.0, note="first")
    presence_mod.schedule_away(at=150.0, note="second")
    await daemon._check_activations_once()  # only first due
    now["t"] = 150.0
    await daemon._check_activations_once()  # now second due
    assert daemon._transport.notify.await_count == 2
