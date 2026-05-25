"""
Hand history parser for CoinPoker (and similar PokerStars-format) text histories.

Input:
  - A single .txt file
  - A directory (walked recursively for .txt, .zip, .7z files)
  - A .zip archive (.txt files inside parsed)
  - A .7z archive (.txt files inside parsed; requires py7zr — install with
    `pip3 install py7zr --break-system-packages` on macOS)

Output:
  - JSONL files in the output directory, one file per bucket.
    Bucket key: f"{game}_{stakes}_{max_players}max_{'ante' if ante else 'no_ante'}.jsonl"
    e.g. "NLH_NL25_6max_no_ante.jsonl"

Usage:
  python3 hh_parser.py <input_path> <output_dir>
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# Optional dependency for .7z archives. If not installed, .7z files
# are skipped with a warning rather than causing a hard failure.
try:
    import py7zr  # type: ignore
    HAS_7Z = True
except ImportError:
    HAS_7Z = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Action:
    player: str
    verb: str               # 'fold' | 'check' | 'call' | 'bet' | 'raise'
    amount: float = 0.0     # for call/bet: amount put in; for raise: increment
    total_bet: float = 0.0  # for raise: the "to X" target (cumulative this street)
    all_in: bool = False


@dataclass
class Hand:
    hand_id: str
    timestamp: str
    site: str                       # "CoinPoker"
    game: str                       # "NLH" (No Limit Hold'em)
    table: str
    max_players: int                # 2, 4, 5, 6, 9, ...
    button_seat: int
    sb: float
    bb: float
    ante: float                     # 0.0 if no ante
    stakes: str                     # "NL25", "NL50", ...
    straddle: Optional[dict] = None # {"player": str, "amount": float}

    # Players: name -> {"seat": int, "stack": float, "position": str}
    players: dict = field(default_factory=dict)

    # Actions per street
    preflop: list = field(default_factory=list)
    flop: list = field(default_factory=list)
    turn: list = field(default_factory=list)
    river: list = field(default_factory=list)

    # Board
    flop_cards: list = field(default_factory=list)   # ["Ts","8h","3d"]
    turn_card: Optional[str] = None
    river_card: Optional[str] = None

    # Results
    shown: dict = field(default_factory=dict)        # name -> ["Kd","Jd"]
    mucked: list = field(default_factory=list)       # names that mucked at showdown
    collected: dict = field(default_factory=dict)    # name -> amount


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Currency symbol class: ₮ (USDT/CoinPoker), € (EUR), $ (USD), £ (GBP).
# Symbol is optional — some lines have it, some don't depending on the room.
CUR = r"[₮€$£]?"

# Header: "CoinPoker Hand #3925170738:  Hold'em No Limit (₮0.1/₮0.25 CPCC) - 2026/05/02 0:00:19 UTC"
#     or: "CoinPoker Hand #3855940937:  Hold'em No Limit (₮0.1/₮0.25 - Ante ₮0.04 CPCC) - 2026/05/01 0:00:41 UTC"
#     or: "PokerStars Hand #394746585: Hold'em No Limit (€0.05/€0.10 EUR) - 2026/03/02 0:00:25 UTC"
RE_HEADER = re.compile(
    r"^(CoinPoker|PokerStars) Hand #(\d+):\s+"
    r"(Hold'em No Limit|Omaha [^()]+?)\s+"
    rf"\({CUR}([\d.]+)/{CUR}([\d.]+)"
    rf"(?:\s+-\s+Ante\s+{CUR}([\d.]+))?"
    r"[^)]*\)\s+-\s+"
    r"(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}:\d{2})"
)

# Table: "Table 'CPR_31st NL 0.10-0.25 EV-INRIT-BPR-RC-TR (B) 392517' 6-max Seat #3 is the button"
RE_TABLE = re.compile(r"^Table '(.+?)' (\d+)-max Seat #(\d+) is the button")

# Seat: "Seat 1: CoolerJoe1 (₮26.59 in chips)"
RE_SEAT = re.compile(rf"^Seat (\d+): (.+?) \({CUR}([\d.]+) in chips\)")

# Blinds: "STP321: posts small blind ₮0.1"
RE_BLIND = re.compile(rf"^(.+?): posts (small blind|big blind) {CUR}([\d.]+)")

# Straddle: "TipsyTip: posts straddle ₮0.5"
RE_STRADDLE = re.compile(rf"^(.+?): posts straddle {CUR}([\d.]+)")

# Ante: "Goldrush49ers: posts the ante ₮0.04"
RE_ANTE = re.compile(rf"^(.+?): posts the ante {CUR}([\d.]+)")

# Actions
RE_FOLD = re.compile(r"^(.+?): folds")
RE_CHECK = re.compile(r"^(.+?): checks")
RE_CALL = re.compile(rf"^(.+?): calls {CUR}([\d.]+)( and is all-in)?")
RE_BET = re.compile(rf"^(.+?): bets {CUR}([\d.]+)( and is all-in)?")
RE_RAISE = re.compile(rf"^(.+?): raises {CUR}([\d.]+) to {CUR}([\d.]+)( and is all-in)?")

# Board street markers
RE_FLOP = re.compile(r"^\*\*\* FLOP \*\*\* \[([^\]]+)\]")
RE_TURN = re.compile(r"^\*\*\* TURN \*\*\* \[[^\]]+\] \[([^\]]+)\]")
RE_RIVER = re.compile(r"^\*\*\* RIVER \*\*\* \[[^\]]+\] \[([^\]]+)\]")

# Showdowns / collections
RE_SHOWS = re.compile(r"^(.+?): shows \[([^\]]+)\]")
RE_MUCKS = re.compile(r"^(.+?): mucks hand")
RE_COLLECTED = re.compile(rf"^(.+?) collected {CUR}([\d.]+) from pot")


# ---------------------------------------------------------------------------
# Position assignment
# ---------------------------------------------------------------------------

# Position order going clockwise from the button.
# For N-max games, we take the first N labels.
_POSITION_ORDER_BY_SIZE = {
    2: ["BTN", "BB"],                            # HU: button is SB, then BB
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "HJ", "CO"],
}


def assign_positions(seats_to_names: dict, button_seat: int) -> dict:
    """
    Given a dict {seat_num: player_name} and the button seat,
    return {player_name: position_label}.

    Seats might be non-contiguous (gaps allowed). We walk seats in sorted
    order starting from the seat *after* the button, treating that as SB
    (or BB if 2-max where button == SB).
    """
    seats = sorted(seats_to_names.keys())
    if not seats:
        return {}

    n = len(seats)
    order = _POSITION_ORDER_BY_SIZE.get(n)
    if order is None:
        # Fallback: just use generic labels
        order = ["BTN", "SB", "BB"] + [f"EP{i}" for i in range(n - 3)]

    # Find button index in the seats list
    try:
        btn_idx = seats.index(button_seat)
    except ValueError:
        # Button player no longer at table (rare); pick nearest lower seat
        btn_idx = max(i for i, s in enumerate(seats) if s <= button_seat) \
                  if any(s <= button_seat for s in seats) else 0

    # Walk clockwise from button, assigning positions in order
    result = {}
    for i, label in enumerate(order):
        seat = seats[(btn_idx + i) % n]
        name = seats_to_names[seat]
        result[name] = label
    return result


# ---------------------------------------------------------------------------
# Hand splitting and parsing
# ---------------------------------------------------------------------------

# Hands begin with a header line like "<Site> Hand #<id>:" — used for splitting
# a multi-hand file into individual chunks. Kept separate from RE_HEADER (which
# parses the full header) since we only need cheap prefix detection here.
_HAND_START_PREFIXES = ("CoinPoker Hand #", "PokerStars Hand #")


def _is_hand_start(line: str) -> bool:
    return any(line.startswith(p) for p in _HAND_START_PREFIXES)


def split_hands(text: str) -> list[str]:
    """Split a full file's content into individual hand chunks."""
    chunks = []
    current = []
    for line in text.splitlines():
        if _is_hand_start(line):
            if current:
                chunks.append("\n".join(current))
                current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current))
    # Filter out anything that doesn't actually start with a hand header
    return [c for c in chunks if _is_hand_start(c.lstrip())]


