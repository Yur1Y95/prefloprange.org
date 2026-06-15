"""
Regression test: the preflop drill must POST THE BLINDS.

Guards the behavior that looked "missing" in a user screenshot (all seats at
100 BB, no SB/BB blind chips). The frontend draws the blind chips from these
context fields and shows each seat's stack from context.stacks, so the source
of truth is the engine context. If this regresses, the table silently loses its
blinds again.

What we lock in:
- RFI: SB stack = 99.5, BB stack = 99.0, others = 100.0, pot = 1.5.
- The blind is deducted from the blind seat even when it is the hero.
- vs_RFI: blinds still posted AND the opener's open is deducted (pot 4.0).

Run as a plain script (no pytest):  python3 test_drill_blinds.py
"""

from drill_engine import (
    get_drill_hand_rfi, get_drill_hand_vs_rfi, SB, BB, STARTING_STACK, OPEN_SIZE,
)

_passed = 0
_failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}")


# Minimal range file: enough RFI/vs_RFI data that the generators don't bail
# with None (P-011). Hand contents are irrelevant — we only assert the chip /
# stack context, which the engine computes independently of the dealt hand.
RANGE = {
    "config": {
        "positions":     ["UTG", "MP", "CO", "BTN", "SB", "BB"],
        "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
        "vs_rfi_options": {"BTN": ["CO"]},
    },
    "spots": {
        "RFI": {
            "UTG": {"AA": {"open": 1.0}},
            "SB":  {"AA": {"open": 1.0}},
        },
        "vs_RFI": {
            "BTN": {"vs_CO": {"AA": {"3bet": 1.0}}},
        },
    },
}


# ---- RFI: blinds posted, non-blind seats untouched ----

ctx = get_drill_hand_rfi(RANGE, "UTG")["context"]
st = ctx["stacks"]

check("RFI SB stack = 99.5 (posted 0.5)", st["SB"] == round(STARTING_STACK - SB, 1) == 99.5)
check("RFI BB stack = 99.0 (posted 1.0)", st["BB"] == round(STARTING_STACK - BB, 1) == 99.0)
check("RFI UTG stack untouched = 100.0", st["UTG"] == 100.0)
check("RFI BTN stack untouched = 100.0", st["BTN"] == 100.0)
check("RFI pot = blinds = 1.5",          ctx["pot"] == round(SB + BB, 1) == 1.5)
check("RFI no open raiser yet",          ctx["open_raiser"] is None)


# ---- RFI where the hero IS a blind: the blind is still deducted ----

ctx_sb = get_drill_hand_rfi(RANGE, "SB")["context"]
check("RFI hero=SB: SB stack = 99.5",       ctx_sb["stacks"]["SB"] == 99.5)
check("RFI hero=SB: hero_stack = 99.5",     ctx_sb["hero_stack"] == 99.5)
check("RFI hero=SB: BB still posted 99.0",  ctx_sb["stacks"]["BB"] == 99.0)


# ---- vs_RFI: blinds posted AND the opener's raise deducted ----

ctx_vs = get_drill_hand_vs_rfi(RANGE, "BTN", "CO")["context"]
sv = ctx_vs["stacks"]

check("vs_RFI SB still 99.5",                  sv["SB"] == 99.5)
check("vs_RFI BB still 99.0",                  sv["BB"] == 99.0)
check("vs_RFI opener CO stack = 97.5",         sv["CO"] == round(STARTING_STACK - OPEN_SIZE, 1) == 97.5)
check("vs_RFI pot = 1.5 + open 2.5 = 4.0",     ctx_vs["pot"] == round(SB + BB + OPEN_SIZE, 1) == 4.0)
check("vs_RFI open_raiser = CO",               ctx_vs["open_raiser"] == "CO")
check("vs_RFI open_size = 2.5",                ctx_vs["open_size"] == OPEN_SIZE == 2.5)


print(f"\n{_passed} passed, {_failed} failed")
raise SystemExit(1 if _failed else 0)
