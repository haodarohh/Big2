from big2.cards import Card, Rank, Suit
from big2.rules import HandType, beats, classify


def c(rank: Rank, suit: Suit) -> Card:
    return Card(rank, suit)


def test_single():
    combo = classify([c(Rank.THREE, Suit.DIAMOND)])
    assert combo.type == HandType.SINGLE


def test_pair_requires_same_rank():
    assert classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.DIAMOND)]) is None
    combo = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB)])
    assert combo.type == HandType.PAIR


def test_triple():
    combo = classify([c(Rank.SEVEN, Suit.DIAMOND), c(Rank.SEVEN, Suit.CLUB), c(Rank.SEVEN, Suit.HEART)])
    assert combo.type == HandType.TRIPLE


def test_straight_excludes_two():
    straight = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB), c(Rank.FIVE, Suit.HEART),
                          c(Rank.SIX, Suit.SPADE), c(Rank.SEVEN, Suit.DIAMOND)])
    assert straight.type == HandType.STRAIGHT

    wrap = classify([c(Rank.JACK, Suit.DIAMOND), c(Rank.QUEEN, Suit.CLUB), c(Rank.KING, Suit.HEART),
                      c(Rank.ACE, Suit.SPADE), c(Rank.TWO, Suit.DIAMOND)])
    assert wrap is None


def test_plain_flush_is_not_a_legal_combo():
    # Same suit but not consecutive — this ruleset has no "flush" category.
    combo = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FIVE, Suit.DIAMOND), c(Rank.SEVEN, Suit.DIAMOND),
                       c(Rank.NINE, Suit.DIAMOND), c(Rank.KING, Suit.DIAMOND)])
    assert combo is None


def test_full_house():
    combo = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
                       c(Rank.FOUR, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB)])
    assert combo.type == HandType.FULL_HOUSE


def test_four_of_a_kind():
    combo = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
                       c(Rank.THREE, Suit.SPADE), c(Rank.FOUR, Suit.DIAMOND)])
    assert combo.type == HandType.FOUR_OF_A_KIND


def test_straight_flush():
    combo = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.DIAMOND), c(Rank.FIVE, Suit.DIAMOND),
                       c(Rank.SIX, Suit.DIAMOND), c(Rank.SEVEN, Suit.DIAMOND)])
    assert combo.type == HandType.STRAIGHT_FLUSH


def test_five_card_hierarchy():
    straight = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB), c(Rank.FIVE, Suit.HEART),
                          c(Rank.SIX, Suit.SPADE), c(Rank.SEVEN, Suit.DIAMOND)])
    full_house = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
                            c(Rank.FOUR, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB)])
    quad = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB), c(Rank.THREE, Suit.HEART),
                      c(Rank.THREE, Suit.SPADE), c(Rank.FOUR, Suit.DIAMOND)])
    straight_flush = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.FOUR, Suit.DIAMOND), c(Rank.FIVE, Suit.DIAMOND),
                                c(Rank.SIX, Suit.DIAMOND), c(Rank.SEVEN, Suit.DIAMOND)])

    assert beats(full_house, straight)
    assert beats(quad, full_house)
    assert beats(straight_flush, quad)
    assert not beats(straight, full_house)


def test_beats_requires_same_size():
    pair = classify([c(Rank.THREE, Suit.DIAMOND), c(Rank.THREE, Suit.CLUB)])
    triple = classify([c(Rank.FOUR, Suit.DIAMOND), c(Rank.FOUR, Suit.CLUB), c(Rank.FOUR, Suit.HEART)])
    assert not beats(triple, pair)


def test_single_suit_tiebreak():
    low = classify([c(Rank.THREE, Suit.DIAMOND)])
    high = classify([c(Rank.THREE, Suit.SPADE)])
    assert beats(high, low)
    assert not beats(low, high)


def test_suit_order_is_spade_heart_diamond_club():
    diamond_k = classify([c(Rank.KING, Suit.DIAMOND)])
    club_k = classify([c(Rank.KING, Suit.CLUB)])
    assert beats(diamond_k, club_k)
    assert not beats(club_k, diamond_k)


def test_two_is_highest_single():
    two = classify([c(Rank.TWO, Suit.DIAMOND)])
    ace = classify([c(Rank.ACE, Suit.SPADE)])
    assert beats(two, ace)


def test_pair_same_rank_suit_tiebreak():
    # Both are pairs of 5 (possible: a rank has 4 cards, a pair only uses 2).
    high_pair = classify([c(Rank.FIVE, Suit.SPADE), c(Rank.FIVE, Suit.HEART)])
    low_pair = classify([c(Rank.FIVE, Suit.CLUB), c(Rank.FIVE, Suit.DIAMOND)])
    assert beats(high_pair, low_pair)
    assert not beats(low_pair, high_pair)
