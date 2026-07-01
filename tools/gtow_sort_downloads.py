"""
gtow_sort_downloads.py — route captured GTOW dumps from ~/Downloads into the right
per-limit dump folder.

The bookmarklet saves files as  gtow_<limit>_<hero>_<sig>.html  into your browser's
Downloads folder (a bookmarklet can't choose the save location). This reads the
`<limit>` token from each filename and moves the file into
`tools/gtow_dumps/<limit>/`, ready for gtow_import_limits.py.

Default is a dry-run (shows the moves, touches nothing); pass --apply to move.

USAGE
-----
  python3 tools/gtow_sort_downloads.py                  # dry-run, ~/Downloads
  python3 tools/gtow_sort_downloads.py --apply          # actually move
  python3 tools/gtow_sort_downloads.py --limit nl10 --apply   # force one limit
                                          # (use for old gtow_<HERO>_<ts> dumps)
  python3 tools/gtow_sort_downloads.py --downloads /path/to/dir --apply
"""

import argparse
import glob
import os
import re
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMPS_DIR = os.path.join(BASE_DIR, "tools", "gtow_dumps")
_SAFE = re.compile(r"[^A-Za-z0-9]")


def limit_of(filename, forced=None):
    """The limit folder for a dump. Forced wins; else the 2nd '_'-field
    (gtow_<limit>_...). Returns None if it can't be determined."""
    if forced:
        return _SAFE.sub("", forced).lower() or None
    parts = os.path.basename(filename).split("_")
    if len(parts) >= 3 and parts[0] == "gtow":
        return _SAFE.sub("", parts[1]).lower() or None
    return None


def plan(downloads, forced=None):
    """Return [(src, dest_folder, dest_path or None, limit or None), ...]."""
    out = []
    for src in sorted(glob.glob(os.path.join(downloads, "gtow_*.html"))):
        lim = limit_of(src, forced)
        if not lim:
            out.append((src, None, None, None))
            continue
        folder = os.path.join(DUMPS_DIR, lim)
        out.append((src, folder, os.path.join(folder, os.path.basename(src)), lim))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Sort GTOW dumps into per-limit folders.")
    p.add_argument("--downloads", default=os.path.expanduser("~/Downloads"),
                   help="source folder (default ~/Downloads)")
    p.add_argument("--limit", help="force all matched files into this limit folder")
    p.add_argument("--apply", action="store_true", help="actually move the files")
    args = p.parse_args(argv)

    rows = plan(args.downloads, args.limit)
    if not rows:
        print(f"no gtow_*.html in {args.downloads}")
        return

    moved = skipped = 0
    for src, folder, dest, lim in rows:
        name = os.path.basename(src)
        if lim is None:
            print(f"  ? {name}  — can't read limit (pass --limit to force)")
            skipped += 1
            continue
        rel = os.path.relpath(dest, BASE_DIR)
        if args.apply:
            os.makedirs(folder, exist_ok=True)
            shutil.move(src, dest)
            print(f"  -> {rel}")
        else:
            print(f"  would move {name}  ->  {rel}")
        moved += 1

    print(f"\n{moved} to move, {skipped} unrecognised"
          + ("" if args.apply else "  (dry-run — re-run with --apply)"))


if __name__ == "__main__":
    main()
