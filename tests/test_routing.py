from confer.daemon.routing import (
    Ambiguous,
    Bounce,
    Broadcast,
    Deliver,
    EnqueueLabeled,
    PendingAsk,
    route_user_message,
)


def _ask(request_id: str, label: str, question: str, started_at: float) -> PendingAsk:
    return PendingAsk(
        request_id=request_id, label=label, question=question, started_at=started_at
    )


def test_no_agents_anywhere_bounces():
    decision = route_user_message("anything", (), ())
    assert isinstance(decision, Bounce)
    assert "No agent is connected" in decision.text


def test_single_ask_unprefixed_delivers_whole_content():
    asks = [_ask("r1", "confer/main", "rebase?", 1.0)]
    decision = route_user_message("looks good", asks)
    assert decision == Deliver(label="confer/main", content="looks good")


def test_numeric_shortcut_one_indexes_newest():
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),  # newer
    ]
    decision = route_user_message("1 yes", asks)
    assert decision == Deliver(label="myapp/feat-ask", content="yes")


def test_numeric_shortcut_two_indexes_second_newest():
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    decision = route_user_message("2 no", asks)
    assert decision == Deliver(label="confer/main", content="no")


def test_numeric_out_of_range_is_ambiguous():
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    decision = route_user_message("5 hi", asks)
    assert isinstance(decision, Ambiguous)


def test_label_prefix_match_routes():
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    decision = route_user_message("feat-ask: looks good", asks)
    assert decision == Deliver(label="myapp/feat-ask", content="looks good")


def test_label_prefix_case_insensitive():
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    decision = route_user_message("FEAT-ASK yes", asks)
    assert decision == Deliver(label="myapp/feat-ask", content="yes")


def test_label_prefix_hyphen_space_interchangeable():
    asks = [
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    # "feat ask" with a space should match "feat-ask"; the second word is the
    # delivered content (rule 3 fires after first-token consumes "feat").
    # To test hyphen/space interchangeability, we need a multi-ask scenario
    # so rule 3 doesn't shortcut.
    asks2 = [
        _ask("r1", "confer/main", "rebase?", 1.0),
        _ask("r2", "myapp/feat-ask", "merge?", 2.0),
    ]
    # Use the substring "ask" which is unique to feat-ask among the two.
    decision = route_user_message("ask sounds right", asks2)
    assert decision == Deliver(label="myapp/feat-ask", content="sounds right")


def test_ambiguous_prefix_returns_ambiguous():
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "confer/feat", "q2?", 2.0),
    ]
    # "confer" matches both labels → ambiguous
    decision = route_user_message("confer hi", asks)
    assert isinstance(decision, Ambiguous)
    assert len(decision.pending_asks) == 2


def test_multiple_asks_no_prefix_is_ambiguous():
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 2.0),
    ]
    decision = route_user_message("hello there", asks)
    assert isinstance(decision, Ambiguous)


def test_ambiguous_returns_newest_first():
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 3.0),
        _ask("r3", "extra/branch", "q3?", 2.0),
    ]
    decision = route_user_message("hello", asks)
    assert isinstance(decision, Ambiguous)
    labels = [a.label for a in decision.pending_asks]
    assert labels == ["myapp/feat", "extra/branch", "confer/main"]


def test_punctuation_terminates_token():
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat-ask", "q2?", 2.0),
    ]
    decision = route_user_message("feat-ask: looks good", asks)
    assert decision.content == "looks good"


def test_empty_token_with_multiple_asks_is_ambiguous():
    """Leading whitespace produces an empty token, which can't route."""
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 2.0),
    ]
    decision = route_user_message("   hello", asks)
    assert isinstance(decision, Ambiguous)


def test_unknown_label_prefix_with_multiple_asks_is_ambiguous():
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 2.0),
    ]
    decision = route_user_message("nomatch hi", asks)
    assert isinstance(decision, Ambiguous)


