# Import pipeline — dumps → pack → verified

Once the `.html` dumps are captured, the rest is the project's tested tooling. Run it,
don't reimplement it.

## 0. Make the dumps reachable

Captured files land in the user's real `~/Downloads`; the import scripts run in the
sandbox, whose `~` is **not** the user's home. Request access to the Downloads folder
(`request_cowork_directory` on Downloads) so the sandbox can read it, then pass that
mounted path explicitly to the sorter. (Alternatively `cp` the `gtow_<limit>_*.html`
files into `tools/gtow_dumps/<limit>/` yourself.)

## 1. Sort into the limit folder

```bash
# dry-run first, then --apply; pass the real Downloads mount, not sandbox ~
python3 tools/gtow_sort_downloads.py --downloads <MOUNTED_DOWNLOADS> --limit <lim>
python3 tools/gtow_sort_downloads.py --downloads <MOUNTED_DOWNLOADS> --limit <lim> --apply
```

This moves `gtow_<limit>_*.html` into `tools/gtow_dumps/<lim>/`. One folder per limit
— never let two stakes share a folder, or dumps import into the wrong pack.

## 2. Import (spots + config + coverage in one pass)

```bash
python3 tools/gtow_import_limits.py --limit <lim>           # dry-run: what parsed
python3 tools/gtow_import_limits.py --limit <lim> --apply   # write pack + config
```

Per limit this parses every dump, merges spots into the pack, rebuilds
`config.vs_rfi_options`/`vs_3bet_options`/`vs_4bet_options` from the data
(`gtow_autoconfig`, so the frontend shows the spots), and prints coverage — all under
**one** timestamped `.bak`.

Watch the output for:
- **`⚠ SHRINK`** — an incoming dump has fewer hands than the spot already in the pack
  (a stale re-capture rolling it back). Delete the stale dump and re-run; don't apply
  over good data.
- **refuse / skipped** — `gtow_parse` refuses nodes our schema can't hold (limped pot,
  squeeze-over-3bet — P-026). Expected for stray multiway dumps; they're listed and
  skipped, not mislabelled. The refuse is **not** bypassable with `--spot`.
- **`HJ → MP`** — applied automatically (hero and villain); no action needed.

Single-dump fallback (debugging one spot):
```bash
python3 tools/gtow_parse.py tools/gtow_dumps/<lim>/<dump>.html            # dry-run
python3 tools/gtow_parse.py tools/gtow_dumps/<lim>/<dump>.html --apply    # one spot
# --spot/--pos/--villain only when the history strip is genuinely ambiguous,
# never to override a refuse.
```

## New limit (pack/folder/mapping don't exist yet)

The importer **skips a limit whose pack file is missing**, so set these up first:

1. **Add a line to `tools/gtow_dumps/limits.json`:**
   ```json
   "nl300": { "folder": "tools/gtow_dumps/nl300", "pack": "data/GTOWNL300.json" }
   ```
2. **Create the dump folder:** `tools/gtow_dumps/nl300/`.
3. **Create the empty pack** `data/GTOWNL300.json` with this skeleton — `autoconfig`
   fills the `*_options` from the data on import, so leave them empty:
   ```json
   {
     "meta": { "game_type": "Cash", "table_size": "6max", "stack_depth": "100bb",
               "label": "GTO Wizard NL300 6-max 100bb" },
     "config": {
       "positions": ["UTG","MP","CO","BTN","SB","BB"],
       "rfi_positions": ["UTG","MP","CO","BTN","SB"],
       "vs_rfi_options": {}, "vs_3bet_options": {}, "vs_4bet_options": {},
       "squeeze_options": {}, "vs_squeeze_options": {}
     },
     "spots": { "RFI": {}, "vs_RFI": {}, "vs_3bet": {}, "vs_4bet": {} },
     "ev":    { "RFI": {}, "vs_RFI": {}, "vs_3bet": {}, "vs_4bet": {} }
   }
   ```

## Verify

1. **Coverage** — should read `RFI 5/5`, `vs_RFI 15/15`, `vs_3bet 15/15`, and the
   `vs_4bet` pairs you grabbed:
   ```bash
   python3 tools/gtow_coverage.py data/GTOW<LIMIT>.json
   ```
2. **Load through the engine** — confirm the pack parses and `ev` mirrors `spots`
   without orphans (a stray empty/`vs_null` record is the kind of thing this catches —
   see P-035):
   ```bash
   python3 -c "import range_engine as r; d=r.load_range_file('data/GTOW<LIMIT>.json'); \
   print('RFI', list(d['spots']['RFI'])); print('ev RFI UTG AA', r.get_ev(d,'RFI','UTG','AA'))"
   ```
3. **If you changed any tool** (you normally shouldn't), run the suites — the project
   rule is "tests are part of done":
   ```bash
   python3 tools/test_gtow_parse.py && python3 tools/test_gtow_tools.py
   ```

## Docs (end-of-chat convention)

A new pack is a real project event — record it so the next chat knows:
- **`CLAUDE.md`** — add a short `GTOWNL<N>` paragraph near decision #13 (4 spots
  filled, frequencies + EV, gametype/rake, the live sizes you read).
- **`docs/roadmap.md`** — note the pack under the GTOW track.
- **`docs/problems.md`** — only if a genuinely new capture trap appeared (extend P-034).
- **Security** — before any `git push`, scan the diff for secrets and remind the user.
  Dumps are gitignored (`tools/gtow_dumps/**/*.html`); make sure no cookie/token leaked
  into a pack, doc, or the skill.
