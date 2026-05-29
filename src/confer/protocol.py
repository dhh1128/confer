import json
from dataclasses import asdict, dataclass
from typing import Literal, Union


CURRENT_PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class Hello:
    request_id: str
    label_preferred: str
    pid: int
    protocol_version: int = CURRENT_PROTOCOL_VERSION
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
class AskBegin:
    request_id: str
    question: str
    give_up_after_seconds: int
    on_timeout: Literal["use_best_judgment", "abort"]
    kind: Literal["ASK_BEGIN"] = "ASK_BEGIN"


@dataclass(frozen=True)
class AskReply:
    request_id: str
    content: str
    kind: Literal["ASK_REPLY"] = "ASK_REPLY"


@dataclass(frozen=True)
class AskTimeout:
    request_id: str
    outcome: Literal["use_best_judgment", "abort"]
    kind: Literal["ASK_TIMEOUT"] = "ASK_TIMEOUT"


@dataclass(frozen=True)
class AskCancel:
    request_id: str
    kind: Literal["ASK_CANCEL"] = "ASK_CANCEL"


@dataclass(frozen=True)
class CheckMessages:
    request_id: str
    kind: Literal["CHECK_MESSAGES"] = "CHECK_MESSAGES"


@dataclass(frozen=True)
class CheckMessagesResult:
    request_id: str
    formatted: str
    count: int
    kind: Literal["CHECK_MESSAGES_RESULT"] = "CHECK_MESSAGES_RESULT"


@dataclass(frozen=True)
class Inject:
    """User-side CLI message: route this content as if it had arrived via
    Discord. HELLO-exempt per CLI Inject Tool (ci7n4pvm)."""
    request_id: str
    content: str
    kind: Literal["INJECT"] = "INJECT"


@dataclass(frozen=True)
class InjectResult:
    request_id: str
    outcome: Literal[
        "delivered", "queued_labeled", "broadcast", "bounced", "ambiguous"
    ]
    detail: str
    kind: Literal["INJECT_RESULT"] = "INJECT_RESULT"


@dataclass(frozen=True)
class ListAsks:
    """User-side CLI message: ask the daemon for a formatted view of pending
    asks. HELLO-exempt per CLI Inject Tool (ci7n4pvm)."""
    request_id: str
    kind: Literal["LIST_ASKS"] = "LIST_ASKS"


@dataclass(frozen=True)
class ListAsksResult:
    request_id: str
    formatted: str
    count: int
    kind: Literal["LIST_ASKS_RESULT"] = "LIST_ASKS_RESULT"


@dataclass(frozen=True)
class Bye:
    kind: Literal["BYE"] = "BYE"


@dataclass(frozen=True)
class Error:
    code: str
    message: str
    request_id: str | None = None
    kind: Literal["ERROR"] = "ERROR"


@dataclass(frozen=True)
class Status:
    request_id: str
    kind: Literal["STATUS"] = "STATUS"


@dataclass(frozen=True)
class StatusResult:
    request_id: str
    uptime_seconds: float
    gateway_state: str
    clients: list[str]
    kind: Literal["STATUS_RESULT"] = "STATUS_RESULT"


Message = Union[
    Hello,
    HelloOk,
    HelloErr,
    Notify,
    NotifyResult,
    AskBegin,
    AskReply,
    AskTimeout,
    AskCancel,
    CheckMessages,
    CheckMessagesResult,
    Inject,
    InjectResult,
    ListAsks,
    ListAsksResult,
    Bye,
    Error,
    Status,
    StatusResult,
]


_MESSAGE_TYPES: dict[str, type] = {
    "HELLO": Hello,
    "HELLO_OK": HelloOk,
    "HELLO_ERR": HelloErr,
    "NOTIFY": Notify,
    "NOTIFY_RESULT": NotifyResult,
    "ASK_BEGIN": AskBegin,
    "ASK_REPLY": AskReply,
    "ASK_TIMEOUT": AskTimeout,
    "ASK_CANCEL": AskCancel,
    "CHECK_MESSAGES": CheckMessages,
    "CHECK_MESSAGES_RESULT": CheckMessagesResult,
    "INJECT": Inject,
    "INJECT_RESULT": InjectResult,
    "LIST_ASKS": ListAsks,
    "LIST_ASKS_RESULT": ListAsksResult,
    "BYE": Bye,
    "ERROR": Error,
    "STATUS": Status,
    "STATUS_RESULT": StatusResult,
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
