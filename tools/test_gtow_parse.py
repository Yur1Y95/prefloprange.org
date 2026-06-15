"""
Tests for gtow_parse, built from REAL cells copied verbatim out of the
CO-vs-UTG dump (the one already stored in NL25GTOW.json as spots.vs_RFI.CO.vs_UTG).
Run: python3 tools/test_gtow_parse.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))           # tools/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
import gtow_parse as gw  # noqa: E402
import range_engine as rng  # noqa: E402

# Minimal but faithful: real class/id/style/value strings from the dump. The
# parser only reads class+id+style+.rtc_value, so trimming the inner markup
# does not change what it sees.
CELL = (
    '<div class="rtc rtc_strategy_ev_range_normalized ra_table_cell" id="0_{hand}" '
    'data-tst="range_table_cell_0_{hand}" style="background-image: {img}; '
    'background-size: {size};"><div class="rtc_value"><span>{ev}</span></div>'
    '<div class="rtc_title">{hand} </div></div>'
)
DARK = "linear-gradient(to right, rgb(125, 31, 31), rgb(125, 31, 31))"
RED = "linear-gradient(to right, rgb(240, 60, 60), rgb(240, 60, 60))"
GREEN = "linear-gradient(to right, rgb(90, 185, 102), rgb(90, 185, 102))"
BLUE = "linear-gradient(to right, rgb(61, 124, 184), rgb(61, 124, 184))"

CELLS = [
    # hand, image layers (top-first), sizes (first value per layer), ev
    ("AA",  f"{DARK}, {RED}",          "0.06% 100%, 100% 100%",              "14.73"),
    ("QQ",  f"{RED}, {GREEN}",         "81.15% 100%, 100% 100%",             "1.98"),
    ("AQs", f"{RED}, {GREEN}",         "58.85% 100%, 100% 100%",             "0.46"),
    ("ATs", f"{RED}, {GREEN}, {BLUE}", "52.69% 100%, 95.41% 100%, 100% 100%", "0.02"),
    ("A9s", f"{RED}, {GREEN}, {BLUE}", "47.79% 100%, 53.38% 100%, 100% 100%", "0"),
    ("QJs", f"{RED}, {GREEN}, {BLUE}", "15.59% 100%, 17.42% 100%, 100.01% 100%", "0"),
    ("A2s", f"{RED}, {BLUE}",          "0.14% 100%, 100% 100%",              "0"),
    ("55",  f"{GREEN}, {BLUE}",        "5.24% 100%, 100% 100%",              "0"),
    ("QTs", f"{BLUE}",                 "100% 100%",                          "0"),
]

# Full 6-seat strip: UTG opened, HJ folded, CO to act (hero), and the future
# seats BTN/SB/BB carry only an "apply action" prompt (no chosen action).
HISTORY = (
    '<div data-tst="hs_0_preflop_UTG"><div class="hspotcrd_action">'
    '<div class="hspotcrd_action_text">Fold </div></div>'
    '<div class="hspotcrd_action hspotcrd_action_active">'
    '<div class="hspotcrd_action_text">Raise 2.5</div></div>'
    '<div class="hspotcrd_action"><div class="hspotcrd_action_text">Allin 100</div></div></div>'
    '<div data-tst="hs_1_preflop_HJ"><div class="hspotcrd_action hspotcrd_action_active">'
    '<div class="hspotcrd_action_text">Fold </div></div></div>'
    '<div data-tst="hs_2_preflop_CO_active"><div class="hspotcrd_action_prompt">'
    'Применить действие</div></div>'
    '<div data-tst="hs_3_preflop_BTN"><div class="hspotcrd_action_prompt">'
    'Применить действие</div></div>'
    '<div data-tst="hs_4_preflop_SB"><div class="hspotcrd_action_prompt">'
    'Применить действие</div></div>'
    '<div data-tst="hs_5_preflop_BB"><div class="hspotcrd_action_prompt">'
    'Применить действие</div></div>'
    '<i class="mdi mdi-chevron-right" data-tst="hs_arrow_right"></i>'
)

# Real right-table ("EV-only") cells: id "1_*", placeholder var() colours, plus a
# folded variant with no style/value. The parser must skip ALL of these.
RIGHT_TABLE = (
    '<div class="rtc rtc_ev_range_normalized ra_table_cell" id="1_AA" '
    'data-tst="range_table_cell_1_AA" style="background-image: '
    'linear-gradient(to right, var(--clr-eveqeqrbl0), var(--clr-eveqeqrbl0)); '
    'background-size: 100% 99.98%;"><div class="rtc_value"><span>0</span></div>'
    '<div class="rtc_title">AA </div></div>'
    '<div class="rtc rtc_folded rtc_ev_range_normalized ra_table_cell" id="1_K3s" '
    'data-tst="range_table_cell_1_K3s"><div class="rtc_title">K3s </div></div>'
)

HTML = HISTORY + "".join(
    CELL.format(hand=h, img=img, size=sz, ev=ev) for h, img, sz, ev in CELLS
) + RIGHT_TABLE


# --- Squeeze + multiway fixtures (Stage 2a) -------------------------------- #
def _seat(idx, pos, action=None):
    """One history-strip seat. action=None marks the active hero seat (a prompt,
    no chosen action); otherwise the seat shows that action as its active one."""
    if action is None:
        return (f'<div data-tst="hs_{idx}_preflop_{pos}_active">'
                '<div class="hspotcrd_action_prompt">Применить действие</div></div>')
    return (f'<div data-tst="hs_{idx}_preflop_{pos}">'
            '<div class="hspotcrd_action hspotcrd_action_active">'
            f'<div class="hspotcrd_action_text">{action}</div></div></div>')


# Squeeze node: BTN opens 2.5, SB cold-calls, BB is hero. Reuses the same hand
# cells, so the red bucket must now surface as "squeeze" (not "3bet").
SQUEEZE_HISTORY = (
    _seat(0, "UTG", "Fold ") + _seat(1, "HJ", "Fold ") + _seat(2, "CO", "Fold ")
    + _seat(3, "BTN", "Raise 2.5") + _seat(4, "SB", "Call ") + _seat(5, "BB")
)
SQUEEZE_HTML = SQUEEZE_HISTORY + "".join(
    CELL.format(hand=h, img=img, size=sz, ev=ev) for h, img, sz, ev in CELLS
)

# 0 raisers + 1 caller -> limped pot (vs_limp): unsupported -> must refuse.
LIMP_HISTORY = (
    _seat(0, "UTG", "Fold ") + _seat(1, "HJ", "Fold ") + _seat(2, "CO", "Fold ")
    + _seat(3, "BTN", "Fold ") + _seat(4, "SB", "Call ") + _seat(5, "BB")
)
# 2 raisers + 1 caller -> squeeze over a 3-bet: unsupported -> must refuse.
SQUEEZE_OVER_3BET_HISTORY = (
    _seat(0, "UTG", "Raise 2.5") + _seat(1, "HJ", "Raise 10")
    + _seat(2, "CO", "Call ") + _seat(3, "BTN")
)

# vs_squeeze node: UTG opens 2.25, HJ + CO cold-call, BB squeezes 13, action back
# to the opener UTG (hero). 2 raisers + 2 callers, the squeeze is the LAST action
# -> vs_squeeze (vs the squeeze-over-3bet case whose last action is a Call). The
# opener appears twice in the strip: as the seat-0 raise and as the active hero.
# Reuses the same hand cells -> the red bucket must now surface as "4bet".
VS_SQUEEZE_HISTORY = (
    _seat(0, "UTG", "Raise 2.25") + _seat(1, "HJ", "Call ") + _seat(2, "CO", "Call ")
    + _seat(3, "BTN", "Fold ") + _seat(4, "SB", "Fold ") + _seat(5, "BB", "Raise 13")
    + _seat(6, "UTG")
)
VS_SQUEEZE_HTML = VS_SQUEEZE_HISTORY + "".join(
    CELL.format(hand=h, img=img, size=sz, ev=ev) for h, img, sz, ev in CELLS
)

# 2 raisers + 1 caller, squeeze IS last, but hero (BTN) is a cold-caller, not the
# opener (UTG) -> out of v1 scope -> must refuse.
VS_SQUEEZE_CALLER_HISTORY = (
    _seat(0, "UTG", "Raise 2.5") + _seat(1, "MP", "Call ")
    + _seat(2, "CO", "Raise 11") + _seat(3, "BTN")
)


def test_right_table_ignored():
    # Only the 9 left-table (0_*) cells are parsed; the right table is invisible.
    hands = [hand for hand, _, _ in gw.parse_matrix(HTML)]
    assert hands == [h for h, *_ in CELLS], hands
    assert "AA" in hands and hands.count("AA") == 1


def test_detect_spot():
    spot, hero, villain = gw.detect_spot(HTML)
    assert (spot, hero, villain) == ("vs_RFI", "CO", "UTG"), (spot, hero, villain)


def test_strategy_matches_ground_truth():
    strategy, ev = gw.build_entries(HTML, "vs_RFI")
    assert strategy["AA"] == {"3bet": 1.0}, strategy["AA"]
    assert strategy["QQ"] == {"3bet": 0.81, "call": 0.19}, strategy["QQ"]
    assert strategy["AQs"] == {"3bet": 0.59, "call": 0.41}, strategy["AQs"]
    assert strategy["ATs"] == {"3bet": 0.53, "call": 0.43}, strategy["ATs"]
    assert strategy["A9s"] == {"3bet": 0.48, "call": 0.06}, strategy["A9s"]
    assert strategy["55"] == {"call": 0.05}, strategy["55"]
    # A2s raise is 0.14% -> rounds to 0.00 -> dropped -> pure fold -> absent
    assert "A2s" not in strategy
    # QTs is 100% fold -> absent
    assert "QTs" not in strategy


def test_qjs_is_more_precise_than_manual():
    # Manual transcription stored QJs as {'3bet': 0.16} and missed the 1.83%
    # call sliver. The parser keeps it (0.02) — same 3bet, finer call.
    strategy, _ = gw.build_entries(HTML, "vs_RFI")
    assert strategy["QJs"] == {"3bet": 0.16, "call": 0.02}, strategy["QJs"]


def test_ev_only_nonzero():
    _, ev = gw.build_entries(HTML, "vs_RFI")
    assert ev["AA"] == 14.73
    assert ev["QQ"] == 1.98
    assert ev["ATs"] == 0.02
    assert "A9s" not in ev  # displayed EV 0 -> excluded
    assert "QTs" not in ev


def test_spot_changes_raise_action_name():
    # Same bars, different spot -> raise bucket renamed.
    s_rfi, _ = gw.build_entries(HTML, "RFI")
    s_4b, _ = gw.build_entries(HTML, "vs_3bet")
    assert s_rfi["AA"] == {"open": 1.0}
    assert s_4b["AA"] == {"4bet": 1.0}


def test_detect_squeeze():
    # 1 raiser (BTN) + 1 caller (SB) before hero -> squeeze, villain is the pair.
    spot, hero, villain = gw.detect_spot(SQUEEZE_HTML)
    assert (spot, hero, villain) == ("squeeze", "BB", "BTN-SB"), (spot, hero, villain)


def test_squeeze_strategy_and_ev():
    strategy, ev = gw.build_entries(SQUEEZE_HTML, "squeeze")
    # Same bars as the vs_RFI fixture, but the red bucket is now "squeeze".
    assert strategy["AA"] == {"squeeze": 1.0}, strategy["AA"]
    assert strategy["QQ"] == {"squeeze": 0.81, "call": 0.19}, strategy["QQ"]
    assert strategy["55"] == {"call": 0.05}, strategy["55"]
    assert "QTs" not in strategy            # pure fold dropped
    assert ev["AA"] == 14.73 and "QTs" not in ev


def test_refuse_limped_pot():
    # 0 raisers + 1 caller -> vs_limp: refuse instead of mislabelling (P-026).
    try:
        gw.detect_spot(LIMP_HISTORY)
        assert False, "expected UnsupportedNode for a limped pot"
    except gw.UnsupportedNode:
        pass


def test_refuse_squeeze_over_3bet():
    # 2 raisers + 1 caller -> squeeze over a 3-bet: refuse (no schema yet).
    try:
        gw.detect_spot(SQUEEZE_OVER_3BET_HISTORY)
        assert False, "expected UnsupportedNode for squeeze-over-3bet"
    except gw.UnsupportedNode:
        pass


def test_detect_vs_squeeze():
    # 2 raisers + caller(s), squeeze last, hero == opener -> vs_squeeze. Villain
    # is the lineup "<opener>-<squeezer>-<caller(s)>". The HJ caller is aliased to
    # MP (GTOW names the 2nd seat HJ), so the lineup reads UTG-BB-MP-CO.
    spot, hero, villain = gw.detect_spot(VS_SQUEEZE_HTML)
    assert (spot, hero, villain) == ("vs_squeeze", "UTG", "UTG-BB-MP-CO"), \
        (spot, hero, villain)


def test_vs_squeeze_strategy_and_ev():
    strategy, ev = gw.build_entries(VS_SQUEEZE_HTML, "vs_squeeze")
    # Same bars as the vs_RFI fixture, but the red bucket is now "4bet".
    assert strategy["AA"] == {"4bet": 1.0}, strategy["AA"]
    assert strategy["QQ"] == {"4bet": 0.81, "call": 0.19}, strategy["QQ"]
    assert strategy["55"] == {"call": 0.05}, strategy["55"]
    assert "QTs" not in strategy            # pure fold dropped
    assert ev["AA"] == 14.73 and "QTs" not in ev


def test_refuse_vs_squeeze_caller():
    # Squeeze is last, but hero is a cold-caller (not the opener) -> v1 refuses
    # rather than storing it under the wrong range (P-026).
    try:
        gw.detect_spot(VS_SQUEEZE_CALLER_HISTORY)
        assert False, "expected UnsupportedNode for a caller facing a squeeze"
    except gw.UnsupportedNode:
        pass


def test_range_engine_reads_vs_squeeze():
    # End-to-end: parse -> store under the lineup key -> read back via the engine.
    strategy, ev = gw.build_entries(VS_SQUEEZE_HTML, "vs_squeeze")
    data = {"spots": {"vs_squeeze": {"UTG": {"UTG-BB-MP-CO": strategy}}},
            "ev": {"vs_squeeze": {"UTG": {"UTG-BB-MP-CO": ev}}}}
    expanded = rng.get_vs_squeeze_range(data, "UTG", "UTG-BB-MP-CO")
    assert expanded["AA"] == {"4bet": 1.0}, expanded["AA"]
    assert rng.get_vs_squeeze_range(data, "UTG", "UTG-CO-MP") == {}   # missing -> {}
    assert rng.get_ev(data, "vs_squeeze", "UTG", "AA", "UTG-BB-MP-CO") == 14.73
    assert rng.get_ev(data, "vs_squeeze", "UTG", "QTs", "UTG-BB-MP-CO") is None
    assert rng.get_ev(data, "vs_squeeze", "UTG", "AA", None) is None  # no lineup -> None


def test_range_engine_reads_squeeze():
    # End-to-end: parse -> store under the pair key -> read back via the engine.
    strategy, ev = gw.build_entries(SQUEEZE_HTML, "squeeze")
    data = {"spots": {"squeeze": {"BB": {"BTN-SB": strategy}}},
            "ev": {"squeeze": {"BB": {"BTN-SB": ev}}}}
    expanded = rng.get_squeeze_range(data, "BB", "BTN-SB")
    assert expanded["AA"] == {"squeeze": 1.0}, expanded["AA"]
    assert rng.get_squeeze_range(data, "BB", "CO-SB") == {}     # missing pair -> {}
    assert rng.get_ev(data, "squeeze", "BB", "AA", "BTN-SB") == 14.73
    assert rng.get_ev(data, "squeeze", "BB", "QTs", "BTN-SB") is None  # no EV entry
    assert rng.get_ev(data, "squeeze", "BB", "AA", None) is None       # no pair -> None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
