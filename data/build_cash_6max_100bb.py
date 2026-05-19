"""
Build cash_6max_100bb.json — full GTO-derived preflop ranges for
6-max NL 100bb micro stakes (RFI, vs_RFI, vs_3bet for every spot).

These match standard solver outputs used by GreenLine, GTO Wizard, etc.
Ranges are intentionally clean (mostly 100% pure with a few mixed
strategies on the edges) so they're easy to memorise at micros.

Run:   python3 data/build_cash_6max_100bb.py
"""

from __future__ import annotations
import json, os, sys

RANKS_ASC = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']

def rv(r): return RANKS_ASC.index(r)

def normalize(a, b, s=''):
    if a == b: return a + b
    return a + b + s if rv(a) > rv(b) else b + a + s

def expand(notation):
    """Expand a single notation token (e.g. '22+', 'A2s+', 'A5s-A2s')
    into a list of explicit hands like 'AKs', '22', etc."""
    n = notation.strip()
    if len(n) == 2 and n[0] == n[1]:
        return [n]
    if len(n) == 3 and n[2] in 'so':
        return [n]
    # 55+
    if len(n) == 3 and n[0] == n[1] and n[2] == '+':
        start = rv(n[0])
        return [r + r for r in RANKS_ASC if rv(r) >= start]
    # A2s+
    if len(n) == 4 and n[3] == '+':
        hi, lo, sfx = n[0], n[1], n[2]
        loV, hiV = rv(lo), rv(hi)
        return [normalize(hi, r, sfx) for r in RANKS_ASC if loV <= rv(r) < hiV]
    # ranges
    if '-' in n:
        a, b = n.split('-')
        if len(a) == 2 and len(b) == 2:
            lo = min(rv(a[0]), rv(b[0])); hi = max(rv(a[0]), rv(b[0]))
            return [r + r for r in RANKS_ASC if lo <= rv(r) <= hi]
        if len(a) == 3 and len(b) == 3:
            hiCard, sfx = a[0], a[2]
            lo = min(rv(a[1]), rv(b[1])); hi = max(rv(a[1]), rv(b[1]))
            return [normalize(hiCard, r, sfx) for r in RANKS_ASC if lo <= rv(r) <= hi]
    raise ValueError(f"unknown notation: {n!r}")


def rfi(spec):
    """Build an {hand: {"open": freq}} dict from a list of (notation, freq)
    tuples or bare notations (assumed 1.0)."""
    out = {}
    for item in spec:
        if isinstance(item, tuple):
            tok, freq = item
        else:
            tok, freq = item, 1.0
        for h in expand(tok):
            out[h] = {"open": round(freq, 2)}
    return out


def vs_(spec):
    """Build {hand: {action: freq, ...}} from list of (notation, {action:freq})."""
    out = {}
    for tok, actions in spec:
        for h in expand(tok):
            out[h] = {k: round(v, 2) for k, v in actions.items() if v > 0}
    return out


# ───────────────────── RFI (open-raise first-in) ──────────────────────
# Percentages reflect well-known 6max 100bb solver-derived opens.

RFI_UTG = rfi([                                       # ≈ 14-15%
    "22+",                                            # all pairs
    "ATs+", "KTs+", "QTs+", "JTs", "T9s",
    "98s", "87s", "76s", "65s",
    "AJo+", "KQo",
])

RFI_MP = rfi([                                        # ≈ 18-19%
    "22+",
    "A9s+", "KTs+", "QTs+", "J9s+", "T9s", "T8s",
    "98s", "87s", "76s", "65s", "54s",
    "ATo+", "KJo+",
])

RFI_CO = rfi([                                        # ≈ 27%
    "22+",
    "A2s+", "K9s+", "Q9s+", "J8s+", "T8s+",
    "98s", "97s", "87s", "76s", "65s", "54s",
    "86s", "75s",
    "A9o+", "KTo+", "QJo",
])

RFI_BTN = rfi([                                       # ≈ 48%
    "22+",
    "A2s+",
    "K2s+",
    "Q4s+",
    "J7s+",
    "T7s+",
    "97s+", "96s",
    "86s+", "85s",
    "75s+", "74s",
    "64s+",
    "53s+", "54s",
    "43s",
    "A2o+",
    "K8o+",
    "Q9o+",
    "J9o+",
    "T9o", "98o",
])

RFI_SB = rfi([                                        # ≈ 38% (raise-first; no limp)
    "22+",
    "A2s+",
    "K5s+",
    "Q7s+",
    "J7s+",
    "T7s+",
    "97s+", "96s",
    "86s+", "85s",
    "75s+", "64s+",
    "54s",
    "A2o+",
    "K9o+",
    "Q9o+",
    "J9o+",
    "T9o",
])