def _stakes_label(bb: float) -> str:
    """0.25 → 'NL25', 1.0 → 'NL100', etc."""
    cents = round(bb * 100)
    return f"NL{cents}"


def parse_hand(text: str) -> Optional[Hand]:
    """Parse one hand-history chunk into a Hand object. Returns None on failure."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    m = RE_HEADER.match(lines[0])
    if not m:
        return None
    site, hand_id, game_raw, sb_s, bb_s, ante_s, ts = m.groups()
    sb = float(sb_s)
    bb = float(bb_s)
    ante = float(ante_s) if ante_s else 0.0
    game = "NLH" if game_raw.startswith("Hold'em No Limit") else "PLO"

    m = RE_TABLE.match(lines[1])
    if not m:
        return None
    table, max_players_s, button_seat_s = m.groups()
    max_players = int(max_players_s)
    button_seat = int(button_seat_s)

    hand = Hand(
        hand_id=hand_id,
        timestamp=ts,
        site=site,
        game=game,
        table=table,
        max_players=max_players,
        button_seat=button_seat,
        sb=sb,
        bb=bb,
        ante=ante,
        stakes=_stakes_label(bb),
    )

    # Walk through remaining lines
    seats_to_names: dict[int, str] = {}
    street = "preheader"   # preheader → preflop → flop → turn → river → showdown → summary
    skip_uncalled = False  # we just skip "Uncalled bet" lines, they're informational

    for ln in lines[2:]:
        # --- Street markers ---
        if ln.startswith("*** HOLE CARDS ***"):
            street = "preflop"
            continue
        m = RE_FLOP.match(ln)
        if m:
            street = "flop"
            hand.flop_cards = m.group(1).split()
            continue
        m = RE_TURN.match(ln)
        if m:
            street = "turn"
            hand.turn_card = m.group(1).strip()
            continue
        m = RE_RIVER.match(ln)
        if m:
            street = "river"
            hand.river_card = m.group(1).strip()
            continue
        if ln.startswith("*** SHOW DOWN ***"):
            street = "showdown"
            continue
        if ln.startswith("*** SUMMARY ***"):
            street = "summary"
            continue

        # --- Pre-action lines (seats, blinds, antes, straddles) ---
        if street == "preheader":
            m = RE_SEAT.match(ln)
            if m:
                seat = int(m.group(1))
                name = m.group(2).strip()
                stack = float(m.group(3))
                seats_to_names[seat] = name
                hand.players[name] = {
                    "seat": seat,
                    "stack": stack,
                    "position": None,  # filled below
                }
                continue
            m = RE_BLIND.match(ln)
            if m:
                # Posting blinds happens before HOLE CARDS; nothing to record here
                # beyond the fact that it happened (we infer SB/BB from positions)
                continue
            m = RE_STRADDLE.match(ln)
            if m:
                hand.straddle = {
                    "player": m.group(1).strip(),
                    "amount": float(m.group(2)),
                }
                continue
            m = RE_ANTE.match(ln)
            if m:
                continue  # antes already counted from header
            # otherwise: unknown pre-header line, skip

        # --- Action lines ---
        if street in ("preflop", "flop", "turn", "river"):
            action = _parse_action_line(ln)
            if action is not None:
                getattr(hand, street).append(asdict(action))
                continue
            # "Uncalled bet (₮X) returned to NAME" → informational, skip
            if ln.startswith("Uncalled bet"):
                continue
            # "NAME collected ₮X from pot" can appear at end of any street if everyone folded
            m = RE_COLLECTED.match(ln)
            if m:
                hand.collected[m.group(1).strip()] = float(m.group(2))
                continue

        # --- Showdown lines ---
        if street == "showdown":
            m = RE_SHOWS.match(ln)
            if m:
                hand.shown[m.group(1).strip()] = m.group(2).split()
                continue
            m = RE_MUCKS.match(ln)
            if m:
                hand.mucked.append(m.group(1).strip())
                continue
            m = RE_COLLECTED.match(ln)
            if m:
                hand.collected[m.group(1).strip()] = float(m.group(2))
                continue

        # --- Summary lines we ignore (Total pot, Board, per-seat recap) ---
        # We don't trust Total pot / Rake fields (CoinPoker bundles promo drops
        # into "Rake"), and per-seat recap is redundant with what we already
        # parsed. The summary is skipped entirely.

    # Fill in positions
    positions = assign_positions(seats_to_names, button_seat)
    for name, pos in positions.items():
        if name in hand.players:
            hand.players[name]["position"] = pos

    return hand


def _parse_action_line(ln: str) -> Optional[Action]:
    """Try to match the line as a poker action. Returns Action or None."""
    m = RE_FOLD.match(ln)
    if m:
        return Action(player=m.group(1).strip(), verb="fold")

    m = RE_CHECK.match(ln)
    if m:
        return Action(player=m.group(1).strip(), verb="check")

    m = RE_CALL.match(ln)
    if m:
        return Action(
            player=m.group(1).strip(),
            verb="call",
            amount=float(m.group(2)),
            all_in=bool(m.group(3)),
        )

    m = RE_BET.match(ln)
    if m:
        return Action(
            player=m.group(1).strip(),
            verb="bet",
            amount=float(m.group(2)),
            all_in=bool(m.group(3)),
        )

    m = RE_RAISE.match(ln)
    if m:
        return Action(
            player=m.group(1).strip(),
            verb="raise",
            amount=float(m.group(2)),
            total_bet=float(m.group(3)),
            all_in=bool(m.group(4)),
        )

    return None


# ---------------------------------------------------------------------------
# Input source handling (file / directory / zip archive)
# ---------------------------------------------------------------------------

def iter_text_sources(path: str) -> Iterable[tuple[str, str]]:
    """
    Yield (source_label, file_content) tuples for every .txt file found.
    Sources can be a single .txt, a directory tree, or a .zip archive.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    if p.is_file():
        if p.suffix.lower() == ".zip":
            yield from _iter_zip(p)
        elif p.suffix.lower() == ".7z":
            yield from _iter_7z(p)
        elif p.suffix.lower() == ".txt":
            yield (str(p), p.read_text(encoding="utf-8", errors="ignore"))
        else:
            # Try reading as text anyway
            yield (str(p), p.read_text(encoding="utf-8", errors="ignore"))
        return

    # Directory: walk recursively
    for entry in sorted(p.rglob("*")):
        if entry.is_file():
            if entry.suffix.lower() == ".txt":
                yield (str(entry), entry.read_text(encoding="utf-8", errors="ignore"))
            elif entry.suffix.lower() == ".zip":
                yield from _iter_zip(entry)
            elif entry.suffix.lower() == ".7z":
                yield from _iter_7z(entry)


