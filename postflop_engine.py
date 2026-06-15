"""
postflop_engine.py — postflop cash trainer logic.

Sibling of drill_engine.py (which handles preflop). Same idea:
generate a spot, let the player answer fold/call, grade it.

Pipeline:  generate_spot() -> player picks fold/call ->
           grade(spot, action) -> verdict from decision.py

Villain types are DRAFT ranges. Replace the combos in VILLAIN_TYPES
with ranges built from your real PokerKing hand database later — the
structure won't change, only the strings inside.
"""

from __future__ import annotations
import random

import equity
import decision

# ---------------------------------------------------------------------------
# Villain archetypes — DRAFT. Tune from real DB later.
# "cont_range" = hands this player type continues with facing a bet on
# the flop (i.e. what he'd have here when he bets / calls).
# Written in standard notation; equity.py expands it.
# ---------------------------------------------------------------------------

VILLAIN_TYPES = {
    "nit": {
        "label": "Tight passive (nit)",
        "desc": "Only continues with strong made hands. Rarely bluffs.",
        "cont_range": ["TT+", "AQs+", "AQo+", "KQs"],
    },
    "fish": {
        "label": "Passive fish",
        "desc": "Calls far too wide with any pair, any draw, any ace.",
        "cont_range": ["22+", "A2s+", "A2o+", "K8s+", "QTs+", "JTs",
                       "T9s", "98s", "87s", "76s", "65s", "54s",
                       "KQo", "KJo", "QJo"],
    },
    "maniac": {
        "label": "Aggro maniac",
        "desc": "Bets and raises relentlessly with a very wide, "
                "bluff-heavy range.",
        "cont_range": ["22+", "A2s+", "A7o+", "K5s+", "Q8s+", "J8s+",
                       "T8s+", "97s+", "86s+", "75s+", "64s+", "53s+",
                       "KTo+", "QTo+", "JTo"],
    },
    "reg": {
        "label": "Regular (TAG)",
        "desc": "Tight-aggressive regular. Bets strong hands and nut "
                "draws, some well-timed bluffs.",
        "cont_range": ["JJ+", "AKs", "AQs", "AJs", "KQs",
                       "JTs", "T9s", "98s", "87s",
                       "AKo", "AQo", "KQo"],
    },
    "gto": {
        "label": "GTO solver",
        "desc": "Balanced solver range mixing value hands and bluffs "
                "at precise frequencies.",
        "cont_range": ["TT+", "AQs+", "AJs", "KQs", "AKo", "AQo",
                       "JTs", "T9s", "98s", "87s", "76s", "65s",
                       "Ah9h", "Ah8h", "Ah7h", "Kh9h"],
    },
}

# Common heads-up postflop spots: (hero_pos, villain_pos)
_POSITIONS_POOL = [
    ("BTN", "BB"),
    ("CO",  "BB"),
    ("HJ",  "BB"),
    ("BTN", "SB"),
    ("BB",  "BTN"),
    ("BB",  "CO"),
    ("SB",  "BTN"),
]

# Simple hero hand pool to deal from (kept readable; expand freely).
_HERO_HANDS = [
    "AhKh", "AsKd", "QcQd", "JhJs", "AhQs", "KdQd", "AsJs",
    "TsTh", "9c9d", "AhTh", "KhJh", "QsJs", "AdQc", "KsTs",
    "8h8s", "7d7c", "Ah5h", "Kc9c", "JdTd", "Qh9h",
]


def _deal_board(hero_cards, n=3):
    """Deal n distinct board cards not colliding with hero."""
    used = set(equity.parse_cards(hero_cards))
    deck = [c for c in equity.FULL_DECK if c not in used]
    picked = random.sample(deck, n)
    return "".join(equity.card_str(c) for c in picked)


def generate_spot(villain_type: str | None = None,
                  seed: int | None = None) -> dict:
    """Build one flop spot.

    Returns a dict the frontend can render directly. The villain's
    actual range is included as `_villain_range` (underscore = internal,
    the UI should NOT show it — the player must read the TYPE, not the
    range; that's the training).
    """
    if seed is not None:
        random.seed(seed)

    if villain_type is None:
        villain_type = random.choice(list(VILLAIN_TYPES))
    vt = VILLAIN_TYPES[villain_type]

    hero = random.choice(_HERO_HANDS)
    board = _deal_board(hero, 3)
    hero_pos, villain_pos = random.choice(_POSITIONS_POOL)

    # Pot / bet sizing typical for micro cash single-raised pot on flop.
    # pot already includes villain's bet (see decision.required_equity).
    pot = random.choice([6.0, 8.0, 10.0, 12.0])
    bet_fraction = random.choice([0.33, 0.5, 0.66, 0.75, 1.0])
    to_call = round(pot * bet_fraction, 1)
    pot_with_bet = round(pot + to_call, 1)

    return {
        "hero": hero,
        "board": board,
        "hero_pos": hero_pos,
        "villain_pos": villain_pos,
        "villain_type": villain_type,
        "villain_label": vt["label"],
        "villain_desc": vt["desc"],
        "pot": pot_with_bet,
        "to_call": to_call,
        "_villain_range": vt["cont_range"],
    }