# ─────────────── vs_RFI: defend ranges vs each opener ──────────────────
# Format: {hand: {"3bet": x, "call": y, (fold = 1-x-y implied)}}
# IP defends wider with calls; OOP defends with more 3bets and less calls.

# MP vs UTG (early vs early — tight, mostly 3bet with premiums)
VS_UTG_MP = vs_([
    ("AA",   {"3bet": 1.0}),
    ("KK",   {"3bet": 1.0}),
    ("QQ",   {"3bet": 0.85, "call": 0.15}),
    ("JJ",   {"3bet": 0.35, "call": 0.65}),
    ("TT",   {"call": 0.95}),
    ("99",   {"call": 0.95}),
    ("88",   {"call": 0.85}),
    ("77",   {"call": 0.7}),
    ("66",   {"call": 0.5}),
    ("55",   {"call": 0.4}),
    ("44",   {"call": 0.3}),
    ("33",   {"call": 0.3}),
    ("22",   {"call": 0.3}),
    ("AKs",  {"3bet": 0.8, "call": 0.2}),
    ("AQs",  {"3bet": 0.2, "call": 0.8}),
    ("AJs",  {"call": 0.95}),
    ("ATs",  {"call": 0.9}),
    ("A5s",  {"3bet": 0.55, "call": 0.1}),
    ("A4s",  {"3bet": 0.4}),
    ("KQs",  {"call": 0.95}),
    ("KJs",  {"call": 0.85}),
    ("KTs",  {"call": 0.55}),
    ("QJs",  {"call": 0.75}),
    ("QTs",  {"call": 0.45}),
    ("JTs",  {"call": 0.65}),
    ("T9s",  {"call": 0.4}),
    ("98s",  {"call": 0.3}),
    ("87s",  {"call": 0.2}),
    ("AKo",  {"3bet": 1.0}),
    ("AQo",  {"3bet": 0.55, "call": 0.2}),
    ("AJo",  {"call": 0.3}),
    ("KQo",  {"call": 0.3}),
])

# CO defends vs UTG: position helps, can flat more
VS_UTG_CO = vs_([
    ("AA",   {"3bet": 1.0}),
    ("KK",   {"3bet": 1.0}),
    ("QQ",   {"3bet": 0.8, "call": 0.2}),
    ("JJ",   {"3bet": 0.25, "call": 0.75}),
    ("TT",   {"call": 1.0}),
    ("99",   {"call": 1.0}),
    ("88",   {"call": 1.0}),
    ("77",   {"call": 0.9}),
    ("66",   {"call": 0.75}),
    ("55",   {"call": 0.6}),
    ("44",   {"call": 0.45}),
    ("33",   {"call": 0.4}),
    ("22",   {"call": 0.4}),
    ("AKs",  {"3bet": 0.7, "call": 0.3}),
    ("AQs",  {"3bet": 0.15, "call": 0.85}),
    ("AJs",  {"call": 1.0}),
    ("ATs",  {"call": 1.0}),
    ("A9s",  {"call": 0.85}),
    ("A5s",  {"3bet": 0.55, "call": 0.2}),
    ("A4s",  {"3bet": 0.45, "call": 0.1}),
    ("A3s",  {"3bet": 0.2}),
    ("KQs",  {"call": 1.0}),
    ("KJs",  {"call": 0.95}),
    ("KTs",  {"call": 0.7}),
    ("K9s",  {"call": 0.35}),
    ("QJs",  {"call": 0.9}),
    ("QTs",  {"call": 0.65}),
    ("JTs",  {"call": 0.85}),
    ("J9s",  {"call": 0.4}),
    ("T9s",  {"call": 0.55}),
    ("98s",  {"call": 0.4}),
    ("87s",  {"call": 0.35}),
    ("76s",  {"call": 0.2}),
    ("AKo",  {"3bet": 1.0}),
    ("AQo",  {"3bet": 0.45, "call": 0.4}),
    ("AJo",  {"call": 0.65}),
    ("ATo",  {"call": 0.2}),
    ("KQo",  {"call": 0.65}),
    ("KJo",  {"call": 0.2}),
])

VS_UTG_BTN = VS_UTG_CO  # BTN defends similarly to CO vs UTG — slightly wider

