#!/usr/bin/env python3
"""
Reference reconstruction of a 4-color embossed-tile poker deck.

NOT an original asset and NOT production tiles: this is a faithful redraw of a
reference image the user flagged on 2026-06-14 as the target look for Track B
card art ("крайне красивые, лучше, чем сделали мы"). The original was pasted
inline in chat and never landed on disk, so this generator reconstructs the
picture so the reference survives across chats. Treat the output as a visual
TARGET, not as the final card assets.

Style cues captured (what the user liked over our current flat GTOW tiles):
  - 4-color suits: spade=charcoal, heart=red, diamond=blue, club=green
  - rounded tiles with a soft top->bottom gloss gradient (premium, not matte)
  - ONE large suit watermark, EMBOSSED (white up-left rim + dark down-right rim)
  - big heavy white rank letter, slightly left of center, overlapping the mark
  - small light suit index, top-left only
  - ten drawn as "T"

Run: python3 gen_cards_ref.py  ->  cards_ref_4color_emboss_20260614.svg
"""

import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "cards_ref_4color_emboss_20260614.svg")

TILE_W, TILE_H = 88, 124
GAP, MARGIN = 10, 18
COLS, ROWS = 13, 4

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]

# row order top->bottom matches the reference image
SUITS = ["spade", "heart", "diamond", "club"]

COLORS = {
    "spade":   dict(top="#4a4a4a", bot="#373737", mark="#2b2b2b"),
    "heart":   dict(top="#cc2b2b", bot="#b11d1d", mark="#8c1414"),
    "diamond": dict(top="#2b56e2", bot="#193ec1", mark="#132d98"),
    "club":    dict(top="#27b341", bot="#179931", mark="#117622"),
}


def suit_shapes(suit):
    """Suit drawn in a 100x100 box, NO fill (parent <g> sets the colour)."""
    if suit == "heart":
        return ('<path d="M50,31 C50,31 47,11 30,11 C8,11 8,38 8,38 '
                'C8,58 28,72 50,90 C72,72 92,58 92,38 C92,38 92,11 70,11 '
                'C53,11 50,31 50,31 Z"/>')
    if suit == "spade":
        return ('<path d="M50,70 C50,70 47,90 30,90 C8,90 8,62 8,62 '
                'C8,42 28,28 50,10 C72,28 92,42 92,62 C92,62 92,90 70,90 '
                'C53,90 50,70 50,70 Z"/>'
                '<path d="M50,63 C50,78 45,86 35,92 L65,92 '
                'C55,86 50,78 50,63 Z"/>')
    if suit == "diamond":
        return '<path d="M50,8 L88,50 L50,92 L12,50 Z"/>'
    # club
    return ('<circle cx="50" cy="32" r="18"/>'
            '<circle cx="32" cy="56" r="18"/>'
            '<circle cx="68" cy="56" r="18"/>'
            '<path d="M50,52 C54,68 58,80 68,92 L32,92 '
            'C42,80 46,68 50,52 Z"/>')


def watermark(suit, cx, cy, s, mark):
    sh = suit_shapes(suit)
    tx, ty = cx - 50 * s, cy - 50 * s
    return (
        f'<g transform="translate({tx:.2f},{ty:.2f}) scale({s:.4f})">'
        f'<g fill="#000000" opacity="0.30" filter="url(#soft)" transform="translate(2.4,3.0)">{sh}</g>'
        f'<g fill="#ffffff" opacity="0.13" filter="url(#soft)" transform="translate(-2.0,-2.6)">{sh}</g>'
        f'<g fill="{mark}">{sh}</g>'
        f'</g>'
    )


def corner_pip(suit, cx, cy, s):
    sh = suit_shapes(suit)
    tx, ty = cx - 50 * s, cy - 50 * s
    return (f'<g transform="translate({tx:.2f},{ty:.2f}) scale({s:.4f})">'
            f'<g fill="#ffffff" opacity="0.85">{sh}</g></g>')


def rank_text(r, x0, y0):
    fs = TILE_H * 0.56
    tx = x0 + TILE_W * 0.46
    ty = y0 + TILE_H * 0.53 + fs * 0.35
    font = 'font-family="Arial Black, Arial, Helvetica, sans-serif" font-weight="800"'
    return (
        f'<text x="{tx + 1.5:.1f}" y="{ty + 2:.1f}" text-anchor="middle" {font} '
        f'font-size="{fs:.1f}" fill="#000000" opacity="0.30">{r}</text>'
        f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" {font} '
        f'font-size="{fs:.1f}" fill="#ffffff">{r}</text>'
    )


def tile(suit, r, col, row):
    x0 = MARGIN + col * (TILE_W + GAP)
    y0 = MARGIN + row * (TILE_H + GAP)
    c = COLORS[suit]
    parts = ['<g>']
    parts.append(
        f'<rect x="{x0}" y="{y0}" width="{TILE_W}" height="{TILE_H}" rx="12" '
        f'fill="url(#grad_{suit})"/>')
    # top sheen
    parts.append(
        f'<rect x="{x0 + 3}" y="{y0 + 3}" width="{TILE_W - 6}" '
        f'height="{TILE_H * 0.42:.0f}" rx="9" fill="#ffffff" opacity="0.05"/>')
    # big embossed watermark
    parts.append(watermark(suit, x0 + TILE_W * 0.585, y0 + TILE_H * 0.52, 0.86, c["mark"]))
    # small corner index (top-left only, like the reference)
    parts.append(corner_pip(suit, x0 + TILE_W * 0.155, y0 + TILE_H * 0.135, 0.17))
    # heavy white rank letter
    parts.append(rank_text(r, x0, y0))
    parts.append('</g>')
    return "".join(parts)


def build():
    W = MARGIN * 2 + COLS * TILE_W + (COLS - 1) * GAP
    H = MARGIN * 2 + ROWS * TILE_H + (ROWS - 1) * GAP
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'width="{W}" height="{H}">']
    out.append('<defs>')
    out.append('<filter id="soft" x="-20%" y="-20%" width="140%" height="140%">'
               '<feGaussianBlur stdDeviation="0.9"/></filter>')
    for suit in SUITS:
        c = COLORS[suit]
        out.append(f'<linearGradient id="grad_{suit}" x1="0" y1="0" x2="0" y2="1">'
                   f'<stop offset="0" stop-color="{c["top"]}"/>'
                   f'<stop offset="1" stop-color="{c["bot"]}"/></linearGradient>')
    out.append('</defs>')
    out.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#161616"/>')
    for row, suit in enumerate(SUITS):
        for col, r in enumerate(RANKS):
            out.append(tile(suit, r, col, row))
    out.append('</svg>')
    return "".join(out)


if __name__ == "__main__":
    svg = build()
    with open(OUT, "w") as f:
        f.write(svg)
    print("wrote", OUT, "(%d bytes)" % len(svg))
