"""
gtow_capture_list.py — turn a pack's coverage gaps into a machine-readable list of
GTO Wizard nodes to capture, with a per-seat action recipe and a human-readable
description for each.

This is the bridge between "what's missing" (gtow_coverage) and "go capture it"
(gtow_autocapture). It emits, for every missing RFI / vs_RFI / vs_3bet spot, the
exact preflop action sequence that defines the node, so a human (guided mode) or a
browser driver (auto mode) knows precisely where to navigate in GTOW.

The recipe is derived from seating order (config.positions), so it's universal:

  vs_RFI  hero=CO villain=UTG   -> UTG opens, MP folds, hero CO to act
  vs_3bet hero=UTG villain=BB   -> UTG opens, folds to BB, BB 3-bets, hero UTG to act

Action labels are SEMANTIC (open / fold / 3bet / 4bet), not bet sizes — the GTOW
tree fixes the size, so navigation maps "open" -> click the Raise button, etc.

USAGE
-----
  python3 tools/gtow_capture_list.py data/GTOWNL10.json                 # print plan
  python3 tools/gtow_capture_list.py data/GTOWNL10.json --out nodes.json
  python3 tools/gtow_capture_list.py data/GTOWNL10.json --limit nl10    # force tag
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
import gtow_coverage as cov  # noqa: E402

DUMPS_DIR = os.path.join(cov.BASE_DIR, "tools", "gtow_dumps")
LIMITS_MAP = os.path.join(DUMPS_DIR, "limits.json")

# spot -> (raise-action label, short filename tag)
_SPOT_META = {
    "vs_RFI": ("3bet", "vsRFI"),
    "vs_3bet": ("4bet", "vs3bet"),
}


def limit_for_pack(pack_path, forced=None):
    """Reverse-lookup the limit label for a pack from limits.json (or --limit)."""
    if forced:
        return forced
    if os.path.isfile(LIMITS_MAP):
        with open(LIMITS_MAP, encoding="utf-8") as f:
            mapping = json.load(f)
        target = os.path.abspath(pack_path)
        for label, entry in mapping.items():
            entry_pack = entry["pack"]
            entry_abs = (entry_pack if os.path.isabs(entry_pack)
                         else os.path.join(cov.BASE_DIR, entry_pack))
            if os.path.abspath(entry_abs) == target:
                return label
    # fall back to the pack's filename stem, lowercased
    return os.path.splitext(os.path.basename(pack_path))[0].lower()


def build_recipe(positions, spot, hero, villain):
    """
    Return (recipe, description) for a heads-up node.
      recipe: [[seat, action], ...] for every seat that acts BEFORE hero's decision
      description: human sentence ending in "hero <POS> to act"
    """
    order = positions
    hi = order.index(hero)
    recipe = []

    if spot == "vs_RFI":
        # One opener (villain) seated before hero; everyone else before hero folds.
        for seat in order[:hi]:
            recipe.append([seat, "open" if seat == villain else "fold"])

    elif spot == "vs_3bet":
        # Hero opened first; a later seat (villain) 3-bet; action is back to hero.
        vi = order.index(villain)
        for seat in order[:hi]:
            recipe.append([seat, "fold"])
        recipe.append([hero, "open"])
        for seat in order[hi + 1:vi]:
            recipe.append([seat, "fold"])
        recipe.append([villain, "3bet"])
    else:
        raise ValueError(f"no recipe builder for spot {spot!r}")

    verb = {"open": "opens", "fold": "folds", "3bet": "3-bets", "4bet": "4-bets"}
    parts = [f"{seat} {verb[act]}" for seat, act in recipe]
    desc = ", ".join(parts) + f", hero {hero} to act"
    return recipe, desc


def make_nodes(data, limit):
    """Build a capture node for every missing vs_RFI / vs_3bet spot in the pack.
    (RFI gaps, if any, are listed too but need no action recipe.)"""
    positions = data.get("config", {}).get("positions", [])
    report = cov.coverage(data)
    nodes = []
    for spot, hero, villain in report["missing"]:
        if spot == "RFI":
            tag = f"gtow_{limit}_{hero}_RFI.html"
            nodes.append({
                "limit": limit, "spot": "RFI", "hero": hero, "villain": None,
                "recipe": [], "desc": f"all fold to {hero}, hero {hero} opens",
                "out": os.path.join("tools", "gtow_dumps", limit, tag),
            })
            continue
        recipe, desc = build_recipe(positions, spot, hero, villain)
        _, shorttag = _SPOT_META[spot]
        tag = f"gtow_{limit}_{hero}_{shorttag}_{villain}.html"
        nodes.append({
            "limit": limit, "spot": spot, "hero": hero, "villain": villain,
            "recipe": recipe, "desc": desc,
            "tab": "стратегия + EV",
            "out": os.path.join("tools", "gtow_dumps", limit, tag),
        })
    return nodes


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate a GTOW capture list from coverage gaps.")
    p.add_argument("pack", help="pack JSON to scan for gaps")
    p.add_argument("--limit", help="limit tag (default: from limits.json / filename)")
    p.add_argument("--out", help="write the node list to this JSON file")
    args = p.parse_args(argv)

    with open(args.pack, encoding="utf-8") as f:
        data = json.load(f)
    limit = limit_for_pack(args.pack, args.limit)
    nodes = make_nodes(data, limit)

    if not nodes:
        print(f"no gaps in {args.pack} — nothing to capture.")
        return

    print(f"{len(nodes)} nodes to capture for limit '{limit}':\n")
    for n in nodes:
        print(f"  {n['spot']:8} {n['hero']:4} "
              f"{('vs ' + n['villain']) if n['villain'] else '':9}  {n['desc']}")
        print(f"           -> {n['out']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\nwrote {len(nodes)} nodes -> {args.out}")
    else:
        print("\n(pass --out nodes.json to save for gtow_autocapture.py)")


if __name__ == "__main__":
    main()
