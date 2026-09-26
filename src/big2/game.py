"""Game state machine and the two seat controllers (human / jev-backed AI).

`run_game` only knows about the `Controller` protocol below — each
controller is responsible for returning an already-legal move (or None for
a pass), retrying internally however makes sense for that seat type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .ai_jev import JevError, request_choice
from .cards import THREE_OF_CLUBS, Card, shuffled_deck
from .combos import all_combos
from .logging_util import GameLogger
from .rules import Combo, HandType, beats, classify

MAX_JEV_RETRIES = 5


def deal(num_players: int, rng=None) -> list[list[Card]]:
    if num_players not in (2, 3, 4):
        raise ValueError("num_players must be 2, 3, or 4")

    deck = shuffled_deck(rng)

    if num_players == 3:
        # 17 cards each, 1 card removed — but never the 3♣, or nobody
        # could legally make the game's opening play.
        idx = deck.index(THREE_OF_CLUBS)
        if idx == 51:
            deck[0], deck[51] = deck[51], deck[0]
        deck = deck[:51]

    per_player = len(deck) // num_players
    return [deck[i * per_player:(i + 1) * per_player] for i in range(num_players)]


def find_starting_player(hands: list[list[Card]]) -> int:
    for i, hand in enumerate(hands):
        if THREE_OF_CLUBS in hand:
            return i
    raise ValueError("3♣ is missing from the deal")


class Controller(Protocol):
    def choose_move(
        self, hand: list[Card], required: Combo | None, is_leading: bool, must_include_3c: bool
    ) -> Combo | None:
        ...


@dataclass
class HumanController:
    name: str
    prompt: Callable[[str], str] = input  # overridable for testing

    def choose_move(self, hand, required, is_leading, must_include_3c):
        sorted_hand = sorted(hand)
        while True:
            _render_hand(sorted_hand)
            if is_leading:
                print(f"{self.name}，輪到你自由出牌" + ("（第一手必須包含梅花3）" if must_include_3c else "") + "：")
            else:
                print(f"{self.name}，目前要壓過：{_describe_combo(required)}（輸入空白或 p 過牌）：")
            raw = self.prompt("> ").strip().lower()

            if raw in ("", "p", "pass") :
                if is_leading:
                    print("這一輪你必須出牌，不能過牌。")
                    continue
                return None

            try:
                indices = [int(tok) for tok in raw.split()]
                cards = [sorted_hand[i - 1] for i in indices]
            except (ValueError, IndexError):
                print("輸入無效，請輸入手牌編號（例如：1 3 5）。")
                continue

            combo = classify(cards)
            if combo is None:
                print("這不是合法的牌型（單張/對子/三條/五張牌型）。")
                continue
            if must_include_3c and THREE_OF_CLUBS not in combo.cards:
                print("第一手必須包含梅花3。")
                continue
            if not is_leading and not beats(combo, required):
                print(f"這手牌壓不過 {_describe_combo(required)}。")
                continue
            return combo


@dataclass
class AIController:
    name: str
    logger: GameLogger

    def choose_move(self, hand, required, is_leading, must_include_3c):
        candidates = all_combos(hand)
        if must_include_3c:
            candidates = [c for c in candidates if THREE_OF_CLUBS in c.cards]

        options = {f"opt_{i}": _describe_combo(c) for i, c in enumerate(candidates)}
        lookup = {f"opt_{i}": c for i, c in enumerate(candidates)}
        if not is_leading:
            options["pass"] = "Pass — play no cards this turn"

        state = _describe_state(self.name, hand, required, is_leading, must_include_3c)
        feedback = ""

        for attempt in range(1, MAX_JEV_RETRIES + 1):
            try:
                choice_key = request_choice(state + feedback, options)
            except JevError as exc:
                self.logger.log({
                    "event": "ai_call_error", "player": self.name, "attempt": attempt, "error": str(exc),
                })
                feedback = f"\n\n(Attempt {attempt} failed: {exc}. Reply with exactly one of the given option keys.)"
                continue

            if choice_key == "pass":
                self.logger.log({
                    "event": "ai_call", "player": self.name, "attempt": attempt,
                    "options": options, "choice": choice_key, "accepted": True,
                })
                return None

            combo = lookup[choice_key]
            legal = is_leading or beats(combo, required)
            self.logger.log({
                "event": "ai_call", "player": self.name, "attempt": attempt,
                "options": options, "choice": choice_key, "accepted": legal,
            })
            if legal:
                return combo

            feedback = (
                f"\n\n(Attempt {attempt}: you chose {options[choice_key]!r}, which does not beat the "
                f"current required combo {_describe_combo(required)}. Choose a different option, or 'pass'.)"
            )

        self.logger.log({"event": "ai_retries_exhausted", "player": self.name})
        if not is_leading:
            return None
        singles = [c for c in candidates if c.type == HandType.SINGLE]
        return min(singles, key=lambda combo: combo.strength)


def _print_remaining_counts(controllers: list[Controller], hands: list[list[Card]]) -> None:
    parts = [f"{controller.name}={len(hand)}" for controller, hand in zip(controllers, hands)]
    print("剩餘張數：" + " ".join(parts))


def _render_hand(sorted_hand: list[Card]) -> None:
    labels = [f"[{i + 1}]{card}" for i, card in enumerate(sorted_hand)]
    print(" ".join(labels))


def _describe_combo(combo: Combo) -> str:
    cards = " ".join(str(c) for c in combo.cards)
    return f"{combo.type.name} ({cards})"


def _describe_state(name: str, hand: list[Card], required: Combo | None, is_leading: bool, must_include_3c: bool) -> str:
    hand_str = " ".join(str(c) for c in sorted(hand))
    lines = [
        "You are playing 大老二 (Taiwanese Big Two).",
        f"Your hand ({len(hand)} cards): {hand_str}",
    ]
    if is_leading:
        lines.append("You are leading this trick: you may play any combo from the options.")
        if must_include_3c:
            lines.append("This is the game's opening play: your combo must include 3♣.")
    else:
        lines.append(f"You must beat the current combo: {_describe_combo(required)}, or choose 'pass'.")
    return "\n".join(lines)


@dataclass
class GameResult:
    winner_seat: int
    winner_name: str


def run_game(hands: list[list[Card]], controllers: list[Controller], logger: GameLogger) -> GameResult:
    n = len(hands)
    hands = [list(h) for h in hands]
    current = leader = find_starting_player(hands)
    required: Combo | None = None
    passes_in_a_row = 0
    must_include_3c = True

    while True:
        hand = hands[current]
        is_leading = required is None
        move = controllers[current].choose_move(hand, required, is_leading, must_include_3c and is_leading)

        if move is None:
            print(f"{controllers[current].name} 過牌")
            logger.log({"event": "pass", "player": controllers[current].name})
            _print_remaining_counts(controllers, hands)
            passes_in_a_row += 1
            current = (current + 1) % n
            if passes_in_a_row == n - 1:
                current = leader
                required = None
                passes_in_a_row = 0
            continue

        for card in move.cards:
            hand.remove(card)
        print(f"{controllers[current].name} 出牌：{_describe_combo(move)}")
        logger.log({"event": "play", "player": controllers[current].name, "combo": _describe_combo(move)})
        _print_remaining_counts(controllers, hands)
        must_include_3c = False
        required = move
        leader = current
        passes_in_a_row = 0

        if not hand:
            return GameResult(winner_seat=current, winner_name=controllers[current].name)

        current = (current + 1) % n
