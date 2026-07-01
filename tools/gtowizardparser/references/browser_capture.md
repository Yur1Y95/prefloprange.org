# Browser capture — the Chrome MCP loop

This is the fragile heart of the skill. For each of the 50 nodes you: navigate →
wait for the strategy to *actually* load → force the "strategy + EV" tab → confirm
hero → save the page to `~/Downloads`. The recipe below ran NL500/NL1000/NL2000 (150
nodes) with zero edits; treat it as settled and change it only with a reason.

## The per-node loop

1. **Navigate** to the node URL (Chrome MCP `navigate`). You may pipe up to ~5 nodes
   through `browser_batch: [navigate, javascript_tool]` — the injected JS polls for
   load itself, so a batch stays correct.
2. **Inject one self-contained async IIFE** (template below) via `javascript_tool`. A
   full navigation is a real reload, so `window.*` helpers are wiped every time —
   **inline the whole thing each call**, don't stash helpers on `window`.
3. **Read the returned scalars.** `heroOK:false` → the line/`history_spot` is wrong;
   fix it and re-navigate. `evOK:false` but `cells>=169` → data is there, the EV tab
   just didn't catch; **do not re-navigate** — re-run a short EV-dispatch+save on the
   already-loaded page.
4. The save drops `gtow_<limit>_<hero>_<sig>.html` into `~/Downloads`.

## The capture IIFE (template)

Replace `<HEROTOKEN>` with the GTOW seat name (**MP hero → `HJ`**), and `<FILENAME>`
with `gtow_<limit>_<hero>_<spot-sig>.html`. Keep the body short — deep vs_4bet nodes
risk the CDP 45s `Runtime.evaluate` timeout (trap 4).

```js
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // --- load gate -----------------------------------------------------------
  const cells   = () => document.querySelectorAll('[id^="0_"]').length;
  const active  = () => {
    const a = document.querySelector('[data-tst*="_preflop_"][data-tst$="_active"]');
    return a ? a.getAttribute('data-tst') : '';
  };
  // A cell is "loaded" once a non-fold (non-blue) bar is painted. AA is *usually*
  // a raise, but in deep blind-vs-blind vs_4bet AA is a pure call (green) — so gate
  // on AA OR KK being non-blue, never on "AA is red" (trap 8).
  const nonFold = id => {
    const el = document.getElementById(id);
    if (!el) return false;
    const bg = (el.getAttribute('style') || '') + el.style.backgroundImage;
    const m = bg.match(/rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g) || [];
    return m.some(s => { const [r,g,b]=s.match(/\d+/g).map(Number); return !(b>=r&&b>=g); });
  };
  const loaded = () => nonFold('0_AA') || nonFold('0_KK');

  // poll <=30 * 500ms for: 169 cells AND a painted strategy AND hero is active
  let ok = false;
  for (let i = 0; i < 30; i++) {
    if (cells() >= 169 && loaded() && active().endsWith('_<HEROTOKEN>_active')) { ok = true; break; }
    await sleep(500);
  }

  // --- force the "strategy + EV" tab (trap 2) ------------------------------
  const fire = el => ['pointerdown','mousedown','pointerup','mouseup','click']
    .forEach(t => el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window})));
  const evCells = () => document.querySelectorAll('.rtc_strategy_ev_range_normalized').length;

  for (let tries = 0; tries < 4 && evCells() === 0; tries++) {
    // the caret that opens the tab menu sits at x<150, 168<y<205 (an info overlay
    // hovers above the tab and steals clicks aimed higher — trap 2)
    const caret = [...document.querySelectorAll('.gw_pop_menu_opener')].find(e => {
      const r = e.getBoundingClientRect(); return r.left < 150 && r.top > 168 && r.top < 205;
    });
    if (caret) { fire(caret); await sleep(600); }
    // the menu item whose label contains both "стратеги" and "ev"
    const item = [...document.querySelectorAll('.gwbtns_btn')].find(e => {
      const t = (e.textContent || '').toLowerCase();
      return t.includes('стратеги') && t.includes('ev');
    });
    if (item) { fire(item); await sleep(1200); }
  }

  // --- save the page (trap 3: never return HTML, write a file) -------------
  let saved = false;
  if (cells() >= 169 && evCells() > 0) {
    const blob = new Blob([document.documentElement.outerHTML], {type:'text/html'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = '<FILENAME>';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    saved = true;
  }

  // return ONLY scalars — the tool cuts anything with a URL/query string (trap 3)
  return JSON.stringify({
    cells: cells(), evCells: evCells(), active: active(),
    heroOK: active().endsWith('_<HEROTOKEN>_active'), evOK: evCells() > 0, saved
  });
})();
```