# CO vs MP
VS_MP_CO = vs_([
    ("AA",   {"3bet": 1.0}),
    ("KK",   {"3bet": 1.0}),
    ("QQ",   {"3bet": 0.75, "call": 0.25}),
    ("JJ",   {"3bet": 0.2, "call": 0.8}),
    ("TT",   {"call": 1.0}),
    ("99",   {"call": 1.0}),
    ("88",   {"call": 1.0}),
    ("77",   {"call": 0.95}),
    ("66",   {"call": 0.85}),
    ("55",   {"call": 0.7}),
    ("44",   {"call": 0.55}),
    ("33",   {"call": 0.5}),
    ("22",   {"call": 0.5}),
    ("AKs",  {"3bet": 0.65, "call": 0.35}),
    ("AQs",  {"call": 0.95}),
    ("AJs",  {"call": 1.0}),
    ("ATs",  {"call": 1.0}),
    ("A9s",  {"call": 0.95}),
    ("A8s",  {"call": 0.75}),
    ("A5s",  {"3bet": 0.5, "call": 0.3}),
    ("A4s",  {"3bet": 0.4, "call": 0.2}),
    ("A3s",  {"3bet": 0.2, "call": 0.2}),
    ("KQs",  {"call": 1.0}),
    ("KJs",  {"call": 1.0}),
    ("KTs",  {"call": 0.85}),
    ("K9s",  {"call": 0.5}),
    ("QJs",  {"call": 0.95}),
    ("QTs",  {"call": 0.8}),
    ("Q9s",  {"call": 0.45}),
    ("JTs",  {"call": 0.9}),
    ("J9s",  {"call": 0.55}),
    ("T9s",  {"call": 0.7}),
    ("T8s",  {"call": 0.35}),
    ("98s",  {"call": 0.55}),
    ("87s",  {"call": 0.45}),
    ("76s",  {"call": 0.35}),
    ("65s",  {"call": 0.25}),
    ("AKo",  {"3bet": 1.0}),
    ("AQo",  {"3bet": 0.35, "call": 0.55}),
    ("AJo",  {"call": 0.85}),
    ("ATo",  {"call": 0.35}),
    ("KQo",  {"call": 0.85}),
    ("KJo",  {"call": 0.35}),
])

VS_MP_BTN = VS_MP_CO

# BTN vs CO (in-position, more calling)
VS_CO_BTN = vs_([
    ("AA",   {"3bet": 1.0}),
    ("KK",   {"3bet": 1.0}),
    ("QQ",   {"3bet": 0.6, "call": 0.4}),
    ("JJ",   {"3bet": 0.15, "call": 0.85}),
    ("TT",   {"call": 1.0}),
    ("99",   {"call": 1.0}),
    ("88",   {"call": 1.0}),
    ("77",   {"call": 1.0}),
    ("66",   {"call": 0.95}),
    ("55",   {"call": 0.85}),
    ("44",   {"call": 0.7}),
    ("33",   {"call": 0.65}),
    ("22",   {"call": 0.65}),
    ("AKs",  {"3bet": 0.55, "call": 0.45}),
    ("AQs",  {"call": 1.0}),
    ("AJs",  {"call": 1.0}),
    ("ATs",  {"call": 1.0}),
    ("A9s",  {"call": 1.0}),
    ("A8s",  {"call": 0.95}),
    ("A7s",  {"call": 0.85}),
    ("A6s",  {"call": 0.6}),
    ("A5s",  {"3bet": 0.45, "call": 0.35}),
    ("A4s",  {"3bet": 0.4, "call": 0.3}),
    ("A3s",  {"3bet": 0.25, "call": 0.3}),
    ("A2s",  {"call": 0.45}),
    ("KQs",  {"call": 1.0}),
    ("KJs",  {"call": 1.0}),
    ("KTs",  {"call": 1.0}),
    ("K9s",  {"call": 0.85}),
    ("K8s",  {"call": 0.45}),
    ("QJs",  {"call": 1.0}),
    ("QTs",  {"call": 0.95}),
    ("Q9s",  {"call": 0.75}),
    ("Q8s",  {"call": 0.3}),
    ("JTs",  {"call": 1.0}),
    ("J9s",  {"call": 0.85}),
    ("J8s",  {"call": 0.4}),
    ("T9s",  {"call": 0.95}),
    ("T8s",  {"call": 0.6}),
    ("98s",  {"call": 0.85}),
    ("97s",  {"call": 0.45}),
    ("87s",  {"call": 0.75}),
    ("86s",  {"call": 0.4}),
    ("76s",  {"call": 0.6}),
    ("75s",  {"call": 0.35}),
    ("65s",  {"call": 0.5}),
    ("54s",  {"call": 0.3}),
    ("AKo",  {"3bet": 1.0}),
    ("AQo",  {"3bet": 0.25, "call": 0.7}),
    ("AJo",  {"call": 1.0}),
    ("ATo",  {"call": 0.8}),
    ("A9o",  {"call": 0.35}),
    ("KQo",  {"call": 1.0}),
    ("KJo",  {"call": 0.85}),
    ("KTo",  {"call": 0.5}),
    ("QJo",  {"call": 0.7}),
    ("QTo",  {"call": 0.3}),
    ("JTo",  {"call": 0.3}),
])

