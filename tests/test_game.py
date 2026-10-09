"""Exercise real game turns and AI request context without live model calls."""

import json
import random
from unittest.mock import Mock

import pytest

from big2.ai_decision import DecisionError
from big2.cards import THREE_OF_CLUBS, Card, Rank, Suit
from big2.combos import all_combos
from big2.game import MAX_DECISION_RETRIES, AIController, GameEngine, deal, find_starting_player, run_ai_batch, run_game
from big2.logging_util import GameLogger
from big2.rules import beats, classify


class GreedyController:
    """Deterministic stub: always play the smallest legal combo it can,
    otherwise pass. Used to drive run_game() in tests without any network
    calls."""

    def __init__(self, name: str) -> None:
        self.name = name

    def choose_move(self, hand, required, is_leading, must_include_3c, context=None):
        """Return the smallest legal move from hand; ignore optional public context."""
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


def test_cli_ai_receives_public_context(monkeypatch, tmp_path):
    """The CLI loop supplies opening and subsequent public facts to the model."""
    logger = GameLogger(tmp_path)
    hands = [[THREE_OF_CLUBS, Card(Rank.FIVE, Suit.CLUB)], [Card(Rank.FOUR, Suit.CLUB)]]
    request = Mock(side_effect=["opt_0", "opt_0"])
    monkeypatch.setattr("big2.game.request_choice", request)
    result = run_game(hands, [AIController("P0", logger), AIController("P1", logger)], logger)
    assert result.winner_seat == 1
    opening = request.call_args_list[0].args[0]
    following = request.call_args_list[1].args[0]
    assert "Your seat: 0 (P0)" in opening
    assert "Seat order: 0=P0 -> 1=P1" in opening
    assert "Remaining cards: P0=2, P1=1" in opening
    assert "Last player to play: none" in opening
    assert "History: no turns yet" in opening
    assert "Your hand (2 cards): 3♣ 5♣" in opening
    assert "4♣" not in opening
    assert "1. P0 played SINGLE (3♣)" in following
    assert "Remaining cards: P0=1, P1=1" in following
    assert "Last player to play: 0 (P0)" in following
    assert "5♣" not in following


def test_history_survives_trick_reset_and_snapshot_is_independent(tmp_path):
    """Public snapshots stay immutable across passes, winning turns and new games."""
    hands = [[THREE_OF_CLUBS, Card(Rank.FIVE, Suit.CLUB)], [Card(Rank.FOUR, Suit.CLUB)]]
    engine = GameEngine(hands, ["P0", "P1"], GameLogger(tmp_path))
    opening = engine.turn_context()
    first = engine.apply(classify([THREE_OF_CLUBS]))
    after_play = engine.turn_context()
    passed = engine.apply(None)
    reset = engine.turn_context()
    assert engine.is_leading
    assert reset.last_play_seat == 0
    assert reset.current_seat == 0
    assert reset.remaining == (1, 1)
    assert reset.history == ("P0 played SINGLE (3♣)", "P1 passed")
    assert opening.history == ()
    assert opening.remaining == (2, 1)
    assert opening.last_play_seat is None
    assert after_play.history == ("P0 played SINGLE (3♣)",)
    engine.apply(classify([Card(Rank.FIVE, Suit.CLUB)]))
    assert engine.finished
    assert len(engine.history) == 3
    assert engine.history[:2] == [first, passed]
    assert first.remaining == {"P0": 1, "P1": 1}
    fresh = GameEngine(hands, ["P0", "P1"], GameLogger(tmp_path))
    assert fresh.history == []