def _combo_notation(combo) -> str:
    """Collapse a concrete 2-card combo back to range notation:
    (14,1),(14,2) -> 'AA';  (14,1),(13,1) -> 'AKs';  (14,1),(13,2) -> 'AKo'."""
    (r1, s1), (r2, s2) = combo
    rc = equity.RANK_TO_CHAR
    if r1 == r2:
        return rc[r1] + rc[r2]                       # pocket pair
    hi, lo = (r1, r2) if r1 > r2 else (r2, r1)
    return rc[hi] + rc[lo] + ("s" if s1 == s2 else "o")


# Max distinct hands listed per category tooltip before truncating.
_HANDS_CAP = 28


def _notation_sort_key(notation: str):
    """Sort hands strong->weak: by high rank, then low rank, suited first."""
    rch = equity.RANK_CHARS
    hi = rch[notation[0]]
    lo = rch[notation[1]]
    suited = 0 if (len(notation) == 3 and notation[2] == "o") else 1
    return (-hi, -lo, -suited)


def _format_hands(counter) -> str:
    """'AKo·9, AQo·6, …' sorted by combo count desc then hand strength."""
    items = sorted(counter.items(),
                   key=lambda kv: (-kv[1], _notation_sort_key(kv[0])))
    shown = items[:_HANDS_CAP]
    parts = [f"{hand}·{n}" for hand, n in shown]
    extra = len(items) - len(shown)
    if extra > 0:
        parts.append(f"+{extra} more")
    return ", ".join(parts)


def _breakdown(combos, board):
    """Aggregate hand_classify over a list of 2-card combos.
    Returns made-hand counts and draw counts as percentages, each with a
    `hands` string (notation·combos) for the hover tooltip."""
    import hand_classify
    from collections import Counter
    made = {}
    draws = {}
    made_hands = {}   # label -> Counter(notation -> combos)
    draw_hands = {}
    total = 0
    for c in combos:
        cstr = equity.card_str(c[0]) + equity.card_str(c[1])
        r = hand_classify.classify(cstr, board)
        note = _combo_notation(c)
        ml = r["made"]
        made[ml] = made.get(ml, 0) + 1
        made_hands.setdefault(ml, Counter())[note] += 1
        for d in r["draws"]:
            draws[d] = draws.get(d, 0) + 1
            draw_hands.setdefault(d, Counter())[note] += 1
        total += 1
    if total == 0:
        return {"made": [], "draws": [], "total": 0}

    def pack(d, hands_map):
        items = sorted(d.items(), key=lambda kv: -kv[1])
        return [{"label": k, "combos": v,
                 "pct": round(v / total * 100, 1),
                 "hands": _format_hands(hands_map.get(k, Counter()))}
                for k, v in items]

    return {"made": pack(made, made_hands),
            "draws": pack(draws, draw_hands), "total": total}


def _legal_villain_combos(villain_range, hero, board):
    """Expand villain range and drop combos blocked by hero/board."""
    combos = equity.expand_range(villain_range)
    blocked = set(equity.parse_cards(hero)) | set(equity.parse_cards(board))
    return [c for c in combos
            if c[0] not in blocked and c[1] not in blocked
            and c[0] != c[1]]


def grade(spot: dict, player_action: str) -> dict:
    """Grade the player's fold/call against the math.

    Reuses decision.grade_spot — the same proven engine we verified
    against the pro calculator.
    """
    decision_spot = {
        "hero": spot["hero"],
        "board": spot["board"],
        "villain_range": spot["_villain_range"],
        "pot": spot["pot"],
        "to_call": spot["to_call"],
        "iters": 8000,
    }
    verdict = decision.grade_spot(decision_spot, player_action)
    # Attach the spot context back so the UI can show a full recap
    verdict["hero"] = spot["hero"]
    verdict["board"] = spot["board"]
    verdict["villain_label"] = spot["villain_label"]
    verdict["pot"] = spot["pot"]
    verdict["to_call"] = spot["to_call"]

    # --- Breakdown (equity.poker-style), computed only at grade time ---
    import hand_classify
    hero_cls = hand_classify.classify(spot["hero"], spot["board"])
    verdict["hero_breakdown"] = {
        "made": hero_cls["made"],
        "draws": hero_cls["draws"],
    }
    vcombos = _legal_villain_combos(
        spot["_villain_range"], spot["hero"], spot["board"])
    verdict["villain_breakdown"] = _breakdown(vcombos, spot["board"])
    return verdict


# --- local check: python postflop_engine.py ---
if __name__ == "__main__":
    for vt in VILLAIN_TYPES:
        s = generate_spot(villain_type=vt, seed=7)
        print(f"\n[{s['villain_label']}]  ({s['villain_desc']})")
        print(f"  Hero {s['hero']}  Board {s['board']}  "
              f"Pot {s['pot']}  Bet to call {s['to_call']}")
        for act in ("fold", "call"):
            v = grade(s, act)
            mark = "OK " if v["is_correct"] else "X  "
            print(f"  {mark} you {act:4s} | correct={v['correct_action']:4s}"
                  f" | eq {v['hero_equity']*100:5.1f}% "
                  f"need {v['required_equity']*100:5.1f}%")
        print(f"  -> {grade(s, 'call')['explain']}")