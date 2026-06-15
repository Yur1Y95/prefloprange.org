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
javascript:(function(){try{var h=document.documentElement.outerHTML;var a=document.querySelector('[data-tst*="_preflop_"][data-tst$="_active"]');var p=a?(a.getAttribute('data-tst').match(/_preflop_([A-Z0-9+]+)_active/)||[])[1]:'';var n='gtow_'+(p||'spot')+'_'+Date.now()+'.html';var b=new Blob([h],{type:'text/html'});var u=URL.createObjectURL(b);var e=document.createElement('a');e.href=u;e.download=n;document.body.appendChild(e);e.click();e.remove();setTimeout(function(){URL.revokeObjectURL(u);},1500);}catch(err){alert('GTOW grab failed: '+err);}})();
```

> Some browsers strip a leading `javascript:` when you paste into the URL field.
> If the bookmark does nothing, edit it and re-type `javascript:` at the front.

## Use (per spot)

1. In GTO Wizard open a spot on the **"стратегия + EV"** tab. Make sure the matrix
   header is the seat you want as **hero** (the active card) — same capture rule as
   before.
2. Click **GTOW grab** on the bookmarks bar.
3. A file `gtow_<HERO>_<number>.html` lands in your **Downloads** folder.

The filename's `<HERO>` is just a convenience tag; the importer re-detects the real
spot/hero/villain from the saved page, so you don't have to name anything by hand.

## Import a batch

Move the captures into a per-limit folder, then import them all at once:

```bash
# move this run's captures into the NL10 folder
mv ~/Downloads/gtow_*.html ~/Desktop/Poker_Trainer/tools/gtow_dumps/nl10/

# dry-run: see what each dump parsed to (writes nothing)
python3 tools/gtow_import_all.py tools/gtow_dumps/nl10

# write them all into the NL10 pack (one timestamped .bak first)
python3 tools/gtow_import_all.py tools/gtow_dumps/nl10 --file data/GTOWNL10.json --apply
```

One folder per limit (`nl10/`, `nl25/`, …) so dumps from different stakes never
mix into the wrong pack.