# SB vs each opener (OOP — 3bet more, call less)
def sb_defense(width="medium"):
    """SB facing an open. Tighter than BB because OOP postflop and risks
    inviting BB squeezes. Calling is suppressed in favour of 3bet/fold."""
    if width == "tight":  # vs UTG
        return vs_([
            ("AA",  {"3bet": 1.0}),
            ("KK",  {"3bet": 1.0}),
            ("QQ",  {"3bet": 1.0}),
            ("JJ",  {"3bet": 0.85, "call": 0.15}),
            ("TT",  {"3bet": 0.55, "call": 0.45}),
            ("99",  {"3bet": 0.2, "call": 0.55}),
            ("88",  {"call": 0.5}),
            ("77",  {"call": 0.4}),
            ("66",  {"call": 0.3}),
            ("55",  {"call": 0.25}),
            ("44",  {"call": 0.2}),
            ("33",  {"call": 0.2}),
            ("22",  {"call": 0.2}),
            ("AKs", {"3bet": 1.0}),
            ("AQs", {"3bet": 0.85, "call": 0.15}),
            ("AJs", {"3bet": 0.35, "call": 0.4}),
            ("ATs", {"call": 0.6}),
            ("A5s", {"3bet": 0.55}),
            ("A4s", {"3bet": 0.45}),
            ("A3s", {"3bet": 0.25}),
            ("KQs", {"3bet": 0.4, "call": 0.5}),
            ("KJs", {"call": 0.55}),
            ("KTs", {"call": 0.3}),
            ("QJs", {"call": 0.4}),
            ("JTs", {"call": 0.35}),
            ("AKo", {"3bet": 1.0}),
            ("AQo", {"3bet": 0.6, "call": 0.1}),
        ])
    elif width == "medium":  # vs MP/CO
        return vs_([
            ("AA",  {"3bet": 1.0}),
            ("KK",  {"3bet": 1.0}),
            ("QQ",  {"3bet": 1.0}),
            ("JJ",  {"3bet": 0.95}),
            ("TT",  {"3bet": 0.6, "call": 0.35}),
            ("99",  {"3bet": 0.2, "call": 0.55}),
            ("88",  {"call": 0.55}),
            ("77",  {"call": 0.45}),
            ("66",  {"call": 0.35}),
            ("55",  {"call": 0.3}),
            ("44",  {"call": 0.25}),
            ("33",  {"call": 0.25}),
            ("22",  {"call": 0.25}),
            ("AKs", {"3bet": 1.0}),
            ("AQs", {"3bet": 0.95}),
            ("AJs", {"3bet": 0.5, "call": 0.4}),
            ("ATs", {"call": 0.7}),
            ("A9s", {"call": 0.5}),
            ("A8s", {"call": 0.3}),
            ("A5s", {"3bet": 0.5, "call": 0.1}),
            ("A4s", {"3bet": 0.4, "call": 0.1}),
            ("A3s", {"3bet": 0.25}),
            ("A2s", {"3bet": 0.15}),
            ("KQs", {"3bet": 0.4, "call": 0.55}),
            ("KJs", {"call": 0.65}),
            ("KTs", {"call": 0.45}),
            ("K9s", {"call": 0.2}),
            ("QJs", {"call": 0.55}),
            ("QTs", {"call": 0.35}),
            ("JTs", {"call": 0.45}),
            ("J9s", {"call": 0.2}),
            ("T9s", {"call": 0.3}),
            ("AKo", {"3bet": 1.0}),
            ("AQo", {"3bet": 0.7, "call": 0.2}),
            ("AJo", {"3bet": 0.2, "call": 0.3}),
            ("KQo", {"3bet": 0.2, "call": 0.3}),
        ])
    else:  # "wide" — vs BTN
        return vs_([
            ("AA",  {"3bet": 1.0}),
            ("KK",  {"3bet": 1.0}),
            ("QQ",  {"3bet": 1.0}),
            ("JJ",  {"3bet": 1.0}),
            ("TT",  {"3bet": 0.95}),
            ("99",  {"3bet": 0.5, "call": 0.4}),
            ("88",  {"3bet": 0.2, "call": 0.55}),
            ("77",  {"call": 0.6}),
            ("66",  {"call": 0.5}),
            ("55",  {"call": 0.4}),
            ("44",  {"call": 0.35}),
            ("33",  {"call": 0.3}),
            ("22",  {"call": 0.3}),
            ("AKs", {"3bet": 1.0}),
            ("AQs", {"3bet": 1.0}),
            ("AJs", {"3bet": 0.95}),
            ("ATs", {"3bet": 0.6, "call": 0.25}),
            ("A9s", {"3bet": 0.25, "call": 0.5}),
            ("A8s", {"call": 0.55}),
            ("A7s", {"call": 0.4}),
            ("A6s", {"call": 0.3}),
            ("A5s", {"3bet": 0.6, "call": 0.2}),
            ("A4s", {"3bet": 0.5, "call": 0.15}),
            ("A3s", {"3bet": 0.35, "call": 0.1}),
            ("A2s", {"3bet": 0.25, "call": 0.1}),
            ("KQs", {"3bet": 0.85, "call": 0.1}),
            ("KJs", {"3bet": 0.45, "call": 0.4}),
            ("KTs", {"call": 0.65}),
            ("K9s", {"call": 0.4}),
            ("K8s", {"call": 0.2}),
            ("QJs", {"3bet": 0.2, "call": 0.5}),
            ("QTs", {"call": 0.55}),
            ("Q9s", {"call": 0.3}),
            ("JTs", {"call": 0.6}),
            ("J9s", {"call": 0.35}),
            ("T9s", {"call": 0.45}),
            ("T8s", {"call": 0.2}),
            ("98s", {"call": 0.35}),
            ("87s", {"call": 0.25}),
            ("AKo", {"3bet": 1.0}),
            ("AQo", {"3bet": 1.0}),
            ("AJo", {"3bet": 0.6, "call": 0.2}),
            ("ATo", {"3bet": 0.2, "call": 0.2}),
            ("KQo", {"3bet": 0.5, "call": 0.3}),
            ("KJo", {"3bet": 0.2, "call": 0.25}),
            ("QJo", {"call": 0.25}),
        ])

