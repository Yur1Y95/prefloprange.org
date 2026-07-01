#!/usr/bin/env python3
"""
migrate_to_pg.py — extract current file-based data into rows shaped for the
Postgres schema (db/schema.sql). Stdlib only (the Cowork sandbox has no PyPI).

What it reads
-------------
  srs_state/<pack>.srs.json   (list of srs.Card dicts)
      -> `cards` rows  : current SRS state, one per card
      -> `answers` rows: one per card.history entry (mode='learn'), reconstructed
                         from the card identity + the logged {date,rating,correct}
  history.json                (Drill per-hand log)
      -> `answers` rows: mode='drill'

Honest limitations (these are exactly what the new schema fixes going forward):
  * history.json has NO date — only "HH:MM:SS" — and is a rolling 200. We can
    only place those rows on the file's mtime date. Pre-migration Drill history
    therefore collapses onto a single day. (User accepted this cost 2026-06-19.)
  * history.json has NO pack field -> migrated Drill rows get pack='(unknown)'.
  * card.history does not store the chosen action -> migrated Learn rows have
    action=NULL; we keep `correct` and `rating` (what the dashboard needs) and
    set correct_action to the strategy's dominant action.

This is a *design/verification* artifact: it proves the current data maps cleanly
onto the schema and is reused by tools/verify_schema_sqlite.py. The real Supabase
load (real user_id, real connection) is a later chat.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRS_STATE_DIR = os.path.join(BASE_DIR, "srs_state")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")

# Current data is single-user. Real migration maps this to the Supabase auth id.
DEFAULT_USER = "00000000-0000-0000-0000-000000000001"


def _dominant_action(strategy: dict) -> str:
    """Action with the highest frequency, or '' for an empty strategy."""
    if not strategy:
        return ""
    return max(strategy.items(), key=lambda kv: kv[1])[0]


def _card_id(hand: str, position: str, spot: str, villain: str) -> str:
    """Mirror srs.Card.card_id."""
    if villain:
        return f"{hand}__{position}__{spot}__{villain}"
    return f"{hand}__{position}__{spot}"


def extract_cards(srs_state_dir: str = SRS_STATE_DIR, user_id: str = DEFAULT_USER):
    """Yield `cards` rows from every srs_state/<pack>.srs.json."""
    rows = []
    if not os.path.isdir(srs_state_dir):
        return rows
    for fn in sorted(os.listdir(srs_state_dir)):
        if not fn.endswith(".srs.json"):
            continue
        pack = fn[: -len(".srs.json")]
        with open(os.path.join(srs_state_dir, fn), "r", encoding="utf-8") as f:
            cards = json.load(f)
        for c in cards:
            rows.append({
                "user_id": user_id,
                "pack": pack,
                "hand": c.get("hand", ""),
                "position": c.get("position", ""),
                "spot": c.get("spot", ""),
                "villain": c.get("villain_position", "") or "",
                "correct_strategy": json.dumps(c.get("correct_strategy", {}),
                                               ensure_ascii=False),
                "ease_factor": c.get("ease_factor", 2.5),
                "interval_days": c.get("interval_days", 0),
                "next_review": c.get("next_review") or None,
                "last_seen": c.get("last_seen") or None,
                "consecutive_correct": c.get("consecutive_correct", 0),
                "total_seen": c.get("total_seen", 0),
                "total_correct": c.get("total_correct", 0),
                "stability": None,   # FSRS — not populated until A.4
                "difficulty": None,
            })
    return rows


def extract_learn_answers(srs_state_dir: str = SRS_STATE_DIR, user_id: str = DEFAULT_USER):
    """Yield `answers` rows (mode='learn') from each card's history[]."""
    rows = []
    if not os.path.isdir(srs_state_dir):
        return rows
    for fn in sorted(os.listdir(srs_state_dir)):
        if not fn.endswith(".srs.json"):
            continue
        pack = fn[: -len(".srs.json")]
        with open(os.path.join(srs_state_dir, fn), "r", encoding="utf-8") as f:
            cards = json.load(f)
        for c in cards:
            hand = c.get("hand", "")
            position = c.get("position", "")
            spot = c.get("spot", "")
            villain = c.get("villain_position", "") or ""
            cid = _card_id(hand, position, spot, villain)
            dom = _dominant_action(c.get("correct_strategy", {}))
            for h in c.get("history", []):
                d = h.get("date", "")
                # We only have a date; place the event at noon UTC of that day.
                ts = f"{d}T12:00:00+00:00" if d else None
                rating = h.get("rating")
                rows.append({
                    "user_id": user_id,
                    "ts": ts,
                    "mode": "learn",
                    "pack": pack,
                    "spot": spot,
                    "position": position,
                    "villain": villain or None,
                    "hand": hand,
                    "action": None,                     # not recorded in history[]
                    "correct": bool(h.get("correct", False)),
                    "is_timeout": False,
                    "revealed": (rating == 1),          # best-effort: AGAIN often = reveal
                    "rating": rating,
                    "ev": None,
                    "correct_action": dom,
                    "card_id": cid,
                })
    return rows


