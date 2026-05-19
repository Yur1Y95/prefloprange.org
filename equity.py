"""
equity.py — clean-room poker equity engine for the trainer/analyzer.

Written from scratch, zero external dependencies, no GPL code.
Designed to drop into the FastAPI backend (Milestone 2 postflop + Milestone 3 analyzer).

What it does:
  - Parses cards like "Ah", "Td", "2c".
  - Fast 7-card hand evaluator (best 5 of 7) via rank/suit histograms,
    NOT the slow "loop over all 21 combinations" approach.
  - Monte Carlo equity for: a hero hand vs a villain RANGE, on any board
    (preflop / flop / turn / river), with dead cards supported.
  - Exact enumeration when the remaining space is tiny (e.g. turn->river),
    so river/turn spots are exact, earlier streets are sampled.

Public API (this is what the backend calls):
  parse_cards("AhKh")            -> [(14,0),(13,0)]
  expand_range(["AA","AKs","A2s+"]) -> list of 2-card combos
  equity(hero, villain_range, board=..., iters=...) -> dict with win/tie/loss/equity
"""

from __future__ import annotations
import random
from itertools import combinations
from collections import Counter

# ---------------------------------------------------------------------------
# Card representation
# rank: 2..14  (J=11, Q=12, K=13, A=14)
# suit: 0..3   (s=0, h=1, d=2, c=3)  -- order is irrelevant, only equality matters
# A card is a tuple (rank, suit). A full deck is 52 such tuples.
# ---------------------------------------------------------------------------

RANK_CHARS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
              "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
RANK_TO_CHAR = {v: k for k, v in RANK_CHARS.items()}
SUIT_CHARS = {"s": 0, "h": 1, "d": 2, "c": 3}
SUIT_TO_CHAR = {v: k for k, v in SUIT_CHARS.items()}

FULL_DECK = [(r, s) for r in range(2, 15) for s in range(4)]


def parse_cards(text: str) -> list[tuple[int, int]]:
    """'AhKh' or 'Ah Kh' or 'ah, kh' -> [(14,1),(13,1)]."""
    cleaned = "".join(ch for ch in text if ch.isalnum())
    if len(cleaned) % 2 != 0:
        raise ValueError(f"Bad card string: {text!r}")
    out = []
    for i in range(0, len(cleaned), 2):
        r = cleaned[i].upper()
        s = cleaned[i + 1].lower()
        if r not in RANK_CHARS or s not in SUIT_CHARS:
            raise ValueError(f"Bad card: {cleaned[i:i+2]!r}")
        out.append((RANK_CHARS[r], SUIT_CHARS[s]))
    return out


def card_str(card: tuple[int, int]) -> str:
    return RANK_TO_CHAR[card[0]] + SUIT_TO_CHAR[card[1]]


# ---------------------------------------------------------------------------
# 7-card hand evaluator
# Returns a tuple score; bigger tuple = stronger hand (plain tuple comparison).
# Category codes: 8 SF, 7 quads, 6 full house, 5 flush, 4 straight,
#                 3 trips, 2 two pair, 1 pair, 0 high card.
# ---------------------------------------------------------------------------

def _best_straight_high(ranks_present: set[int]) -> int:
    """Highest card of the best straight in a set of ranks, or 0 if none.
    Handles the wheel (A-2-3-4-5) by treating Ace as 1."""
    rs = set(ranks_present)
    if 14 in rs:
        rs.add(1)  # Ace plays low for the wheel
    high = 0
    for top in range(14, 4, -1):  # need top..top-4 present
        if all((top - k) in rs for k in range(5)):
            high = top
            break
    return high


def evaluate7(cards: list[tuple[int, int]]) -> tuple:
    """Evaluate the best 5-card hand out of 5, 6 or 7 cards.
    Fast: uses rank counts and suit buckets, no 21-combo loop."""
    ranks = [c[0] for c in cards]
    rank_count = Counter(ranks)

    # --- suits / flush detection ---
    suit_buckets: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    for r, s in cards:
        suit_buckets[s].append(r)
    flush_suit = None
    for s, rs in suit_buckets.items():
        if len(rs) >= 5:
            flush_suit = s
            break

    # --- straight flush ---
    if flush_suit is not None:
        sf_high = _best_straight_high(set(suit_buckets[flush_suit]))
        if sf_high:
            return (8, sf_high)

    # group ranks by how many times they appear, each group high->low
    by_count: dict[int, list[int]] = {}
    for r, c in rank_count.items():
        by_count.setdefault(c, []).append(r)
    for c in by_count:
        by_count[c].sort(reverse=True)

    quads = by_count.get(4, [])
    trips = by_count.get(3, [])
    pairs = by_count.get(2, [])
    singles = by_count.get(1, [])

    # --- four of a kind ---
    if quads:
        q = quads[0]
        kicker = max(r for r in ranks if r != q)
        return (7, q, kicker)

    # --- full house (trips + another pair/trips) ---
    if trips:
        # with 7 cards you can have two trips; use highest as the set
        if len(trips) >= 2:
            return (6, trips[0], trips[1])
        if pairs:
            return (6, trips[0], pairs[0])

    # --- flush ---
    if flush_suit is not None:
        top5 = sorted(suit_buckets[flush_suit], reverse=True)[:5]
        return (5, *top5)

    # --- straight ---
    st_high = _best_straight_high(set(ranks))
    if st_high:
        return (4, st_high)

    # --- trips ---
    if trips:
        t = trips[0]
        kick = sorted((r for r in ranks if r != t), reverse=True)[:2]
        return (3, t, *kick)

    # --- two pair ---
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kick)

    # --- one pair ---
    if len(pairs) == 1:
        p = pairs[0]
        kick = sorted((r for r in ranks if r != p), reverse=True)[:3]
        return (1, p, *kick)

    # --- high card ---
    top5 = sorted(ranks, reverse=True)[:5]
    return (0, *top5)


