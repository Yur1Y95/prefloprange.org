"""
Reconstructed minimal GTOW dump for vs_3bet UTG vs BTN.

UTG open 2.5 -> BTN 3bet 8 -> folds back -> UTG to act. Non-folded left cells + history.
    python3 tools/gtow_dumps/_build_utg_vs_btn.py
    python3 tools/gtow_parse.py tools/gtow_dumps/utg_vs_btn.html --apply
r/R -> 4bet bucket, g call, b fold.
"""

import os

CLR = {"r": "rgb(240, 60, 60)", "R": "rgb(125, 31, 31)",
       "g": "rgb(90, 185, 102)", "b": "rgb(61, 124, 184)"}

CELLS = [
    ("AA", [("r", 100)], "29.75"),
    ("AKs", [("r", 100)], "3.51"),
    ("AQs", [("r", 0.01), ("g", 100)], "0.42"),
    ("AJs", [("r", 66.06), ("g", 99.96), ("b", 100)], "0.08"),
    ("ATs", [("r", 3.17), ("g", 30.41), ("b", 100)], "0"),
    ("A9s", [("r", 10.27), ("b", 100)], "0"),
    ("A8s", [("r", 26.68), ("b", 100)], "0"),
    ("A7s", [("r", 27.98), ("b", 100)], "0"),
    ("A6s", [("r", 12.71), ("b", 100)], "0"),
    ("A5s", [("r", 28.2), ("g", 42.49), ("b", 100)], "0"),
    ("A4s", [("r", 41.02), ("g", 41.04), ("b", 99.99)], "0"),
    ("A3s", [("r", 17.04), ("b", 100)], "0"),
    ("A2s", [("b", 100)], "0"),
    ("AKo", [("R", 30.1), ("r", 76.06), ("g", 100)], "1.56"),
    ("KK", [("R", 5.78), ("r", 100)], "13.27"),
    ("KQs", [("r", 50.27), ("g", 84), ("b", 100)], "0.01"),
    ("KJs", [("r", 92.44), ("g", 99.98), ("b", 100)], "0.08"),
    ("KTs", [("r", 96.39), ("g", 99.61), ("b", 100)], "0.02"),
    ("K9s", [("r", 19.51), ("b", 100)], "0"),
    ("K8s", [("r", 8.43), ("b", 100)], "0"),
    ("K7s", [("r", 13.34), ("b", 100)], "0"),
    ("K6s", [("r", 14.88), ("b", 100)], "0"),
    ("K5s", [("b", 100)], "0"),
    ("K4s", [("b", 100)], "0"),
    ("AQo", [("r", 42.66), ("b", 100)], "0"),
    ("KQo", [("b", 100)], "0"),
    ("QQ", [("R", 10.89), ("r", 64.94), ("g", 100)], "2.15"),
    ("QJs", [("g", 0.01), ("b", 100)], "0"),
    ("QTs", [("b", 100)], "0"),
    ("Q9s", [("b", 100)], "0"),
    ("AJo", [("b", 100)], "0"),
    ("KJo", [("b", 100)], "0"),
    ("QJo", [("b", 100)], "0"),
    ("JJ", [("r", 16.68), ("g", 100)], "0.17"),
    ("JTs", [("g", 22.61), ("b", 100)], "0"),
    ("ATo", [("b", 100)], "0"),
    ("KTo", [("b", 100)], "0"),
    ("TT", [("r", 1.25), ("g", 42.12), ("b", 100)], "0"),
    ("T9s", [("g", 99.15), ("b", 100)], "0.01"),
    ("A9o", [("b", 100)], "0"),
    ("99", [("g", 36.34), ("b", 100)], "0"),
    ("88", [("g", 33.91), ("b", 100)], "0"),
    ("87s", [("g", 99.09), ("b", 100)], "0.07"),
    ("77", [("g", 44.76), ("b", 100)], "0"),
    ("76s", [("g", 99.72), ("b", 100)], "0.07"),
    ("66", [("g", 98.98), ("b", 100)], "0.02"),
    ("65s", [("g", 99.99), ("b", 100)], "0.08"),
    ("A5o", [("b", 100)], "0"),
    ("55", [("g", 99.91), ("b", 100)], "0.1"),
    ("54s", [("g", 99.99), ("b", 100)], "0.13"),
    ("44", [("g", 99.99), ("b", 100)], "0.24"),
    ("33", [("g", 100)], "0.38"),
]

HIST_SEATS = [
    (0, "UTG", "Raise 2.5"),
    (1, "HJ", "Fold "),
    (2, "CO", "Fold "),
    (3, "BTN", "Raise 8"),
    (4, "SB", "Fold "),
    (5, "BB", "Fold "),
]


def cell_html(hand, segs, ev):
    imgs = ", ".join(f"linear-gradient(to right, {CLR[c]}, {CLR[c]})" for c, _ in segs)
    sizes = ", ".join(f"{w}% 100%" for _, w in segs)
    return ('<div class="rtc rtc_strategy_ev_range_normalized ra_table_cell" '
            f'id="0_{hand}" data-tst="range_table_cell_0_{hand}" '
            f'style="background-image: {imgs}; background-size: {sizes};">'
            f'<div class="rtc_value"><span>{ev}</span></div>'
            f'<div class="rtc_title">{hand} </div></div>')


def hist_html():
    out = []
    for n, pos, act in HIST_SEATS:
        out.append(f'<div class="hspot-card" data-tst="hs_{n}_preflop_{pos}">'
                   '<div class="hspotcrd_action hspotcrd_action_active">'
                   f'<div class="hspotcrd_action_text">{act}</div></div></div>')
    out.append('<div class="hspot-card" data-tst="hs_6_preflop_UTG_active"></div>')
    return "".join(out)


def main():
    cells = "\n".join(cell_html(*c) for c in CELLS)
    html = ("<!doctype html><html><body>\n"
            '<div class="hspotscont_inner_scrollable">' + hist_html() + "</div>\n"
            '<div class="ra_table ra_table-container" data-tst="range_table_left">\n'
            + cells + "\n</div>\n</body></html>\n")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utg_vs_btn.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {out_path}  ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
