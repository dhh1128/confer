import json

from confer import hooks
from confer.presence import Presence


def _jsonl(path, objs):
    path.write_text("\n".join(json.dumps(o) for o in objs) + "\n")


AWAY = Presence(away=True)


def test_stop_allows_when_present():
    assert hooks.run_stop_hook("{}", presence=Presence(away=False)) == (0, "")


def test_stop_allows_on_bad_json():
    assert hooks.run_stop_hook("not json", presence=AWAY) == (0, "")


def test_stop_allows_on_non_dict_json():
    assert hooks.run_stop_hook("[1, 2]", presence=AWAY) == (0, "")


def test_stop_allows_when_stop_hook_active():
    payload = json.dumps({"stop_hook_active": True, "transcript_path": "/x"})
    assert hooks.run_stop_hook(payload, presence=AWAY) == (0, "")


def test_stop_allows_when_transcript_path_missing():
    payload = json.dumps({"stop_hook_active": False})
    assert hooks.run_stop_hook(payload, presence=AWAY) == (0, "")


def test_stop_allows_when_transcript_unreadable(tmp_path):
    payload = json.dumps(
        {"stop_hook_active": False, "transcript_path": str(tmp_path / "nope.jsonl")}
    )
    # Fail-open: unreadable transcript must not block.
    assert hooks.run_stop_hook(payload, presence=AWAY)[0] == 0


def test_stop_blocks_when_away_and_no_confer_tool(tmp_path):
    t = tmp_path / "t.jsonl"
    _jsonl(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "done"}]}},
    ])
    payload = json.dumps({"stop_hook_active": False, "transcript_path": str(t)})
    code, msg = hooks.run_stop_hook(payload, presence=AWAY)
    assert code == 2
    assert "away from the keyboard" in msg


def test_stop_block_includes_note(tmp_path):
    t = tmp_path / "t.jsonl"
    _jsonl(t, [{"type": "user", "message": {"content": []}}])
    payload = json.dumps({"stop_hook_active": False, "transcript_path": str(t)})
    code, msg = hooks.run_stop_hook(
        payload, presence=Presence(away=True, note="back at 3")
    )
    assert code == 2 and "back at 3" in msg


def test_stop_allows_when_confer_tool_used_after_last_user(tmp_path):
    t = tmp_path / "t.jsonl"
    _jsonl(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__confer__notify", "input": {}}]}},
    ])
    payload = json.dumps({"stop_hook_active": False, "transcript_path": str(t)})
    assert hooks.run_stop_hook(payload, presence=AWAY) == (0, "")


def test_stop_handles_messy_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    lines = [
        "",                                                   # empty line
        "{bad json",                                          # decode error
        json.dumps(42),                                       # non-dict
        json.dumps({"type": "user", "message": {"content": "plain"}}),
        json.dumps({"type": "assistant", "message": {"content": None}}),
        json.dumps({"type": "assistant", "message": {"content": "str"}}),
        json.dumps({"type": "assistant", "message": {"content": [
            "rawstring",                                      # block not a dict
            {"type": "text", "text": "x"},                    # not tool_use
            {"type": "tool_use", "name": 123},                # name not a str
            {"type": "tool_use", "name": "mcp__other__foo"},  # non-confer tool
        ]}}),
        json.dumps({"type": "system"}),                       # neither user nor assistant
    ]
    t.write_text("\n".join(lines) + "\n")
    payload = json.dumps({"stop_hook_active": False, "transcript_path": str(t)})
    # No confer tool after the last user turn → block.
    assert hooks.run_stop_hook(payload, presence=AWAY)[0] == 2


def test_prompt_hook_clears_presence(tmp_path, monkeypatch):
    from confer import presence as presence_mod
    p = tmp_path / "confer.presence"
    monkeypatch.setattr(presence_mod, "presence_file", lambda: p)
    presence_mod.set_away(now=1.0)
    assert hooks.run_prompt_hook() == 0
    assert not p.exists()
