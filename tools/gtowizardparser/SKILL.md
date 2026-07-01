---
name: gtowizardparser
description: >-
  Capture GTO Wizard preflop ranges (strategy + EV) for ONE cash stake and import
  them into a Poker_Trainer range pack. Use this whenever the user wants to pull /
  parse / grab / capture GTOW ranges or fill a pack for a limit — e.g.
  "GTOWizardParser NL300", "спарси диапазоны с NL500", "собери NL100 + EV",
  "нужны префлоп-диапазоны из GTO Wizard", "добей покрытие GTOW для nl50", or to
  extend an existing GTOW pack. Drives GTO Wizard in the browser via the Chrome MCP
  on the user's logged-in account, then runs the project's own parser/importer.
  Covers the 50-node cash 6-max tree (RFI ×5, vs_RFI ×15, vs_3bet ×15, vs_4bet ×15)
  with per-hand frequencies + EV. Trigger even when the user only names a stake and
  says "parse" / "capture" / "спарси" without spelling out the steps.
---

# GTOWizardParser — capture GTO Wizard preflop ranges into a Poker_Trainer pack

## What this is

A repeatable orchestrator for the workflow that already filled 8 packs (NL10…NL2000).
The user names a stake; you produce a complete preflop range pack for it — RFI,
vs_RFI, vs_3bet, vs_4bet, with frequencies **and** GTO EV — and import it into
`data/GTOW<LIMIT>.json`.

**The parser is not this skill.** Decoding the GTOW DOM into ranges+EV is done by the
already-tested `tools/gtow_parse.py`; importing is `tools/gtow_import_limits.py`;
coverage is `tools/gtow_coverage.py`. Those are solid — do **not** reimplement them.
This skill owns the one part that was never packaged and is genuinely fragile: the
**browser capture** — navigating GTOW's 50 nodes, forcing the "strategy + EV" tab,
and saving each page so the parser has something to read.

## Boundary and safety — read before running