def extract_drill_answers(history_file: str = HISTORY_FILE, user_id: str = DEFAULT_USER):
    """Yield `answers` rows (mode='drill') from history.json.

    history.json has no date -> we stamp every row with the file's mtime date
    plus its recorded HH:MM:SS. This collapses pre-migration Drill history onto
    one day; it is the known, accepted cost of not having journaled dates before.
    """
    rows = []
    if not os.path.exists(history_file):
        return rows
    with open(history_file, "r", encoding="utf-8") as f:
        hist = json.load(f)
    mtime_day = date.fromtimestamp(os.path.getmtime(history_file)).isoformat()
    for e in hist:
        hhmmss = e.get("ts", "00:00:00") or "00:00:00"
        ts = f"{mtime_day}T{hhmmss}+00:00"
        villain = e.get("villain_position") or None
        rows.append({
            "user_id": user_id,
            "ts": ts,
            "mode": "drill",
            "pack": "(unknown)",                  # not stored in history.json
            "spot": e.get("spot", ""),
            "position": e.get("hero_position", ""),
            "villain": villain,
            "hand": e.get("hand", ""),
            "action": e.get("player_action"),
            "correct": bool(e.get("correct", False)),
            "is_timeout": bool(e.get("is_timeout", False)),
            "revealed": False,
            "rating": None,                       # drill has no SRS rating
            "ev": e.get("ev"),
            "correct_action": e.get("correct_action", ""),
            "card_id": None,
        })
    return rows


def extract_all(user_id: str = DEFAULT_USER):
    """All rows: (cards, answers). answers = learn + drill, sorted by ts."""
    cards = extract_cards(user_id=user_id)
    answers = extract_learn_answers(user_id=user_id) + extract_drill_answers(user_id=user_id)
    answers.sort(key=lambda r: r["ts"] or "")
    return cards, answers


def _write_csv(rows, path):
    if not rows:
        return 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main(argv):
    out_dir = argv[1] if len(argv) > 1 else None
    cards, answers = extract_all()
    learn = [a for a in answers if a["mode"] == "learn"]
    drill = [a for a in answers if a["mode"] == "drill"]
    print(f"cards   : {len(cards)} rows")
    print(f"answers : {len(answers)} rows  (learn {len(learn)} / drill {len(drill)})")
    days = sorted({(a['ts'] or '')[:10] for a in answers if a['ts']})
    print(f"answer days: {len(days)}  span {days[0] if days else '-'}..{days[-1] if days else '-'}")
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        n1 = _write_csv(cards, os.path.join(out_dir, "cards.csv"))
        n2 = _write_csv(answers, os.path.join(out_dir, "answers.csv"))
        print(f"wrote {n1} cards.csv + {n2} answers.csv -> {out_dir}")


if __name__ == "__main__":
    main(sys.argv)
