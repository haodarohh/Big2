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

MAX_JEV_RETRIES = 10

PERSONALITIES = {
    "balanced": "Balance preserving strong combinations, gaining control, and making progress toward emptying your hand.",
    "conservative": "Prefer preserving strong cards and combinations; avoid unnecessary contests and pass when saving control cards is more useful.",
    "aggressive": "Be more willing to spend strong cards to gain control and accelerate emptying your hand.",
}


@dataclass(frozen=True)
class TurnContext:
    """Public facts before a decision, with no hidden hands or mutable references.

    Seat names and remaining counts share seat order; current_seat identifies
    the choosing player. last_play_seat is None before the first play.
    History contains chronological descriptions of completed public turns.
    Constructing a snapshot has no side effects.
    """
    seat_names: tuple[str, ...]
    remaining: tuple[int, ...]
    current_seat: int
    last_play_seat: int | None
    history: tuple[str, ...]


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
    """Seat controller contract: choose a legal move from private and public facts."""

    def choose_move(
        self, hand: list[Card], required: Combo | None, is_leading: bool, must_include_3c: bool,
        context: TurnContext | None = None,
    ) -> Combo | None:
        """Return a legal combo or pass for hand and trick constraints.

        context is an optional public snapshot; implementations may prompt a
        human or call a model but must not mutate the supplied hand.
        """
        ...


@dataclass
class HumanController:
    """Human seat named name; prompt supplies input and choose_move prints feedback."""
    name: str
    prompt: Callable[[str], str] = input  # overridable for testing

    def choose_move(self, hand, required, is_leading, must_include_3c, context=None):
        """Prompt until hand/trick constraints yield a legal combo or pass.

        context is accepted for the shared contract but unused. Prints the
        hand and validation feedback without changing the supplied cards.
        """
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
    """Model-backed seat with name, decision logger and configurable personality.

    personality selects prompt guidance only; legal checks remain unchanged.
    """
    name: str
    logger: GameLogger
    personality: str = "balanced"

    def __post_init__(self) -> None:
        """Reject unknown personality settings before any external call occurs."""
        if self.personality not in PERSONALITIES:
            raise ValueError(f"unknown AI personality: {self.personality!r}")

    def choose_move(self, hand, required, is_leading, must_include_3c, context=None):
        """Return a validated combo or pass using hand, trick and public context.

        Calls the model and writes decision logs, retrying up to MAX_JEV_RETRIES times;
        exhaustion passes or leads the smallest permitted single. Does not
        change hand or context or compute strategic option scores.
        """
        candidates = all_combos(hand)
        if must_include_3c:
            candidates = [c for c in candidates if THREE_OF_CLUBS in c.cards]

        options = {f"opt_{i}": _describe_combo(c) for i, c in enumerate(candidates)}
        lookup = {f"opt_{i}": c for i, c in enumerate(candidates)}
        if not is_leading:
            options["pass"] = "Pass — play no cards this turn"

        state = _describe_state(
            self.name, hand, required, is_leading, must_include_3c, context, self.personality
        )
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

        # Record what the fallback is so a failed turn is visible in the log,
        # not just that retries ran out.
        if is_leading:
            singles = [c for c in candidates if c.type == HandType.SINGLE]
            fallback_combo = min(singles, key=lambda combo: combo.strength)
            fallback = f"lead smallest single {_describe_combo(fallback_combo)}"
        else:
            fallback_combo = None
            fallback = "pass"
        self.logger.log({
            "event": "ai_retries_exhausted", "player": self.name,
            "attempts": MAX_JEV_RETRIES, "fallback": fallback,
        })
        return fallback_combo


def _render_hand(sorted_hand: list[Card]) -> None:
    labels = [f"[{i + 1}]{card}" for i, card in enumerate(sorted_hand)]
    print(" ".join(labels))


def _describe_combo(combo: Combo) -> str:
    cards = " ".join(str(c) for c in combo.cards)
    return f"{combo.type.name} ({cards})"


