"""
test_gtow_tools.py — unit tests for the GTOW batch-import tooling:
  gtow_coverage   (expected matrix + coverage diff)
  gtow_autoconfig (derive config option maps from spots)
  gtow_import_all (stale-dump SHRINK guard)
  gtow_sort_downloads (limit token from filename)

Plain asserts, run as a script (no pytest):  python3 tools/test_gtow_tools.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtow_coverage as cov
import gtow_autoconfig as ac
import gtow_import_all as ia
import gtow_sort_downloads as sd

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {name}")


SIXMAX = {
    "positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
    "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
}


def _pack(spots, config=None):
    return {"config": config or dict(SIXMAX), "spots": spots}


def test_expected_matrix():
    exp = cov.expected_matrix(SIXMAX)
    check("RFI expected = 5 openers", exp["RFI"] == SIXMAX["rfi_positions"])
    # vs_RFI: hero faces openers seated before; UTG has none, BB faces all five.
    check("vs_RFI UTG absent (first to act)", "UTG" not in exp["vs_RFI"])
    check("vs_RFI MP faces UTG", exp["vs_RFI"]["MP"] == ["UTG"])
    check("vs_RFI BB faces all openers",
          exp["vs_RFI"]["BB"] == ["UTG", "MP", "CO", "BTN", "SB"])
    # vs_3bet: opener faces a 3-bet from any LATER seat (incl. BB).
    check("vs_3bet UTG vs five later seats",
          exp["vs_3bet"]["UTG"] == ["MP", "CO", "BTN", "SB", "BB"])
    check("vs_3bet SB vs BB only", exp["vs_3bet"]["SB"] == ["BB"])
    check("vs_3bet BB absent (can't open)", "BB" not in exp["vs_3bet"])


def test_coverage_missing():
    # Pack has RFI for UTG only, one vs_RFI pair, one squeeze.
    pack = _pack({
        "RFI": {"UTG": {"AA": {"open": 1.0}}, "MP": {}},   # MP empty -> not covered
        "vs_RFI": {"MP": {"vs_UTG": {"AA": {"3bet": 1.0}}}},
        "squeeze": {"BB": {"BTN-SB": {"AA": {"squeeze": 1.0}}}},
    })
    rep = cov.coverage(pack)
    check("RFI have only UTG", rep["heads_up"]["RFI"]["have"] == ["UTG"])
    check("RFI missing includes MP", "MP" in rep["heads_up"]["RFI"]["missing"])
    check("vs_RFI MP/UTG counted as have",
          ("MP", "UTG") in rep["heads_up"]["vs_RFI"]["have"])
    check("vs_RFI CO/UTG counted as missing",
          ("CO", "UTG") in rep["heads_up"]["vs_RFI"]["missing"])
    check("squeeze present reported",
          ("BB", "BTN-SB") in rep["multiway"]["squeeze"])
    # The flat remaining list mixes spots; ensure RFI MP shows up.
    check("missing list has RFI MP", ("RFI", "MP", None) in rep["missing"])


def test_derive_options():
    pack = _pack({
        "vs_RFI": {"BTN": {"vs_CO": {"AA": {"3bet": 1.0}},
                            "vs_MP": {"AA": {"3bet": 1.0}},
                            "vs_UTG": {}}},          # empty -> excluded
        "vs_3bet": {"UTG": {"vs_BTN": {"AA": {"4bet": 1.0}}}},
        "squeeze": {"BB": {"BTN-SB": {"AA": {"squeeze": 1.0}}}},
    })
    opts = ac.derive_options(pack)
    # bare positions, sorted by seating (MP before CO), empty pair dropped
    check("vs_rfi_options bare + sorted",
          opts["vs_rfi_options"]["BTN"] == ["MP", "CO"])
    check("vs_3bet_options derived",
          opts["vs_3bet_options"]["UTG"] == ["BTN"])
    check("squeeze_options keeps bare lineup",
          opts["squeeze_options"]["BB"] == ["BTN-SB"])
    check("no spurious keys for absent spots", "vs_4bet_options" not in opts)


def test_derive_options_idempotent():
    pack = _pack({"vs_RFI": {"BB": {"vs_BTN": {"AA": {"3bet": 1.0}}}}})
    opts = ac.derive_options(pack)
    ac.apply_options(pack, opts)
    again = ac.derive_options(pack)
    check("derive stable after apply", opts == again)


def test_shrink_guard():
    pack = _pack({"RFI": {"SB": {h: {"open": 1.0} for h in
                                 ["AA", "KK", "QQ", "JJ", "TT"]}}})  # 5 hands
    # incoming dump with only 3 hands -> a shrink
    parsed = [("stale.html", "RFI", "SB", None, "—",
               {"AA": {"open": 1.0}, "KK": {"open": 1.0}, "QQ": {"open": 1.0}}, {})]
    shrinks = ia.warn_overwrites(parsed, pack)
    check("shrink detected (5 -> 3)", shrinks == 1)
    # incoming dump that grows -> no shrink
    grow = [("fresh.html", "RFI", "SB", None, "—",
             {h: {"open": 1.0} for h in ["AA", "KK", "QQ", "JJ", "TT", "99", "88"]}, {})]
    check("growth is not a shrink", ia.warn_overwrites(grow, pack) == 0)
    # brand-new spot -> no warning
    new = [("new.html", "vs_3bet", "UTG", "BTN", "vs_BTN", {"AA": {"4bet": 1.0}}, {})]
    check("new spot is not a shrink", ia.warn_overwrites(new, pack) == 0)


def test_limit_of():
    check("new-format limit", sd.limit_of("gtow_nl10_BB_R2.5-C_8033.html") == "nl10")
    check("forced limit wins",
          sd.limit_of("gtow_UTG_123.html", forced="NL25") == "nl25")
    check("non-gtow file -> None", sd.limit_of("notes.txt") is None)


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