def _iter_zip(zip_path: Path) -> Iterable[tuple[str, str]]:
    """Yield (label, content) for each .txt inside a .zip archive.

    Also handles .7z files nested inside the .zip (CoinPoker archives pack
    daily hand history dumps as .7z files inside an outer .zip).
    """
    import tempfile
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name_lower = info.filename.lower()
            if name_lower.endswith(".txt"):
                with zf.open(info) as f:
                    data = f.read()
                label = f"{zip_path}!{info.filename}"
                yield (label, data.decode("utf-8", errors="ignore"))
            elif name_lower.endswith(".7z"):
                # Extract the nested .7z to a temp file and recurse
                if not HAS_7Z:
                    print(
                        f"[skip] {zip_path}!{info.filename}: nested .7z requires py7zr "
                        f"(install with: pip3 install py7zr --break-system-packages)",
                        file=sys.stderr,
                    )
                    continue
                with zf.open(info) as f:
                    raw7z = f.read()
                with tempfile.NamedTemporaryFile(suffix=".7z", delete=False) as tmp:
                    tmp.write(raw7z)
                    tmp_path = Path(tmp.name)
                try:
                    yield from _iter_7z(tmp_path,
                                        label_prefix=f"{zip_path}!{info.filename}")
                finally:
                    tmp_path.unlink(missing_ok=True)


