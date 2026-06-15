"""
Procedural poker-table ART renderer  (Track B — realistic table, 2026-06-03).

WHAT THIS IS
------------
Build-time tool (NOT served at runtime). Renders the realistic table backdrop
used by the new design direction: a top-down stadium table with a VOLUMETRIC
rounded-cushion rail (per-pixel Lambert + Blinn shading of a torus
cross-section -> one continuous rounded surface, no flat "stepped" rings) and a
MONOLITHIC felt (solid green + smooth overhead lamp glow + soft vignette +
betting line; deliberately almost no grain — earlier noisy felt read as a
"cheap kitchen rag"). Deterministic (fixed seeds) -> same output every run.

OUTPUTS (into $TABLE_OUT, default /tmp/tr)
  table_v2.png        1500x860 RGBA, transparent surround + baked soft shadow.
                      This is the asset -> copy to static/table_art/table.png
  table_v2_dark.png   same, composited on a dark room bg (for visual review)
  table_v2_crop.png   zoomed top-left corner (rail+felt close-up review)

HOW TO REGENERATE  (macOS TCC currently blocks Python from ~/Desktop, so render
in /tmp then copy the PNG into the project):
    cp static/table_art/render_table.py /tmp/tr/render.py
    cd /tmp/tr && python3 render.py
    cp /tmp/tr/table_v2.png  <project>/static/table_art/table.png
(Once Python is granted Desktop access in System Settings > Privacy & Security >
Files and Folders, set TABLE_OUT=static/table_art and run in place.)
Deps: numpy, Pillow  (pip3 install numpy Pillow)

TUNABLES (top of file): RAIL_PX (cushion thickness), BUMP_AMP (cushion roundness),
RAIL_BASE/RAIL_SPEC (rail colour/gloss), FELT_* (felt colours), LIGHT (lamp dir),
glow width (0.82) and vignette in the felt block, spec_* weights in the rail block.

INTEGRATION COORDS — where the felt rect sits inside the 1500x860 image, as % of
the image (use these to overlay the HTML seat layer on top of the <img> backdrop):
    left 4.667%   top 9.07%   width 90.67%   height 79.07%
i.e. table center is the image center (CY nudged up 12px for shadow room), the
playable stadium is TW x TH = 1360 x 680. See static/table_v4_preview.html for a
working overlay (seat tokens / hole cards / pot pill placed in % of that rect).
"""
import os
import numpy as np
from PIL import Image, ImageFilter

OUT = os.environ.get("TABLE_OUT", "/tmp/tr")
SS = 2
W, H = 1500, 860
TW, TH = 1360, 680
CX, CY = W / 2, H / 2 - 12

RAIL_PX = 92          # slightly wider cushion for more presence
SEAM_PX = 10          # wider mahogany strip (visible in AI ref)
BUMP_AMP = 0.92

# Rail: dark charcoal leather, matches AI reference
RAIL_BASE = np.array([0.130, 0.122, 0.115])
RAIL_SPEC = np.array([0.88,  0.85,  0.80])
# Felt: clean flat dark green — no lamp glow, no vignette
FELT_FLAT = np.array([0.112, 0.415, 0.228])
# Wood seam strip: dark mahogany between rail and felt
SEAM_COL  = np.array([0.220, 0.095, 0.042])

LIGHT = np.array([0.0, -0.50, 0.87]); LIGHT = LIGHT / np.linalg.norm(LIGHT)


def value_noise(h, w, base, seed):
    rng = np.random.default_rng(seed)
    small = (rng.random((base, base)) * 255).astype('uint8')
    img = Image.fromarray(small).resize((w, h), Image.BILINEAR)
    return np.asarray(img, dtype='float32') / 255.0


def normalize3(vx, vy, vz):
    m = np.sqrt(vx * vx + vy * vy + vz * vz) + 1e-9
    return vx / m, vy / m, vz / m


ow, oh = W * SS, H * SS
X, Y = np.meshgrid(np.arange(ow, dtype='float32'), np.arange(oh, dtype='float32'))

