# GTO Wizard dumps → range pack

Saved HTML of GTO Wizard "Solutions" pages, one file per spot. Fed to
`tools/gtow_parse.py`, which decodes the strategy bars + EV and writes them into
`data/NL25GTOW.json`.

## How to capture a spot

1. In GTO Wizard open the spot you want (RFI / vs_RFI / vs_3bet / squeeze), tab **«стратегия + EV»**.
   ⚠️ It MUST be the *strategy + EV* view (EV numbers visible inside the cells). The
   plain *strategy* view emits cells classed `rtc_strategy_range_normalized` (no
   `_ev`, no `rtc_value`), and the parser reads **0 hands** from every such dump —
   see `docs/problems.md` P-033. If a whole folder imports as `0 hands`, this is it.
2. Save the page DOM. Easiest: DevTools → Elements → right-click `<html>` →
   *Copy → Copy outerHTML* → paste into a file here. Name it after the spot, e.g.
   `mp_rfi.html`, `co_vs_utg.html`, `co_vs_btn_3bet.html`, `bb_sqz_btn_sb.html`.

## How to import

```bash
# 1. dry-run — see what was detected & parsed, change nothing
python3 tools/gtow_parse.py tools/gtow_dumps/co_vs_utg.html

# 2. write into the pack (makes a timestamped .bak first)
python3 tools/gtow_parse.py tools/gtow_dumps/co_vs_utg.html --apply
```

If the history strip is ambiguous (auto-detection wrong), override it:

```bash
python3 tools/gtow_parse.py tools/gtow_dumps/co_vs_btn_3bet.html \
    --spot vs_3bet --pos CO --villain BTN --apply
```

## Batch import, config & coverage (the fast path)

For a whole limit, don't parse files one by one — use the orchestrator. See
`BOOKMARKLET.md` for the capture + one-command flow. In short:

```bash
python3 tools/gtow_sort_downloads.py --apply     # ~/Downloads -> per-limit folders
python3 tools/gtow_import_limits.py --apply      # all limits: spots + config + coverage
```

- **`tools/gtow_import_limits.py`** — reads `limits.json` (limit -> {folder, pack}) and,
  per limit, imports every dump, refreshes `config` option maps, prints coverage.
  One `.bak` per pack. `--limit nl10` to do just one; default is dry-run.
- **`tools/gtow_autoconfig.py pack --apply`** — rebuilds `config.vs_rfi_options` /
  `vs_3bet_options` / … from the data already in `spots` (fixes P-033's empty-config
  side-effect, so the frontend shows the spots). Run automatically by the orchestrator.
- **`tools/gtow_coverage.py pack`** — what's filled vs. what's left to capture
  (RFI / vs_RFI / vs_3bet expected from the table's seats; squeeze/vs_squeeze present-only).
- **`⚠ SHRINK` guard** — the importer warns when an incoming dump has FEWER hands than
  the spot already in the pack (a stale re-capture rolling it back). Keep folders to
  *current* dumps and delete superseded ones before `--apply`.

## Browser autocapture (optional, ⚠ ToS risk)

To skip the per-spot clicking, `tools/gtow_autocapture.py` drives a real browser to
save spots and verifies each one parsed (catches the wrong-tab trap on the spot).
**This automates navigation/extraction of GTOW — beyond "save page" — and may
violate their terms; your account is what's at risk.** Untested in CI (needs a real
browser); the `navigate_to_node` hook must be wired to the live GTOW UI first.

```bash
pip install playwright && playwright install chromium        # once, on the Mac
python3 tools/gtow_capture_list.py data/GTOWNL10.json --out /tmp/nodes.json
python3 tools/gtow_autocapture.py /tmp/nodes.json --dry-run   # see the plan
python3 tools/gtow_autocapture.py /tmp/nodes.json --mode guided   # you navigate, it saves+verifies
```

`gtow_capture_list.py` turns the coverage gaps into a node list (spot/hero/villain +
per-seat action recipe). The browser profile (`tools/gtow_dumps/.browser_profile/`)
holds your GTOW session and is gitignored.

## Notes

- **Position names:** GTO Wizard calls the 2nd seat `HJ`; our packs call it `MP`.
  The parser aliases `HJ → MP` automatically (hero and villain).
- **Action mapping:** the aggressive bars (Raise + Allin) merge into one schema
  action — `open` (RFI), `3bet` (vs_RFI), `4bet` (vs_3bet), `squeeze` (squeeze).
  Green = `call`, blue = fold (implicit, dropped).
- **Squeeze nodes** (1 opener + ≥1 cold caller in front of hero — e.g. GTOW node
  `F-F-F-R2.5-C`: BTN opens, SB calls, BB to act) auto-detect as spot `squeeze`
  and write under the bare seating-pair key `"<opener>-<caller>"` (opener first,
  e.g. `BTN-SB`) — no `vs_` prefix. Capture trap (same as vs_3bet): the active
  card in the history strip must be HERO, not the next seat — confirm the matrix
  header is the hero's position before you copy the DOM.
- **Multiway refuse (P-026):** a node our schema can't represent yet — a limped
  pot (0 raisers + caller) or a squeeze over a 3-bet (2 raisers + caller) — makes
  the parser refuse with a clear message instead of mislabelling it. This refuse
  is NOT bypassable with `--spot` (override stays only for a missing strip).
- **Thresholds:** an action whose frequency rounds to `0.00` (< 0.5%) is dropped;
  EV is stored only for hands whose displayed EV ≠ 0. This makes parser output a
  little finer than the old hand-transcribed numbers (it catches sub-1% slivers
  the screenshot reads missed) — expected, and more accurate.
- Dumps are disposable; keep or delete them after import as you like.