def test_batch_context_includes_human_turns_and_previous_batches(monkeypatch, tmp_path):
    """The web batch loop retains human and AI history while stopping at humans."""
    logger = GameLogger(tmp_path)
    five = Card(Rank.FIVE, Suit.CLUB)
    engine = GameEngine([[THREE_OF_CLUBS, five, Card(Rank.SEVEN, Suit.CLUB)],
                         [Card(Rank.FOUR, Suit.CLUB), Card(Rank.ACE, Suit.SPADE)]], ["Human", "AI"], logger)
    controllers = [GreedyController("Human"), AIController("AI", logger)]
    request = Mock(side_effect=["pass", "pass"])
    monkeypatch.setattr("big2.game.request_choice", request)
    engine.apply(classify([THREE_OF_CLUBS]))
    first_batch = run_ai_batch(engine, controllers, [True, False])
    engine.apply(classify([five]))
    second_batch = run_ai_batch(engine, controllers, [True, False])
    state = request.call_args_list[1].args[0]
    assert len(first_batch) == len(second_batch) == 1
    assert engine.current == 0
    assert request.call_count == 2
    assert "1. Human played SINGLE (3♣)\n2. AI passed\n3. Human played SINGLE (5♣)" in state
    assert "Remaining cards: Human=1, AI=2" in state
    assert "Your seat: 1 (AI)" in state
    assert "Your hand (2 cards): 4♣ A♠" in state
    assert "7♣" not in state
    assert "Last player to play: 0 (Human)" in state


def test_personalities_change_guidance_only(monkeypatch, tmp_path):
    """All personalities receive identical candidates and decide strategy themselves."""
    logger = GameLogger(tmp_path)
    hand = [THREE_OF_CLUBS, Card(Rank.FOUR, Suit.CLUB)]
    request = Mock(return_value="opt_0")
    monkeypatch.setattr("big2.game.request_choice", request)
    AIController("AI", logger).choose_move(hand, None, True, False)
    AIController("AI", logger, "conservative").choose_move(hand, None, True, False)
    AIController("AI", logger, "aggressive").choose_move(hand, None, True, False)
    balanced, conservative, aggressive = request.call_args_list
    assert "Personality: balanced. Balance preserving" in balanced.args[0]
    assert "Personality: conservative. Prefer preserving" in conservative.args[0]
    assert "Personality: aggressive. Be more willing" in aggressive.args[0]
    assert balanced.args[1] == conservative.args[1] == aggressive.args[1]
    assert "Judge for yourself" in balanced.args[0]
    assert "A pass does not prove" in balanced.args[0]
    assert "A plain flush is invalid; 2 cannot be in a straight" in balanced.args[0]


def test_unknown_personality_is_rejected(tmp_path):
    """Invalid local settings fail before model calls."""
    with pytest.raises(ValueError, match="unknown AI personality"):
        AIController("AI", GameLogger(tmp_path), "unknown")


def test_illegal_choice_retries_with_same_context(monkeypatch, tmp_path):
    """Unbeatable options remain available, with feedback added after rejection."""
    logger = GameLogger(tmp_path)
    engine = GameEngine([[THREE_OF_CLUBS, Card(Rank.FOUR, Suit.CLUB), Card(Rank.SEVEN, Suit.CLUB)],
                         [Card(Rank.THREE, Suit.DIAMOND), Card(Rank.FIVE, Suit.CLUB)]], ["P0", "P1"], logger)
    engine.apply(classify([THREE_OF_CLUBS]))
    engine.apply(classify([Card(Rank.FIVE, Suit.CLUB)]))
    request = Mock(side_effect=["opt_0", "opt_1"])
    monkeypatch.setattr("big2.game.request_choice", request)
    chosen = AIController("P0", logger).choose_move(engine.hand, engine.required, False, False, engine.turn_context())
    assert chosen == classify([Card(Rank.SEVEN, Suit.CLUB)])
    assert request.call_count == 2
    first, retry = request.call_args_list
    assert first.args[1]["opt_0"] == "SINGLE (4♣)"
    assert retry.args[0].startswith(first.args[0])
    assert "does not beat" in retry.args[0]
    assert first.args[1] == retry.args[1]


