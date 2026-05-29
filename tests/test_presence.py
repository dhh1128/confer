import json

import pytest

from confer import presence as presence_mod


@pytest.fixture
def presence_path(tmp_path, monkeypatch):
    p = tmp_path / "confer.presence"
    monkeypatch.setattr(presence_mod, "presence_file", lambda: p)
    return p


def test_absent_file_is_present(presence_path):
    assert presence_mod.read_presence().away is False
    assert presence_mod.is_away() is False


def test_set_away_with_note_round_trips(presence_path):
    pr = presence_mod.set_away("lunch", now=123.0)
    assert (pr.away, pr.note, pr.since) == (True, "lunch", 123.0)
    assert json.loads(presence_path.read_text()) == {
        "away": True, "since": 123.0, "note": "lunch",
    }
    read = presence_mod.read_presence()
    assert (read.away, read.note, read.since) == (True, "lunch", 123.0)
    assert presence_mod.is_away() is True


def test_set_away_without_note_omits_note(presence_path):
    presence_mod.set_away(now=5.0)
    assert "note" not in json.loads(presence_path.read_text())
    assert presence_mod.read_presence().note is None


def test_set_away_default_now_uses_wall_clock(presence_path, monkeypatch):
    monkeypatch.setattr(presence_mod.time, "time", lambda: 999.0)
    assert presence_mod.set_away().since == 999.0


def test_set_present_removes_file(presence_path):
    presence_mod.set_away(now=1.0)
    presence_mod.set_present()
    assert not presence_path.exists()
    assert presence_mod.is_away() is False


def test_set_present_is_idempotent_when_absent(presence_path):
    presence_mod.set_present()  # no file present; must not raise
    assert not presence_path.exists()


def test_corrupt_marker_is_treated_as_away(presence_path):
    presence_path.write_text("{not json")
    pr = presence_mod.read_presence()
    assert pr.away is True and pr.note is None
