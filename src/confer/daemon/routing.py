"""Pure reply-routing logic per Reply Routing Rules (7kxpvnqj) and
Reply Routing Parser (nqx7pmv4).

The daemon's user-message dispatcher calls `route_user_message` with the
incoming DM content and a snapshot of currently-pending asks; the function
returns a `RouteDecision` that the daemon then acts on. The function is pure
(no I/O, no daemon state) so it can be tested in isolation.
"""

import string
from dataclasses import dataclass
from typing import Union


_NO_AGENTS_BOUNCE = (
    "No agent is asking you anything right now — your message wasn't delivered. "
    "(Check-in tool coming in a later phase.)"
)


@dataclass(frozen=True)
class PendingAsk:
    request_id: str
    label: str
    question: str
    started_at: float  # monotonic seconds; newer values sort first


@dataclass(frozen=True)
class Deliver:
    label: str
    content: str


@dataclass(frozen=True)
class Bounce:
    text: str  # exact DM body to send back


@dataclass(frozen=True)
class Ambiguous:
    pending_asks: tuple[PendingAsk, ...]  # newest-first; daemon formats the DM


RouteDecision = Union[Deliver, Bounce, Ambiguous]


def route_user_message(
    content: str, pending_asks: tuple[PendingAsk, ...] | list[PendingAsk]
) -> RouteDecision:
    """Apply the five-rule precedence ladder from 7kxpvnqj.

    The function does not strip whitespace from the delivered content beyond
    removing a successfully-matched routing prefix and its trailing separator;
    callers may further strip if they wish.
    """
    asks = tuple(sorted(pending_asks, key=lambda a: a.started_at, reverse=True))
    if not asks:
        return Bounce(text=_NO_AGENTS_BOUNCE)

    token, rest = _split_first_token(content)

    # Rule (2): numeric shortcut.
    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(asks):
            return Deliver(label=asks[idx].label, content=rest)
        return Ambiguous(pending_asks=asks)

    # Rule (1): label-prefix match (case-insensitive, hyphen/space interchangeable).
    if token:
        matches = _label_prefix_matches(token, asks)
        if len(matches) == 1:
            return Deliver(label=matches[0].label, content=rest)
        if len(matches) > 1:
            return Ambiguous(pending_asks=asks)

    # Rule (3): exactly one pending ask → whole message as content.
    if len(asks) == 1:
        return Deliver(label=asks[0].label, content=content)

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
    # Strip a single immediately-following separator run so "feat-ask: hello"
    # delivers "hello" not " hello" or ": hello".
    while rest and (rest[0] in string.whitespace or rest[0] in ":,;.!?-"):
        rest = rest[1:]
    return token, rest


def _label_prefix_matches(
    token: str, asks: tuple[PendingAsk, ...]
) -> list[PendingAsk]:
    """Return all asks whose label contains the normalized token as a substring.

    Per 7kxpvnqj rule (1): case-insensitive; hyphens and spaces interchangeable
    in matching. We also accept slashes as match-equivalent to hyphens since
    labels include them (e.g., "confer/main").
    """
    normalized_token = _normalize_for_match(token)
    if not normalized_token:
        return []
    matches: list[PendingAsk] = []
    for ask in asks:
        if normalized_token in _normalize_for_match(ask.label):
            matches.append(ask)
    return matches


def _normalize_for_match(s: str) -> str:
    return s.lower().replace("-", " ").replace("/", " ")