def _iter_7z(archive_path: Path,
             label_prefix: str | None = None) -> Iterable[tuple[str, str]]:
    """Yield (label, content) for each .txt inside a .7z archive.

    label_prefix: if provided, used instead of archive_path in the label
    (useful when the .7z was extracted from inside a .zip).
    """
    if not HAS_7Z:
        print(
            f"[skip] {archive_path}: .7z support requires py7zr "
            f"(install with: pip3 install py7zr --break-system-packages)",
            file=sys.stderr,
        )
        return
    import tempfile
    prefix = label_prefix or str(archive_path)
    with tempfile.TemporaryDirectory() as tmp:
        with py7zr.SevenZipFile(archive_path, mode="r") as zf:
            txt_names = [n for n in zf.getnames() if n.lower().endswith(".txt")]
            if not txt_names:
                return
            zf.extract(path=tmp, targets=txt_names)
        for name in txt_names:
            extracted = Path(tmp) / name
            if not extracted.is_file():
                continue
            label = f"{prefix}!{name}"
            yield (label, extracted.read_text(encoding="utf-8", errors="ignore"))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def bucket_key(h: Hand) -> str:
    ante = "ante" if h.ante > 0 else "no_ante"
    return f"{h.site}_{h.game}_{h.stakes}_{h.max_players}max_{ante}"