def _describe_state(
    name: str, hand: list[Card], required: Combo | None, is_leading: bool, must_include_3c: bool,
    context: TurnContext | None = None, personality: str = "balanced",
) -> str:
    """Render private hand and public facts with strategy guidance, without scoring moves."""
    hand_str = " ".join(str(c) for c in sorted(hand))
    lines = [
        "You are playing 大老二 (Taiwanese Big Two).",
        f"You are {name}.",
        f"Your hand ({len(hand)} cards): {hand_str}",
        "Rules: ranks ascend 3,4,5,6,7,8,9,10,J,Q,K,A,2; suits ascend clubs,diamonds,hearts,spades. "
        "Only equal card counts can beat one another. Five-card categories ascend straight,full house,four-of-a-kind,straight flush. "
        "A plain flush is invalid; 2 cannot be in a straight.",
        f"Personality: {personality}. {PERSONALITIES[personality]}",
        "Your goal is to empty your hand first. Judge for yourself how each move affects your remaining hand, "
        "including whether it breaks strong combinations. Use public history and opponents' remaining counts "
        "to decide whether to keep pressing or pass. Prioritize going out immediately and consider blocking "
        "opponents who are close to going out. A pass does not prove a player has no beating cards.",
    ]
    if context is not None:
        lines.extend([
            f"Your seat: {context.current_seat} ({context.seat_names[context.current_seat]})",
            "Seat order: " + " -> ".join(f"{i}={n}" for i, n in enumerate(context.seat_names)),
            "Remaining cards: " + ", ".join(f"{n}={c}" for n, c in zip(context.seat_names, context.remaining)),
        ])
        last = context.last_play_seat
        lines.append("Last player to play: " + ("none" if last is None else f"{last} ({context.seat_names[last]})"))
        lines.append("History:" if context.history else "History: no turns yet")
        lines.extend(f"{i}. {event}" for i, event in enumerate(context.history, 1))
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
    returns a `TurnEvent` describing what happened. Public events persist in
    history across trick resets; turn_context exposes an independent public
    snapshot, never other seats' hidden cards."""

    def __init__(self, hands: list[list[Card]], names: list[str], logger: GameLogger) -> None:
        """Copy hands and initialize turn/history state using names and logger.

        Returns no value; requires a dealt 3♣ and does not log until apply.
        """
        self.hands = [list(h) for h in hands]
        self.names = names
        self.logger = logger
        self.n = len(hands)
        self.current = self.leader = find_starting_player(self.hands)
        self.required: Combo | None = None
        self.passes_in_a_row = 0
        self.must_include_3c = True
        self.winner_seat: int | None = None
        self.history: list[TurnEvent] = []

    def turn_context(self) -> TurnContext:
        """Return independent public facts for the current seat, without exposing hands.

        Takes no arguments, does not mutate the engine, and converts events
        to strings so controllers cannot modify historical event snapshots.
        """
        history = tuple(
            f"{event.player_name} passed" if event.combo is None
            else f"{event.player_name} played {_describe_combo(event.combo)}"
            for event in self.history
        )
        # leader is initialized before anyone plays, so only history can
        # distinguish the starting seat from an actual last player to play.
        return TurnContext(
            tuple(self.names), tuple(len(h) for h in self.hands), self.current,
            self.leader if self.history else None, history,
        )

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
        """Apply an already-legal combo or pass, returning and retaining its public event.

        Mutates hands/trick/turn/winner state and writes the game log. History
        survives trick resets and includes the winning turn.
        """
        seat = self.current
        name = self.names[seat]

        if move is None:
            self.passes_in_a_row += 1
            self.logger.log({"event": "pass", "player": name})
            event = TurnEvent(name, "pass", None, self._remaining())
            self.history.append(event)
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
        self.history.append(event)

        if not self.hands[seat]:
            self.winner_seat = seat
            # Game over: write the AI call totals once, here, so CLI and web
            # both get them without each wiring its own end-of-game hook.
            self.logger.log_ai_summary()
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
    the entire game out in one call. Each controller receives fresh public
    context. Returns applied events, mutating engine and writing its log;
    controllers and is_human are aligned in seat order."""
    events: list[TurnEvent] = []
    while not engine.finished and not is_human[engine.current]:
        controller = controllers[engine.current]
        move = controller.choose_move(
            engine.hand, engine.required, engine.is_leading, engine.must_include_3c and engine.is_leading,
            context=engine.turn_context(),
        )
        events.append(engine.apply(move))
    return events


def run_game(hands: list[list[Card]], controllers: list[Controller], logger: GameLogger) -> GameResult:
    """Play hands through controllers with fresh public snapshots until a winner.

    Returns the winning seat/name; prints turns, invokes seat controllers and
    logs applied moves. GameEngine copies the caller's hands before playing.
    """
    names = [c.name for c in controllers]
    engine = GameEngine(hands, names, logger)

    while True:
        controller = controllers[engine.current]
        move = controller.choose_move(
            engine.hand, engine.required, engine.is_leading, engine.must_include_3c and engine.is_leading,
            context=engine.turn_context(),
        )
        event = engine.apply(move)

        if event.kind == "pass":
            print(f"{event.player_name} 過牌")
        else:
            print(f"{event.player_name} 出牌：{_describe_combo(event.combo)}")
        print("剩餘張數：" + " ".join(f"{n}={c}" for n, c in event.remaining.items()))

        if engine.finished:
            return GameResult(winner_seat=engine.winner_seat, winner_name=names[engine.winner_seat])
