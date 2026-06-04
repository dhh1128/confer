import json

import pytest

from confer import presence as presence_mod
from confer.presence import PendingAway, Presence


@pytest.fixture
def presence_path(tmp_path, monkeypatch):
    p = tmp_path / "confer.presence"
    monkeypatch.setattr(presence_mod, "presence_file", lambda: p)
    return p


# ─── baseline / backward compatibility ──────────────────────────────────────

def test_absent_file_is_present(presence_path):
    assert presence_mod.read_presence().away is False
    assert presence_mod.is_away(now=0.0) is False


def test_set_away_with_note_round_trips(presence_path):
    pr = presence_mod.set_away("lunch", now=123.0)
    assert (pr.away, pr.note, pr.since) == (True, "lunch", 123.0)
    assert json.loads(presence_path.read_text()) == {
        "away": True, "since": 123.0, "note": "lunch",
    }
    read = presence_mod.read_presence()
    assert (read.away, read.note, read.since) == (True, "lunch", 123.0)
    assert presence_mod.is_away(now=200.0) is True


def test_set_away_without_note_omits_note(presence_path):
    presence_mod.set_away(now=5.0)
    assert "note" not in json.loads(presence_path.read_text())
    assert presence_mod.read_presence().note is None


def test_set_away_default_now_uses_wall_clock(presence_path, monkeypatch):
    monkeypatch.setattr(presence_mod.time, "time", lambda: 999.0)
    assert presence_mod.set_away().since == 999.0


def test_is_away_default_now_uses_wall_clock(presence_path, monkeypatch):
    monkeypatch.setattr(presence_mod.time, "time", lambda: 50.0)
    presence_mod.schedule_away(at=40.0)  # already fired by t=50
    assert presence_mod.is_away() is True


def test_set_present_removes_file(presence_path):
    presence_mod.set_away(now=1.0)
    presence_mod.set_present(now=2.0)
    assert not presence_path.exists()
    assert presence_mod.is_away(now=2.0) is False


def test_set_present_default_now_uses_wall_clock(presence_path, monkeypatch):
    monkeypatch.setattr(presence_mod.time, "time", lambda: 100.0)
    presence_mod.schedule_away(at=200.0)  # still future at t=100
    presence_mod.set_present()  # default now → 100.0, keeps the future entry
    assert presence_mod.read_presence().pending == (PendingAway(at=200.0),)


def test_set_present_is_idempotent_when_absent(presence_path):
    presence_mod.set_present(now=1.0)
    assert not presence_path.exists()


def test_corrupt_marker_is_treated_as_away(presence_path):
    presence_path.write_text("{not json")
    pr = presence_mod.read_presence()
    assert pr.away is True and pr.note is None


def test_non_dict_json_marker_is_treated_as_away(presence_path):
    presence_path.write_text("[1, 2, 3]")
    assert presence_mod.read_presence().away is True


# ─── scheduled away (sq7nkp4x) ──────────────────────────────────────────────

def test_schedule_away_is_not_effective_until_its_time(presence_path):
    presence_mod.schedule_away(at=1000.0, note="standup")
    assert presence_mod.is_away(now=999.0) is False
    assert presence_mod.is_away(now=1000.0) is True  # fires at exactly its time
    assert presence_mod.is_away(now=1001.0) is True


def test_multiple_schedules_accumulate_and_sort(presence_path):
    presence_mod.schedule_away(at=1400.0, note="review")
    presence_mod.schedule_away(at=1100.0, note="standup")
    pending = presence_mod.read_presence().pending
    assert pending == (
        PendingAway(at=1100.0, note="standup"),
        PendingAway(at=1400.0, note="review"),
    )


def test_scheduling_preserves_existing_sticky_away(presence_path):
    presence_mod.set_away("lunch", now=100.0)
    presence_mod.schedule_away(at=2000.0)
    p = presence_mod.read_presence()
    assert p.away is True and p.note == "lunch"
    assert p.pending == (PendingAway(at=2000.0),)


def test_set_away_preserves_pending_schedule(presence_path):
    presence_mod.schedule_away(at=2000.0, note="later")
    presence_mod.set_away(now=10.0)
    assert presence_mod.read_presence().pending == (
        PendingAway(at=2000.0, note="later"),
    )