def run(input_path: str, output_dir: str) -> dict:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clean stale .jsonl files from any previous run so that buckets which
    # don't appear in the current input don't linger with old data.
    # Other file types in the directory are left alone.
    stale = list(out_dir.glob("*.jsonl"))
    for f in stale:
        f.unlink()
    if stale:
        print(f"[clean] removed {len(stale)} stale .jsonl file(s) from {out_dir}")

    # Per-bucket open file handles
    bucket_files: dict[str, io.TextIOWrapper] = {}
    bucket_counts: dict[str, int] = defaultdict(int)
    files_processed = 0
    hands_parsed = 0
    hands_failed = 0

    try:
        for label, content in iter_text_sources(input_path):
            files_processed += 1
            for chunk in split_hands(content):
                hand = parse_hand(chunk)
                if hand is None:
                    hands_failed += 1
                    continue
                key = bucket_key(hand)
                if key not in bucket_files:
                    bucket_files[key] = open(
                        out_dir / f"{key}.jsonl", "w", encoding="utf-8"
                    )
                bucket_files[key].write(json.dumps(asdict(hand), ensure_ascii=False) + "\n")
                bucket_counts[key] += 1
                hands_parsed += 1
    finally:
        for f in bucket_files.values():
            f.close()

    return {
        "files_processed": files_processed,
        "hands_parsed": hands_parsed,
        "hands_failed": hands_failed,
        "buckets": dict(bucket_counts),
    }


def _print_summary(stats: dict) -> None:
    print(f"\nFiles processed: {stats['files_processed']}")
    print(f"Hands parsed:    {stats['hands_parsed']}")
    print(f"Hands failed:    {stats['hands_failed']}")
    print("\nBuckets:")
    for key in sorted(stats["buckets"]):
        print(f"  {key:35s} {stats['buckets'][key]:>8d} hands")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    stats = run(sys.argv[1], sys.argv[2])
    _print_summary(stats)