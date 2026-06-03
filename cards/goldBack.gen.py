#!/usr/bin/env python3
"""Generator for goldBack.svg — opponent card back (black + gold, ornate).

Run:  python3 cards/goldBack.gen.py
Writes goldBack.svg next to this file (viewBox 0 0 64 92, matches the .card box ratio).
Designed to stay legible down to ~28px: strong silhouette (double gold frame +
central spade medallion) survives downscaling; the guilloche lattice reads as
texture at small sizes. Palette tied to the app's --gold / --gold-hi tokens.
See CLAUDE.md decision #12 and docs/roadmap.md B.1-cards.
"""
import os

GOLD = "#c9a84c"      # --gold
GOLD_HI = "#e8c97a"   # --gold-hi

# Inner panel (where the lattice lives), inset from the card edge.
PX0, PY0, PW, PH = 5.0, 5.0, 54.0, 82.0
STEP = 4.5            # lattice spacing (smaller = denser)


def _line(x1, y1, x2, y2):
    return f"M {x1:.2f} {y1:.2f} L {x2:.2f} {y2:.2f}"


def _lattice():
    """Two families of parallel diagonals, coordinates pre-clipped to the panel
    so the path bbox equals the panel (no symmetry drift)."""
    segsA, segsB = [], []
    c = -PH
    while c <= PW:                       # slope +1  (u - v = c)
        vLo, vHi = max(0.0, -c), min(PH, PW - c)
        if vLo < vHi:
            segsA.append(_line(vLo + c + PX0, vLo + PY0, vHi + c + PX0, vHi + PY0))
        c += STEP
    c = 0.0
    while c <= PW + PH:                   # slope -1  (u + v = c)
        vLo, vHi = max(0.0, c - PW), min(PH, c)
        if vLo < vHi:
            segsB.append(_line(c - vLo + PX0, vLo + PY0, c - vHi + PX0, vHi + PY0))
        c += STEP
    return " ".join(segsA), " ".join(segsB)


# Spade path (from static/favicon.svg, 100-unit space, centred ~(50,50.6)),
# remapped to the medallion centre (32,46) and scaled.
SPADE = ("M 50 36 C 57.6 42.7 63.2 50 60.6 57 C 59.1 60.8 54.7 62 52 59 "
         "L 53.2 65.2 L 46.8 65.2 L 48 59 C 45.3 62 40.9 60.8 39.4 57 "
         "C 36.8 50 42.4 42.7 50 36 Z")
SPADE_SCALE = 0.62


def _bracket(cx, cy, sx, sy, arm=5.0):
    """Short corner L-bracket pointing inward from (cx,cy); sx,sy are +/-1."""
    return f"M {cx:.2f} {cy + sy*arm:.2f} L {cx:.2f} {cy:.2f} L {cx + sx*arm:.2f} {cy:.2f}"


def build_svg():
    dA, dB = _lattice()
    brackets = " ".join([
        _bracket(9.0, 9.0,  1,  1),
        _bracket(55.0, 9.0, -1,  1),
        _bracket(9.0, 83.0,  1, -1),
        _bracket(55.0, 83.0, -1, -1),
    ])
    return f'''<svg viewBox="0 0 64 92" xmlns="http://www.w3.org/2000/svg">
  <title>Poker Trainer — card back</title>
  <defs>
    <radialGradient id="bgGold" cx="50%" cy="46%" r="62%">
      <stop offset="0" stop-color="#1c1308"/>
      <stop offset="0.55" stop-color="#0f0b06"/>
      <stop offset="1" stop-color="#060606"/>
    </radialGradient>
    <linearGradient id="spadeGold" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{GOLD_HI}"/>
      <stop offset="1" stop-color="{GOLD}"/>
    </linearGradient>
    <clipPath id="panelClip">
      <rect x="{PX0}" y="{PY0}" width="{PW}" height="{PH}" rx="4"/>
    </clipPath>
  </defs>

  <!-- base -->
  <rect x="0" y="0" width="64" height="92" rx="8" fill="url(#bgGold)"/>

  <!-- guilloche lattice, clipped to the inner panel -->
  <g clip-path="url(#panelClip)" stroke="{GOLD}" stroke-width="0.35" fill="none" opacity="0.14">
    <path d="{dA}"/>
    <path d="{dB}"/>
  </g>

  <!-- frame -->
  <rect x="2.5" y="2.5" width="59" height="87" rx="6" fill="none" stroke="{GOLD}" stroke-width="0.9"/>
  <rect x="5" y="5" width="54" height="82" rx="4" fill="none" stroke="{GOLD_HI}" stroke-width="0.4" opacity="0.55"/>

  <!-- corner fleurons -->
  <path d="{brackets}" fill="none" stroke="{GOLD}" stroke-width="0.6" stroke-linecap="round" opacity="0.85"/>

  <!-- central medallion -->
  <g>
    <polygon points="32,26 47,46 32,66 17,46" fill="#0a0805" fill-opacity="0.55" stroke="{GOLD}" stroke-width="0.9"/>
    <polygon points="32,29.5 44,46 32,62.5 20,46" fill="none" stroke="{GOLD_HI}" stroke-width="0.4" opacity="0.6"/>
    <g transform="translate(32 46) scale({SPADE_SCALE}) translate(-50 -50.6)">
      <path d="{SPADE}" fill="url(#spadeGold)"/>
    </g>
  </g>
</svg>
'''


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goldBack.svg")
    with open(out, "w") as f:
        f.write(build_svg())
    print("wrote", out)