# ---------------------------------------------------------------------------
# Range expansion: standard poker notation -> list of concrete 2-card combos
# Supports: "AA", "AKs", "AKo", "AK", "A2s+", "JTs+", "99-22", "QJo+"
# A combo is a frozenset-free tuple of 2 cards: ((r,s),(r,s))
# ---------------------------------------------------------------------------

def _suited_combos(r1: int, r2: int) -> list:
    return [((r1, s), (r2, s)) for s in range(4)]


def _offsuit_combos(r1: int, r2: int) -> list:
    out = []
    for s1 in range(4):
        for s2 in range(4):
            if s1 != s2:
                out.append(((r1, s1), (r2, s2)))
    return out


def _pair_combos(r: int) -> list:
    return [((r, a), (r, b)) for a, b in combinations(range(4), 2)]


def _token_to_combos(tok: str) -> list:
    tok = tok.strip()
    if not tok:
        return []

    # explicit 2-card combo, e.g. "KhQh" -> exactly that combo
    if (len(tok) == 4 and tok[0].upper() in RANK_CHARS
            and tok[1].lower() in SUIT_CHARS
            and tok[2].upper() in RANK_CHARS
            and tok[3].lower() in SUIT_CHARS):
        return [tuple(parse_cards(tok))]

    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok

    # pocket pair, e.g. "99" or "99+" or "99-22"
    if len(core) == 2 and core[0] == core[1]:
        r = RANK_CHARS[core[0].upper()]
        ranks = range(r, 15) if plus else [r]
        out = []
        for rr in ranks:
            out += _pair_combos(rr)
        return out

    # dash range of pairs, e.g. "99-22"
    if "-" in core and len(core) == 5:
        a, b = core.split("-")
        ra = RANK_CHARS[a[0].upper()]
        rb = RANK_CHARS[b[0].upper()]
        lo, hi = sorted((ra, rb))
        out = []
        for rr in range(lo, hi + 1):
            out += _pair_combos(rr)
        return out

    # two ranks with optional s/o suffix, e.g. "AKs", "A2s+", "QJo"
    suited = core.endswith("s")
    offsuit = core.endswith("o")
    body = core[:-1] if (suited or offsuit) else core
    hi = RANK_CHARS[body[0].upper()]
    lo = RANK_CHARS[body[1].upper()]

    def build(h, l):
        if suited:
            return _suited_combos(h, l)
        if offsuit:
            return _offsuit_combos(h, l)
        return _suited_combos(h, l) + _offsuit_combos(h, l)

    if not plus:
        return build(hi, lo)

    # "+" on a non-pair walks the low card up toward the high card
    out = []
    for l in range(lo, hi):
        out += build(hi, l)
    return out


def expand_range(tokens) -> list:
    """tokens: list[str] like ['AA','AKs','A2s+','99-22'] OR a single
    comma/space separated string. Returns deduped list of 2-card combos."""
    if isinstance(tokens, str):
        tokens = tokens.replace(",", " ").split()
    seen = set()
    out = []
    for t in tokens:
        for combo in _token_to_combos(t):
            key = frozenset(combo)
            if key not in seen:
                seen.add(key)
                out.append(combo)
    return out


# ---------------------------------------------------------------------------
# Equity: hero (2 specific cards) vs a villain RANGE, on any board.
# Auto-picks exact enumeration when cheap, Monte Carlo otherwise.
# ---------------------------------------------------------------------------

