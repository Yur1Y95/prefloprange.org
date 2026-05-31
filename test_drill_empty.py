"""
P-011 regression tests: empty/absent spots must degrade cleanly, not crash.

- get_*_range on a config position with no data returns {} (no KeyError).
- get_drill_hand_* returns None for an empty range (caller -> 404).
- filled positions still return a real hand.

Run: python3 test_drill_empty.py
"""

import json
import os

from range_engine import get_rfi_range, get_vs_rfi_range, get_vs_3bet_range
from drill_engine import (
    get_drill_hand_rfi,
    get_drill_hand_vs_rfi,
    get_drill_hand_vs_3bet,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_failures = []


def check(label, cond):
    status = "ok  " if cond else "FAIL"
    if not cond:
        _failures.append(label)
    print(f"  {status} {label}")


def _load(name):
    with open(os.path.join(BASE_DIR, "data", name)) as f:
        return json.load(f)


def test_soft_lookups_no_keyerror():
    # Minimal range_data: config offers positions, spots are empty.
    data = {
        "config": {
            "positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
            "vs_rfi_options": {"BTN": ["UTG"]},
            "vs_3bet_options": {"UTG": ["BTN"]},
        },
        "spots": {"RFI": {}, "vs_RFI": {}, "vs_3bet": {}},
    }
    check("get_rfi_range missing -> {}", get_rfi_range(data, "CO") == {})
    check("get_vs_rfi_range missing -> {}", get_vs_rfi_range(data, "BTN", "UTG") == {})
    check("get_vs_3bet_range missing -> {}", get_vs_3bet_range(data, "UTG", "BTN") == {})

    # No 'spots' key at all must also not raise.
    check("get_rfi_range no spots key -> {}", get_rfi_range({}, "UTG") == {})


def test_drill_hand_none_on_empty():
    data = {
        "config": {
            "positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
            "vs_rfi_options": {"BTN": ["UTG"]},
            "vs_3bet_options": {"UTG": ["BTN"]},
        },
        "spots": {"RFI": {}, "vs_RFI": {}, "vs_3bet": {}},
    }
    check("RFI empty -> None", get_drill_hand_rfi(data, "CO") is None)
    check("vs_RFI empty -> None", get_drill_hand_vs_rfi(data, "BTN", "UTG") is None)
    check("vs_3bet empty -> None", get_drill_hand_vs_3bet(data, "UTG", "BTN") is None)


def test_real_packs():
    # NL25GTOW: RFI filled (UTG..SB), vs_RFI/vs_3bet empty.
    gtow = _load("NL25GTOW.json")
    check("NL25GTOW RFI UTG -> hand", get_drill_hand_rfi(gtow, "UTG") is not None)
    check("NL25GTOW vs_RFI BTN<UTG -> None", get_drill_hand_vs_rfi(gtow, "BTN", "UTG") is None)
    check("NL25GTOW vs_3bet -> None", get_drill_hand_vs_3bet(gtow, "UTG", "BTN") is None)

    # cash_6max_100bb: vs_RFI filled.
    cash = _load("cash_6max_100bb.json")
    q = get_drill_hand_vs_rfi(cash, "BTN", "UTG")
    check("cash_6max vs_RFI BTN<UTG -> hand", q is not None)
    check("cash_6max vs_RFI pot = 4.0", q is not None and q["context"]["pot"] == 4.0)


if __name__ == "__main__":
    print("test_soft_lookups_no_keyerror");  test_soft_lookups_no_keyerror()
    print("test_drill_hand_none_on_empty");  test_drill_hand_none_on_empty()
    print("test_real_packs");                test_real_packs()
    if _failures:
        print(f"\n{len(_failures)} FAILED: {_failures}")
        raise SystemExit(1)
    print("\nAll P-011 stage-1 tests passed.")
