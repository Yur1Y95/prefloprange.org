"""
Unit tests for stats_store.py — the Drill Stats/History read layer.

Stdlib only (no psycopg, no fastapi), so it runs in the Cowork sandbox like
test_srs.py / test_cards_store.py. Two things are covered:

  1. The pure conversions that carry all the shape logic (_nest_stats,
     _history_entry, _fmt_ts) — the bug-prone DB-row -> frontend-shape mapping
     (field remap, timeout sentinel, RFI villain, card1/card2 absence, ts).
  2. The JSON branch end-to-end, which is the exact contract the /api/stats and
     /api/history endpoints depend on when DATABASE_URL is unset (the mandated
     soft degradation / current prod).

The DB branch is not exercised here (no Postgres/driver in the sandbox); its SQL
is verified live by the user. But both branches funnel through the same pure
conversions, and those ARE tested here.

Run:  python3 test_stats_store.py
"""

import os
import json
import tempfile
from datetime import datetime, timezone

# Guarantee the JSON branch: a stray local .env with DATABASE_URL must not make
# these tests reach a real database. db.get_pool() is None without it.
os.environ.pop("DATABASE_URL", None)

import db
import stats_store


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------

def test_db_not_configured_in_sandbox():
    assert db.get_pool() is None
    assert db.database_configured() is False
    print("  PASS  no DATABASE_URL -> JSON branch active")


# ---------------------------------------------------------------------------
# _nest_stats — flat rows -> nested {spot: {key: counts}}
# ---------------------------------------------------------------------------

def test_nest_stats_shape_and_defaults():
    rows = [
        {"spot": "RFI",    "key": "UTG",       "correct": 3, "total": 5, "timeouts": 1},
        {"spot": "vs_RFI", "key": "BTN_vs_MP", "correct": 2, "total": 2, "timeouts": 0},
    ]
    out = stats_store._nest_stats(rows)
    # Every known spot is seeded even with no rows (frontend iterates spots).
    for spot in ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso"):
        assert spot in out, f"missing seeded spot {spot}"
    assert out["RFI"]["UTG"] == {"correct": 3, "total": 5, "timeouts": 1}
    assert out["vs_RFI"]["BTN_vs_MP"] == {"correct": 2, "total": 2, "timeouts": 0}
    assert out["vs_3bet"] == {}            # no data -> empty, not absent
    print("  PASS  _nest_stats nests rows + seeds all known spots")


def test_nest_stats_coerces_ints_and_unknown_spot():
    # Counts may arrive as other numeric types; an unknown spot is still kept.
    rows = [{"spot": "squeeze", "key": "BB_vs_BTN-SB", "correct": 1.0, "total": 4, "timeouts": 0}]
    out = stats_store._nest_stats(rows)
    cell = out["squeeze"]["BB_vs_BTN-SB"]
    assert cell == {"correct": 1, "total": 4, "timeouts": 0}
    assert all(isinstance(v, int) for v in cell.values())
    print("  PASS  _nest_stats coerces ints + keeps unknown spot")


# ---------------------------------------------------------------------------
# _fmt_ts — journal ts -> display string
# ---------------------------------------------------------------------------

def test_fmt_ts_datetime_none_and_str():
    dt = datetime(2026, 6, 22, 14, 33, 21, tzinfo=timezone.utc)
    assert stats_store._fmt_ts(dt) == "2026-06-22 14:33"
    assert stats_store._fmt_ts(None) == ""
    # str fallback (sqlite/tests): drop the 'T', trim to minutes.
    assert stats_store._fmt_ts("2026-06-22T14:33:21+00:00") == "2026-06-22 14:33"
    print("  PASS  _fmt_ts handles datetime / None / ISO-string")


# ---------------------------------------------------------------------------
# _history_entry — journal row -> the shape drill.js renders
# ---------------------------------------------------------------------------

def _row(**over):
    base = {
        "ts": datetime(2026, 6, 22, 14, 33, tzinfo=timezone.utc),
        "spot": "RFI", "position": "UTG", "villain": None, "hand": "AKs",
        "action": "open", "correct_action": "open", "correct": True,
        "ev": 2.31, "is_timeout": False,
    }
    base.update(over)
    return base