def test_illegal_choice_can_retry_to_pass(monkeypatch, tmp_path):
    """A rejected low single can be followed by an accepted pass."""
    logger = GameLogger(tmp_path)
    request = Mock(side_effect=["opt_0", "pass"])
    monkeypatch.setattr("big2.game.request_choice", request)
    result = AIController("AI", logger).choose_move([THREE_OF_CLUBS], classify([Card(Rank.FIVE, Suit.CLUB)]), False, False)
    assert result is None
    assert request.call_count == 2
    assert "does not beat" in request.call_args.args[0]


def test_following_falls_back_to_pass_after_errors(monkeypatch, tmp_path):
    """Five external failures exhaust retries and pass when following."""
    logger = GameLogger(tmp_path)
    request = Mock(side_effect=DecisionError("unavailable"))
    monkeypatch.setattr("big2.game.request_choice", request)
    result = AIController("AI", logger).choose_move([THREE_OF_CLUBS], classify([Card(Rank.FIVE, Suit.CLUB)]), False, False)
    assert result is None
    assert request.call_count == MAX_DECISION_RETRIES
    records = [json.loads(line) for line in logger.path.read_text().splitlines()]
    assert records[-1]["event"] == "ai_retries_exhausted"


def test_opening_falls_back_to_three_of_clubs_after_errors(monkeypatch, tmp_path):
    """An opening seat must still play 3♣ after five model failures."""
    logger = GameLogger(tmp_path)
    request = Mock(side_effect=DecisionError("unavailable"))
    monkeypatch.setattr("big2.game.request_choice", request)
    result = AIController("AI", logger).choose_move([Card(Rank.FIVE, Suit.CLUB), THREE_OF_CLUBS], None, True, True)
    assert result == classify([THREE_OF_CLUBS])
    assert request.call_count == MAX_DECISION_RETRIES
    records = [json.loads(line) for line in logger.path.read_text().splitlines()]
    assert records[-1]["event"] == "ai_retries_exhausted"


def test_leading_falls_back_to_smallest_single_after_errors(monkeypatch, tmp_path):
    """A later leader falls back to its smallest single without an opening restriction."""
    logger = GameLogger(tmp_path)
    request = Mock(side_effect=DecisionError("unavailable"))
    monkeypatch.setattr("big2.game.request_choice", request)
    four = Card(Rank.FOUR, Suit.CLUB)
    result = AIController("AI", logger).choose_move([Card(Rank.FIVE, Suit.CLUB), four], None, True, False)
    assert result == classify([four])
    assert request.call_count == MAX_DECISION_RETRIES


def test_exhausted_retries_and_summary_are_logged(monkeypatch, tmp_path):
    """Ten illegal picks log the fallback, and the winning play writes call totals."""
    logger = GameLogger(tmp_path)
    engine = GameEngine([[THREE_OF_CLUBS, Card(Rank.FOUR, Suit.CLUB)],
                         [Card(Rank.THREE, Suit.DIAMOND), Card(Rank.FIVE, Suit.CLUB)]], ["P0", "P1"], logger)
    engine.apply(classify([THREE_OF_CLUBS]))
    engine.apply(classify([Card(Rank.FIVE, Suit.CLUB)]))
    monkeypatch.setattr("big2.game.request_choice", Mock(return_value="opt_0"))
    assert AIController("P0", logger).choose_move(engine.hand, engine.required, False, False, engine.turn_context()) is None
    engine.apply(None)  # P0 passes after the failed turn; P1 plays out to win
    engine.apply(classify([Card(Rank.THREE, Suit.DIAMOND)]))
    records = [json.loads(line) for line in logger.path.read_text(encoding="utf-8").splitlines()]
    exhausted = next(r for r in records if r["event"] == "ai_retries_exhausted")
    assert exhausted["attempts"] == 10 and exhausted["fallback"] == "pass"
    summary = records[-1]
    assert summary == {**summary, "event": "ai_stats", "calls": 10, "failed_calls": 10,
                       "request_errors": 0, "illegal_choices": 10, "turns_exhausted": 1}
