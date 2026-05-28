import json
from dataclasses import asdict, dataclass
from typing import Literal, Union


@dataclass(frozen=True)
class Hello:
    request_id: str
    label_preferred: str
    pid: int
    kind: Literal["HELLO"] = "HELLO"


@dataclass(frozen=True)
class HelloOk:
    request_id: str
    label_assigned: str
    kind: Literal["HELLO_OK"] = "HELLO_OK"


@dataclass(frozen=True)
class HelloErr:
    request_id: str
    reason: str
    kind: Literal["HELLO_ERR"] = "HELLO_ERR"


@dataclass(frozen=True)
class Notify:
    request_id: str
    message: str
    kind: Literal["NOTIFY"] = "NOTIFY"


@dataclass(frozen=True)
class NotifyResult:
    request_id: str
    status: str
    info: str
    kind: Literal["NOTIFY_RESULT"] = "NOTIFY_RESULT"


@dataclass(frozen=True)
class Bye:
    kind: Literal["BYE"] = "BYE"


@dataclass(frozen=True)
class Error:
    code: str
    message: str
    request_id: str | None = None
    kind: Literal["ERROR"] = "ERROR"


Message = Union[Hello, HelloOk, HelloErr, Notify, NotifyResult, Bye, Error]


_MESSAGE_TYPES: dict[str, type] = {
    "HELLO": Hello,
    "HELLO_OK": HelloOk,
    "HELLO_ERR": HelloErr,
    "NOTIFY": Notify,
    "NOTIFY_RESULT": NotifyResult,
    "BYE": Bye,
    "ERROR": Error,
}


def encode(msg: Message) -> bytes:
    return (json.dumps(asdict(msg)) + "\n").encode("utf-8")


def decode(line: bytes) -> Message:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in message: {e.msg}") from e
    if not isinstance(data, dict):
        raise ValueError(
            f"message must be a JSON object, got {type(data).__name__}"
        )
    kind = data.get("kind")
    if kind is None:
        raise ValueError("message missing required 'kind' field")
    msg_type = _MESSAGE_TYPES.get(kind)
    if msg_type is None:
        raise ValueError(f"unknown message kind: {kind!r}")
    try:
        return msg_type(**data)
    except TypeError as e:
        raise ValueError(f"invalid fields for {kind}: {e}") from e
