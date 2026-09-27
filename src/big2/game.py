"""Game state machine and the two seat controllers (human / jev-backed AI).

`run_game` only knows about the `Controller` protocol below — each
controller is responsible for returning an already-legal move (or None for
a pass), retrying internally however makes sense for that seat type.

`GameEngine` is the seat-agnostic turn state machine underneath `run_game`
(whose turn it is, what beats what, when a round of passes wraps back to
the leader, when someone's hand runs out). The CLI's `run_game` blocks on
`Controller.choose_move` for every seat including humans; the web server
(`web.py`) instead calls `run_ai_batch` to advance only the AI seats and
supplies the human seat's move separately from an HTTP request via
`validate_move` + `GameEngine.apply`.
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


class IllegalMoveError(ValueError):
    """Raised by `validate_move` when a proposed human move isn't legal
    given the engine's current trick. The message is Chinese and meant to
    be shown directly to the player."""


@dataclass
class TurnEvent:
    """One applied turn, as returned by `GameEngine.apply`. `combo` is None
    for a pass. `remaining` maps seat name -> card count, in seat order,
    snapshotted right after this turn."""
    player_name: str
    kind: str  # "play" or "pass"
    combo: Combo | None
    remaining: dict[str, int]


class GameEngine:
    """Mutable per-trick state for one game: whose turn it is, what the
    current trick requires, and the "3♣ must open, a round of passes
    returns control to the last player who played" rules. `apply()` is the
    only mutator — it takes an already-legal move for the current seat and
    returns a `TurnEvent` describing what happened."""

    def __init__(self, hands: list[list[Card]], names: list[str], logger: GameLogger) -> None:
        self.hands = [list(h) for h in hands]
        self.names = names
        self.logger = logger
        self.n = len(hands)
        self.current = self.leader = find_starting_player(self.hands)
        self.required: Combo | None = None
        self.passes_in_a_row = 0
        self.must_include_3c = True
        self.winner_seat: int | None = None

    @property
    def is_leading(self) -> bool:
        return self.required is None

    @property
    def finished(self) -> bool:
        return self.winner_seat is not None

    @property
    def hand(self) -> list[Card]:
        return self.hands[self.current]

    def apply(self, move: Combo | None) -> TurnEvent:
        seat = self.current
        name = self.names[seat]

        if move is None:
            self.passes_in_a_row += 1
            self.logger.log({"event": "pass", "player": name})
            event = TurnEvent(name, "pass", None, self._remaining())
            # A full round of passes (everyone but the last player who
            # played) hands control back to that player with a clean slate.
            self.current = (self.current + 1) % self.n
            if self.passes_in_a_row == self.n - 1:
                self.current = self.leader
                self.required = None
                self.passes_in_a_row = 0
            return event

        for card in move.cards:
            self.hands[seat].remove(card)
        self.must_include_3c = False
        self.required = move
        self.leader = seat
        self.passes_in_a_row = 0
        self.logger.log({"event": "play", "player": name, "combo": _describe_combo(move)})
        event = TurnEvent(name, "play", move, self._remaining())

        if not self.hands[seat]:
            self.winner_seat = seat
        else:
            self.current = (self.current + 1) % self.n
        return event

    def _remaining(self) -> dict[str, int]:
        return {self.names[i]: len(self.hands[i]) for i in range(self.n)}


def validate_move(engine: GameEngine, cards: list[Card] | None) -> Combo | None:
    """Validate a human-submitted move against `engine`'s current trick.
    `cards` empty/None means "pass". Raises `IllegalMoveError` (message
    safe to show the player) on failure; never mutates the engine — mirrors
    the checks `HumanController.choose_move` does inline for the CLI."""
    if not cards:
        if engine.is_leading:
            raise IllegalMoveError("這一輪你必須出牌，不能過牌。")
        return None

    combo = classify(cards)
    if combo is None:
        raise IllegalMoveError("這不是合法的牌型（單張/對子/三條/五張牌型）。")
    if engine.must_include_3c and engine.is_leading and THREE_OF_CLUBS not in combo.cards:
        raise IllegalMoveError("第一手必須包含梅花3。")
    if not engine.is_leading and not beats(combo, engine.required):
        raise IllegalMoveError(f"這手牌壓不過 {_describe_combo(engine.required)}。")
    return combo


def run_ai_batch(engine: GameEngine, controllers: list[Controller], is_human: list[bool]) -> list[TurnEvent]:
    """Advance `engine` through consecutive AI-seat turns until it's a
    human seat's turn or the game ends. Used by the web server, which gets
    the human seat's move from an HTTP request instead of a blocking
    `Controller.choose_move` call. With no human seats at all, this plays
    the entire game out in one call."""
    events: list[TurnEvent] = []
    while not engine.finished and not is_human[engine.current]:
        controller = controllers[engine.current]
        move = controller.choose_move(
            engine.hand, engine.required, engine.is_leading, engine.must_include_3c and engine.is_leading
        )
        events.append(engine.apply(move))
    return events


def run_game(hands: list[list[Card]], controllers: list[Controller], logger: GameLogger) -> GameResult:
    names = [c.name for c in controllers]
    engine = GameEngine(hands, names, logger)

    while True:
        controller = controllers[engine.current]
        move = controller.choose_move(
            engine.hand, engine.required, engine.is_leading, engine.must_include_3c and engine.is_leading
        )
        event = engine.apply(move)

        if event.kind == "pass":
            print(f"{event.player_name} 過牌")
        else:
            print(f"{event.player_name} 出牌：{_describe_combo(event.combo)}")
        print("剩餘張數：" + " ".join(f"{n}={c}" for n, c in event.remaining.items()))

        if engine.finished:
            return GameResult(winner_seat=engine.winner_seat, winner_name=names[engine.winner_seat])
