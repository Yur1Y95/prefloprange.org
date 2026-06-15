"""
Reconstructed minimal GTOW dump for vs_3bet UTG vs CO.

UTG open 2.5 -> CO 3bet 8 -> folds back -> UTG to act (Fold/Call/Raise 21.5/Allin).
Non-folded left "стратегия + EV" cells id="0_*" + history strip. Run:

    python3 tools/gtow_dumps/_build_utg_vs_co.py
    python3 tools/gtow_parse.py tools/gtow_dumps/utg_vs_co.html --apply

Cell = (hand, [(colour, width%), ...], ev). r/R -> 4bet bucket, g call, b fold.
"""

import os

CLR = {
    "r": "rgb(240, 60, 60)",
    "R": "rgb(125, 31, 31)",
    "g": "rgb(90, 185, 102)",
    "b": "rgb(61, 124, 184)",
}

CELLS = [
    ("AA", [("r", 100)], "29.31"),
    ("AKs", [("r", 100)], "3.78"),
    ("AQs", [("r", 0.75), ("g", 100)], "0.4"),
    ("AJs", [("r", 70.36), ("g", 97.51), ("b", 100)], "0.05"),
    ("ATs", [("r", 15.78), ("g", 36.18), ("b", 100)], "0"),
    ("A9s", [("r", 7.93), ("b", 100)], "0"),
    ("A8s", [("r", 7.16), ("b", 100)], "0"),
    ("A7s", [("r", 17.91), ("b", 100)], "0"),
    ("A6s", [("r", 3.42), ("b", 100)], "0"),
    ("A5s", [("r", 39.72), ("g", 54.56), ("b", 100)], "-0.01"),
    ("A4s", [("r", 32.24), ("b", 100)], "0"),
    ("A3s", [("r", 5.1), ("b", 100)], "0"),
    ("A2s", [("b", 100)], "0"),
    ("AKo", [("R", 43.15), ("r", 79.74), ("g", 100)], "1.92"),
    ("KK", [("R", 5.76), ("r", 100)], "12.12"),
    ("KQs", [("r", 31.75), ("g", 61.72), ("b", 100)], "0"),
    ("KJs", [("r", 93.69), ("g", 99.99), ("b", 100)], "0.14"),
    ("KTs", [("r", 79.7), ("g", 83.41), ("b", 100)], "0.02"),
    ("K9s", [("r", 22.99), ("b", 100)], "0"),
    ("K8s", [("r", 6.38), ("b", 100)], "0"),
    ("K7s", [("r", 11.39), ("b", 100)], "0"),
    ("K6s", [("r", 16.73), ("b", 100)], "0"),
    ("K5s", [("r", 5.06), ("b", 100)], "0"),
    ("K4s", [("b", 100)], "0"),
    ("AQo", [("r", 41.17), ("b", 100)], "0"),
    ("KQo", [("b", 100)], "0"),
    ("QQ", [("R", 20.01), ("r", 54.87), ("g", 100)], "1.81"),
    ("QJs", [("b", 100)], "0"),
    ("QTs", [("b", 100)], "0"),
    ("Q9s", [("b", 100)], "0"),
    ("AJo", [("b", 100)], "0"),
    ("KJo", [("b", 100)], "0"),
    ("QJo", [("b", 100)], "0"),
    ("JJ", [("r", 19.54), ("g", 99.99), ("b", 100)], "0.13"),
    ("JTs", [("g", 21.99), ("b", 100)], "0"),
    ("ATo", [("b", 100)], "0"),
    ("KTo", [("b", 100)], "0"),
    ("TT", [("r", 0.39), ("g", 29.44), ("b", 100)], "0"),
    ("T9s", [("g", 99.61), ("b", 100)], "0.02"),
    ("A9o", [("b", 100)], "0"),
    ("99", [("r", 0.89), ("g", 35.74), ("b", 100)], "0"),
    ("88", [("r", 0.74), ("g", 32.96), ("b", 100)], "0"),
    ("87s", [("g", 99.98), ("b", 100)], "0.17"),
    ("77", [("g", 50.85), ("b", 100)], "0"),
    ("76s", [("g", 99.99), ("b", 100)], "0.16"),
    ("66", [("g", 98.32), ("b", 100)], "0.04"),
    ("65s", [("g", 99.93), ("b", 100)], "0.12"),
    ("A5o", [("b", 100)], "0"),
    ("55", [("g", 99.96), ("b", 100)], "0.12"),
    ("54s", [("g", 99.97), ("b", 100)], "0.17"),
    ("44", [("g", 100)], "0.26"),
    ("33", [("g", 99.99), ("b", 100)], "0.4"),
]

# UTG open 2.5, HJ fold, CO 3bet 8, BTN/SB/BB fold, UTG to act (hero).
HIST_SEATS = [
    (0, "UTG", "Raise 2.5"),
    (1, "HJ", "Fold "),
    (2, "CO", "Raise 8"),
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
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utg_vs_co.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out_path}  ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
