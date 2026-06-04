"""Tests for away time-input parsing (awaytime.py, sq7nkp4x)."""

from datetime import datetime

import pytest

from confer import awaytime


# A fixed reference "now": 2026-05-29 14:00:00 local.
NOW = datetime(2026, 5, 29, 14, 0, 0).timestamp()


# ─── --in <minutes> ─────────────────────────────────────────────────────────

def test_in_minutes_adds_to_now():
    assert awaytime.parse_in_minutes("5", now=NOW) == NOW + 300.0


def test_in_zero_is_now():
    assert awaytime.parse_in_minutes("0", now=NOW) == NOW


def test_in_accepts_fractional():
    assert awaytime.parse_in_minutes("1.5", now=NOW) == NOW + 90.0


def test_in_rejects_non_number():
    with pytest.raises(awaytime.AwayTimeError):
        awaytime.parse_in_minutes("soon", now=NOW)


def test_in_rejects_negative():
    with pytest.raises(awaytime.AwayTimeError):
        awaytime.parse_in_minutes("-3", now=NOW)


def test_in_default_now_uses_wall_clock(monkeypatch):
    monkeypatch.setattr(awaytime._time, "time", lambda: 1000.0)
    assert awaytime.parse_in_minutes("2") == 1000.0 + 120.0


# ─── --at <HHMM> ────────────────────────────────────────────────────────────

def test_at_future_time_today():
    # 18:00 is later than 14:00 → today at 18:00.
    got = awaytime.parse_at_clock("1800", now=NOW)
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 29, 18, 0, 0)


def test_at_past_time_rolls_to_tomorrow():
    # 09:00 already passed at 14:00 → tomorrow at 09:00 (sq7nkp4x).
    got = awaytime.parse_at_clock("0900", now=NOW)
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 30, 9, 0, 0)


def test_at_exactly_now_rolls_to_tomorrow():
    # 14:00 == now → not in the future → tomorrow.
    got = awaytime.parse_at_clock("1400", now=NOW)
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 30, 14, 0, 0)


def test_at_within_24h_cap_holds():
    # Any --at result is at most 24h out (the past=tomorrow rule guarantees it).
    for hhmm in ("0000", "0900", "1400", "1359", "2359"):
        got = awaytime.parse_at_clock(hhmm, now=NOW)
        assert 0 <= got - NOW <= 24 * 3600


def test_at_accepts_colon_form():
    got = awaytime.parse_at_clock("18:30", now=NOW)
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 29, 18, 30, 0)


def test_at_accepts_bare_hour():
    got = awaytime.parse_at_clock("18", now=NOW)
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 29, 18, 0, 0)


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "2500", "1860", "12:30:00", "9:9:9", "::", "aa:bb"],
)
def test_at_rejects_malformed(bad):
    with pytest.raises(awaytime.AwayTimeError):
        awaytime.parse_at_clock(bad, now=NOW)


def test_at_default_now_uses_wall_clock(monkeypatch):
    monkeypatch.setattr(awaytime._time, "time", lambda: NOW)
    got = awaytime.parse_at_clock("1800")
    assert datetime.fromtimestamp(got) == datetime(2026, 5, 29, 18, 0, 0)
