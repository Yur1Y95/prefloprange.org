"""Recolor the table felt to a vivid casino green.

Why this exists
---------------
The active table asset (`table.png`) is a Higgsfield-rendered photoreal table.
Its original felt was a desaturated *sage/olive* that read washed-out on the very
dark UI. Instead of re-generating the whole table (which would change geometry and
force re-calibrating seat positions), we recolor ONLY the felt of the existing
asset, locally. This keeps all the realism that is already baked in — the black
rail, the lighting gradient, the soft texture, the stadium shape, the transparent
surround — and leaves the table footprint byte-for-byte the same (`.table-area`
in style.css is untouched).

How it works
------------
1. Isolate the felt. The felt is the only *greenish* opaque region; the rail is
   gray (R~=G~=B) and the surround is transparent. So the mask is
   `opaque AND (G - max(R,B) >= 4)`. A 2px box-blur feathers the mask edge so the
   recolor blends cleanly into the rail with no hard seam.
2. Keep the lighting. We take each felt pixel's luminance (which encodes the
   center-glow -> dark-edge gradient), normalize it with a mild contrast stretch,
   and map it through a 3-stop green ramp (shadow -> base -> highlight). The
   lighting/texture is preserved; only the hue/saturation become vivid green.

Input  : table_pre_casino_green_20260619.bak.png  (the original sage asset)
Output : table.png  (1500x860 RGBA, same footprint, vivid casino-green felt)

Re-run :  python3 recolor_felt.py
Switch variant: change VARIANT below to "A_classic" / "B_vivid" / "C_emerald".
The live asset chosen by the user (2026-06-19) is "B_vivid".
"""
import os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "table_pre_casino_green_20260619.bak.png")  # sage original
OUT = os.path.join(HERE, "table.png")

VARIANT = "B_vivid"  # user choice 2026-06-19
CONTRAST = 1.18      # mild luminance contrast stretch before the green ramp

# 3-stop green ramps (shadow near rail -> base -> bright center), RGB 0..255.
# A is anchored on the approved design tokens (--felt-shadow/--felt/--felt-hi).
RAMPS = {
    "A_classic": dict(shadow=(11, 58, 33),  base=(29, 107, 64), hi=(55, 154, 89)),   # #0b3a21 / #1d6b40 / #379a59
    "B_vivid":   dict(shadow=(12, 74, 40),  base=(25, 138, 74), hi=(63, 178, 103)),  # brighter, casino-under-lights
    "C_emerald": dict(shadow=(6, 64, 44),   base=(15, 122, 82), hi=(43, 176, 122)),  # cooler emerald
}


def boxblur(x, r=2):
    """Separable box blur on a 2D array (numpy only, no scipy)."""
    x = x.astype(np.float32)
    k = 2 * r + 1
    c = np.cumsum(np.pad(x, ((r + 1, r), (0, 0)), mode="edge"), axis=0)
    x = (c[k:] - c[:-k]) / k
    c = np.cumsum(np.pad(x, ((0, 0), (r + 1, r)), mode="edge"), axis=1)
    x = (c[:, k:] - c[:, :-k]) / k
    return x


def ramp(t, shadow, base, hi):
    s = np.array(shadow, np.float32)
    b = np.array(base, np.float32)
    h = np.array(hi, np.float32)
    t = t[..., None]
    low = t < 0.5
    return np.where(low, s + (b - s) * (t / 0.5), b + (h - b) * ((t - 0.5) / 0.5))


def main():
    a = np.asarray(Image.open(SRC).convert("RGBA")).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3]
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = 0.299 * R + 0.587 * G + 0.114 * B

    opaque = alpha > 180
    greenness = G - np.maximum(R, B)
    felt = opaque & (greenness >= 4)
    soft = boxblur(felt.astype(np.float32), 2)[..., None]  # feathered 0..1

    lo, hi = np.percentile(lum[felt], 2), np.percentile(lum[felt], 98)
    t = np.clip((lum - lo) / (hi - lo), 0, 1)
    t = np.clip((t - 0.5) * CONTRAST + 0.5, 0, 1)

    v = RAMPS[VARIANT]
    new = ramp(t, v["shadow"], v["base"], v["hi"])
    blended = rgb * (1 - soft) + new * soft
    out = np.dstack([np.clip(blended, 0, 255), alpha]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(OUT)
    print(f"wrote {OUT}  variant={VARIANT}  felt_px={int(felt.sum())}")


if __name__ == "__main__":
    main()
