# GTOW one-click dump bookmarklet

Instead of opening DevTools and copying `outerHTML` for every spot, this
bookmarklet saves the current GTO Wizard page to an `.html` file in one click.
The page stays exactly as you're viewing it — no automation, no scraping, just a
"save this page" button.

## Install (once)

1. Show the bookmarks bar in Chrome: `⌘⇧B`.
2. Right-click the bar → **Add page…** (or **Add bookmark**).
3. **Name:** `GTOW grab`
4. **URL:** paste the whole line below (it starts with `javascript:`):

```
javascript:(function(){try{var L=(prompt('Limit tag for this capture:',localStorage.getItem('gtow_limit')||'nl10')||'').trim();if(!L){return;}localStorage.setItem('gtow_limit',L);L=L.replace(/[^A-Za-z0-9]+/g,'').toLowerCase();var a=document.querySelector('[data-tst*="_preflop_"][data-tst$="_active"]');var hero=a?((a.getAttribute('data-tst').match(/_preflop_([A-Z0-9+]+)_active/)||[])[1]||'spot'):'spot';hero=hero.replace(/[^A-Za-z0-9+]/g,'');var acts=[].filter.call(document.querySelectorAll('.hspotcrd_action_text'),function(e){return e.closest('.hspotcrd_action_active');}).map(function(e){return e.textContent.trim();});var sig=acts.join('-').replace(/[^A-Za-z0-9.]+/g,'').slice(0,40)||'node';var t=(''+Date.now()).slice(-4);var n='gtow_'+L+'_'+hero+'_'+sig+'_'+t+'.html';var h=document.documentElement.outerHTML;var b=new Blob([h],{type:'text/html'});var u=URL.createObjectURL(b);var e=document.createElement('a');e.href=u;e.download=n;document.body.appendChild(e);e.click();e.remove();setTimeout(function(){URL.revokeObjectURL(u);},1500);}catch(err){alert('GTOW grab failed: '+err);}})();
```

> Some browsers strip a leading `javascript:` when you paste into the URL field.
> If the bookmark does nothing, edit it and re-type `javascript:` at the front.

## Use (per spot)

1. In GTO Wizard open a spot on the **"стратегия + EV"** tab. Make sure the matrix
   header is the seat you want as **hero** (the active card) — same capture rule as
   before.
2. Click **GTOW grab** on the bookmarks bar.
3. It asks for a **limit tag** (pre-filled with your last one — just press Enter to
   reuse `nl10`, or type `nl25` etc.). The tag is remembered for next time.
4. A self-describing file lands in your **Downloads** folder:

   ```
   gtow_<limit>_<hero>_<action-signature>_<id>.html
   e.g.  gtow_nl10_BB_Raise2.5-Fold-Fold-Call_8033.html
   ```

The `<limit>` token is what routes the file to the right pack (see below); the
`<hero>` and `<action-signature>` make the dump readable at a glance. None of it is
authoritative — the importer **re-detects** the real spot/hero/villain from the
saved page, so a wrong tag never corrupts anything, it just mislabels the filename.

## Import — the one-command flow

After a capture session, sort the Downloads into per-limit folders, then import
**every limit** into its pack (ranges + config + a coverage report) in one go:

```bash
# 1. route ~/Downloads/gtow_<limit>_*.html into tools/gtow_dumps/<limit>/
python3 tools/gtow_sort_downloads.py            # dry-run, then:
python3 tools/gtow_sort_downloads.py --apply

# 2. import all mapped limits: spots -> pack, refresh config, print coverage
python3 tools/gtow_import_limits.py             # dry-run, then:
python3 tools/gtow_import_limits.py --apply
```

The limit→pack mapping lives in `tools/gtow_dumps/limits.json` — add a stake = add
one line. To import just one: `--limit nl10`. For a single folder the old
`gtow_import_all.py <folder> --file <pack> --apply` still works.

> ⚠ **Folders hold *current* dumps, not stale ones.** The importer replaces a spot
> with whatever dump is in the folder, so an old re-capture can roll a spot back
> (e.g. SB RFI 109 → 96 hands). The importer prints a loud `⚠ SHRINK` warning when
> an incoming dump has fewer hands than what's already in the pack — if you see it,
> delete the stale dump before `--apply`.

One folder per limit (`nl10/`, `nl25/`, …) so dumps from different stakes never
mix into the wrong pack.