def test_history_entry_rfi_field_remap():
    e = stats_store._history_entry(_row())
    assert e["hero_position"] == "UTG"           # position -> hero_position
    assert e["villain_position"] is None         # RFI -> None
    assert e["player_action"] == "open"          # action -> player_action
    assert e["hand"] == "AKs"
    assert e["card1"] == "" and e["card2"] == "" # not journaled; drill.js falls back to hand
    assert e["ev"] == 2.31 and e["correct"] is True
    assert e["ts"] == "2026-06-22 14:33"
    print("  PASS  _history_entry RFI: field remap + empty card1/card2 + ts")


def test_history_entry_vs_spot_and_ev_null():
    e = stats_store._history_entry(_row(
        spot="vs_3bet", position="BTN", villain="MP", hand="QJs",
        action="fold", correct_action="call", correct=False, ev=None,
    ))
    assert e["villain_position"] == "MP"
    assert e["player_action"] == "fold" and e["correct_action"] == "call"
    assert e["ev"] is None and e["correct"] is False
    print("  PASS  _history_entry vs-spot: villain + null EV passthrough")


def test_history_entry_timeout_restores_sentinel():
    # On a timeout the journal stored action=NULL; the badge expects 'timeout'.
    e = stats_store._history_entry(_row(action=None, correct=False, ev=None, is_timeout=True))
    assert e["is_timeout"] is True
    assert e["player_action"] == "timeout"
    print("  PASS  _history_entry timeout: NULL action -> 'timeout' sentinel")


# ---------------------------------------------------------------------------
# JSON branch end-to-end — the endpoint contract under soft degradation
# ---------------------------------------------------------------------------

def _tmp(name, payload):
    d = tempfile.mkdtemp(prefix="stats_store_test_")
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return p


def test_read_stats_json_overlays_defaults():
    p = _tmp("stats.json", {
        "RFI": {"UTG": {"correct": 3, "total": 5, "timeouts": 1}},
        "vs_RFI": {"BTN_vs_MP": {"correct": 2, "total": 2, "timeouts": 0}},
    })
    out = stats_store.read_stats(p)
    assert out["RFI"]["UTG"]["total"] == 5
    assert out["vs_RFI"]["BTN_vs_MP"]["correct"] == 2
    for spot in ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso"):
        assert spot in out
    print("  PASS  read_stats JSON branch overlays file onto seeded defaults")


def test_read_stats_json_missing_file_is_empty_defaults():
    out = stats_store.read_stats(os.path.join(tempfile.mkdtemp(), "nope.json"))
    assert out == {spot: {} for spot in ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso")}
    print("  PASS  read_stats JSON branch: missing file -> empty defaults")


def test_read_history_json_respects_limit():
    entries = [{"hand": f"H{i}", "ts": f"00:00:0{i}"} for i in range(5)]
    p = _tmp("history.json", entries)
    assert len(stats_store.read_history(p, 2)) == 2
    assert stats_store.read_history(p, 2)[0]["hand"] == "H0"   # order preserved
    assert len(stats_store.read_history(p, 100)) == 5          # fewer than limit -> all
    print("  PASS  read_history JSON branch respects limit + preserves order")


def test_read_history_json_missing_file_is_empty():
    assert stats_store.read_history(os.path.join(tempfile.mkdtemp(), "nope.json"), 50) == []
    print("  PASS  read_history JSON branch: missing file -> []")


def test_read_history_limit_is_clamped():
    entries = [{"hand": f"H{i}"} for i in range(10)]
    p = _tmp("history.json", entries)
    # Below 1 clamps to 1; above the ceiling clamps to _HISTORY_MAX (no crash).
    assert len(stats_store.read_history(p, 0)) == 1
    assert len(stats_store.read_history(p, 10_000)) == 10      # file has only 10
    print("  PASS  read_history clamps the limit to [1, _HISTORY_MAX]")


if __name__ == "__main__":
    import sys
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} FAILED")
        sys.exit(1)
    print(f"All {len(tests)} stats_store tests passed")
