"""
Unit tests for dashboard_store.py — the per-user Progress dashboard read layer.

Stdlib only (no psycopg, no fastapi), so it runs in the Cowork sandbox like
test_stats_store.py / test_cards_store.py. Covered:

  1. The pure math that carries all the risk — _streaks (gaps-and-islands +
     today/yesterday seeding), _window_days (dense zero-filled window +
     anti-farm 'trained' flag), _nest_by_spot (per-spot grouping + key format +
     accuracy), _accuracy (zero-hands -> None).
  2. The soft-degradation contract: read_overview() returns {available: False}
     when no database is configured (the dashboard is inherently DB-only).

The DB branch (the SQL itself) is not exercised here — there is no Postgres in
the sandbox; it is verified live by the user. But every payload funnels through
the pure helpers above, and those ARE tested here.

Run:  python3 test_dashboard_store.py
"""

import os
from datetime import date, timedelta

# Best-effort: clear DATABASE_URL so the default path is the degradation branch.
# (The soft-degradation test below does not rely on this — it forces get_pool to
# None directly — so it stays deterministic even when a local .env is mounted,
# which is exactly the Cowork-sandbox case.)
os.environ.pop("DATABASE_URL", None)

import db
import dashboard_store as ds


# ---------------------------------------------------------------------------
# Soft degradation — the dashboard is inherently DB-only.
# ---------------------------------------------------------------------------

def test_read_overview_degrades_without_db():
    # Force "no database configured" regardless of the ambient env (a mounted
    # .env or a missing psycopg driver must not turn this into a flaky test).
    orig = db.get_pool
    db.get_pool = lambda: None
    try:
        out = ds.read_overview()
    finally:
        db.get_pool = orig
    assert out["available"] is False
    # No crash, no panels — the frontend shows a "needs the database" state.
    assert "totals" not in out
    print("  PASS  read_overview -> {available: False} when no DB pool")


# ---------------------------------------------------------------------------
# _accuracy
# ---------------------------------------------------------------------------

def test_accuracy_basic_and_zero():
    assert ds._accuracy(0, 0) is None          # no hands -> None (UI shows a dash)
    assert ds._accuracy(0, 4) == 0.0
    assert ds._accuracy(8, 10) == 80.0
    assert ds._accuracy(1, 3) == 33.3          # rounded to 0.1
    print("  PASS  _accuracy: None on zero hands, rounds to 0.1")


# ---------------------------------------------------------------------------
# _streaks — current + longest over qualified days
# ---------------------------------------------------------------------------

def _d(day):  # June 2026 helper
    return date(2026, 6, day)


def test_streaks_empty():
    assert ds._streaks([], _d(23)) == {"current": 0, "longest": 0}
    print("  PASS  _streaks: no qualified days -> 0/0")


def test_streaks_longest_run():
    # Two islands: {1,2,3} (len 3) and {5} and {7,8} (len 2). Longest = 3.
    days = [_d(1), _d(2), _d(3), _d(5), _d(7), _d(8)]
    out = ds._streaks(days, _d(23))
    assert out["longest"] == 3
    print("  PASS  _streaks: longest = longest consecutive island")


def test_streaks_current_from_today():
    # today qualifies; 21,22,23 consecutive, then a gap -> current = 3.
    days = [_d(18), _d(19), _d(21), _d(22), _d(23)]
    out = ds._streaks(days, _d(23))
    assert out["current"] == 3
    print("  PASS  _streaks: current counts back from today")


def test_streaks_current_seeds_from_yesterday():
    # today (23) NOT trained yet, but 20,21,22 are -> streak still alive = 3.
    days = [_d(20), _d(21), _d(22)]
    out = ds._streaks(days, _d(23))
    assert out["current"] == 3
    print("  PASS  _streaks: untrained today does not break yesterday's streak")


def test_streaks_current_zero_when_stale():
    # Neither today nor yesterday qualifies -> current 0 (older run ignored).
    days = [_d(10), _d(11), _d(12)]
    out = ds._streaks(days, _d(23))
    assert out["current"] == 0
    assert out["longest"] == 3
    print("  PASS  _streaks: current 0 when neither today nor yesterday qualifies")


def test_streaks_single_today():
    out = ds._streaks([_d(23)], _d(23))
    assert out == {"current": 1, "longest": 1}
    print("  PASS  _streaks: single qualified today -> 1/1")


# ---------------------------------------------------------------------------
# _window_days — dense, zero-filled, trained-flagged window
# ---------------------------------------------------------------------------

def test_window_days_dense_and_flags():
    per_day = {_d(20): (5, 3), _d(23): (25, 20)}
    out = ds._window_days(per_day, today=_d(23), days=4, threshold=20)
    assert len(out) == 4                                   # 20,21,22,23 inclusive
    assert out[0]["day"] == "2026-06-20" and out[-1]["day"] == "2026-06-23"
    assert out[0] == {"day": "2026-06-20", "hands": 5, "correct": 3, "trained": False}  # 5 < 20
    assert out[1]["hands"] == 0 and out[1]["trained"] is False                          # zero-filled
    assert out[3]["trained"] is True                                                    # 25 >= 20
    print("  PASS  _window_days: dense window, zero-fill, anti-farm trained flag")


def test_window_days_threshold_boundary():
    per_day = {_d(23): (20, 10)}
    out = ds._window_days(per_day, today=_d(23), days=1, threshold=20)
    assert out[0]["trained"] is True       # exactly at threshold counts
    print("  PASS  _window_days: hands == threshold counts as trained")


# ---------------------------------------------------------------------------
# _nest_by_spot — grouping + key format + accuracy + ordering
# ---------------------------------------------------------------------------

def test_nest_by_spot_grouping_keys_and_order():
    rows = [
        {"spot": "vs_3bet", "position": "UTG", "villain": "CO", "hands": 2, "correct": 0},
        {"spot": "RFI",     "position": "UTG", "villain": None, "hands": 10, "correct": 8},
        {"spot": "RFI",     "position": "BTN", "villain": "",   "hands": 5,  "correct": 5},
        {"spot": "vs_RFI",  "position": "BTN", "villain": "MP", "hands": 4,  "correct": 2},
        {"spot": "mystery", "position": "X",   "villain": None, "hands": 1,  "correct": 1},
    ]
    out = ds._nest_by_spot(rows)
    spots = [s["spot"] for s in out]
    # Known spots in trainer order; unknown ('mystery') sorts last but stays.
    assert spots == ["RFI", "vs_RFI", "vs_3bet", "mystery"]

    rfi = out[0]
    assert rfi["hands"] == 15 and rfi["correct"] == 13
    assert rfi["accuracy"] == 86.7                          # 13/15
    keys = [r["key"] for r in rfi["rows"]]
    assert keys == ["UTG", "BTN"]                           # RFI / villain '' -> position only

    vs = out[1]
    assert vs["rows"][0]["key"] == "BTN_vs_MP"              # vs-spot key format
    assert vs["rows"][0]["accuracy"] == 50.0
    print("  PASS  _nest_by_spot: grouping, key format, totals, accuracy, order")


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
    print(f"All {len(tests)} dashboard_store tests passed")
