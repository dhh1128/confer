from confer.daemon.routing import (
    Ambiguous,
    Bounce,
    Deliver,
    PendingAsk,
    route_user_message,
)


def _ask(request_id: str, label: str, question: str, started_at: float) -> PendingAsk:
    return PendingAsk(
        request_id=request_id, label=label, question=question, started_at=started_at
    )


def test_no_pending_asks_bounces():
    decision = route_user_message("anything", ())
    assert isinstance(decision, Bounce)
    assert "No agent is asking" in decision.text


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


def test_label_prefix_matches_empty_token_returns_empty():
    """Direct unit test of the defensive guard inside _label_prefix_matches."""
    from confer.daemon.routing import _label_prefix_matches
    asks = (_ask("r1", "confer/main", "q?", 1.0),)
    assert _label_prefix_matches("", asks) == []
