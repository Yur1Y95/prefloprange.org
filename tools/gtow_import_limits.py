"""
gtow_import_limits.py — one command to import every limit's dumps into its pack.

gtow_import_all.py handles ONE folder -> ONE pack. Once you're maintaining several
stakes (nl10, nl25, nl50, ...) you don't want to remember each folder/pack pairing
and run it by hand. This reads a mapping file and, for each limit, does the whole
pass end to end:

    1. parse every dump in the limit's folder      (gtow_import_all.process_folder)
    2. merge the spots into the pack                (gtow_parse.merge_into_data)
    3. refresh config villain-options from the data (gtow_autoconfig — fixes P-033)
    4. print a coverage report: what's left to grab (gtow_coverage)

Steps 2+3 share ONE timestamped .bak per pack (not one per spot, not one per step).

MAPPING FILE  (tools/gtow_dumps/limits.json)
--------------------------------------------
    {
      "nl10": { "folder": "tools/gtow_dumps/nl10", "pack": "data/GTOWNL10.json" },
      "nl25": { "folder": "tools/gtow_dumps/nl25", "pack": "data/NL25GTOW.json"  }
    }
Paths are relative to the project root. Add a limit = add one line.

USAGE
-----
  python3 tools/gtow_import_limits.py                  # dry-run, ALL limits
  python3 tools/gtow_import_limits.py --apply          # import + config + coverage
  python3 tools/gtow_import_limits.py --limit nl10 --apply        # just one limit
  python3 tools/gtow_import_limits.py --map other_map.json        # custom mapping
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
import gtow_parse as gw          # noqa: E402
import gtow_import_all as ia     # noqa: E402
import gtow_autoconfig as ac     # noqa: E402
import gtow_coverage as cov      # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MAP = os.path.join(BASE_DIR, "tools", "gtow_dumps", "limits.json")


def _abs(path):
    """Resolve a mapping path relative to the project root."""
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def import_limit(label, folder, pack, apply):
    """Run the full pass for one limit. Returns True if anything was parsed."""
    print(f"\n{'='*64}\n{label}   {folder}  ->  {pack}\n{'='*64}")
    folder, pack = _abs(folder), _abs(pack)

    if not os.path.isdir(folder):
        print(f"  ! folder not found — skipping ({folder})")
        return False
    if not os.path.isfile(pack):
        print(f"  ! pack not found — skipping ({pack})")
        return False

    parsed, skipped = ia.process_folder(folder)
    ia.print_parsed(parsed, skipped)

    if apply and parsed:
        with open(pack, encoding="utf-8") as f:
            data = json.load(f)
        ia.warn_overwrites(parsed, data)   # flag stale dumps shrinking a spot
        backup = f"{pack}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(pack, backup)
        for _, spot, hero, villain, _, strategy, ev_map in parsed:
            gw.merge_into_data(data, spot, hero, villain, strategy, ev_map)
        ac.apply_options(data, ac.derive_options(data))   # refresh config (P-033)
        with open(pack, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\napplied {len(parsed)} spots + refreshed config -> {pack}")
        print(f"backup -> {backup}")
    elif apply:
        print("\nnothing to apply")

    # Coverage of the pack as it now stands (post-import when --apply).
    print()
    with open(pack, encoding="utf-8") as f:
        cov._print(cov.coverage(json.load(f)), pack)
    return bool(parsed)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Import every limit's GTOW dumps into its pack.")
    p.add_argument("--map", default=DEFAULT_MAP, help="mapping JSON (limit -> folder/pack)")
    p.add_argument("--limit", help="only this limit label from the map")
    p.add_argument("--apply", action="store_true", help="write into the packs")
    args = p.parse_args(argv)

    with open(args.map, encoding="utf-8") as f:
        mapping = json.load(f)

    if args.limit:
        if args.limit not in mapping:
            sys.exit(f"limit {args.limit!r} not in map (have: {', '.join(mapping)})")
        mapping = {args.limit: mapping[args.limit]}

    for label, entry in mapping.items():
        import_limit(label, entry["folder"], entry["pack"], args.apply)

    if not args.apply:
        print(f"\n{'='*64}\n(dry-run — re-run with --apply to write packs + config)")


if __name__ == "__main__":
    main()
