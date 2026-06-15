#!/usr/bin/env python3
"""
cards/gen_cards.py — 4-colour "embossed-tile" playing cards, all 52.

Style (user decision 2026-06-14, matched 1:1 to the reference deck the user
flagged as the target — docs/design_refs/gtow_cards_original_*.png):
  - near-FLAT 4-colour suit tile (tiny gloss only), rounded corners;
  - colours sampled directly from the reference PNG (tile + emblem per suit);
  - ONE large suit emblem as an EMBOSSED watermark (darker shade of the tile,
    light up-left rim + dark down-right rim), placed UPPER-RIGHT and bleeding
    off the top/right edges, clipped to the card shape;
  - big heavy white rank on the LEFT, vertically centred, soft shadow;
  - NO corner index (suit carried by the big emblem + tile colour);
  - Ten renders as "T" (file stays "<suit>10.svg").

Deterministic vector output → 52 crisp, consistent SVGs.

viewBox 210x315 (ratio 2:3) and filenames `<suit><RankName>.svg` match the
existing /cards integration, so this is a drop-in replacement (cardSvgUrl in
static/cards.js is unchanged; only its ?v= cache-bust is bumped on swap).

Run:    python3 cards/gen_cards.py                      # writes into cards/
Stage:  TILES_OUT=cards/_tiles_emboss python3 cards/gen_cards.py
Backups: cards/_backup_realistic_20260614/ (pre-tile realistic deck)
         cards/_backup_tile_20260614/       (flat-tile deck, made on this swap)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("TILES_OUT", HERE)
os.makedirs(OUT, exist_ok=True)

W, H, R = 210, 315, 16          # card box + corner radius

# (tile colour, emblem colour) sampled from the reference PNG.
TILE = {
    "heart":   ("#982010", "#581008"),
    "diamond": ("#2030b8", "#102070"),
    "club":    ("#48a840", "#286020"),
    "spade":   ("#504848", "#302828"),
}

# Clean suit emblems normalised to a 0..100 box, no fill (parent <g> colours it,
# so one path serves the shadow / highlight / base copies of the emboss).
SUIT = {
    "heart": '<path d="M50 90 C 50 90 11 60 11 32 C 11 16 22 7 34 7 C 43 7 49 14 50 24 C 51 14 57 7 66 7 C 78 7 89 16 89 32 C 89 60 50 90 50 90 Z"/>',
    "diamond": '<path d="M50 4 L 86 50 L 50 96 L 14 50 Z"/>',
    "spade": '<path d="M50 6 C 44 15 14 39 14 61 C 14 74 28 83 43 70 C 42 82 40 89 34 95 L 66 95 C 60 89 58 82 57 70 C 72 83 86 74 86 61 C 86 39 56 15 50 6 Z"/>',
    # One union path (3 overlapping lobes + stem, all same winding) so the club
    # reads as a single solid shape — no centre seam, and no alpha-stacking in
    # the semi-transparent emboss layers.
    "club": '<path d="M30,28 a20,20 0 1,1 40,0 a20,20 0 1,1 -40,0 Z M12,53 a20,20 0 1,1 40,0 a20,20 0 1,1 -40,0 Z M48,53 a20,20 0 1,1 40,0 a20,20 0 1,1 -40,0 Z M50,51 C54,69 58,82 67,95 L33,95 C42,82 46,69 50,51 Z"/>',
}

# (filename stem, displayed label) — Ten displays as "T" (poker notation),
# but the file stays "<suit>10.svg" so cardSvgUrl mapping is unchanged.
RANKS = [("Ace", "A"), ("King", "K"), ("Queen", "Q"), ("Jack", "J"),
         ("10", "T"), ("9", "9"), ("8", "8"), ("7", "7"),
         ("6", "6"), ("5", "5"), ("4", "4"), ("3", "3"), ("2", "2")]

FONT = "'Arial Black','Helvetica Neue',Arial,sans-serif"

# --- layout (measured from the reference PNG) ------------------------------
# rank: centred, glyph height ~44% of tile; emblem centroid ~0.67x / 0.49y,
# big and bleeding off the right edge.
WM_SIZE = 285            # emblem box (px) — large, bleeds off the right
WM_CX, WM_CY = 0.70, 0.49  # emblem centre as a fraction of W, H (right, centred)
RANK_FS = 192            # rank size (~44% of card height)
RANK_CX = 0.50           # rank centre x as a fraction of W (centred)
RANK_Y = 226             # rank baseline (vertically centred)


def _shade(hexc, f):
    """Multiply an #rrggbb colour by factor f (clamped) → lighten/darken."""
    c = hexc.lstrip("#")
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [max(0, min(255, int(v * f))) for v in rgb]
    return "#%02x%02x%02x" % tuple(rgb)


def _emblem_emboss(suit, cx, cy, size, mark):
    """Big embossed watermark: dark down-right rim + light up-left rim + base."""
    s = size / 100.0
    tx, ty = cx - size / 2, cy - size / 2
    shp = SUIT[suit]
    return (
        f'<g transform="translate({tx:.1f},{ty:.1f}) scale({s:.4f})">'
        f'<g fill="#000000" opacity="0.25" filter="url(#soft)" transform="translate(1.5,1.9)">{shp}</g>'
        f'<g fill="#ffffff" opacity="0.16" filter="url(#soft)" transform="translate(-1.3,-1.7)">{shp}</g>'
        f'<g fill="{mark}">{shp}</g>'
        f'</g>'
    )


def card_svg(suit, label):
    tile, mark = TILE[suit]
    top, bot = _shade(tile, 1.12), _shade(tile, 0.90)   # subtle gloss
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bot}"/>
    </linearGradient>
    <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.8"/></filter>
    <clipPath id="cc"><rect x="0" y="0" width="{W}" height="{H}" rx="{R}" ry="{R}"/></clipPath>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" rx="{R}" ry="{R}" fill="url(#g)"/>
  <g clip-path="url(#cc)">{_emblem_emboss(suit, W*WM_CX, H*WM_CY, WM_SIZE, mark)}</g>
  <text x="{W*RANK_CX+2:.0f}" y="{RANK_Y+3}" font-family="{FONT}" font-size="{RANK_FS}" font-weight="900" fill="#000000" opacity="0.28" text-anchor="middle">{label}</text>
  <text x="{W*RANK_CX:.0f}" y="{RANK_Y}" font-family="{FONT}" font-size="{RANK_FS}" font-weight="900" fill="#ffffff" text-anchor="middle">{label}</text>
</svg>
"""


def main():
    n = 0
    for suit in ("heart", "diamond", "club", "spade"):
        for rank_name, label in RANKS:
            path = os.path.join(OUT, f"{suit}{rank_name}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(card_svg(suit, label))
            n += 1
    print(f"✓  {n} embossed-tile cards → {OUT}/")


if __name__ == "__main__":
    main()