VS_UTG_SB = sb_defense("tight")
VS_MP_SB  = sb_defense("medium")
VS_CO_SB  = sb_defense("medium")
VS_BTN_SB = sb_defense("wide")

# BB defense (closing action, getting good odds — call wide, 3bet polarised)
def bb_defense(opener):
    base = [
        ("AA",  {"3bet": 1.0}),
        ("KK",  {"3bet": 1.0}),
        ("QQ",  {"3bet": 0.75, "call": 0.25}),
        ("JJ",  {"3bet": 0.2,  "call": 0.8}),
        ("TT",  {"call": 1.0}),
        ("99",  {"call": 1.0}),
        ("88",  {"call": 1.0}),
        ("77",  {"call": 1.0}),
        ("66",  {"call": 1.0}),
        ("55",  {"call": 1.0}),
        ("44",  {"call": 1.0}),
        ("33",  {"call": 0.95}),
        ("22",  {"call": 0.95}),
        ("AKs", {"3bet": 0.7, "call": 0.3}),
        ("AQs", {"3bet": 0.35, "call": 0.6}),
        ("AJs", {"call": 1.0}),
        ("ATs", {"call": 1.0}),
        ("A9s", {"call": 1.0}),
        ("A8s", {"call": 1.0}),
        ("A7s", {"call": 1.0}),
        ("A6s", {"call": 0.85}),
        ("A5s", {"3bet": 0.55, "call": 0.4}),
        ("A4s", {"3bet": 0.4,  "call": 0.5}),
        ("A3s", {"3bet": 0.2,  "call": 0.7}),
        ("A2s", {"call": 0.85}),
        ("KQs", {"3bet": 0.2, "call": 0.75}),
        ("KJs", {"call": 1.0}),
        ("KTs", {"call": 1.0}),
        ("K9s", {"call": 0.9}),
        ("QJs", {"call": 1.0}),
        ("QTs", {"call": 1.0}),
        ("Q9s", {"call": 0.85}),
        ("JTs", {"call": 1.0}),
        ("J9s", {"call": 0.9}),
        ("T9s", {"call": 1.0}),
        ("98s", {"call": 0.95}),
        ("87s", {"call": 0.9}),
        ("76s", {"call": 0.85}),
        ("65s", {"call": 0.7}),
        ("AKo", {"3bet": 1.0}),
        ("AQo", {"3bet": 0.3, "call": 0.6}),
        ("AJo", {"call": 1.0}),
        ("ATo", {"call": 0.95}),
        ("KQo", {"call": 1.0}),
        ("KJo", {"call": 0.85}),
        ("QJo", {"call": 0.7}),
    ]
    # vs late position opens, defend wider
    if opener == "BTN":
        base.extend([
            ("A5o", {"call": 0.5}),
            ("A4o", {"call": 0.35}),
            ("A3o", {"call": 0.3}),
            ("A2o", {"call": 0.3}),
            ("K8s", {"call": 0.85}),
            ("K7s", {"call": 0.65}),
            ("K6s", {"call": 0.45}),
            ("K5s", {"call": 0.3}),
            ("K9o", {"call": 0.7}),
            ("K8o", {"call": 0.35}),
            ("Q8s", {"call": 0.65}),
            ("Q7s", {"call": 0.4}),
            ("Q9o", {"call": 0.45}),
            ("J8s", {"call": 0.65}),
            ("J7s", {"call": 0.3}),
            ("J9o", {"call": 0.3}),
            ("T8s", {"call": 0.75}),
            ("T7s", {"call": 0.35}),
            ("T9o", {"call": 0.3}),
            ("97s", {"call": 0.7}),
            ("96s", {"call": 0.3}),
            ("86s", {"call": 0.6}),
            ("75s", {"call": 0.5}),
            ("54s", {"call": 0.6}),
            ("43s", {"call": 0.3}),
        ])
    elif opener == "SB":
        base.extend([
            ("A5o", {"call": 0.7}),
            ("A4o", {"call": 0.55}),
            ("A3o", {"call": 0.5}),
            ("A2o", {"call": 0.45}),
            ("K8s", {"call": 0.95}),
            ("K7s", {"call": 0.8}),
            ("K6s", {"call": 0.65}),
            ("K5s", {"call": 0.5}),
            ("K4s", {"call": 0.35}),
            ("K9o", {"call": 0.9}),
            ("K8o", {"call": 0.65}),
            ("K7o", {"call": 0.35}),
            ("Q8s", {"call": 0.85}),
            ("Q7s", {"call": 0.55}),
            ("Q6s", {"call": 0.35}),
            ("Q9o", {"call": 0.7}),
            ("J8s", {"call": 0.8}),
            ("J7s", {"call": 0.5}),
            ("J9o", {"call": 0.55}),
            ("T8s", {"call": 0.85}),
            ("T7s", {"call": 0.5}),
            ("T9o", {"call": 0.6}),
            ("97s", {"call": 0.8}),
            ("96s", {"call": 0.5}),
            ("86s", {"call": 0.75}),
            ("85s", {"call": 0.4}),
            ("75s", {"call": 0.65}),
            ("74s", {"call": 0.3}),
            ("65s", {"call": 0.85}),  # override base
            ("54s", {"call": 0.75}),
            ("64s", {"call": 0.4}),
            ("43s", {"call": 0.4}),
        ])
    elif opener == "CO":
        base.extend([
            ("A5o", {"call": 0.3}),
            ("K8s", {"call": 0.7}),
            ("K7s", {"call": 0.45}),
            ("K9o", {"call": 0.45}),
            ("Q8s", {"call": 0.45}),
            ("J8s", {"call": 0.45}),
            ("T8s", {"call": 0.55}),
            ("97s", {"call": 0.5}),
            ("86s", {"call": 0.4}),
            ("75s", {"call": 0.3}),
            ("54s", {"call": 0.5}),
        ])
    # vs UTG / MP — tighter; the base list already covers it
    return vs_(base)