- **This drives a third-party paid site.** Capture navigates GTO Wizard
  programmatically (Chrome MCP), which goes beyond "save this page" and may violate
  GTOW's terms — the user's paid account is what is at risk. The user has accepted
  this risk (CLAUDE.md decision #13). Still, say one plain sentence reminding them
  before a fresh run, and never run it against an account the user hasn't OK'd.
- **Never persist secrets.** GTOW pages and the browser profile contain auth
  cookies/JWTs. Dumps are gitignored (`tools/gtow_dumps/**/*.html`). Never copy
  cookies, tokens, `localStorage`, or `Authorization` headers into the repo, a pack,
  the chat, or memory. From `javascript_tool` return **only scalars** (counts, the
  active-card token, button labels) — anything containing the URL/query string is
  cut by the tool's privacy filter anyway.
- **You drive the browser each run.** This is not a hands-off background job. Expect
  to be in the loop via Chrome MCP. (A separate Playwright path exists in
  `tools/gtow_autocapture.py` but its navigation hook is unimplemented and it carries
  more ToS exposure — out of scope here.)

## Prerequisites

1. **Chrome MCP connected** and a Chrome tab logged into GTO Wizard with an active
   solver subscription. If the extension isn't connected, ask the user to connect it
   — do not fall back to clicking pixels.
2. **Workspace can read the user's Downloads.** Captured `.html` lands in the real
   `~/Downloads`; the import tools run in the sandbox. Request access to the
   Downloads folder so the sandbox can see those files (see
   `references/import_pipeline.md`).
3. **Repo present** at the Poker_Trainer root with `tools/gtow_*.py` and
   `tools/gtow_dumps/limits.json`.

## Scope

**In scope:** one cash **6-max** stake, the "general 2.5x / with cold calls" tree,
100bb, four spots — RFI, vs_RFI, vs_3bet, vs_4bet — frequencies + EV. That is the
50-node pack this skill is proven on (NL500/NL1000/NL2000 ran with zero recipe edits).

**Out of scope (do not promise these here):**
- **squeeze / vs_squeeze** — the parser supports them, but there is no stable capture
  recipe yet; capture by hand if needed, don't fold into a 50-node run.
- **iso** — not a GTOW spot; `gtow_parse.detect_spot` deliberately refuses limped
  pots. Comes from `parsed/` hand-history buckets instead.
- **non-cash / non-6-max trees, other depths or open sizes** — a different tree means
  different `gametype` and sizes; treat as a new, separate effort.

## Run flow

Work one stake per run. Each step points to the reference with the exact details.

1. **Confirm the stake and resolve the pack.** Map the user's words to a limit token
   and pack path the way `limits.json` does: `NL300` → token `nl300`, folder
   `tools/gtow_dumps/nl300/`, pack `data/GTOWNL300.json`. If the limit isn't in
   `tools/gtow_dumps/limits.json`, or the pack file doesn't exist, you'll create both
   in step 5 — see `references/import_pipeline.md` (§ New limit).

2. **Read the live tree from GTOW — never hardcode.** Open a GTOW solution for this
   stake and read `gametype`, `gmff_rake`, and **every bet size** off the live page.
   Sizes differ by rake/stake (NL10…NL200 all differed); reusing another stake's
   numbers silently builds wrong lines. Known values for past packs are in
   `references/url_recipe.md` as a **reference only** — re-read, don't assume. Force
   `depth=100` (some stakes default to 300bb).

3. **Build the 50-node list.** RFI ×5 + vs_RFI ×15 + vs_3bet ×15 + vs_4bet ×15. The
   per-spot line construction (`preflop_actions`, `history_spot`) is in
   `references/url_recipe.md`. `tools/gtow_capture_list.py data/GTOW<LIMIT>.json`
   turns coverage gaps into a machine list if the pack already exists; for a fresh
   pack, all 50 are missing.

4. **Capture each node in the browser.** For every node: navigate → wait for the
   strategy to actually load → force the "strategy + EV" tab → verify the active card
   is your hero → save the page to `~/Downloads`. The exact loop, the load gate, the
   EV-tab dispatch, and the **8 known traps** are in `references/browser_capture.md`.
   Follow it precisely — these traps are why naive capture fails.

5. **Import.** Sort the dumps into the limit folder, then run the importer (it merges
   spots, refreshes `config`, and prints coverage in one pass). Commands and the
   new-pack skeleton are in `references/import_pipeline.md`.

6. **Verify and record.** Coverage should read `RFI 5/5`, `vs_RFI 15/15`,
   `vs_3bet 15/15`, and the `vs_4bet` pairs you grabbed. Load the pack through
   `range_engine` to confirm `ev` mirrors `spots` with no orphans. Then update the
   project docs per the end-of-chat convention (`references/import_pipeline.md`
   § Verify & docs).

## Non-negotiable invariants

These are the things that, when skipped, produce silent bad data:

- **Read sizes live, per stake.** Hardcoded sizes = wrong `preflop_actions` lines =
  you capture the wrong node and never notice.
- **Confirm hero before saving.** The matrix you save must be hero's. The history
  strip's active card (`[data-tst$="_active"]`) must end in `_<HERO>_active`. Note
  **GTOW calls the 2nd seat `HJ`, our packs call it `MP`** — so MP-hero shows
  `_HJ_active`; the parser aliases `HJ → MP` on import.
- **EV tab, not plain strategy.** A dump from the plain "strategy" tab has cells
  classed `rtc_strategy_range_normalized` (no `_ev`) and parses as **0 hands**. The
  gate must confirm `rtc_strategy_ev_range_normalized` cells exist before saving.
- **One folder per limit.** Dumps for different stakes never share a folder, or they
  import into the wrong pack. Keep only *current* dumps — the importer's `⚠ SHRINK`
  warning flags a stale re-capture rolling a spot back.

## Reference files

- `references/url_recipe.md` — building the 50 URLs: params, per-spot line + `history_spot`, per-limit `gametype`/`gmff_rake`/sizes table (reference only — read live).
- `references/browser_capture.md` — the Chrome MCP capture loop: load gate, EV-tab JS-dispatch, save-to-Downloads, and the 8 P-034 traps with fixes.
- `references/import_pipeline.md` — sort → import → coverage, creating a new limit/pack, and the end-of-chat doc updates.
