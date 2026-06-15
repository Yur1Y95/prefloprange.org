"""
gtow_parse.py — extract a preflop range (strategy + EV) from a saved GTO Wizard
"Solutions" page and (optionally) merge it into a range-pack JSON.

WHY THIS EXISTS
---------------
GTO Wizard does not give you the numbers as text. In the matrix each hand cell
encodes its strategy as a stack of coloured CSS bars (background-image gradients
+ background-size widths) and shows the hand EV as a tiny number. Until now we
transcribed those by hand off screenshots (see CLAUDE.md decision #13) — slow and
error-prone. This script reads the raw HTML of the page and decodes both layers
exactly, so the test pack NL25GTOW.json can be filled reproducibly.

WHAT IT READS
-------------
The "стратегия + EV" table (left range table). Its cells carry
class "rtc_strategy_ev_range_normalized" and id "0_<HAND>" (e.g. "0_AKs").
  - strategy  -> the background gradient colours + sizes
  - hand EV   -> the <span> inside .rtc_value
The right "EV-only" table (id "1_*") is ignored: on free accounts it is empty
(placeholder colours, all zeros, often display:none).

COLOUR -> ACTION
----------------
GTO Wizard's palette (stable across spots):
  blue   rgb(61,124,184)  -> Fold
  green  rgb(90,185,102)  -> Call
  reds   rgb(240,60,60) / rgb(125,31,31) -> Raise / Allin (aggressive bucket)
The colour only says fold/call/raise; what the *raise* means (open, 3bet, 4bet)
depends on the spot, which we read from the action history strip at the top.

USAGE
-----
  python3 tools/gtow_parse.py DUMP.html                 # dry-run: show what was parsed
  python3 tools/gtow_parse.py DUMP.html --apply          # write into data/NL25GTOW.json
  # override auto-detection if the history strip is ambiguous:
  python3 tools/gtow_parse.py DUMP.html --spot vs_3bet --pos CO --villain BTN --apply

A timestamped .bak of the JSON is written before any --apply.
"""

import argparse
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(BASE_DIR, "data", "NL25GTOW.json")

# Drop an action whose frequency rounds to 0.00 (raw < 0.5%). These slivers are
# solver noise and clutter the pack; everything >= 0.5% is kept verbatim.
FREQ_DROP = 0.005

# GTO Wizard names the 2nd seat "HJ"; our packs call it "MP".
POSITION_ALIASES = {"HJ": "MP"}

# Spot -> name of the single aggressive (non-call) action in our schema.
RAISE_ACTION = {"RFI": "open", "vs_RFI": "3bet", "vs_3bet": "4bet",
                "vs_4bet": "allin", "squeeze": "squeeze", "vs_squeeze": "4bet"}


class UnsupportedNode(Exception):
    """The history strip describes a table shape our schema can't represent yet
    (a limped pot, or a squeeze over a 3-bet). We raise instead of guessing a
    spot label, so a stray multiway dump can't silently poison the pack — see
    problems.md P-026."""


# --------------------------------------------------------------------------- #
# Strategy matrix
# --------------------------------------------------------------------------- #

_CELL_RE = re.compile(
    r'class="rtc rtc_strategy_ev_range_normalized ra_table_cell"\s+'
    r'id="0_([^"]+)"[^>]*?style="([^"]*)"'
)
_VALUE_RE = re.compile(r'class="rtc_value"><span>([^<]*)</span>')
_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_BG_RE = re.compile(
    r"background-image:\s*(.*?);\s*background-size:\s*([^;\"]*)", re.DOTALL
)


def classify_colour(r, g, b):
    """Map a bar colour to a strategy role by dominant channel (palette-agnostic)."""
    if b >= r and b >= g:
        return "fold"
    if g >= r:
        return "call"
    return "raise"


