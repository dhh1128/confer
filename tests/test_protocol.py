import pytest

from confer.protocol import (
    AskBegin,
    AskCancel,
    AskReply,
    AskTimeout,
    Bye,
    CheckMessages,
    CheckMessagesResult,
    Error,
    Hello,
    HelloErr,
    HelloOk,
    Notify,
    NotifyResult,
    Status,
    StatusResult,
    decode,
    encode,
)


def _roundtrip(msg):
    encoded = encode(msg)
    return decode(encoded.rstrip(b"\n"))


def test_encode_produces_one_ndjson_line():
    encoded = encode(Bye())
    assert encoded.endswith(b"\n")
    assert encoded.count(b"\n") == 1


def test_hello_roundtrips():
    msg = Hello(request_id="abc", label_preferred="confer/main", pid=1234)
    assert _roundtrip(msg) == msg


def test_hello_ok_roundtrips():
    msg = HelloOk(request_id="abc", label_assigned="confer/main#a3f1")
    assert _roundtrip(msg) == msg


def test_hello_err_roundtrips():
    msg = HelloErr(request_id="abc", reason="config missing")
    assert _roundtrip(msg) == msg


def test_notify_roundtrips():
    msg = Notify(request_id="xyz", message="hello world")
    assert _roundtrip(msg) == msg


def test_notify_result_roundtrips():
    msg = NotifyResult(request_id="xyz", status="ok", info="sent at 2026-05-28")
    assert _roundtrip(msg) == msg


def test_bye_roundtrips():
    assert _roundtrip(Bye()) == Bye()


def test_error_with_request_id_roundtrips():
    msg = Error(code="bad_message", message="malformed", request_id="xyz")
    assert _roundtrip(msg) == msg


def test_error_without_request_id_roundtrips():
    msg = Error(code="protocol", message="bad framing")
    assert _roundtrip(msg) == msg


def test_status_roundtrips():
    msg = Status(request_id="s1")
    assert _roundtrip(msg) == msg


def test_status_result_roundtrips():
    msg = StatusResult(
        request_id="s1",
        uptime_seconds=12.5,
        gateway_state="ready",
        clients=["confer/main", "myapp/main#a3f1"],
    )
    assert _roundtrip(msg) == msg


def test_decode_raises_on_invalid_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        decode(b"not json at all")


def test_decode_raises_on_non_object_json():
    with pytest.raises(ValueError, match="JSON object"):
        decode(b"[1, 2, 3]")


def test_decode_raises_on_missing_kind():
    with pytest.raises(ValueError, match="missing required 'kind'"):
        decode(b'{"request_id": "x"}')


def test_decode_raises_on_unknown_kind():
    with pytest.raises(ValueError, match="unknown message kind"):
        decode(b'{"kind": "NOPE"}')


def test_decode_raises_on_invalid_fields():
    with pytest.raises(ValueError, match="invalid fields"):
        decode(b'{"kind": "HELLO"}')


def test_ask_begin_roundtrips():
    msg = AskBegin(
        request_id="r1",
        question="should I rebase or merge?",
        give_up_after_seconds=1800,
        on_timeout="use_best_judgment",
    )
    assert _roundtrip(msg) == msg


def test_ask_begin_with_abort_mode_roundtrips():
    msg = AskBegin(
        request_id="r2",
        question="drop the users table?",
        give_up_after_seconds=86400,
        on_timeout="abort",
    )
    assert _roundtrip(msg) == msg


def test_ask_reply_roundtrips():
    msg = AskReply(request_id="r1", content="rebase please")
    assert _roundtrip(msg) == msg


def test_ask_timeout_use_best_judgment_roundtrips():
    msg = AskTimeout(request_id="r1", outcome="use_best_judgment")
    assert _roundtrip(msg) == msg


def test_ask_timeout_abort_roundtrips():
    msg = AskTimeout(request_id="r1", outcome="abort")
    assert _roundtrip(msg) == msg


def test_ask_cancel_roundtrips():
    msg = AskCancel(request_id="r1")
    assert _roundtrip(msg) == msg


def test_check_messages_roundtrips():
    msg = CheckMessages(request_id="r1")
    assert _roundtrip(msg) == msg


def test_check_messages_result_roundtrips():
    msg = CheckMessagesResult(
        request_id="r1",
        formatted="[1] 2026-05-29 broadcast: hello there",
        count=1,
    )
    assert _roundtrip(msg) == msg
