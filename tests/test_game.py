import random

from big2.cards import THREE_OF_CLUBS
from big2.combos import all_combos
from big2.game import deal, find_starting_player, run_game
from big2.logging_util import GameLogger
from big2.rules import beats


class GreedyController:
    """Deterministic stub: always play the smallest legal combo it can,
    otherwise pass. Used to drive run_game() in tests without any network
    calls."""

    def __init__(self, name: str) -> None:
        self.name = name

    def choose_move(self, hand, required, is_leading, must_include_3c):
        candidates = all_combos(hand)
        if must_include_3c:
            candidates = [c for c in candidates if THREE_OF_CLUBS in c.cards]
        if not is_leading:
            candidates = [c for c in candidates if beats(c, required)]
        if not candidates:
            return None
        return min(candidates, key=lambda c: (c.size, c.strength))


def test_deal_counts():
    assert [len(h) for h in deal(4, random.Random(1))] == [13, 13, 13, 13]
    assert [len(h) for h in deal(3, random.Random(1))] == [17, 17, 17]
    assert [len(h) for h in deal(2, random.Random(1))] == [26, 26]


def test_deal_always_keeps_three_of_clubs_in_play():
    for seed in range(50):
        hands = deal(3, random.Random(seed))
        assert find_starting_player(hands) is not None


def test_game_runs_to_completion(tmp_path):
    hands = deal(4, random.Random(42))
    controllers = [GreedyController(f"P{i}") for i in range(4)]
    logger = GameLogger(log_dir=tmp_path)
    result = run_game(hands, controllers, logger)
    assert result.winner_seat in range(4)
    assert logger.path.exists()
