"""Recolour the LayIpoker green card back into a dark graphite back.

The source (LayIpoker/cardgreen.png, 50x68 RGBA) is a green back with a
diamond-lattice texture and a central spade medallion. We keep the structure
(it is tonal) and remap luminance onto a neutral graphite ramp tuned to the
chrome-redesign palette (CLAUDE.md #17). Alpha (rounded corners) is preserved.

Output: cards/darkBack.png, upscaled ~2.4x (Lanczos) so it stays crisp on the
64x92 .card-back box. Used by .mini-back and .card-back in style.css.

Run:  python3 cards/recolor_back.py
Rollback path: style.css still references cards/goldBack.svg if reverted.
"""
import os
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "LayIpoker", "cardgreen.png")
OUT = os.path.join(BASE, "cards", "darkBack.png")
UPSCALE = 2.4

# Graphite ramp (shadow -> base -> highlight), aligned with --recessed/--surface-2/--stroke.
SHADOW = (12, 13, 17)
BASE_C = (28, 31, 38)
HILITE = (74, 80, 92)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(t):
    # two-segment ramp: 0..0.5 shadow->base, 0.5..1 base->highlight
    if t < 0.5:
        return lerp(SHADOW, BASE_C, t / 0.5)
    return lerp(BASE_C, HILITE, (t - 0.5) / 0.5)


def main():
    im = Image.open(SRC).convert("RGBA")
    px = im.load()
    w, h = im.size

    # luminance range over opaque pixels, for contrast stretch
    lo, hi = 255, 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            l = 0.299 * r + 0.587 * g + 0.114 * b
            lo = min(lo, l)
            hi = max(hi, l)
    span = max(1.0, hi - lo)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 8:
                continue
            l = 0.299 * r + 0.587 * g + 0.114 * b
            t = (l - lo) / span            # 0..1 stretched
            t = t ** 0.92                  # mild lift so the lattice stays visible
            nr, ng, nb = ramp(t)
            op[x, y] = (nr, ng, nb, a)

    nw, nh = round(w * UPSCALE), round(h * UPSCALE)
    out = out.resize((nw, nh), Image.LANCZOS)
    out.save(OUT)
    print(f"wrote {OUT} ({nw}x{nh}), luminance span {lo:.0f}..{hi:.0f}")


if __name__ == "__main__":
    main()
