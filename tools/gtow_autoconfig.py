"""
gtow_autoconfig.py — rebuild a pack's config option maps from the data it actually
holds, so the frontend's villain selectors light up for every spot you captured.

THE PROBLEM IT FIXES (P-033)
----------------------------
The frontend decides which villain buttons to show for vs_RFI / vs_3bet (and which
spots exist at all) from `config.vs_rfi_options` / `config.vs_3bet_options` etc.
When you batch-import GTOW dumps the data lands in `spots`, but the config maps stay
`{}` — so the page shows nothing, even though the ranges are right there. You then
have to hand-write the config. This derives it from `spots` instead.

WHAT IT DERIVES
---------------
For every spot that has data, the bare villain key under each hero:
  vs_RFI    -> vs_rfi_options[hero]     = [opener, ...]          (bare positions)
  vs_3bet   -> vs_3bet_options[hero]    = [3bettor, ...]
  vs_4bet   -> vs_4bet_options[hero]    = [4bettor, ...]
  iso       -> iso_options[hero]        = [limper-spot, ...]
  squeeze   -> squeeze_options[hero]    = ["<opener>-<caller>", ...]   (bare lineup)
  vs_squeeze-> vs_squeeze_options[hero] = ["<opener>-<squeezer>-<caller(s)>", ...]

Villain lists are sorted by seating order (config.positions). The frontend prepends
"vs_" itself for the heads-up spots, so we store BARE positions — matching how the
hand-written packs (cash_micro_100bb, NL25GTOW) already look.

NOTE: as of today the frontend reads vs_rfi_options / vs_3bet_options / vs_4bet_options
/ iso_options. squeeze_options / vs_squeeze_options are written for forward-compat
(the squeeze pages aren't wired yet) — harmless, and ready when they are.

Each option map is fully REBUILT from the data (data is the source of truth for a
GTOW pack), so the run is idempotent. rfi_positions is left as-is when present.

USAGE
-----
  python3 tools/gtow_autoconfig.py data/GTOWNL10.json            # dry-run diff
  python3 tools/gtow_autoconfig.py data/GTOWNL10.json --apply    # write config
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
import gtow_coverage as cov  # noqa: E402  (reuse _order / present_villains)

# spot -> config key holding its villain options
SPOT_OPTION_KEY = {
    "vs_RFI": "vs_rfi_options",
    "vs_3bet": "vs_3bet_options",
    "vs_4bet": "vs_4bet_options",
    "iso": "iso_options",
    "squeeze": "squeeze_options",
    "vs_squeeze": "vs_squeeze_options",
}


def derive_options(data):
    """Return {config_key: {hero: [villain-key, ...]}} from non-empty spots only."""
    config = data.get("config", {})
    spots = data.get("spots", {})
    key = cov._order(config.get("positions", []))
    # squeeze lineups sort by their opener (first token), then the whole string
    lineup_key = lambda s: (key(s.split("-")[0]), s)

    out = {}
    for spot, cfg_key in SPOT_OPTION_KEY.items():
        node = spots.get(spot, {})
        hero_map = {}
        for hero in node:
            villains = cov.present_villains(spots, spot, hero)
            if not villains:
                continue
            sort = lineup_key if spot in ("squeeze", "vs_squeeze") else key
            hero_map[hero] = sorted(villains, key=sort)
        if hero_map:
            out[cfg_key] = {h: hero_map[h] for h in sorted(hero_map, key=key)}
    return out


def diff_options(config, derived):
    """Yield human-readable change lines comparing current config to derived."""
    for cfg_key, new_map in derived.items():
        old_map = config.get(cfg_key, {})
        if old_map == new_map:
            yield f"  {cfg_key}: unchanged ({len(new_map)} heroes)"
            continue
        yield f"  {cfg_key}:"
        heroes = sorted(set(old_map) | set(new_map),
                        key=cov._order(config.get("positions", [])))
        for hero in heroes:
            old_v, new_v = old_map.get(hero), new_map.get(hero)
            if old_v == new_v:
                continue
            if old_v is None:
                yield f"      + {hero}: {new_v}"
            elif new_v is None:
                yield f"      - {hero}: (removed)"
            else:
                yield f"      ~ {hero}: {old_v} -> {new_v}"


def apply_options(data, derived):
    """Overwrite the derived option maps in data['config'] (full rebuild)."""
    config = data.setdefault("config", {})
    for cfg_key, new_map in derived.items():
        config[cfg_key] = new_map


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Rebuild config villain-option maps from a pack's spots.")
    p.add_argument("file", nargs="?", default=cov.DEFAULT_FILE, help="pack JSON")
    p.add_argument("--apply", action="store_true", help="write into the pack")
    args = p.parse_args(argv)

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    derived = derive_options(data)
    if not derived:
        print("no vs_/squeeze data in spots — nothing to derive.")
        return

    print(f"config options derived from {args.file}:\n")
    lines = list(diff_options(data.get("config", {}), derived))
    print("\n".join(lines) if lines else "  (no changes)")

    if not args.apply:
        print("\n(dry-run — re-run with --apply to write config)")
        return

    backup = f"{args.file}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(args.file, backup)
    apply_options(data, derived)
    with open(args.file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\napplied -> {args.file}\nbackup  -> {backup}")


if __name__ == "__main__":
    main()