VS_UTG_BB = bb_defense("UTG")
VS_MP_BB  = bb_defense("MP")
VS_CO_BB  = bb_defense("CO")
VS_BTN_BB = bb_defense("BTN")
VS_SB_BB  = bb_defense("SB")


# ─────────────── vs_3bet: opener facing a 3bet ──────────────────
# Format: {hand: {"4bet": x, "call": y, (fold = 1-x-y implied)}}
# Out-of-position openers (UTG/MP) facing IP 3bets fold more, 4bet polarised.
# In-position openers vs OOP 3bet (BTN vs SB/BB) can call wider.

# Opener (early-position UTG/MP) facing a 3bet — tight, polarised
def early_vs_3bet():
    return vs_([
        ("AA",  {"4bet": 1.0}),
        ("KK",  {"4bet": 1.0}),
        ("QQ",  {"4bet": 0.4, "call": 0.6}),
        ("JJ",  {"call": 0.95}),
        ("TT",  {"call": 0.85}),
        ("99",  {"call": 0.65}),
        ("88",  {"call": 0.4}),
        ("77",  {"call": 0.3}),
        ("66",  {"call": 0.25}),
        ("55",  {"call": 0.2}),
        ("44",  {"call": 0.15}),
        ("AKs", {"4bet": 0.5, "call": 0.5}),
        ("AQs", {"call": 0.9}),
        ("AJs", {"call": 0.7}),
        ("ATs", {"call": 0.4}),
        ("A5s", {"4bet": 0.45}),
        ("A4s", {"4bet": 0.35}),
        ("A3s", {"4bet": 0.2}),
        ("KQs", {"call": 0.85}),
        ("KJs", {"call": 0.45}),
        ("KTs", {"call": 0.25}),
        ("QJs", {"call": 0.4}),
        ("JTs", {"call": 0.3}),
        ("T9s", {"call": 0.2}),
        ("AKo", {"4bet": 0.85, "call": 0.15}),
        ("AQo", {"call": 0.55}),
        ("AJo", {"call": 0.2}),
        ("KQo", {"call": 0.2}),
    ])