cx, cy = CX * SS, CY * SS
Ro = (TH / 2) * SS
seg_half = ((TW - TH) / 2) * SS
rail = RAIL_PX * SS
Ri = Ro - rail
seam = SEAM_PX * SS
Rf = Ri - seam

nx = np.clip(X, cx - seg_half, cx + seg_half)
dx = X - nx
dy = Y - cy
D = np.sqrt(dx * dx + dy * dy)
rdx = dx / (D + 1e-6)
rdy = dy / (D + 1e-6)

inside = D <= Ro
felt_m = D <= Rf
seam_m = (D > Rf) & (D <= Ri)
rail_m = (D > Ri) & (D <= Ro)

# ---- felt ----
# Flat clean dark green — no lamp glow, no vignette, no betting line.
# Matches AI reference: uniform felt, only a very subtle edge shadow
# where rail casts shadow on the outermost ~8% of the felt area.
felt = np.full((oh, ow, 3), FELT_FLAT, dtype='float32')

edge_sh = np.clip((D - Rf * 0.92) / (Rf * 0.08), 0, 1)
felt *= (1.0 - 0.18 * edge_sh)[..., None]

# ---- rail (volumetric cushion) ----
t = np.clip((Ro - D) / rail, 0, 1)
k = BUMP_AMP * np.pi
slope_out = -k * np.cos(np.pi * t)
nx3, ny3, nz3 = normalize3(-slope_out * rdx, -slope_out * rdy, np.ones_like(t))

ndotl = np.clip(nx3 * LIGHT[0] + ny3 * LIGHT[1] + nz3 * LIGHT[2], 0, 1)
hx, hy, hz = normalize3(LIGHT[0], LIGHT[1], LIGHT[2] + 1.0)
ndoth = np.clip(nx3 * hx + ny3 * hy + nz3 * hz, 0, 1)
spec_tight = ndoth ** 80      # small crisp glint
spec_med = ndoth ** 22        # soft leather sheen band
spec_broad = ndoth ** 5       # broad ambient roll

ambient = 0.17
rail_rgb = (RAIL_BASE[None, None, :] * (ambient + 1.0 * ndotl)[..., None]
            + RAIL_SPEC[None, None, :] * (0.34 * spec_tight + 0.26 * spec_med + 0.12 * spec_broad)[..., None])
outer_lip = np.clip((D - Ro * 0.985) / (Ro * 0.015), 0, 1)
rail_rgb *= (1.0 - 0.6 * outer_lip)[..., None]

# ---- composite ----
img = np.zeros((oh, ow, 3), dtype='float32')
img[felt_m] = felt[felt_m]
img[seam_m] = SEAM_COL[None, :]   # dark mahogany wood strip
img[rail_m] = rail_rgb[rail_m]
alpha = inside.astype('float32')

sh = np.asarray(Image.fromarray((inside * 255).astype('uint8'), 'L')
                .filter(ImageFilter.GaussianBlur(radius=18 * SS)), dtype='float32') / 255.0
shift = int(14 * SS)
sh = np.roll(sh, shift, axis=0); sh[:shift] = 0
sh_a = sh * 0.55

out_a = sh_a.copy()
out_rgb = np.zeros((oh, ow, 3), dtype='float32')
ta = alpha
na = ta + out_a * (1 - ta)
for c in range(3):
    out_rgb[..., c] = (img[..., c] * ta) / (na + 1e-9)
out_a = na

rgba8 = (np.dstack([np.clip(out_rgb, 0, 1), np.clip(out_a, 0, 1)]) * 255 + 0.5).astype('uint8')
full = Image.fromarray(rgba8, 'RGBA').resize((W, H), Image.LANCZOS)

os.makedirs(OUT, exist_ok=True)
full.save(f"{OUT}/table_v2.png")

bg = Image.new('RGBA', full.size, (0, 0, 0, 255))
bg.alpha_composite(full)
bg.convert('RGB').save(f"{OUT}/table_v2_dark.png")
crop = bg.crop((40, 40, 40 + 520, 40 + 360)).resize((780, 540), Image.LANCZOS)
crop.convert('RGB').save(f"{OUT}/table_v2_crop.png")
print('saved v2 + dark + crop ->', OUT, full.size)
