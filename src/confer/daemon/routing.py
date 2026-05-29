"""Pure reply-routing logic per Reply Routing Rules (7kxpvnqj), Reply Routing
Parser (nqx7pmv4), and Broadcast Semantics (bw4kqnxp).

The daemon's user-message dispatcher calls `route_user_message` with the
incoming DM content, a snapshot of currently-pending asks, and the set of
currently-connected client labels; the function returns a `RouteDecision`
that the daemon then acts on. The function is pure (no I/O, no daemon
state) so it can be tested in isolation.
"""

import string
from dataclasses import dataclass
from typing import Union


_NO_AGENTS_BOUNCE = (
    "No agent is connected right now — your message wasn't delivered. "
    "Start an agent and try again."
)
_AMBIGUOUS_LABEL_BOUNCE = (
    "Your prefix matches multiple connected agents. Reply with a more "
    "specific prefix so I know which one to address."
)


@dataclass(frozen=True)
class PendingAsk:
    request_id: str
    label: str
    question: str
    started_at: float  # monotonic seconds; newer values sort first


@dataclass(frozen=True)
class Deliver:
    """Deliver to a specific live ask: ASK_REPLY back to the awaiting writer."""
    label: str
    content: str


@dataclass(frozen=True)
class EnqueueLabeled:
    """Enqueue to a connected client's check_messages queue (rule 1 with no
    matching ask). source="labeled_interjection"."""
    label: str
    content: str


@dataclass(frozen=True)
class Broadcast:
    """Copy to every connected client's queue (rule 4). source="broadcast"."""
    content: str


@dataclass(frozen=True)
class Bounce:
    text: str  # exact DM body to send back


@dataclass(frozen=True)
class Ambiguous:
    pending_asks: tuple[PendingAsk, ...]  # newest-first; daemon formats the DM


RouteDecision = Union[Deliver, EnqueueLabeled, Broadcast, Bounce, Ambiguous]


def route_user_message(
    content: str,
    pending_asks: tuple[PendingAsk, ...] | list[PendingAsk],
    connected_labels: tuple[str, ...] | list[str] = (),
) -> RouteDecision:
    """Apply the five-rule precedence ladder from 7kxpvnqj.

    The function does not strip whitespace from the delivered content beyond
    removing a successfully-matched routing prefix and its trailing separator;
    callers may further strip if they wish.
    """
    asks = tuple(sorted(pending_asks, key=lambda a: a.started_at, reverse=True))
    connected = tuple(connected_labels)

    # No agents connected anywhere: nothing useful to do with the message.
    if not asks and not connected:
        return Bounce(text=_NO_AGENTS_BOUNCE)

    token, rest = _split_first_token(content)

    # Rule (2): numeric shortcut into ASKS (only if asks exist).
    if token.isdigit() and asks:
        idx = int(token) - 1
        if 0 <= idx < len(asks):
            return Deliver(label=asks[idx].label, content=rest)
        return Ambiguous(pending_asks=asks)

    # Rule (1): label-prefix match — asks first, then connected clients.
    if token:
        ask_matches = _ask_label_matches(token, asks)
        if len(ask_matches) == 1:
            return Deliver(label=ask_matches[0].label, content=rest)
        if len(ask_matches) > 1:
            return Ambiguous(pending_asks=asks)
        client_matches = _client_label_matches(token, connected)
        if len(client_matches) == 1:
            return EnqueueLabeled(label=client_matches[0], content=rest)
        if len(client_matches) > 1:
            return Bounce(text=_AMBIGUOUS_LABEL_BOUNCE)
        # No label match anywhere; fall through to ask-shortcut / broadcast.

    # Rule (3): exactly one pending ask → whole message as content.
    if len(asks) == 1:
        return Deliver(label=asks[0].label, content=content)

    # Rule (4): zero asks pending → broadcast to all connected clients.
    if not asks and connected:
        return Broadcast(content=content)

    # Rule (5): multiple pending asks and no usable prefix → ambiguous.
    return Ambiguous(pending_asks=asks)


def _split_first_token(content: str) -> tuple[str, str]:
    """Split a token from the start of `content`.

    A token is a maximal prefix of allowed characters: letters, digits, hyphen,
    underscore, slash. Whitespace and punctuation terminate the token. Returns
    (token, rest) where `rest` has any trailing separator stripped.
    """
    stripped = content.lstrip()
    end = 0
    for ch in stripped:
        if ch.isalnum() or ch in "-_/":
            end += 1
        else:
            break
    token = stripped[:end]
    rest = stripped[end:]
    while rest and (rest[0] in string.whitespace or rest[0] in ":,;.!?-"):
        rest = rest[1:]
    return token, rest


def _ask_label_matches(
    token: str, asks: tuple[PendingAsk, ...]
) -> list[PendingAsk]:
    normalized = _normalize_for_match(token)
    if not normalized:
        return []
    return [a for a in asks if normalized in _normalize_for_match(a.label)]


def _client_label_matches(
    token: str, connected: tuple[str, ...]
) -> list[str]:
    normalized = _normalize_for_match(token)
    if not normalized:
        return []
    return [label for label in connected if normalized in _normalize_for_match(label)]


def _normalize_for_match(s: str) -> str:
    return s.lower().replace("-", " ").replace("/", " ")
