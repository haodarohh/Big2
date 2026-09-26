"""Card primitives: suits, ranks, and a standard 52-card deck.

Suit and rank orderings follow Taiwanese Big Two conventions: 3 is the
lowest rank, 2 is the highest, and suits break ties (Spade > Heart > Club
> Diamond) for singles and for the top card of straights/flushes.
"""

from __future__ import annotations

import random
from enum import IntEnum
from typing import NamedTuple


class Suit(IntEnum):
    """Ordered low to high: Spade > Heart > Diamond > Club."""
    CLUB = 0
    DIAMOND = 1
    HEART = 2
    SPADE = 3

    @property
    def symbol(self) -> str:
        return {Suit.DIAMOND: "♦", Suit.CLUB: "♣", Suit.HEART: "♥", Suit.SPADE: "♠"}[self]


class Rank(IntEnum):
    THREE = 0
    FOUR = 1
    FIVE = 2
    SIX = 3
    SEVEN = 4
    EIGHT = 5
    NINE = 6
    TEN = 7
    JACK = 8
    QUEEN = 9
    KING = 10
    ACE = 11
    TWO = 12

    @property
    def symbol(self) -> str:
        return {
            Rank.THREE: "3", Rank.FOUR: "4", Rank.FIVE: "5", Rank.SIX: "6",
            Rank.SEVEN: "7", Rank.EIGHT: "8", Rank.NINE: "9", Rank.TEN: "10",
            Rank.JACK: "J", Rank.QUEEN: "Q", Rank.KING: "K", Rank.ACE: "A",
            Rank.TWO: "2",
        }[self]


class Card(NamedTuple):
    rank: Rank
    suit: Suit

    def __str__(self) -> str:  # e.g. "3♦"
        return f"{self.rank.symbol}{self.suit.symbol}"


THREE_OF_CLUBS = Card(Rank.THREE, Suit.CLUB)


def full_deck() -> list[Card]:
    return [Card(rank, suit) for rank in Rank for suit in Suit]


def shuffled_deck(rng: random.Random | None = None) -> list[Card]:
    deck = full_deck()
    (rng or random).shuffle(deck)
    return deck