def parse_cell_style(style):
    """
    Return {'call': freq, 'raise': freq} as fractions (fold dropped) for one cell.

    The bars are CSS layers all anchored at the left edge; the first-listed layer
    is on top and has the smallest width. So with widths w1 < w2 < ... the visible
    segment of colour i is (w_i - w_{i-1}). Summed per role -> frequencies.
    """
    m = _BG_RE.search(style)
    if not m:
        return {}
    image_part, size_part = m.group(1), m.group(2)

    # One colour per linear-gradient layer (each gradient is solid: from==to).
    colours = []
    for piece in image_part.split("linear-gradient")[1:]:
        rgb = _RGB_RE.search(piece)
        if rgb:
            colours.append(classify_colour(*(int(x) for x in rgb.groups())))

    sizes = []
    for token in size_part.split(","):
        token = token.strip()
        if token:
            sizes.append(float(token.split()[0].rstrip("%")))

    if len(colours) != len(sizes):
        # Layers and widths must line up; if not, the cell markup changed.
        return {}

    roles = {}
    prev = 0.0
    for role, size in zip(colours, sizes):
        roles[role] = roles.get(role, 0.0) + (size - prev) / 100.0
        prev = size
    roles.pop("fold", None)
    return roles


def parse_matrix(html):
    """
    Yield (hand, roles, ev) for every strategy cell, in matrix (DOM) order.
      roles: {'call': f, 'raise': f}  (only present roles)
      ev:    float (0.0 when the cell shows "0")
    """
    matches = list(_CELL_RE.finditer(html))
    for i, m in enumerate(matches):
        hand, style = m.group(1), m.group(2)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        vm = _VALUE_RE.search(html[m.end():end])
        try:
            ev = float(vm.group(1).strip()) if vm else 0.0
        except ValueError:
            ev = 0.0
        yield hand, parse_cell_style(style), ev


# --------------------------------------------------------------------------- #
# Action-history strip -> (spot, hero, villain)
# --------------------------------------------------------------------------- #

_HIST_HEADER_RE = re.compile(r'data-tst="hs_(\d+)_preflop_([A-Z0-9]+?)(_active)?"')
_ACTIVE_ACTION_RE = re.compile(
    r"hspotcrd_action_active.*?hspotcrd_action_text\">([^<]*)<", re.DOTALL
)


