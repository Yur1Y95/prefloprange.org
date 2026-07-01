#!/usr/bin/env python3
"""
cards/gen_cards.py - HYBRID luxe playing cards (AI tile + vector rank), all 52.

Approach (user decision 2026-06-17, Track B):
  - The premium card SURFACE per suit is an AI-generated tile (Higgsfield,
    Nano Banana 2): deep 4-colour background, soft gloss, matte card-stock
    texture, and ONE large tactile EMBOSSED FOIL suit emblem (upper/centre-
    right, bleeding off the right edge). Source tiles live in cards/_ai_tiles/
    (tile_<suit>.png, downscaled from the 1696x2528 originals the user saved).
  - The RANK is drawn on top as crisp VECTOR <text> (white, bold, centred),
    so glyphs stay perfectly legible at any size and "T"/numbers never garble.
    This is the "hybrid": AI makes the look, vector guarantees the read.
  - Each card SVG EMBEDS its suit tile as a JPEG data-URI, so the SVG renders
    standalone when loaded via <img> (where EXTERNAL refs are blocked but data:
    URIs are allowed), and clips it to the rounded-rect card shape so the card
    has clean rounded corners with transparent outside.

4-colour identity kept: heart=red, diamond=blue, club=green, spade=charcoal.
Ten renders as "T"; file stays "<suit>10.svg". viewBox 210x315, filenames
<suit><RankName>.svg -> drop-in (cardSvgUrl in static/cards.js unchanged; only
its ?v= cache-bust is bumped on swap).

Run:    python3 cards/gen_cards.py             # writes 52 SVGs into cards/
Stage:  TILES_OUT=cards/_ai_staging python3 cards/gen_cards.py
Source tiles: cards/_ai_tiles/tile_<suit>.png  (regen the deck any time)
Backup of previous (vector-emboss) deck: cards/_backup_emboss_20260617/
"""
import os
import io
import base64
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("TILES_OUT", HERE)
TILES = os.path.join(HERE, "_ai_tiles")
os.makedirs(OUT, exist_ok=True)

W, H, R = 210, 315, 16          # card box + corner radius (ratio 2:3)

SUITS = ["heart", "diamond", "club", "spade"]

# (filename stem, displayed label) - Ten displays as "T" (poker notation),
# file stays "<suit>10.svg" so the cardSvgUrl mapping is unchanged.
RANKS = [("Ace", "A"), ("King", "K"), ("Queen", "Q"), ("Jack", "J"),
         ("10", "T"), ("9", "9"), ("8", "8"), ("7", "7"),
         ("6", "6"), ("5", "5"), ("4", "4"), ("3", "3"), ("2", "2")]

# --- rank typography (centred over the emblem, like the GTOW reference) -----
FONT = "Arial, 'Helvetica Neue', Helvetica, sans-serif"
RANK_FS = 190           # glyph visual height ~44% of card height
RANK_X = 105            # centred horizontally
RANK_Y = 226            # baseline -> glyph vertically centred
JPEG_Q = 82             # embedded tile quality (small files, photographic)


def tile_data_uri(suit):
    """Re-encode the suit tile as a compact JPEG and return a data: URI."""
    im = Image.open(os.path.join(TILES, "tile_%s.png" % suit)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_Q, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def card_svg(label, uri):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'viewBox="0 0 %(W)d %(H)d" width="%(W)d" height="%(H)d">\n'
        '  <defs>\n'
        '    <clipPath id="cc"><rect x="0" y="0" width="%(W)d" height="%(H)d" '
        'rx="%(R)d" ry="%(R)d"/></clipPath>\n'
        '    <filter id="sh" x="-20%%" y="-20%%" width="140%%" height="140%%">\n'
        '      <feDropShadow dx="1.5" dy="2" stdDeviation="3" '
        'flood-color="#000000" flood-opacity="0.5"/>\n'
        '    </filter>\n'
        '  </defs>\n'
        '  <g clip-path="url(#cc)">\n'
        '    <image xlink:href="%(uri)s" x="0" y="0" width="%(W)d" height="%(H)d" '
        'preserveAspectRatio="xMidYMid slice"/>\n'
        '  </g>\n'
        '  <text x="%(RX)d" y="%(RY)d" text-anchor="middle" '
        'font-family="%(FONT)s" font-weight="700" font-size="%(FS)d" '
        'fill="#ffffff" stroke="#161618" stroke-width="2" paint-order="stroke" '
        'filter="url(#sh)">%(label)s</text>\n'
        '</svg>\n'
    ) % {"W": W, "H": H, "R": R, "uri": uri, "RX": RANK_X, "RY": RANK_Y,
         "FONT": FONT, "FS": RANK_FS, "label": label}


def main():
    uris = {s: tile_data_uri(s) for s in SUITS}
    n = 0
    for suit in SUITS:
        for stem, label in RANKS:
            with open(os.path.join(OUT, "%s%s.svg" % (suit, stem)), "w") as f:
                f.write(card_svg(label, uris[suit]))
            n += 1
    print("wrote %d card svgs to %s" % (n, OUT))


if __name__ == "__main__":
    main()
