"""Pure reply-routing logic per Tag Based Reply Routing (rt7nqp4m), which
rewrites the earlier label-based rules (7kxpvnqj) around thread tags.

The daemon's user-message dispatcher calls `route_user_message` with the
incoming DM content, the currently-awaiting ask-threads, the currently-
replyable notify-threads, and the set of connected client labels; the
function returns a `RouteDecision` the daemon acts on. The function is pure
(no I/O, no daemon state) so it is tested in isolation.
"""

import re
import string
from dataclasses import dataclass
from typing import Union


CONCIERGE_SIGIL = "."
CONCIERGE_STUB = "concierge commands aren't available yet."
NO_AGENTS_BOUNCE = (
    "No agent is connected right now — your message wasn't delivered. "
    "Start an agent and try again."
)
AMBIGUOUS_TAG_BOUNCE = (
    "That tag matches more than one open thread. Reply with a longer tag "
    "(or the full 4-character tag) so I know which one you mean."
)

_TAG_LEN = 4
# Leading "re" reply marker: the letters r-e, any case, followed by at least
# one separator (whitespace / colon / comma). "redeploy" does NOT match
# because 'd' is not a separator.
_MARKER_RE = re.compile(r"^re[\s:,]+", re.IGNORECASE)
# A tag token is a run of base32-ish characters (letters + digits 2-7). We
# match liberally then lowercase; non-base32 tokens simply won't match a tag.
_TOKEN_RE = re.compile(r"[A-Za-z2-7]+")


@dataclass(frozen=True)
class AskThread:
    tag: str
    label: str
    question: str
    started_at: float  # monotonic; newer sorts first


@dataclass(frozen=True)
class NotifyThread:
    tag: str
    label: str


@dataclass(frozen=True)
class DeliverAsk:
    """Route to a specific awaiting ask (→ ASK_REPLY)."""
    tag: str
    content: str


@dataclass(frozen=True)
class EnqueueNotifyReply:
    """Route to a notify-thread's agent inbox as a tagged interjection."""
    tag: str
    label: str
    content: str


@dataclass(frozen=True)
class Broadcast:
    content: str


@dataclass(frozen=True)
class Bounce:
    text: str


@dataclass(frozen=True)
class Ambiguous:
    asks: tuple[AskThread, ...]  # awaiting asks, newest-first


@dataclass(frozen=True)
class Concierge:
    """Leading-'.' message addressed to the daemon, not any agent."""
    content: str


RouteDecision = Union[
    DeliverAsk, EnqueueNotifyReply, Broadcast, Bounce, Ambiguous, Concierge
]


def route_user_message(
    content: str,
    ask_threads,
    notify_threads=(),
    connected_labels=(),
) -> RouteDecision:
    """Apply the tag-based routing ladder (rt7nqp4m)."""
    stripped = content.lstrip()

    # Concierge sigil is checked first, before anything else — even with no
    # agents connected, a "." message is for the daemon, never broadcast.
    if stripped.startswith(CONCIERGE_SIGIL):
        return Concierge(content=stripped)

    asks = tuple(sorted(ask_threads, key=lambda a: a.started_at, reverse=True))
    notifies = tuple(notify_threads)
    connected = tuple(connected_labels)

    if not asks and not connected:
        return Bounce(NO_AGENTS_BOUNCE)

    marker, token, rest = _parse_marker_and_token(stripped)
    if token:
        if marker:
            matches = _prefix_matches(token, asks, notifies)
            if len(matches) == 1:
                return _route_to_thread(matches[0], rest)
            if len(matches) > 1:
                return Bounce(AMBIGUOUS_TAG_BOUNCE)
            # No prefix match — fall through to the no-tag rules below.
        else:
            exact = _exact_match(token, asks, notifies)
            if exact is not None:
                return _route_to_thread(exact, rest)

    # Step (2): exactly one awaiting ask → next-message-wins, full content.
    if len(asks) == 1:
        return DeliverAsk(tag=asks[0].tag, content=content)
    # Step (3): two+ awaiting asks → ambiguity bounce.
    if len(asks) >= 2:
        return Ambiguous(asks=asks)
    # Step (4): no asks awaiting → broadcast to all connected agents. We are
    # past the no-agents guard above, so at least one agent is connected.
    return Broadcast(content=content)


def _route_to_thread(thread, content: str) -> RouteDecision:
    if isinstance(thread, AskThread):
        return DeliverAsk(tag=thread.tag, content=content)
    return EnqueueNotifyReply(tag=thread.tag, label=thread.label, content=content)


def _parse_marker_and_token(stripped: str) -> tuple[bool, str, str]:
    """Return (marker_present, token_lowercased, rest_after_token)."""
    s = stripped
    marker = False
    m = _MARKER_RE.match(s)
    if m:
        marker = True
        s = s[m.end():]
    tok = _TOKEN_RE.match(s)
    if not tok:
        return marker, "", ""
    token = tok.group(0).lower()
    rest = s[tok.end():]
    rest = rest.lstrip(string.whitespace + ":,.-")
    return marker, token, rest


def _all_threads(asks, notifies):
    return list(asks) + list(notifies)


def _prefix_matches(token: str, asks, notifies) -> list:
    return [t for t in _all_threads(asks, notifies) if t.tag.startswith(token)]


def _exact_match(token: str, asks, notifies):
    if len(token) != _TAG_LEN:
        return None
    for t in _all_threads(asks, notifies):
        if t.tag == token:
            return t
    return None
