# URL recipe — building the 50 nodes

Every GTOW spot is reachable by a URL. You vary three things per node —
`preflop_actions`, `history_spot`, and the hero you verify — keeping `gametype`,
`gmff_rake`, and `depth` fixed for the stake.

## URL anatomy

```
https://app.gtowizard.com/solutions?<...account/tree...>
    &gametype=<STAKE-SPECIFIC>      # identifies the solve; READ LIVE per stake
    &gmff_rake=<STAKE>             # e.g. NL100; present from NL50 up
    &depth=100                     # FORCE this — some stakes default to 300bb
    &preflop_actions=<LINE>        # the action sequence up to hero's turn
    &history_spot=<N>              # how many actions precede hero's turn
    &soltab=strategy_ev            # asks for the EV tab (SPA ignores on fresh load)
```

Two things the URL will NOT do for you, no matter what you put in it:

- **`soltab=strategy_ev` does not stick on a fresh full navigation.** The matrix
  loads in plain "strategy" mode; the EV tab is Vue store state, not a URL param. You
  must click it after load — see `browser_capture.md`.
- **`depth` sometimes defaults wrong.** NL100 opened at 300bb until `depth=100` was
  forced. Always set it and confirm the header reads "Cash 100bb".

**Reading `gametype`/`gmff_rake`:** take them from the live URL via the Chrome MCP
**Tab Context** (the tool's privacy filter blocks returning the URL from
`javascript_tool`, but Tab Context shows it). Confirming the page actually loaded a
real solve (matrix with data, header naming the stake) *is* the verification that the
`gametype` string is right — a wrong string yields an empty/fallback screen.

## The action line

`preflop_actions` is the seats' actions in order, joined by `-`:

- `F` — fold
- `R<size>` — raise *to* `<size>` big blinds (e.g. `R2.5`, `R8`, `R21.5`)
- `C` — call

`history_spot` = the number of actions before hero acts (= hero's index in the line).

### Per-spot construction

The 2nd seat is `HJ` in GTOW but `MP` in our packs; positions in seat order are
`UTG, MP(HJ), CO, BTN, SB, BB`.

**RFI** — folds from earlier seats, then hero opens. `history_spot = seat(hero)`
(UTG 0, MP 1, CO 2, BTN 3, SB 4).
```
UTG RFI : preflop_actions=        history_spot=0
CO  RFI : preflop_actions=F-F     history_spot=2
SB  RFI : preflop_actions=F-F-F-F history_spot=4
```

**vs_RFI** — one opener raises, folds to hero. `history_spot = seat(hero)`.
```
CO vs UTG : R2.5-F            history_spot=2
BB vs SB  : F-F-F-F-R<SBopen> history_spot=5
```

**vs_3bet** — hero opens, a later seat 3-bets, folds back to hero. `history_spot=6`.
```
UTG vs BB : R2.5-F-F-F-F-R<3bet>   history_spot=6
```

**vs_4bet** — 3 raisers: opener raises, hero (a later seat) 3-bets, opener 4-bets,
hero to act. Hero is the **3-bettor**, villain is the **opener**. `history_spot=7`.
```
BTN vs CO : F-F-R2.5-R<3bet>-F-F-R<4bet>   history_spot=7
```

Lines are fiddly and easy to get one fold wrong. Don't over-engineer deriving them
perfectly up front — **the capture gate verifies hero is the active card** and you
re-navigate if it's off. Build, navigate, verify, fix.

## The 50 pairs

- **RFI (5):** UTG, MP, CO, BTN, SB. (BB cannot open.)
- **vs_RFI (15):** hero vs each earlier opener —
  MP vs UTG · CO vs {UTG,MP} · BTN vs {UTG,MP,CO} · SB vs {UTG,MP,CO,BTN} ·
  BB vs {UTG,MP,CO,BTN,SB}.
- **vs_3bet (15):** opener (hero) vs a later 3-bettor —
  UTG vs {MP,CO,BTN,SB,BB} · MP vs {CO,BTN,SB,BB} · CO vs {BTN,SB,BB} ·
  BTN vs {SB,BB} · SB vs {BB}.
- **vs_4bet (15):** the mirror — hero is the 3-bettor (later seat), villain the opener
  (earlier seat): MP vs UTG · CO vs {UTG,MP} · BTN vs {UTG,MP,CO} ·
  SB vs {UTG,MP,CO,BTN} · BB vs {UTG,MP,CO,BTN,SB}.

`tools/gtow_capture_list.py data/GTOW<LIMIT>.json --out /tmp/nodes.json` emits this
list (with per-seat action recipes) from a pack's coverage gaps. For a brand-new pack
all 50 are missing, so it lists everything.

## Per-limit reference (READ LIVE — do not trust this table)

Sizes here are what past sessions read; they are recorded so you can sanity-check, not
copy. Rake changes the tree, so **always re-read from the live URL** for the stake you
are capturing. (NL10–NL200 all differed; NL500/1000/2000 happened to converge.)

| limit | gametype | gmff_rake | open / SB | notes |
|---|---|---|---|---|
| nl10 | `Cash6mGeneral_6mNL10R25` | (none) | 2.5 / 3.5 | 3bet BB vs UTG 13.5, vs SB 10.5 |
| nl50 | `Cash6m50zGeneral25Open3betV2SimpleAI` | NL50 | 2.5 / 3 | 3bet IP 7.5, SB 10, BB 9–11; 4bet 20–23 |
| nl100 | `Cash6mGeneral_6mNL100R25` | NL100 | 2.5 / 3.5 | 3bet 8–13; 4bet 20–27.5; **defaults to 300bb** |
| nl200 | `Cash6mGeneral_6mNL200R25` | NL200 | 2.5 / 3.5 | 3bet IP 8, SB 11, BB 13.5/10.5; 4bet 21.5–28.5 |
| nl500 | `Cash6mGeneral_6mNL500R25` | NL500 | 2.5 / 3.5 | 3bet MP 8, CO/BTN 8.5, SB 11.5, BB 13/10.5; 4bet 21.5–27.5 |
| nl1000 | `Cash6mGeneral_6mNL1000R25` | NL1000 | 2.5 / 3.5 | sizes matched NL500 |
| nl2000 | `Cash6mGeneral_6mNL2000R25` | NL2000 | 2.5 / 3.5 | sizes matched NL500 |

**`history_spot` summary:** RFI = seat(hero) · vs_RFI = seat(hero) · vs_3bet = 6 ·
vs_4bet = 7.

**Size lookup shortcut:** the hero's raise size for a node is the `Raise N` action
button on the page (`.sab_btn_name_bet` / `_big` whose text starts `Raise `, *not* the
first big button — that's "Allin 100"). So on a vs_RFI page you read the 3-bet size,
on a vs_3bet page the 4-bet size — collected "for free" as you capture, no separate
size-reading pass. You can also grep a saved dump:
`grep -oE 'sab_btn_name_bet[^>]*>Raise [0-9.]+' dump.html`.
