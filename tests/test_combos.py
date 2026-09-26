from big2.cards import Card, Rank, Suit
from big2.combos import all_combos
from big2.rules import HandType


def c(rank: Rank, suit: Suit) -> Card:
    return Card(rank, suit)


def test_singles_and_pairs():
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.FOUR, Suit.HEART)]
    combos = all_combos(hand)
    types = [combo.type for combo in combos]
    assert types.count(HandType.SINGLE) == 3
    assert types.count(HandType.PAIR) == 1


def test_straight_needs_all_ranks_present():
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB), c(Rank.FIVE, Suit.HEART),
            c(Rank.SIX, Suit.SPADE)]  # missing SEVEN
    combos = all_combos(hand)
    assert not any(combo.type == HandType.STRAIGHT for combo in combos)


def test_straight_suit_product():
    # Two choices for THREE (diamond/club) x 1 choice for the rest => 2 straights
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.FOUR, Suit.HEART),
            c(Rank.FIVE, Suit.HEART), c(Rank.SIX, Suit.HEART), c(Rank.SEVEN, Suit.HEART)]
    combos = all_combos(hand)
    straights = [combo for combo in combos if combo.type == HandType.STRAIGHT]
    assert len(straights) == 2


def test_full_house_excludes_same_rank_pair_and_triple():
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
            c(Rank.THREE, Suit.SPADE)]
    combos = all_combos(hand)
    assert not any(combo.type == HandType.FULL_HOUSE for combo in combos)


def test_four_of_a_kind_each_kicker():
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
            c(Rank.THREE, Suit.SPADE), c(Rank.FOUR, Suit.DIAMOND), c(Rank.FIVE, Suit.CLUB)]
    combos = all_combos(hand)
    quads = [combo for combo in combos if combo.type == HandType.FOUR_OF_A_KIND]
    assert len(quads) == 2  # one kicker per non-quad card


def test_no_duplicate_combos():
    hand = [c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.DIAMOND), c(Rank.FIVE, Suit.DIAMOND),
            c(Rank.SIX, Suit.DIAMOND), c(Rank.SEVEN, Suit.DIAMOND)]
    combos = all_combos(hand)
    card_sets = [combo.cards for combo in combos]
    assert len(card_sets) == len(set(card_sets))