def equity(hero, villain_range, board=None, dead=None,
           iters: int = 20000, seed: int | None = None) -> dict:
    """
    hero          : "AhKh" or [(14,1),(13,1)]
    villain_range : ["AA","KK","AKs"] or expanded combo list or "AhKd" (one combo)
    board         : "" / "Ah7d2c" / list of cards   (0,3,4 or 5 cards)
    dead          : extra removed cards (e.g. folded hands), optional
    iters         : Monte Carlo samples (ignored if exact enumeration is used)

    returns: {"win","tie","loss","equity","samples","method"}
    """
    if seed is not None:
        random.seed(seed)

    hero = parse_cards(hero) if isinstance(hero, str) else list(hero)
    board = [] if not board else (parse_cards(board) if isinstance(board, str) else list(board))
    dead = [] if not dead else (parse_cards(dead) if isinstance(dead, str) else list(dead))

    if isinstance(villain_range, str):
        # single combo like "AhKd" -> 4 chars, else treat as notation
        cleaned = "".join(c for c in villain_range if c.isalnum())
        if len(cleaned) == 4 and all(c.isalnum() for c in cleaned):
            villain_combos = [tuple(parse_cards(cleaned))]
        else:
            villain_combos = expand_range(villain_range)
    elif villain_range and isinstance(villain_range[0], str):
        villain_combos = expand_range(villain_range)
    else:
        villain_combos = list(villain_range)

    blocked = set(hero) | set(board) | set(dead)

    # remove villain combos that clash with known cards
    legal_villain = [c for c in villain_combos
                     if c[0] not in blocked and c[1] not in blocked and c[0] != c[1]]
    if not legal_villain:
        raise ValueError("Villain range is empty after removing blocked cards.")

    wins = ties = losses = 0
    samples = 0
    cards_needed = 5 - len(board)

    # Decide exact vs Monte Carlo. Exact only when the runout space is small.
    # (e.g. river: 0 cards; turn: ~44 boards; flop with fixed villain: 990).
    deck_base = [c for c in FULL_DECK if c not in blocked]

    def settle(hero7, vill7):
        nonlocal wins, ties, losses
        hs = evaluate7(hero7)
        vs = evaluate7(vill7)
        if hs > vs:
            wins += 1
        elif hs < vs:
            losses += 1
        else:
            ties += 1

    use_exact = (cards_needed <= 1 and len(legal_villain) <= 200) or \
                (cards_needed == 0)

    if use_exact:
        method = "exact"
        for v in legal_villain:
            if v[0] in blocked or v[1] in blocked:
                continue
            deck = [c for c in deck_base if c != v[0] and c != v[1]]
            if cards_needed == 0:
                settle(hero + board, list(v) + board)
                samples += 1
            else:  # exactly one card to come
                for x in deck:
                    b = board + [x]
                    settle(hero + b, list(v) + b)
                    samples += 1
    else:
        method = "montecarlo"
        for _ in range(iters):
            v = random.choice(legal_villain)
            if v[0] in blocked or v[1] in blocked:
                continue
            deck = [c for c in deck_base if c != v[0] and c != v[1]]
            extra = random.sample(deck, cards_needed) if cards_needed else []
            b = board + extra
            settle(hero + b, list(v) + b)
            samples += 1

    eq = (wins + ties / 2) / samples if samples else 0.0
    return {
        "win": wins / samples if samples else 0.0,
        "tie": ties / samples if samples else 0.0,
        "loss": losses / samples if samples else 0.0,
        "equity": eq,
        "samples": samples,
        "method": method,
    }


# ---------------------------------------------------------------------------
# Self-test / sanity demo: run `python equity.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    def pct(x):
        return f"{x*100:5.1f}%"

    print("Hand evaluator sanity checks")
    royal = parse_cards("AsKsQsJsTs")
    quads = parse_cards("9s9h9d9cKs")
    assert evaluate7(royal) > evaluate7(quads), "royal must beat quads"
    wheel = parse_cards("As2h3d4c5s")
    assert evaluate7(wheel)[0] == 4, "A-5 wheel must be a straight"
    print("  evaluator OK\n")

    print("Equity sanity (known spots)")
    tests = [
        ("Preflop AA vs KK", "AsAh", ["KK"], "", 60000),
        ("Preflop AKs vs 22 (coinflip)", "AsKs", ["22"], "", 60000),
        ("Flop top set vs flush draw", "AsAh", ["KhQh"], "Ad7h2h", 40000),
    ]
    for name, h, vr, b, it in tests:
        t0 = time.time()
        r = equity(h, vr, board=b, iters=it, seed=1)
        dt = time.time() - t0
        print(f"  {name:34s} eq={pct(r['equity'])} "
              f"(W {pct(r['win'])} T {pct(r['tie'])} L {pct(r['loss'])}) "
              f"[{r['method']}, {r['samples']} samples, {dt:.2f}s]")

    print("\nRange vs range example (BTN open vs BB call, K72r flop)")
    r = equity("KdQc", ["22+", "ATs+", "KQs", "AJo+"], board="Kh7s2d",
               iters=30000, seed=1)
    print(f"  KQ on K72r vs that range: eq={pct(r['equity'])} "
          f"[{r['samples']} samples]")