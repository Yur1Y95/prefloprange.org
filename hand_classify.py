"""
hand_classify.py — classify a 2-card hand on a board into a made-hand
category plus any draws. Street-aware (draws only counted while cards
are still to come).

Standalone & testable, like equity.py. No GPL code. Verified against
the equity.poker breakdown the user cross-checked the engine with.

Public API:
    classify(hero, board) -> {
        "made":  "Top Pair",          # one made-hand label
        "draws": ["Flush Draw"],      # list, possibly empty
        "made_rank": 7,               # ordinal for sorting/aggregation
    }

Made categories (strong -> weak), with ordinal:
    9 Straight or better (straight, flush, full house, quads, SF)
    8 Set / Trips
    7 Two Pair
    6 Overpair          (pocket pair higher than every board card)
    5 Top Pair
    4 Middle Pair
    3 Weak/Bottom Pair
    2 Ace High
    1 King High
    0 Nothing

Draw categories (only if board has 3 or 4 cards, i.e. cards to come):
    Flush Draw      (4 to a flush)
    OESD            (open-ended straight draw, 8 outs)
    Gutshot         (inside straight draw, 4 outs)
    Backdoor FD     (3 to a flush — needs running cards; flop only)

A hand can be made AND have draws (e.g. Top Pair + Flush Draw).
"""

from __future__ import annotations
from collections import Counter
from itertools import combinations

import equity  # reuse parse_cards / evaluate7 / rank constants

MADE_LABELS = {
    9: "Straight+",
    8: "Set/Trips",
    7: "Two Pair",
    6: "Overpair",
    5: "Top Pair",
    4: "Middle Pair",
    3: "Weak Pair",
    2: "Ace High",
    1: "King High",
    0: "Nothing",
}


def _straight_outs(ranks: set[int]) -> int:
    """Return 8 (OESD), 4 (gutshot), or 0. Counts distinct board+hand
    ranks; treats Ace as both high and low."""
    rs = set(ranks)
    if 14 in rs:
        rs.add(1)
    # how many of the 13 possible "completing" ranks make a straight?
    completing = 0
    for draw_card in range(1, 15):
        if draw_card in rs:
            continue
        test = rs | {draw_card}
        if 14 in test:
            test.add(1)
        # check any 5-in-a-row in test
        made = False
        for top in range(14, 4, -1):
            if all((top - k) in test for k in range(5)):
                made = True
                break
        if made:
            completing += 1
    if completing >= 2:
        return 8   # open-ended / double-gutter equivalent
    if completing == 1:
        return 4   # gutshot
    return 0


def classify(hero, board) -> dict:
    hero = equity.parse_cards(hero) if isinstance(hero, str) else list(hero)
    board = (equity.parse_cards(board) if isinstance(board, str)
             else list(board)) if board else []

    all_cards = hero + board
    n_board = len(board)
    cards_to_come = max(0, 5 - n_board) if n_board >= 3 else 0

    hero_ranks = [c[0] for c in hero]
    board_ranks = sorted((c[0] for c in board), reverse=True)
    board_rank_set = set(board_ranks)

    # ---- made hand via the proven evaluator ----
    score = equity.evaluate7(all_cards) if len(all_cards) >= 5 else None
    cat = score[0] if score else None

    made_rank = 0
    if cat is not None and cat >= 3:
        # 3=trips,4=straight,5=flush,6=fullhouse,7=quads,8=SF
        made_rank = 9 if cat >= 4 else 8  # straight+ vs trips/set
        if cat == 3:
            made_rank = 8
    else:
        # pair logic by hand
        rank_count = Counter(c[0] for c in all_cards)
        pairs = [r for r, c in rank_count.items() if c >= 2]
        is_pocket_pair = hero_ranks[0] == hero_ranks[1]

        if cat == 2:  # two pair
            made_rank = 7
        elif pairs:
            top_board = board_ranks[0] if board_ranks else 0
            if is_pocket_pair:
                pp = hero_ranks[0]
                if not board_ranks or pp > top_board:
                    made_rank = 6  # overpair
                else:
                    made_rank = _pair_position(pp, board_ranks)
            else:
                # which hero card paired the board?
                paired = [r for r in hero_ranks if r in board_rank_set]
                if paired:
                    made_rank = _pair_position(max(paired), board_ranks)
                else:
                    made_rank = 0
        if made_rank == 0:
            hi = max(hero_ranks)
            if hi == 14:
                made_rank = 2
            elif hi == 13:
                made_rank = 1
            else:
                made_rank = 0

    # ---- draws (only if cards still to come) ----
    draws = []
    if cards_to_come >= 1 and made_rank < 9:
        # flush draws by suit count — require hero to hold >=2 of the
        # suit, otherwise it's a board flush draw, not the hand's.
        suit_count = Counter(c[1] for c in all_cards)
        hero_suit_count = Counter(c[1] for c in hero)
        fd_suit = None
        for suit, cnt in suit_count.items():
            if cnt == 4 and hero_suit_count.get(suit, 0) >= 2:
                fd_suit = suit
                draws.append("Flush Draw")
                break
        if fd_suit is None and cards_to_come >= 2:
            for suit, cnt in suit_count.items():
                if cnt == 3 and hero_suit_count.get(suit, 0) >= 2:
                    draws.append("Backdoor FD")
                    break

        # straight draws
        sd = _straight_outs(set(c[0] for c in all_cards))
        # don't double-count if already a made straight+
        if made_rank < 9:
            if sd == 8:
                draws.append("OESD")
            elif sd == 4:
                draws.append("Gutshot")

    return {
        "made": MADE_LABELS[made_rank],
        "made_rank": made_rank,
        "draws": draws,
    }


def _pair_position(paired_rank: int, board_ranks_desc: list[int]) -> int:
    """Top/Middle/Weak pair classification relative to the board."""
    uniq = sorted(set(board_ranks_desc), reverse=True)
    if not uniq:
        return 4
    if paired_rank >= uniq[0]:
        return 5  # top pair (or pair of top board card)
    if len(uniq) >= 2 and paired_rank >= uniq[1]:
        return 4  # middle pair
    return 3      # weak / bottom pair


# --- self-test: python hand_classify.py ---
if __name__ == "__main__":
    tests = [
        ("AhKh", "Qh7h2c", "Ace High + Flush Draw expected"),
        ("AhKs", "Ad7c2h", "Top Pair (aces) expected"),
        ("7h7d", "Ks9c2h", "Weak Pair (under board) expected"),
        ("QhQd", "Jc7s2h", "Overpair expected"),
        ("9hTh", "8h7c2d", "OESD + Backdoor/Flush draw-ish"),
        ("5c5d", "5h9s2c", "Set/Trips expected"),
        ("AhKh", "QhJhTh", "Straight+ (flush) expected"),
        ("Js Th", "9h8c2d", "OESD expected"),
        ("Ah2h", "KhQh5c", "Flush Draw expected"),
        ("Kd9d", "Kc7h2s", "Top Pair expected"),
    ]
    for h, b, note in tests:
        r = classify(h, b)
        dr = (" + " + ", ".join(r["draws"])) if r["draws"] else ""
        print(f"  {h:7s} on {b:9s} -> {r['made']}{dr:24s}  ({note})")