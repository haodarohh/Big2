"""Hand classification and comparison for Taiwanese Big Two.

Only combos with the same card count can be compared against one another
(no bombs that beat a different shape). Among 5-card hands, the category
order is: straight < full house < four-of-a-kind < straight flush. A plain
flush (5 same-suit, non-consecutive cards) is not a recognized hand type at
all in this ruleset — it isn't playable as a 5-card combo.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import IntEnum

from .cards import Card, Rank

STRAIGHT_LENGTH = 5

# The 8 valid 5-consecutive-rank windows; TWO is never part of a straight.
STRAIGHT_WINDOWS: list[tuple[Rank, ...]] = [
    tuple(Rank(r) for r in range(start, start + STRAIGHT_LENGTH))
    for start in range(0, Rank.ACE - STRAIGHT_LENGTH + 2)
]


class HandType(IntEnum):
    SINGLE = 1
    PAIR = 2
    TRIPLE = 3
    STRAIGHT = 10
    FULL_HOUSE = 11
    FOUR_OF_A_KIND = 12
    STRAIGHT_FLUSH = 13


_FIVE_CARD_CATEGORY_ORDER = {
    HandType.STRAIGHT: 0,
    HandType.FULL_HOUSE: 1,
    HandType.FOUR_OF_A_KIND: 2,
    HandType.STRAIGHT_FLUSH: 3,
}


@dataclass(frozen=True)
class Combo:
    type: HandType
    cards: tuple[Card, ...]
    strength: tuple[int, ...]

    @property
    def size(self) -> int:
        return len(self.cards)


def classify(cards: list[Card] | tuple[Card, ...]) -> Combo | None:
    """Return the Combo for a set of cards, or None if it isn't a legal shape."""
    cards = tuple(sorted(cards))
    n = len(cards)

    if n == 1:
        c = cards[0]
        return Combo(HandType.SINGLE, cards, (c.rank, c.suit))

    if n == 2:
        if cards[0].rank != cards[1].rank:
            return None
        # A rank has 4 cards, so two different pairs of the same rank can
        # coexist (e.g. 5♠5♥ held by one player, 5♣5♦ by another) — the
        # higher-suited card in each pair breaks the tie.
        top_suit = max(c.suit for c in cards)
        return Combo(HandType.PAIR, cards, (cards[0].rank, top_suit))

    if n == 3:
        if len({c.rank for c in cards}) != 1:
            return None
        return Combo(HandType.TRIPLE, cards, (cards[0].rank,))

    if n == 5:
        return _classify_five(cards)

    return None


def _classify_five(cards: tuple[Card, ...]) -> Combo | None:
    ranks = [c.rank for c in cards]
    rank_counts = Counter(ranks)
    is_flush = len({c.suit for c in cards}) == 1
    is_straight = tuple(sorted(ranks)) in STRAIGHT_WINDOWS

    if is_straight and is_flush:
        top = max(cards, key=lambda c: (c.rank, c.suit))
        return Combo(HandType.STRAIGHT_FLUSH, cards, _five_strength(HandType.STRAIGHT_FLUSH, top.rank, top.suit))

    if sorted(rank_counts.values()) == [1, 4]:
        quad_rank = next(r for r, n in rank_counts.items() if n == 4)
        return Combo(HandType.FOUR_OF_A_KIND, cards, _five_strength(HandType.FOUR_OF_A_KIND, quad_rank, 0))

    if sorted(rank_counts.values()) == [2, 3]:
        triple_rank = next(r for r, n in rank_counts.items() if n == 3)
        return Combo(HandType.FULL_HOUSE, cards, _five_strength(HandType.FULL_HOUSE, triple_rank, 0))

    if is_straight:
        top = max(cards, key=lambda c: (c.rank, c.suit))
        return Combo(HandType.STRAIGHT, cards, _five_strength(HandType.STRAIGHT, top.rank, top.suit))

    return None


def _five_strength(hand_type: HandType, rank: Rank, suit: int) -> tuple[int, ...]:
    return (_FIVE_CARD_CATEGORY_ORDER[hand_type], int(rank), int(suit))


def beats(candidate: Combo, required: Combo) -> bool:
    """Whether `candidate` can be legally played on top of `required`."""
    return candidate.size == required.size and candidate.strength > required.strength
