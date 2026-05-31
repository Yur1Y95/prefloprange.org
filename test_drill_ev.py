"""
Tests for the GTO EV path in the preflop drill (RFI only, Stage 1).

Covers:
- range_engine.get_ev: optional `ev` block lookup, all the "no data" exits.
- drill_engine.get_drill_hand_rfi: attaches `gto_ev` to the payload.
- drill_engine.check_answer: locked display rules — EV only on a correct open,
  None on correct fold / wrong / range without EV.

Run as a plain script (no pytest):  python3 test_drill_ev.py
"""

from range_engine import get_ev
from drill_engine import get_drill_hand_rfi, check_answer

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


# ---- fixtures ----

# Minimal range file WITH an ev block. UTG opens AA (always) and A5s (mixed),
# folds 72o. EV exists for AA and A5s but NOT for KK (open hand, missing EV).
RANGE_WITH_EV = {
    "config": {"positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
               "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"]},
    "spots": {
        "RFI": {
            "UTG": {
                "AA": {"open": 1.0},
                "KK": {"open": 1.0},
                "A5s": {"open": 0.5},
            }
        }
    },
    "ev": {
        "RFI": {
            "UTG": {"AA": 2.31, "A5s": 0.42}
        }
    },
}

# Same strategy, no ev block at all (legacy / incomplete range).
RANGE_NO_EV = {
    "config": RANGE_WITH_EV["config"],
    "spots": RANGE_WITH_EV["spots"],
}


def make_drill_hand(hand, correct_action, gto_ev):
    """Hand-built RFI drill payload, bypassing the random generator."""
    return {
        "spot": "RFI",
        "hero_position": "UTG",
        "villain_position": None,
        "hand": hand,
        "card1": "A♠", "card2": "A♥",
        "frequency": 1.0,
        "actions": {"open": 1.0},
        "rng": 0,
        "correct_action": correct_action,
        "available_actions": ["open", "fold"],
        "gto_ev": gto_ev,
    }


# ---- get_ev ----

def test_get_ev():
    print("test_get_ev")
    check("AA has EV 2.31",        get_ev(RANGE_WITH_EV, "RFI", "UTG", "AA") == 2.31)
    check("A5s has EV 0.42",       get_ev(RANGE_WITH_EV, "RFI", "UTG", "A5s") == 0.42)
    check("KK missing EV -> None", get_ev(RANGE_WITH_EV, "RFI", "UTG", "KK") is None)
    check("72o missing -> None",   get_ev(RANGE_WITH_EV, "RFI", "UTG", "72o") is None)
    check("unknown position -> None", get_ev(RANGE_WITH_EV, "RFI", "CO", "AA") is None)
    check("no ev block -> None",   get_ev(RANGE_NO_EV, "RFI", "UTG", "AA") is None)
    check("unknown spot -> None",  get_ev(RANGE_WITH_EV, "vs_RFI", "UTG", "AA") is None)


# ---- get_drill_hand_rfi attaches gto_ev ----

def test_generator_attaches_ev():
    print("test_generator_attaches_ev")
    # Random hand each call; loop enough to hit AA, KK and a fold hand.
    seen = {}
    for _ in range(4000):
        dh = get_drill_hand_rfi(RANGE_WITH_EV, "UTG")
        seen.setdefault(dh["hand"], dh["gto_ev"])
    check("payload always has gto_ev key",
          all(get_drill_hand_rfi(RANGE_WITH_EV, "UTG").get("gto_ev", "MISSING") != "MISSING"
              for _ in range(20)))
    check("AA gto_ev == 2.31", seen.get("AA") == 2.31)
    check("KK gto_ev is None (open hand, no EV data)", seen.get("KK") is None)
    # a hand outside the range, e.g. 72o, must have None
    if "72o" in seen:
        check("72o gto_ev is None", seen["72o"] is None)


# ---- check_answer display rules ----

def test_correct_open_with_ev():
    print("test_correct_open_with_ev")
    dh = make_drill_hand("AA", "open", 2.31)
    r = check_answer(dh, "open")
    check("correct", r["correct"] is True)
    check("ev == 2.31", r["ev"] == 2.31)
    check("message plain 'Correct — open.'", r["message"] == "Correct — open.")


def test_correct_open_without_ev():
    print("test_correct_open_without_ev")
    dh = make_drill_hand("KK", "open", None)
    r = check_answer(dh, "open")
    check("correct", r["correct"] is True)
    check("ev is None", r["ev"] is None)
    check("message 'Correct — open.'", r["message"] == "Correct — open.")


def test_correct_fold_no_ev():
    print("test_correct_fold_no_ev")
    dh = make_drill_hand("72o", "fold", None)
    r = check_answer(dh, "fold")
    check("correct", r["correct"] is True)
    check("ev is None", r["ev"] is None)
    check("message 'Correct — fold.'", r["message"] == "Correct — fold.")


def test_wrong_no_ev():
    print("test_wrong_no_ev")
    # Should have opened AA (with EV), but folded -> wrong, no EV shown.
    dh = make_drill_hand("AA", "open", 2.31)
    r = check_answer(dh, "fold")
    check("not correct", r["correct"] is False)
    check("ev is None on wrong", r["ev"] is None)
    check("message names correct action",
          r["message"] == "Wrong — correct action: open.")

    # Wrongly opened a fold hand -> wrong, no EV.
    dh2 = make_drill_hand("72o", "fold", None)
    r2 = check_answer(dh2, "open")
    check("wrong open: not correct", r2["correct"] is False)
    check("wrong open: ev None", r2["ev"] is None)
    check("wrong open: message", r2["message"] == "Wrong — correct action: fold.")


def test_timeout_unchanged():
    print("test_timeout_unchanged")
    dh = make_drill_hand("AA", "open", 2.31)
    r = check_answer(dh, "fold", is_timeout=True)
    check("timeout not correct", r["correct"] is False)
    check("timeout flagged", r["is_timeout"] is True)


if __name__ == "__main__":
    test_get_ev()
    test_generator_attaches_ev()
    test_correct_open_with_ev()
    test_correct_open_without_ev()
    test_correct_fold_no_ev()
    test_wrong_no_ev()
    test_timeout_unchanged()
    print(f"\n{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)