def detect_spot(html):
    """
    Read the history strip and return (spot, hero, villain). hero is the seat to
    act (card marked *_active); position names are aliased to ours (HJ -> MP).

    The spot is decided by how many raisers AND callers acted before hero — not
    raisers alone (counting raisers only was the P-026 bug, which mislabelled a
    cold-call node as vs_RFI). Both counts together separate heads-up from
    multiway:

        raisers x callers -> spot
          0 x 0  -> RFI                1 x 0  -> vs_RFI
          2 x 0  -> vs_3bet            3 x 0  -> vs_4bet
          1 x >=1 -> squeeze     (villain := "<opener>-<caller(s)>")
          2 x >=1 -> vs_squeeze  (only if the squeeze is the LAST action and hero
                                  is the opener; villain := "<opener>-<squeezer>-
                                  <caller(s)>")

    For heads-up spots villain is the most recent raiser. For squeeze villain is
    the seating-order pair "<opener>-<caller>" (opener first) — exactly the
    sub-key the pack uses under spots.squeeze.

    vs_squeeze is the mirror image of squeeze: hero OPENED, got cold-called by
    >=1 seat, then someone re-raised (squeezed), and action came back to hero.
    Two raisers + caller(s) is shared with a "squeeze over a 3-bet" node; the two
    are told apart by which action is last before hero — a Raise (the squeeze just
    landed, hero responds -> vs_squeeze) vs a Call (a cold-call of a 3-bet, hero
    would be squeezing over it -> still refused). v1 only supports hero == opener;
    a cold-caller facing the squeeze (hero != opener) is refused (P-026).

    Returns (None, None, None) when the strip is missing (the caller may then
    pass --spot/--pos/--villain). Raises UnsupportedNode for a multiway shape
    our schema can't represent yet (a limped pot, or a squeeze over a 3-bet):
    we refuse rather than mislabel it (problems.md P-026).
    """
    headers = list(_HIST_HEADER_RE.finditer(html))
    if not headers:
        return None, None, None

    hero = None
    sequence = []  # (pos, active_action_text or None) for non-hero seats, in order
    for i, h in enumerate(headers):
        pos = POSITION_ALIASES.get(h.group(2), h.group(2))
        end = headers[i + 1].start() if i + 1 < len(headers) else len(html)
        if h.group(3):  # "_active" -> this is the hero seat
            hero = pos
            continue
        am = _ACTIVE_ACTION_RE.search(html[h.end():end])
        sequence.append((pos, am.group(1).strip() if am else None))

    def is_raise(act):
        return bool(act) and (act.startswith("Raise") or act.startswith("Allin"))

    raisers = [pos for pos, act in sequence if is_raise(act)]
    callers = [pos for pos, act in sequence if act == "Call"]
    nr, nc = len(raisers), len(callers)

    # Was the most recent non-fold action a raise? (folds and the empty future
    # seats carry no raise/call, so they're skipped.) This tells a squeeze that
    # has just landed apart from a cold-call of an earlier 3-bet.
    acted = [act for _, act in sequence if is_raise(act) or act == "Call"]
    last_is_raise = bool(acted) and is_raise(acted[-1])

    # Heads-up ladder: nobody cold-called in front of hero.
    if nc == 0:
        if nr == 0:
            return "RFI", hero, None
        if nr == 1:
            return "vs_RFI", hero, raisers[0]
        if nr == 2:
            return "vs_3bet", hero, raisers[-1]
        if nr == 3:
            return "vs_4bet", hero, raisers[-1]
        raise UnsupportedNode(
            f"{nr} raisers before hero — beyond vs_4bet, no schema for it"
        )

    # A cold caller sits in front of hero -> multiway.
    if nr == 1:
        # squeeze: lone opener (raisers[0]) + caller(s) + hero. Opener leads the
        # key; callers follow in seating order ("BTN-SB", later "BTN-SB-CO").
        pair = "-".join([raisers[0]] + callers)
        return "squeeze", hero, pair

    if nr == 2 and last_is_raise:
        # vs_squeeze: open -> cold-call(s) -> squeeze, action back to hero. The
        # squeeze is the last raiser; the opener is the first. v1 only handles
        # hero == opener (the opener always acts first after a squeeze); a
        # cold-caller facing the squeeze is a different range and is refused.
        opener, squeezer = raisers[0], raisers[-1]
        if hero != opener:
            raise UnsupportedNode(
                f"vs_squeeze with hero={hero} a cold-caller (opener is {opener}) "
                f"is not supported yet — only the opener facing a squeeze. (P-026)"
            )
        # key := "<opener>-<squeezer>-<caller(s)>" (opener first, squeezer next,
        # cold-callers in seating order) — the bare sub-key under spots.vs_squeeze.
        key = "-".join([opener, squeezer] + callers)
        return "vs_squeeze", hero, key

    shape = "limped pot (vs_limp)" if nr == 0 else f"squeeze over a {nr - 1}-bet"
    raise UnsupportedNode(
        f"multiway node not supported yet: {nr} raiser(s) + {nc} caller(s) "
        f"({shape}). Refusing to avoid silently mislabelling it (P-026)."
    )


# --------------------------------------------------------------------------- #
# Build pack entries
# --------------------------------------------------------------------------- #

def build_entries(html, spot):
    """
    Return (strategy, ev_map) for the dump.
      strategy: {hand: {action: freq}}  fold implicit, sliver actions dropped
      ev_map:   {hand: float}           only hands whose displayed EV != 0
    """
    raise_name = RAISE_ACTION[spot]
    strategy, ev_map = {}, {}
    for hand, roles, ev in parse_matrix(html):
        actions = {}
        for role, freq in roles.items():
            name = raise_name if role == "raise" else "call"
            freq = round(freq, 2)
            if freq >= FREQ_DROP:
                actions[name] = actions.get(name, 0.0) + freq
        if actions:
            strategy[hand] = actions
        if ev != 0.0:
            ev_map[hand] = ev
    return strategy, ev_map


def combos_percent(strategy):
    """Rough range width: summed combos / 1326, like range_engine.calculate_*."""
    total = 0.0
    for hand, actions in strategy.items():
        c = 6 if len(hand) == 2 else (4 if hand.endswith("s") else 12)
        total += c * min(1.0, sum(actions.values()))
    return round(total / 1326 * 100, 2)


