"""
gtow_import_all.py — batch-import a whole folder of GTO Wizard dumps into one
range pack.

The single-file gtow_parse.py is great for one spot at a time, but capturing a
limit means dozens of dumps. This walks a folder, detects + parses each dump, and
(with --apply) merges them ALL into the pack in one pass with a single timestamped
.bak — instead of one .bak per spot.

Nodes our schema can't represent (limped pots, squeeze-over-3bet, a cold-caller
facing a squeeze) are reported and skipped, never mislabelled (see P-026).

USAGE
-----
  # dry-run: show every dump's detected spot/hero/villain + range size
  python3 tools/gtow_import_all.py tools/gtow_dumps/nl10

  # write them all into a specific pack (one .bak, then overwrite)
  python3 tools/gtow_import_all.py tools/gtow_dumps/nl10 --file data/GTOWNL10.json --apply

Keep one folder per pack so dumps from different limits never mix.
"""

import argparse
import glob
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))           # tools/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # root
import gtow_parse as gw  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Batch-import GTOW dumps into a pack.")
    p.add_argument("folder", help="folder of saved .html dumps")
    p.add_argument("--file", default=gw.DEFAULT_FILE, help="target pack JSON")
    p.add_argument("--glob", default="*.html", help="filename pattern (default *.html)")
    p.add_argument("--apply", action="store_true", help="write into the pack")
    args = p.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.folder, args.glob)))
    if not files:
        sys.exit(f"no dumps matched {args.glob!r} in {args.folder}")

    parsed, skipped = [], []
    for fp in files:
        name = os.path.basename(fp)
        with open(fp, encoding="utf-8") as f:
            html = f.read()
        try:
            spot, hero, villain = gw.detect_spot(html)
        except gw.UnsupportedNode as e:
            skipped.append((name, str(e)))
            continue
        if not spot or not hero or (spot != "RFI" and not villain):
            skipped.append((name, "could not resolve spot/hero/villain (no history strip?)"))
            continue
        strategy, ev_map = gw.build_entries(html, spot)
        key = "—" if spot == "RFI" else gw.pack_key(spot, villain)
        parsed.append((name, spot, hero, villain, key, strategy, ev_map))
        print(f"{name:34} {spot:11} {hero:5} {key:22} "
              f"{len(strategy):3} hands  {len(ev_map):3} ev")

    # Detect duplicate destinations (two dumps writing the same spot/hero/key).
    seen = {}
    for name, spot, hero, _, key, *_ in parsed:
        dest = (spot, hero, key)
        if dest in seen:
            print(f"  ! {name} overwrites {seen[dest]} (same {spot} {hero} {key})")
        seen[dest] = name

    print(f"\n{len(parsed)} parsed, {len(skipped)} skipped")
    for name, why in skipped:
        print(f"  skip {name}: {why}")

    if not args.apply:
        print("\n(dry-run — re-run with --apply to write into the pack)")
        return

    if not parsed:
        sys.exit("nothing to apply")

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)
    backup = f"{args.file}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(args.file, backup)
    for _, spot, hero, villain, _, strategy, ev_map in parsed:
        gw.merge_into_data(data, spot, hero, villain, strategy, ev_map)
    with open(args.file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\napplied {len(parsed)} spots -> {args.file}\nbackup -> {backup}")


if __name__ == "__main__":
    main()