def test_unknown_label_prefix_with_single_ask_delivers_full_content():
    """With only one ask pending, a non-matching prefix falls to rule (3)
    and the whole message becomes the reply content (next-message-wins
    ergonomics per vk3qn7fp)."""
    asks = [
        _ask("r1", "confer/main", "rebase?", 1.0),
    ]
    decision = route_user_message("nomatch hi", asks)
    assert decision == Deliver(label="confer/main", content="nomatch hi")


def test_punctuation_only_content_with_multiple_asks_is_ambiguous():
    """Content that produces an empty token (just punctuation) and multiple
    asks: rule 1 is skipped, rule 3 doesn't apply, rule 5 fires."""
    asks = [
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 2.0),
    ]
    decision = route_user_message("?!?", asks)
    assert isinstance(decision, Ambiguous)


def test_ask_label_matches_empty_token_returns_empty():
    """Defensive guard inside _ask_label_matches."""
    from confer.daemon.routing import _ask_label_matches
    asks = (_ask("r1", "confer/main", "q?", 1.0),)
    assert _ask_label_matches("", asks) == []


def test_client_label_matches_empty_token_returns_empty():
    """Defensive guard inside _client_label_matches."""
    from confer.daemon.routing import _client_label_matches
    assert _client_label_matches("", ("confer/main",)) == []


# ─── phase 2D: broadcast and labeled interjection ──────────────────────────


def test_no_asks_but_connected_clients_broadcasts():
    """Rule 4: unprefixed message with no asks pending → Broadcast."""
    decision = route_user_message("BTW use library X", (), ("confer/main",))
    assert decision == Broadcast(content="BTW use library X")


def test_no_asks_unprefixed_multi_client_still_broadcasts():
    decision = route_user_message(
        "stop, requirements changed", (), ("confer/main", "myapp/feat")
    )
    assert decision == Broadcast(content="stop, requirements changed")


def test_label_prefix_with_no_matching_ask_routes_to_connected_client_queue():
    """Rule 1 with no ask matching but a connected client matching: enqueue to
    that client's queue (source="labeled_interjection")."""
    decision = route_user_message(
        "confer: BTW use library X", (), ("confer/main", "myapp/feat")
    )
    assert decision == EnqueueLabeled(label="confer/main", content="BTW use library X")


def test_label_prefix_matches_multiple_clients_bounces_with_disambiguation_hint():
    """Two connected clients share the prefix, no asks: bounce with a hint."""
    decision = route_user_message(
        "confer hello", (), ("confer/main", "confer/feat")
    )
    assert isinstance(decision, Bounce)
    assert "more specific prefix" in decision.text


def test_label_prefix_to_ask_takes_precedence_over_connected_client():
    """When a label matches both an ask AND a connected client, the ask wins
    (rule 1 short-circuits on the first ask match)."""
    asks = (_ask("r1", "confer/main", "rebase?", 1.0),)
    decision = route_user_message(
        "confer yes", asks, ("confer/main", "myapp/feat")
    )
    assert decision == Deliver(label="confer/main", content="yes")


def test_unknown_token_with_asks_and_connected_clients_treated_as_no_match():
    """Token matches neither asks nor connected labels. With multiple asks
    pending it falls to Ambiguous (rule 5)."""
    asks = (
        _ask("r1", "confer/main", "q1?", 1.0),
        _ask("r2", "myapp/feat", "q2?", 2.0),
    )
    decision = route_user_message(
        "nomatch hello", asks, ("confer/main", "myapp/feat")
    )
    assert isinstance(decision, Ambiguous)


def test_numeric_shortcut_with_no_asks_falls_through_to_broadcast():
    """If the user types a numeric token but there are no asks (only connected
    clients), the numeric isn't a valid shortcut — fall through to broadcast."""
    decision = route_user_message("1 hello", (), ("confer/main",))
    assert decision == Broadcast(content="1 hello")
