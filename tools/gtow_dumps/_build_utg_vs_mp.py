"""
Reconstructed minimal GTOW dump for vs_3bet UTG vs MP.

UTG open 2.5 -> HJ(MP) 3bet 8 -> folds back -> UTG to act (Fold/Call/Raise 21.5/Allin).
Page pasted in chat; this encodes the cells gtow_parse.py needs (non-folded left
"стратегия + EV" cells id="0_*" + history strip). Folded cells (class rtc_folded)
are omitted — the parser's cell regex skips them anyway. Run:

    python3 tools/gtow_dumps/_build_utg_vs_mp.py
    python3 tools/gtow_parse.py tools/gtow_dumps/utg_vs_mp.html --apply

Cell = (hand, [(colour, width%), ...], ev). Colours:
  r=rgb(240,60,60) R=rgb(125,31,31) (both -> 4bet bucket)  g=rgb(90,185,102) call  b=rgb(61,124,184) fold
Note R = Allin segment: merged into 4bet per schema (decision #13). Only first
size dimension matters to the parser, so we emit "W% 100%".
"""

import os

CLR = {
    "r": "rgb(240, 60, 60)",
    "R": "rgb(125, 31, 31)",
    "g": "rgb(90, 185, 102)",
    "b": "rgb(61, 124, 184)",
}

CELLS = [
    ("AA", [("r", 100)], "29.18"),
    ("AKs", [("r", 100)], "3.64"),
    ("AQs", [("r", 1.81), ("g", 100)], "0.28"),
    ("AJs", [("r", 47.74), ("g", 68.2), ("b", 100.01)], "0.01"),
    ("ATs", [("r", 25.92), ("g", 45.44), ("b", 100)], "-0.01"),
    ("A9s", [("r", 11.2), ("b", 100)], "0"),
    ("A8s", [("r", 9.07), ("b", 100)], "0"),
    ("A7s", [("r", 15.47), ("b", 100)], "0"),
    ("A6s", [("r", 8.34), ("b", 100)], "0"),
    ("A5s", [("r", 44.62), ("g", 57.28), ("b", 100)], "0"),
    ("A4s", [("r", 31.67), ("g", 31.69), ("b", 99.99)], "0"),
    ("A3s", [("r", 4.78), ("b", 100)], "0"),
    ("A2s", [("r", 0.13), ("b", 100)], "0"),
    ("AKo", [("R", 52.68), ("r", 80.29), ("g", 100)], "1.8"),
    ("KK", [("R", 7.37), ("r", 100)], "11.73"),
    ("KQs", [("r", 30.99), ("g", 53.25), ("b", 100)], "0"),
    ("KJs", [("r", 83.56), ("g", 94.17), ("b", 100)], "0.03"),
    ("KTs", [("r", 85.48), ("g", 86.31), ("b", 100)], "0.02"),
    ("K9s", [("r", 22.88), ("b", 100)], "0"),
    ("K8s", [("r", 2.69), ("b", 100)], "0"),
    ("K7s", [("r", 9.18), ("b", 100)], "0"),
    ("K6s", [("r", 15.92), ("b", 100)], "0"),
    ("K5s", [("r", 0.04), ("b", 100)], "0"),
    ("K4s", [("b", 100)], "0"),
    ("AQo", [("r", 31.78), ("b", 100)], "0"),
    ("KQo", [("b", 100)], "0"),
    ("QQ", [("R", 25.07), ("r", 49.93), ("g", 100)], "1.56"),
    ("Q9s", [("b", 100)], "0"),
    ("AJo", [("b", 100)], "0"),
    ("KJo", [("b", 100)], "0"),
    ("QJo", [("b", 100)], "0"),
    ("JJ", [("r", 11.78), ("g", 88.27), ("b", 100)], "0.01"),
    ("JTs", [("g", 19.46), ("b", 100)], "0"),
    ("ATo", [("b", 100)], "0"),
    ("KTo", [("b", 100)], "0"),
    ("TT", [("r", 4.84), ("g", 28.79), ("b", 100)], "0"),
    ("T9s", [("g", 99.51), ("b", 100)], "0.04"),
    ("A9o", [("b", 100)], "0"),
    ("99", [("g", 29.76), ("b", 100)], "0"),
    ("88", [("r", 1.53), ("g", 32.81), ("b", 100)], "0"),
    ("87s", [("g", 99.93), ("b", 100)], "0.17"),
    ("77", [("g", 47.12), ("b", 100)], "0"),
    ("76s", [("g", 99.99), ("b", 100)], "0.11"),
    ("66", [("g", 98.45), ("b", 100)], "0.03"),
    ("65s", [("g", 99.98), ("b", 100)], "0.09"),
    ("A5o", [("b", 100)], "0"),
    ("55", [("g", 99.97), ("b", 100)], "0.09"),
    ("54s", [("g", 99.99), ("b", 100)], "0.13"),
    ("44", [("g", 100)], "0.25"),
    ("33", [("g", 100)], "0.38"),
]

# UTG open 2.5, HJ 3bet 8, CO/BTN/SB/BB fold, UTG to act (hero).
HIST_SEATS = [
    (0, "UTG", "Raise 2.5"),
    (1, "HJ", "Raise 8"),
    (2, "CO", "Fold "),
    (3, "BTN", "Fold "),
    (4, "SB", "Fold "),
    (5, "BB", "Fold "),
]


def cell_html(hand, segs, ev):
    imgs = ", ".join(f"linear-gradient(to right, {CLR[c]}, {CLR[c]})" for c, _ in segs)
    sizes = ", ".join(f"{w}% 100%" for _, w in segs)
    return (
        '<div class="rtc rtc_strategy_ev_range_normalized ra_table_cell" '
        f'id="0_{hand}" data-tst="range_table_cell_0_{hand}" '
        f'style="background-image: {imgs}; background-size: {sizes};">'
        f'<div class="rtc_value"><span>{ev}</span></div>'
        f'<div class="rtc_title">{hand} </div></div>'
    )


def hist_html():
    out = []
    for n, pos, act in HIST_SEATS:
        out.append(
            f'<div class="hspot-card" data-tst="hs_{n}_preflop_{pos}">'
            '<div class="hspotcrd_action hspotcrd_action_active">'
            f'<div class="hspotcrd_action_text">{act}</div></div></div>'
        )
    out.append('<div class="hspot-card" data-tst="hs_6_preflop_UTG_active"></div>')
    return "".join(out)


def main():
    cells = "\n".join(cell_html(*c) for c in CELLS)
    html = (
        "<!doctype html><html><body>\n"
        '<div class="hspotscont_inner_scrollable">' + hist_html() + "</div>\n"
        '<div class="ra_table ra_table-container" data-tst="range_table_left">\n'
        + cells +
        "\n</div>\n</body></html>\n"
    )
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utg_vs_mp.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out_path}  ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