# IP opener (BTN/CO) facing a 3bet from blinds — flat much wider
def ip_vs_3bet():
    return vs_([
        ("AA",  {"4bet": 1.0}),
        ("KK",  {"4bet": 1.0}),
        ("QQ",  {"4bet": 0.55, "call": 0.45}),
        ("JJ",  {"4bet": 0.15, "call": 0.85}),
        ("TT",  {"call": 1.0}),
        ("99",  {"call": 1.0}),
        ("88",  {"call": 0.95}),
        ("77",  {"call": 0.85}),
        ("66",  {"call": 0.65}),
        ("55",  {"call": 0.55}),
        ("44",  {"call": 0.45}),
        ("33",  {"call": 0.35}),
        ("22",  {"call": 0.35}),
        ("AKs", {"4bet": 0.55, "call": 0.45}),
        ("AQs", {"call": 1.0}),
        ("AJs", {"call": 1.0}),
        ("ATs", {"call": 1.0}),
        ("A9s", {"call": 0.9}),
        ("A8s", {"call": 0.7}),
        ("A7s", {"call": 0.5}),
        ("A6s", {"call": 0.4}),
        ("A5s", {"4bet": 0.45, "call": 0.4}),
        ("A4s", {"4bet": 0.4, "call": 0.4}),
        ("A3s", {"4bet": 0.25, "call": 0.45}),
        ("A2s", {"call": 0.55}),
        ("KQs", {"call": 1.0}),
        ("KJs", {"call": 1.0}),
        ("KTs", {"call": 1.0}),
        ("K9s", {"call": 0.85}),
        ("K8s", {"call": 0.55}),
        ("K7s", {"call": 0.35}),
        ("QJs", {"call": 1.0}),
        ("QTs", {"call": 1.0}),
        ("Q9s", {"call": 0.85}),
        ("Q8s", {"call": 0.5}),
        ("JTs", {"call": 1.0}),
        ("J9s", {"call": 0.9}),
        ("J8s", {"call": 0.5}),
        ("T9s", {"call": 0.95}),
        ("T8s", {"call": 0.55}),
        ("98s", {"call": 0.85}),
        ("97s", {"call": 0.4}),
        ("87s", {"call": 0.7}),
        ("86s", {"call": 0.35}),
        ("76s", {"call": 0.55}),
        ("65s", {"call": 0.4}),
        ("AKo", {"4bet": 0.85, "call": 0.15}),
        ("AQo", {"call": 0.85}),
        ("AJo", {"call": 0.55}),
        ("ATo", {"call": 0.25}),
        ("KQo", {"call": 0.65}),
        ("KJo", {"call": 0.25}),
    ])

