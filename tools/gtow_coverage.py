"""
gtow_coverage.py — what's filled and what's still missing in a range pack.

Capturing a limit means clicking through dozens of GTO Wizard spots. It's easy to
lose track of which (hero, villain) pairs you've already grabbed. This walks a
pack and prints a per-spot coverage table plus a flat "remaining to capture" list,
so you know exactly what's left to click — instead of remembering by hand.

The expected RFI / vs_RFI / vs_3bet matrix is derived purely from the pack's
`config.positions` + `config.rfi_positions` by seating order (same logic the hand
seating uses), so it's universal — works for 6-max, 8-max, any pack:

    RFI       : every position that can open                     -> rfi_positions
    vs_RFI    : hero faces one opener seated before them         -> openers before hero
    vs_3bet   : an opener (hero) faces a 3-bet from a later seat  -> seats after hero

squeeze / vs_squeeze are combinatorial (any opener × caller(s) × squeezer), so
there's no finite "expected" set — they're reported present-only (what you've got),
not as missing.

USAGE
-----
  python3 tools/gtow_coverage.py                       # default pack
  python3 tools/gtow_coverage.py data/GTOWNL10.json    # a specific pack
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(BASE_DIR, "data", "NL25GTOW.json")

# Heads-up spots store villains under "vs_<POS>"; we compare on the bare position.
_VS_PREFIX = "vs_"


def _order(positions):
    """Return a sort key: seat -> seating index (unknown seats sort last)."""
    idx = {p: i for i, p in enumerate(positions)}
    return lambda p: idx.get(p, len(positions))


def expected_matrix(config):
    """
    The full RFI / vs_RFI / vs_3bet target for this table, by seating order.
      returns {"RFI": [hero...],
               "vs_RFI": {hero: [villain...]},
               "vs_3bet": {hero: [villain...]}}
    """
    positions = config.get("positions", [])
    rfi = config.get("rfi_positions", positions[:-1])  # BB can't open by default
    idx = {p: i for i, p in enumerate(positions)}

    vs_rfi = {}
    for hero in positions:
        openers = [v for v in rfi if idx.get(v, 99) < idx.get(hero, -1)]
        if openers:
            vs_rfi[hero] = openers

    vs_3bet = {}
    for hero in rfi:  # only a seat that can open can later face a 3-bet
        threebettors = [v for v in positions if idx.get(v, -1) > idx.get(hero, 99)]
        if threebettors:
            vs_3bet[hero] = threebettors

    return {"RFI": list(rfi), "vs_RFI": vs_rfi, "vs_3bet": vs_3bet}


def present_villains(spots, spot, hero):
    """Bare villain positions that have NON-empty data for (spot, hero)."""
    node = spots.get(spot, {}).get(hero, {})
    out = []
    for key, strat in node.items():
        if not strat:
            continue
        out.append(key[len(_VS_PREFIX):] if key.startswith(_VS_PREFIX) else key)
    return out


def coverage(data):
    """Compute coverage; returns a dict the printer (and tests) can consume."""
    config = data.get("config", {})
    spots = data.get("spots", {})
    exp = expected_matrix(config)
    key = _order(config.get("positions", []))

    report = {"heads_up": {}, "multiway": {}, "missing": []}

    # RFI — a flat list of heroes.
    have_rfi = [h for h, s in spots.get("RFI", {}).items() if s]
    miss_rfi = [h for h in exp["RFI"] if h not in have_rfi]
    report["heads_up"]["RFI"] = {
        "have": sorted(have_rfi, key=key),
        "missing": sorted(miss_rfi, key=key),
        "total": len(exp["RFI"]),
    }
    report["missing"] += [("RFI", h, None) for h in sorted(miss_rfi, key=key)]

    # vs_RFI / vs_3bet — hero × villain grids.
    for spot in ("vs_RFI", "vs_3bet"):
        have_pairs, miss_pairs, total = [], [], 0
        for hero in sorted(exp[spot], key=key):
            want = exp[spot][hero]
            got = set(present_villains(spots, spot, hero))
            total += len(want)
            for v in sorted(want, key=key):
                if v in got:
                    have_pairs.append((hero, v))
                else:
                    miss_pairs.append((hero, v))
                    report["missing"].append((spot, hero, v))
        report["heads_up"][spot] = {
            "have": have_pairs, "missing": miss_pairs, "total": total,
        }

    # squeeze / vs_squeeze — present-only (no finite expected set).
    for spot in ("squeeze", "vs_squeeze"):
        node = spots.get(spot, {})
        present = []
        for hero in sorted(node, key=key):
            for lineup, strat in node[hero].items():
                if strat:
                    present.append((hero, lineup))
        report["multiway"][spot] = present

    return report


def _print(report, path):
    print(f"coverage — {path}\n")

    def bar(have, total):
        return f"{have}/{total}" + ("  ✓ complete" if have == total and total else "")

    for spot in ("RFI", "vs_RFI", "vs_3bet"):
        info = report["heads_up"][spot]
        print(f"  {spot:8} {bar(len(info['have']), info['total'])}")
        if spot == "RFI":
            if info["missing"]:
                print(f"      missing: {', '.join(info['missing'])}")
        else:
            if info["missing"]:
                # group missing villains per hero for a compact line
                by_hero = {}
                for hero, v in info["missing"]:
                    by_hero.setdefault(hero, []).append(v)
                for hero, vs in by_hero.items():
                    print(f"      {hero} vs: {', '.join(vs)}")
    print()

    for spot in ("squeeze", "vs_squeeze"):
        present = report["multiway"][spot]
        if present:
            pairs = ", ".join(f"{h}[{l}]" for h, l in present)
            print(f"  {spot:11} present: {pairs}")
        else:
            print(f"  {spot:11} (none — combinatorial, capture as needed)")
    print()

    miss = report["missing"]
    if not miss:
        print("✓ RFI / vs_RFI / vs_3bet fully covered — nothing left to capture.")
    else:
        print(f"remaining to capture ({len(miss)} spots):")
        for spot, hero, v in miss:
            if v is None:
                print(f"  {spot:8} {hero}")
            else:
                print(f"  {spot:8} {hero} vs {v}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_FILE
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _print(coverage(data), path)


if __name__ == "__main__":
    main()