# --------------------------------------------------------------------------- #
# Merge into the pack
# --------------------------------------------------------------------------- #

def pack_key(spot, villain):
    """The sub-key a spot/villain lands under in spots[spot][hero]. squeeze /
    vs_squeeze use the bare seating lineup; heads-up spots prefix with "vs_"."""
    return villain if spot in ("squeeze", "vs_squeeze") else f"vs_{villain}"


def merge_into_data(data, spot, hero, villain, strategy, ev_map):
    """Merge one parsed spot into an already-loaded pack dict (no file IO). Shared
    by apply_to_pack (single spot) and the batch importer (many spots, one save)."""
    spots = data.setdefault("spots", {}).setdefault(spot, {})
    evs = data.setdefault("ev", {}).setdefault(spot, {})

    if spot == "RFI":
        spots[hero] = strategy
        evs[hero] = dict(sorted(ev_map.items(), key=lambda kv: -kv[1]))
    else:
        key = pack_key(spot, villain)
        spots.setdefault(hero, {})[key] = strategy
        evs.setdefault(hero, {})[key] = dict(
            sorted(ev_map.items(), key=lambda kv: -kv[1])
        )


def apply_to_pack(path, spot, hero, villain, strategy, ev_map):
    import json
    from datetime import datetime

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    backup = f"{path}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(path, backup)

    merge_into_data(data, spot, hero, villain, strategy, ev_map)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return backup


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(description="Parse a GTO Wizard dump into a range pack.")
    p.add_argument("html", help="path to the saved page HTML")
    p.add_argument("--spot",
                   choices=["RFI", "vs_RFI", "vs_3bet", "vs_4bet", "squeeze", "vs_squeeze"],
                   help="override detected spot")
    p.add_argument("--pos", help="override detected hero position")
    p.add_argument("--villain", help="override detected villain position")
    p.add_argument("--file", default=DEFAULT_FILE, help="target pack JSON")
    p.add_argument("--apply", action="store_true", help="write into the pack")
    args = p.parse_args(argv)

    with open(args.html, encoding="utf-8") as f:
        html = f.read()

    try:
        d_spot, d_hero, d_villain = detect_spot(html)
    except UnsupportedNode as e:
        # A confidently-unsupported multiway node. Refuse even if the user tried
        # to force --spot, since writing it into a heads-up key would corrupt
        # the pack (P-026). Override stays available only for a missing strip.
        sys.exit(f"refusing to parse: {e}")
    spot = args.spot or d_spot
    hero = POSITION_ALIASES.get(args.pos, args.pos) if args.pos else d_hero
    villain = (POSITION_ALIASES.get(args.villain, args.villain)
               if args.villain else d_villain)

    print(f"detected: spot={d_spot} hero={d_hero} villain={d_villain}")
    if (args.spot or args.pos or args.villain):
        print(f"using:    spot={spot} hero={hero} villain={villain}")

    if not spot or not hero or (spot != "RFI" and not villain):
        sys.exit("could not resolve spot/hero/villain — pass --spot/--pos/--villain")

    strategy, ev_map = build_entries(html, spot)
    if spot == "RFI":
        label = hero
    elif spot == "squeeze":
        label = f"{hero} (squeeze vs {villain})"   # villain is the opener-caller pair
    elif spot == "vs_squeeze":
        label = f"{hero} (vs squeeze {villain})"    # villain is opener-squeezer-caller(s)
    else:
        label = f"{hero} vs_{villain}"
    print(f"\n{spot}  {label}")
    print(f"  hands in range : {len(strategy)}  (~{combos_percent(strategy)}% combos)")
    print(f"  ev entries     : {len(ev_map)}")
    print("  sample:")
    for hand, actions in list(strategy.items())[:8]:
        ev = ev_map.get(hand)
        ev_s = f"  EV {ev}" if ev is not None else ""
        print(f"    {hand:>4}  {actions}{ev_s}")

    if args.apply:
        backup = apply_to_pack(args.file, spot, hero, villain, strategy, ev_map)
        print(f"\napplied -> {args.file}\nbackup  -> {backup}")
    else:
        print("\n(dry-run — re-run with --apply to write into the pack)")


if __name__ == "__main__":
    main()
