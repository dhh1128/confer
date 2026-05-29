from confer.daemon.routing import (
    AMBIGUOUS_TAG_BOUNCE,
    Ambiguous,
    AskThread,
    Bounce,
    Broadcast,
    Concierge,
    DeliverAsk,
    EnqueueNotifyReply,
    NotifyThread,
    NO_AGENTS_BOUNCE,
    route_user_message,
    _parse_marker_and_token,
)


def _ask(tag, label="confer/main", question="q?", started_at=1.0) -> AskThread:
    return AskThread(tag=tag, label=label, question=question, started_at=started_at)


def _notify(tag, label="confer/main") -> NotifyThread:
    return NotifyThread(tag=tag, label=label)


# ─── concierge sigil ───────────────────────────────────────────────────────


def test_leading_dot_is_concierge_even_with_no_agents():
    d = route_user_message(".threads", (), (), ())
    assert d == Concierge(content=".threads")


def test_leading_dot_after_whitespace_is_concierge():
    d = route_user_message("  .sleep all", (_ask("k3qp"),), (), ("confer/main",))
    assert isinstance(d, Concierge)
    assert d.content == ".sleep all"


# ─── no agents ─────────────────────────────────────────────────────────────


def test_no_agents_anywhere_bounces():
    d = route_user_message("hello", (), (), ())
    assert d == Bounce(NO_AGENTS_BOUNCE)


# ─── single-ask shortcut ───────────────────────────────────────────────────


def test_single_ask_unprefixed_delivers_full_content():
    d = route_user_message("looks good", (_ask("k3qp"),), (), ("confer/main",))
    assert d == DeliverAsk(tag="k3qp", content="looks good")


# ─── tag match: with marker, prefix allowed ────────────────────────────────


def test_marker_prefix_routes_to_unique_ask():
    asks = (_ask("k3qp", started_at=1.0), _ask("m4rs", started_at=2.0))
    d = route_user_message("re k3 rebase please", asks, (), ("confer/main", "x/y"))
    assert d == DeliverAsk(tag="k3qp", content="rebase please")


def test_marker_with_colon_and_full_tag():
    asks = (_ask("k3qp", started_at=1.0), _ask("m4rs", started_at=2.0))
    d = route_user_message("Re: k3qp yes", asks, (), ("a", "b"))
    assert d == DeliverAsk(tag="k3qp", content="yes")


def test_marker_comma_form():
    asks = (_ask("k3qp", started_at=1.0), _ask("m4rs", started_at=2.0))
    d = route_user_message("re, k3 here is the answer", asks, (), ("a", "b"))
    assert d == DeliverAsk(tag="k3qp", content="here is the answer")


def test_marker_prefix_ambiguous_bounces():
    asks = (_ask("k3qp", started_at=1.0), _ask("k3rs", started_at=2.0))
    d = route_user_message("re k3 hi", asks, (), ("a", "b"))
    assert d == Bounce(AMBIGUOUS_TAG_BOUNCE)


def test_marker_prefix_no_match_falls_through_to_single_ask():
    asks = (_ask("k3qp"),)
    d = route_user_message("re zz never mind, do it", asks, (), ("confer/main",))
    # 'zz' matches no tag; with one ask pending the whole original content wins.
    assert d == DeliverAsk(tag="k3qp", content="re zz never mind, do it")


# ─── tag match: without marker, full tag required ──────────────────────────


def test_bare_full_tag_routes():
    asks = (_ask("k3qp", started_at=1.0), _ask("m4rs", started_at=2.0))
    d = route_user_message("k3qp answer is x", asks, (), ("a", "b"))
    assert d == DeliverAsk(tag="k3qp", content="answer is x")


def test_bare_prefix_without_marker_is_not_a_tag():
    asks = (_ask("k3qp", started_at=1.0), _ask("m4rs", started_at=2.0))
    # 'k3' bare (no marker) is NOT treated as a tag; two asks → ambiguous.
    d = route_user_message("k3 answer is x", asks, (), ("a", "b"))
    assert isinstance(d, Ambiguous)


# ─── notify-thread reply ───────────────────────────────────────────────────


def test_marker_routes_to_notify_thread():
    d = route_user_message(
        "re m4rs roll it back",
        (),
        (_notify("m4rs"),),
        ("confer/main",),
    )
    assert d == EnqueueNotifyReply(
        tag="m4rs", label="confer/main", content="roll it back"
    )


def test_bare_full_tag_routes_to_notify_thread():
    d = route_user_message(
        "m4rs roll it back", (), (_notify("m4rs"),), ("confer/main",)
    )
    assert d == EnqueueNotifyReply(
        tag="m4rs", label="confer/main", content="roll it back"
    )


def test_notify_threads_do_not_count_for_single_ask_shortcut():
    # One notify-thread, zero asks → a bare message broadcasts, not delivered
    # to the notify (notify is explicit-tag-only).
    d = route_user_message("everyone stop", (), (_notify("m4rs"),), ("confer/main",))
    assert d == Broadcast(content="everyone stop")


# ─── broadcast & ambiguity ─────────────────────────────────────────────────


def test_no_asks_with_connected_agents_broadcasts():
    d = route_user_message("stop, reqs changed", (), (), ("a", "b"))
    assert d == Broadcast(content="stop, reqs changed")


def test_two_asks_no_tag_is_ambiguous_newest_first():
    asks = (
        _ask("k3qp", started_at=1.0),
        _ask("m4rs", started_at=3.0),
        _ask("p7tv", started_at=2.0),
    )
    d = route_user_message("hello", asks, (), ("a", "b", "c"))
    assert isinstance(d, Ambiguous)
    assert [a.tag for a in d.asks] == ["m4rs", "p7tv", "k3qp"]


def test_tag_match_takes_precedence_over_single_ask_shortcut():
    # A bare full tag for a notify still routes to the notify even though one
    # ask is also pending (tag match is step 1, before the single-ask step).
    asks = (_ask("k3qp"),)
    d = route_user_message("m4rs roll back", asks, (_notify("m4rs"),), ("confer/main",))
    assert d == EnqueueNotifyReply(tag="m4rs", label="confer/main", content="roll back")


# ─── parser unit ───────────────────────────────────────────────────────────


def test_parse_marker_and_token_no_token():
    marker, token, rest = _parse_marker_and_token("!!!")
    assert token == ""


def test_parse_marker_plain_token_no_marker():
    marker, token, rest = _parse_marker_and_token("k3qp hello")
    assert marker is False
    assert token == "k3qp"
    assert rest == "hello"


def test_parse_marker_redeploy_is_not_marker():
    marker, token, rest = _parse_marker_and_token("redeploy now")
    assert marker is False
    assert token == "redeploy"


def test_empty_token_with_single_ask_delivers_full_content():
    # Leading punctuation produces an empty token; with one ask pending the
    # whole message is the reply (exercises the token-empty fall-through).
    d = route_user_message("(yes) do it", (_ask("k3qp"),), (), ("confer/main",))
    assert d == DeliverAsk(tag="k3qp", content="(yes) do it")