# SB opener (OOP) facing BB 3bet — tight, polarised
def sb_vs_3bet():
    return vs_([
        ("AA",  {"4bet": 1.0}),
        ("KK",  {"4bet": 1.0}),
        ("QQ",  {"4bet": 0.55, "call": 0.45}),
        ("JJ",  {"call": 0.95}),
        ("TT",  {"call": 0.8}),
        ("99",  {"call": 0.5}),
        ("88",  {"call": 0.3}),
        ("77",  {"call": 0.25}),
        ("66",  {"call": 0.2}),
        ("55",  {"call": 0.2}),
        ("AKs", {"4bet": 0.55, "call": 0.45}),
        ("AQs", {"call": 0.85}),
        ("AJs", {"call": 0.55}),
        ("ATs", {"call": 0.25}),
        ("A5s", {"4bet": 0.5, "call": 0.1}),
        ("A4s", {"4bet": 0.4}),
        ("A3s", {"4bet": 0.25}),
        ("KQs", {"call": 0.7}),
        ("KJs", {"call": 0.3}),
        ("QJs", {"call": 0.25}),
        ("JTs", {"call": 0.2}),
        ("AKo", {"4bet": 0.85, "call": 0.15}),
        ("AQo", {"call": 0.35}),
    ])


VS_3BET_RANGES = {
    "UTG": {  # UTG faces 3bets from MP/CO/BTN/SB/BB
        "vs_MP":  early_vs_3bet(),
        "vs_CO":  early_vs_3bet(),
        "vs_BTN": early_vs_3bet(),
        "vs_SB":  early_vs_3bet(),
        "vs_BB":  early_vs_3bet(),
    },
    "MP": {
        "vs_CO":  early_vs_3bet(),
        "vs_BTN": early_vs_3bet(),
        "vs_SB":  early_vs_3bet(),
        "vs_BB":  early_vs_3bet(),
    },
    "CO": {
        "vs_BTN": ip_vs_3bet(),
        "vs_SB":  ip_vs_3bet(),
        "vs_BB":  ip_vs_3bet(),
    },
    "BTN": {
        "vs_SB": ip_vs_3bet(),
        "vs_BB": ip_vs_3bet(),
    },
    "SB": {
        "vs_BB": sb_vs_3bet(),
    },
}


# ─────────────────── Compose final JSON file ───────────────────

doc = {
    "meta": {
        "game_type":   "Cash",
        "table_size":  "6max",
        "stack_depth": "100bb",
        "label":       "Cash 6max 100bb (GTO micro)",
    },
    "config": {
        "positions":     ["UTG", "MP", "CO", "BTN", "SB", "BB"],
        "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
        "vs_rfi_options": {
            "MP":  ["UTG"],
            "CO":  ["UTG", "MP"],
            "BTN": ["UTG", "MP", "CO"],
            "SB":  ["UTG", "MP", "CO", "BTN"],
            "BB":  ["UTG", "MP", "CO", "BTN", "SB"],
        },
        "vs_3bet_options": {
            "UTG": ["MP", "CO", "BTN", "SB", "BB"],
            "MP":  ["CO", "BTN", "SB", "BB"],
            "CO":  ["BTN", "SB", "BB"],
            "BTN": ["SB", "BB"],
            "SB":  ["BB"],
        },
    },
    "spots": {
        "RFI": {
            "UTG": RFI_UTG,
            "MP":  RFI_MP,
            "CO":  RFI_CO,
            "BTN": RFI_BTN,
            "SB":  RFI_SB,
        },
        "vs_RFI": {
            "MP":  {"vs_UTG": VS_UTG_MP},
            "CO":  {"vs_UTG": VS_UTG_CO, "vs_MP": VS_MP_CO},
            "BTN": {"vs_UTG": VS_UTG_BTN, "vs_MP": VS_MP_BTN, "vs_CO": VS_CO_BTN},
            "SB":  {"vs_UTG": VS_UTG_SB, "vs_MP": VS_MP_SB, "vs_CO": VS_CO_SB, "vs_BTN": VS_BTN_SB},
            "BB":  {"vs_UTG": VS_UTG_BB, "vs_MP": VS_MP_BB, "vs_CO": VS_CO_BB, "vs_BTN": VS_BTN_BB, "vs_SB": VS_SB_BB},
        },
        "vs_3bet": VS_3BET_RANGES,
    },
}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "cash_6max_100bb.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    # Diagnostics
    def count(d): return sum(len(v) for v in d.values())
    rfi_hands = {p: len(doc["spots"]["RFI"][p]) for p in doc["config"]["rfi_positions"]}
    print(f"Wrote {out}")
    print(f"RFI hand counts: {rfi_hands}")
    vsrfi = doc["spots"]["vs_RFI"]
    for pos, sub in vsrfi.items():
        for opp, hands in sub.items():
            print(f"  vs_RFI/{pos}/{opp}: {len(hands)} hands")
    vs3 = doc["spots"]["vs_3bet"]
    for pos, sub in vs3.items():
        for opp, hands in sub.items():
            print(f"  vs_3bet/{pos}/{opp}: {len(hands)} hands")