## The 8 traps (P-034) — what breaks and the fix

1. **Chrome blocks a run of automatic downloads.** After ~3 silent
   `a.download`+click saves, Chrome shows an address-bar "allow multiple downloads?"
   prompt and blocks the rest — files just stop appearing though the JS runs clean.
   **Fix:** the user clicks the blocked-downloads icon → "Always allow
   app.gtowizard.com" once. You can't reach the address bar; ask them to pre-allow at
   the start of a session. (Hasn't fired on NL50–NL2000 — profile-dependent, but be
   ready.)
2. **EV tab won't apply from the URL.** `soltab=strategy_ev` is ignored on a fresh
   load; the dropdown caret + menu item must be clicked with a **full pointer-event
   dispatch** (`pointerdown→mousedown→pointerup→mouseup→click`). `element.click()` and
   coordinate clicks are unreliable — the control listens for pointer events, and an
   info overlay (`gmfover gw_loading_text`) hovers above the tab stealing high clicks.
3. **`javascript_tool` output cap + privacy filter.** Raw HTML can't come back through
   the tool (cut as "Cookie/query string data", truncated ~2KB). **Save to disk**
   (Blob → `~/Downloads`) and return only scalars.
4. **Deep nodes (vs_4bet) load slower → CDP 45s timeout.** A long JS body (5s
   pre-pause + long polls + many retries) can blow the `Runtime.evaluate` 45s limit.
   **Fix:** no pre-pause, poll-cap 30×500ms, EV retries ≤4. On timeout the page is
   still loaded — don't re-navigate; finish EV+save in a separate light call.
5. **Default depth 300bb.** Force `&depth=100` and confirm the header reads
   "Cash 100bb" before trusting a dump.
6. **Chrome appends "(1)" to a repeated filename.** Re-saving `x.html` writes
   `x (1).html`, not an overwrite. On a re-capture, parse/copy the **freshest** file
   (`ls -t` / mtime), not the stale one. In the normal one-shot flow names are unique.
7. **Save only after a REAL load, not just 169 cells.** A fast batch can paint the
   169-cell skeleton and history strip *before* the strategy loads → a dump that
   parses as 0 hands or `spot=None`. Tell-tale: a smaller file (~237KB vs ~300KB).
   Gate on **169 cells AND active card AND AA|KK non-blue** together.
8. **"AA is red" is not a universal load signal.** Deep blind-vs-blind vs_4bet has AA
   as a pure **call** (green), so a "wait for red AA" gate hangs there forever and
   returns a false NOT_LOADED though the strategy loaded. Gate on **AA OR KK
   non-blue** (KK is a raise even where AA flats), as the template does.

## After a node returns

- `heroOK:false` → wrong line; the active token tells you which seat you actually
  landed on. Adjust `preflop_actions`/`history_spot` and re-navigate.
- `evOK:false`, `cells>=169` → re-run just the EV-dispatch + save block on the loaded
  page (don't re-navigate).
- `saved:true` with a sane `cells`/`evCells` → move on. Capture the hero's raise size
  off the page now (the `Raise N` button — see `url_recipe.md`) so the next spot's
  line is ready without a separate pass.