def test_active_note_reflects_sticky_then_fired_entry(presence_path):
    # sticky away wins
    presence_mod.set_away("sticky", now=10.0)
    assert presence_mod.read_presence().active_note(now=10.0) == "sticky"
    # present + a fired schedule → its note
    presence_mod.clear_all()
    presence_mod.schedule_away(at=100.0, note="meeting")
    assert presence_mod.read_presence().active_note(now=150.0) == "meeting"
    # before it fires → no active note
    assert presence_mod.read_presence().active_note(now=50.0) is None


def test_active_note_picks_most_recently_fired(presence_path):
    presence_mod.schedule_away(at=100.0, note="first")
    presence_mod.schedule_away(at=200.0, note="second")
    assert presence_mod.read_presence().active_note(now=250.0) == "second"


# ─── back semantics ─────────────────────────────────────────────────────────

def test_set_present_keeps_future_but_drops_fired_pending(presence_path):
    presence_mod.schedule_away(at=100.0, note="past")
    presence_mod.schedule_away(at=500.0, note="future")
    # At t=200: the 100 entry has fired (away now); typing/back makes present
    # but the 500 entry survives.
    presence_mod.set_present(now=200.0)
    p = presence_mod.read_presence()
    assert p.away is False
    assert p.pending == (PendingAway(at=500.0, note="future"),)
    assert presence_mod.is_away(now=200.0) is False
    assert presence_mod.is_away(now=500.0) is True  # future one still fires


def test_cancel_pending_removes_matching_entry(presence_path):
    presence_mod.schedule_away(at=1100.0, note="standup")
    presence_mod.schedule_away(at=1400.0, note="review")
    assert presence_mod.cancel_pending(1100.0) is True
    assert presence_mod.read_presence().pending == (
        PendingAway(at=1400.0, note="review"),
    )


def test_cancel_pending_returns_false_on_no_match(presence_path):
    presence_mod.schedule_away(at=1400.0)
    assert presence_mod.cancel_pending(9999.0) is False
    assert presence_mod.read_presence().pending == (PendingAway(at=1400.0),)


def test_cancel_last_pending_when_present_removes_file(presence_path):
    presence_mod.schedule_away(at=1400.0)
    presence_mod.cancel_pending(1400.0)
    assert not presence_path.exists()


def test_clear_all_wipes_everything(presence_path):
    presence_mod.set_away("x", now=1.0)
    presence_mod.schedule_away(at=2000.0)
    presence_mod.clear_all()
    assert not presence_path.exists()
    assert presence_mod.is_away(now=3000.0) is False  # even past the schedule


def test_clear_all_idempotent_when_absent(presence_path):
    presence_mod.clear_all()
    assert not presence_path.exists()


# ─── persistence round-trips ────────────────────────────────────────────────

def test_pending_round_trips_through_file(presence_path):
    presence_mod.schedule_away(at=1100.0, note="standup")
    presence_mod.schedule_away(at=1400.0)  # no note
    on_disk = json.loads(presence_path.read_text())
    assert on_disk["pending"] == [
        {"at": 1100.0, "note": "standup"},
        {"at": 1400.0},
    ]
    assert presence_mod.read_presence().pending == (
        PendingAway(at=1100.0, note="standup"),
        PendingAway(at=1400.0, note=None),
    )


def test_read_ignores_malformed_pending_entries(presence_path):
    presence_path.write_text(json.dumps({
        "away": False,
        "pending": [
            "notadict",
            {"note": "missing at"},
            {"at": "notanumber"},
            {"at": 1500.0, "note": "good"},
        ],
    }))
    assert presence_mod.read_presence().pending == (
        PendingAway(at=1500.0, note="good"),
    )


def test_non_list_pending_is_ignored(presence_path):
    presence_path.write_text(json.dumps({"away": True, "pending": "nope"}))
    p = presence_mod.read_presence()
    assert p.away is True and p.pending == ()


def test_save_presence_omits_since_and_note_when_none(presence_path):
    presence_mod.save_presence(Presence(away=True))
    on_disk = json.loads(presence_path.read_text())
    assert on_disk == {"away": True}
