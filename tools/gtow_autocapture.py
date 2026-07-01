"""
gtow_autocapture.py — drive a real browser to save GTO Wizard spots automatically,
then verify each saved page actually parsed (catches the P-033 wrong-tab trap and
bad navigation immediately).

⚠️ STATUS / SCOPE — READ FIRST
------------------------------
* This was written in an environment WITHOUT a browser; it is **not run-tested**.
  It must be run on your Mac, where a real browser and your logged-in GTOW session
  live. Expect to tweak the two GTOW-specific hooks (`navigate_to_node`,
  `ensure_ev_tab`) against the live site — they're the only site-coupled parts and
  are marked LOUDLY below.
* ⚠️ **ToS:** automating navigation/extraction of GTO Wizard goes beyond the
  bookmarklet's "save this page" and may violate GTOW's terms — your paid account
  is the thing at risk. This is your call (you opted in). The script paces itself
  like a human and saves one page at a time; it does NOT hammer their servers.

WHAT IT DOES
------------
Reads a capture list (from gtow_capture_list.py) and, for each node:
  1. (auto mode) navigate GTOW to the node + switch to the «стратегия + EV» tab,
     OR (guided mode) ask YOU to navigate, then press Enter;
  2. save the page DOM to the node's per-limit dump path;
  3. immediately re-parse it with gtow_parse and print OK / ⚠ REDO with the hand
     count — so a 0-hand dump (wrong tab, wrong seat) is caught on the spot.

After a run, the existing pipeline takes over:
  python3 tools/gtow_import_limits.py --limit <limit> --apply

INSTALL (on the Mac, once)
--------------------------
  pip install playwright
  playwright install chromium

USAGE
-----
  # generate the list of gaps first
  python3 tools/gtow_capture_list.py data/GTOWNL10.json --out /tmp/nodes.json

  # see the plan, no browser:
  python3 tools/gtow_autocapture.py /tmp/nodes.json --dry-run

  # guided capture (works today; you navigate, it saves+verifies+names+files):
  python3 tools/gtow_autocapture.py /tmp/nodes.json --mode guided

  # full auto (once navigate_to_node is wired to the live site):
  python3 tools/gtow_autocapture.py /tmp/nodes.json --mode auto
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/
import gtow_parse as gw  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GTOW_URL = "https://app.gtowizard.com/solutions"
# A persistent profile dir keeps you logged into GTOW between runs (log in once).
DEFAULT_PROFILE = os.path.join(BASE_DIR, "tools", "gtow_dumps", ".browser_profile")


# --------------------------------------------------------------------------- #
# Verification — the safety net (works without a browser)
# --------------------------------------------------------------------------- #

def verify_dump(path):
    """Re-parse a saved dump. Returns (ok, message). ok is False for 0-hand pages
    (wrong tab / wrong seat) and for unsupported multiway nodes (P-026)."""
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        return False, f"not saved ({e})"
    try:
        spot, hero, villain = gw.detect_spot(html)
    except gw.UnsupportedNode as e:
        return False, f"unsupported node: {e}"
    if not spot:
        return False, "no history strip — is this a Solutions page?"
    strategy, ev_map = gw.build_entries(html, spot)
    label = hero + ("" if spot == "RFI" else f" {gw.pack_key(spot, villain)}")
    if not strategy:
        return False, (f"{spot} {label}: 0 hands — wrong tab? "
                       "use «стратегия + EV», not «стратегия» (P-033)")
    return True, f"{spot} {label}: {len(strategy)} hands, {len(ev_map)} ev"


# --------------------------------------------------------------------------- #
# GTOW-specific hooks — THE ONLY SITE-COUPLED PARTS. Wire these to the live site.
# --------------------------------------------------------------------------- #

def ensure_ev_tab(page):
    """
    Make sure the matrix is showing the «стратегия + EV» view (cells must carry EV,
    class rtc_strategy_ev_range_normalized) — otherwise every dump parses to 0 hands
    (P-033). Best-effort: click the EV tab if present. SELECTOR IS A GUESS — confirm
    it against the live GTOW DOM and fix if needed.
    """
    for sel in ('text=Стратегия + EV', 'text=Strategy + EV',
                '[data-tst*="strategy_ev"]', '[data-tst*="ev"]'):
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_timeout(400)
                return True
        except Exception:
            pass
    return False  # couldn't find it — guided mode relies on you having set the tab


def navigate_to_node(page, node):
    """
    Navigate GTOW to `node` (spot/hero/villain + `recipe` = [[seat, action], ...]).

    ⚠️ NOT IMPLEMENTED — this is the piece that needs the live site. Two ways to do
    it; pick whichever GTOW actually supports (the desktop Claude with the browser
    should check this FIRST):

      (A) URL-DRIVEN (preferred, robust): if selecting a node changes the URL/hash
          to encode the action line (e.g. .../solutions?line=F-F-F-R2.5 or a #hash),
          just build that URL from `node['recipe']` and `page.goto(url)`. No clicks,
          nothing to break when GTOW's CSS changes. Check: open two different nodes
          and diff page.url.

      (B) CLICK-DRIVEN (fragile): click the action ribbon seat-by-seat following
          `node['recipe']` — Fold/Call/Raise buttons in order. Needs stable
          selectors and breaks on GTOW redesigns.

    Until wired, raise so 'auto' mode fails loudly instead of saving wrong pages.
    Use --mode guided in the meantime (it doesn't need this).
    """
    raise NotImplementedError(
        "navigate_to_node is a stub — wire it to GTOW (URL-driven preferred) or "
        "use --mode guided. See the docstring."
    )


# --------------------------------------------------------------------------- #
# Save + run loop
# --------------------------------------------------------------------------- #

def save_page(page, out_abs):
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    html = page.evaluate("() => document.documentElement.outerHTML")
    with open(out_abs, "w", encoding="utf-8") as f:
        f.write(html)


def run(nodes, mode, profile_dir, pace_ms):
    from playwright.sync_api import sync_playwright  # lazy: only needed for a real run

    ok_count = redo = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(GTOW_URL)
        input("\nLog into GTOW in the opened window, open the Solutions page, "
              "then press Enter to start capturing...")

        for i, node in enumerate(nodes, 1):
            out_abs = os.path.join(BASE_DIR, node["out"])
            print(f"\n[{i}/{len(nodes)}] {node['desc']}")

            if mode == "auto":
                try:
                    navigate_to_node(page, node)
                    ensure_ev_tab(page)
                    page.wait_for_timeout(pace_ms)
                except NotImplementedError as e:
                    print(f"  auto mode not wired: {e}")
                    return
                except Exception as e:
                    print(f"  ⚠ navigation failed: {e} — skipping")
                    redo += 1
                    continue
            else:  # guided
                ensure_ev_tab(page)  # best-effort; you can also set it by hand
                input("  navigate to this node on the «стратегия + EV» tab, "
                      "then press Enter to save...")

            save_page(page, out_abs)
            good, msg = verify_dump(out_abs)
            if good:
                ok_count += 1
                print(f"  OK   {msg}  -> {node['out']}")
            else:
                redo += 1
                print(f"  ⚠ REDO  {msg}")

        ctx.close()

    print(f"\n{ok_count} captured OK, {redo} need redo.")
    if ok_count:
        limit = nodes[0]["limit"]
        print(f"next: python3 tools/gtow_import_limits.py --limit {limit} --apply")


def main(argv=None):
    p = argparse.ArgumentParser(description="Browser-drive GTOW spot capture.")
    p.add_argument("nodes", help="capture-list JSON from gtow_capture_list.py")
    p.add_argument("--mode", choices=["guided", "auto"], default="guided",
                   help="guided: you navigate, it saves+verifies; auto: hands-off")
    p.add_argument("--profile", default=DEFAULT_PROFILE,
                   help="persistent browser profile dir (keeps GTOW login)")
    p.add_argument("--pace", type=int, default=1500,
                   help="ms to wait after navigation before saving (auto mode)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan and exit (no browser)")
    args = p.parse_args(argv)

    with open(args.nodes, encoding="utf-8") as f:
        nodes = json.load(f)
    if not nodes:
        print("empty capture list — nothing to do.")
        return

    print(f"{len(nodes)} nodes, mode={args.mode}:")
    for n in nodes:
        print(f"  {n['spot']:8} {n['hero']:4} "
              f"{('vs ' + n['villain']) if n['villain'] else '':9}  {n['desc']}")

    if args.dry_run:
        print("\n(dry-run — re-run without --dry-run to launch the browser)")
        return

    run(nodes, args.mode, args.profile, args.pace)


if __name__ == "__main__":
    main()
