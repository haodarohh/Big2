"""Enumerate every distinct legal combo playable from a hand.

Deliberately does NOT filter by whether a combo beats the current trick's
required combo — that judgment is left to the AI. This only prunes down
from "every 5-card subset" to "every subset that forms a real hand type",
which is what keeps the option list small enough to hand to jev.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from .cards import Card
from .rules import STRAIGHT_WINDOWS, Combo, classify


def all_combos(hand: list[Card]) -> list[Combo]:
    combos: dict[tuple[Card, ...], Combo] = {}

    def add(cards: tuple[Card, ...]) -> None:
        combo = classify(cards)
        if combo is not None:
            combos[combo.cards] = combo

    by_rank: dict = defaultdict(list)
    for card in hand:
        by_rank[card.rank].append(card)

    # Singles
    for card in hand:
        add((card,))

    # Pairs and triples
    for cards in by_rank.values():
        for pair in combinations(cards, 2):
            add(pair)
        for triple in combinations(cards, 3):
            add(triple)

    # Straights: for each 5-rank window, take the Cartesian product of
    # available suits per rank (skip windows missing a rank entirely).
    for window in STRAIGHT_WINDOWS:
        options_per_rank = [by_rank[r] for r in window]
        if any(len(opts) == 0 for opts in options_per_rank):
            continue
        _add_straight_products(options_per_rank, add)

    # Full houses: triple of one rank + pair of a different rank
    ranks_with_triple = [r for r, cards in by_rank.items() if len(cards) >= 3]
    ranks_with_pair = [r for r, cards in by_rank.items() if len(cards) >= 2]
    for triple_rank in ranks_with_triple:
        for triple in combinations(by_rank[triple_rank], 3):
            for pair_rank in ranks_with_pair:
                if pair_rank == triple_rank:
                    continue
                for pair in combinations(by_rank[pair_rank], 2):
                    add(triple + pair)

    # Four of a kind + kicker
    for quad_rank, cards in by_rank.items():
        if len(cards) < 4:
            continue
        quad = tuple(cards[:4])
        for kicker in hand:
            if kicker.rank != quad_rank:
                add(quad + (kicker,))

    return sorted(combos.values(), key=lambda c: (c.size, c.strength))


def _add_straight_products(options_per_rank: list[list[Card]], add) -> None:
    def rec(i: int, chosen: tuple[Card, ...]) -> None:
        if i == len(options_per_rank):
            add(chosen)
            return
        for card in options_per_rank[i]:
            rec(i + 1, chosen + (card,))

    rec(0, ())
