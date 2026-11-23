from game_docs import visible


def test_moderation_queue_is_excluded_from_public_answer_candidates():
    matches = [
        {"metadata": {"kind": "moderation_queue", "text": "Private report"}},
        {"metadata": {"kind": "live_event", "text": "Weekend tournament"}},
    ]
    assert visible(matches, False) == [matches[1]]
    assert visible(matches, True) == matches
