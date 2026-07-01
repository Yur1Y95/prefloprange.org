"""
fsrs_interval_sim.py — compare FSRS-6 review intervals against our SM-2
graduation ladder, to reason about which intervals suit poker preflop
memorization (Learn Mode).

WHY THIS EXISTS
---------------
Track A.3/A.4 and CLAUDE.md decision #11 ask: would FSRS schedule better than
our hand-tuned SM-2, and what interval behaviour fits poker specifically? This
script answers that empirically by running BOTH schedulers on the same review
patterns and printing the resulting day-intervals side by side.

It is an ANALYSIS / DEV tool, not part of the app runtime:
  - it imports the real `srs.py` (our production SM-2) so the comparison is
    against live code, not a re-implementation;
  - it imports `fsrs` (py-fsrs), which is intentionally NOT in requirements.txt.
    Install it only to run this script:  pip install fsrs
  - it does not touch srs_api, srs_state, or any range pack.

WHAT IT DEMONSTRATES (see docs/fsrs_analysis.md for the write-up)
-----------------------------------------------------------------
1. Good-only ladder: SM-2 (×ease, uncapped) vs FSRS at three target
   retentions. Our SM-2 ≈ FSRS at desired_retention ~0.95 for the first steps,
   but SM-2 never caps and never adapts the growth rate.
2. Difficulty differentiation (the key result): SM-2 gives a trivial pure card
   (AA RFI) and a nasty close-mix card (A5s 55/45) the IDENTICAL ladder, because
   under binary Again/Good grading the SM-2 ease_factor is frozen at 2.5. FSRS,
   given a seeded per-card difficulty, shows the hard card several times more
   often over the same horizon.
3. Lapse recovery: SM-2 hard-resets to 1 day on a miss; FSRS keeps post-lapse
   stability (doesn't forget the card was once strong) and raises difficulty so
   regrowth slows.

All FSRS runs use enable_fuzzing=False for deterministic, comparable numbers.

Run:  python3 tools/fsrs_interval_sim.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

# Make the repo root importable so we exercise the real production srs.py.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import srs  # noqa: E402  (our production SM-2 engine)

try:
    from fsrs import Scheduler, Card as FCard, Rating
except ImportError:  # pragma: no cover - guidance path
    sys.exit(
        "This analysis script needs py-fsrs (not an app dependency).\n"
        "Install it just to run the comparison:  pip install fsrs"
    )


# ---------------------------------------------------------------------------
# SM-2 side (drives the REAL srs.update_card)
# ---------------------------------------------------------------------------

def sm2_good_ladder(n: int) -> tuple[list[int], float]:
    """Answer Good n times in a row; return the interval after each review."""
    card = srs.Card(hand="AA", position="UTG", spot="RFI",
                    correct_strategy={"open": 1.0})
    today = date(2026, 1, 1)
    intervals: list[int] = []
    for _ in range(n):
        srs.update_card(card, srs.GOOD, today=today)
        intervals.append(card.interval_days)
        today = date.fromisoformat(card.next_review)
    return intervals, card.ease_factor


def sm2_pattern(ratings: list[int]) -> list[tuple[str, int, float]]:
    """Apply a sequence of ratings; return (label, interval, ease) per step."""
    card = srs.Card(hand="A5s", position="UTG", spot="RFI",
                    correct_strategy={"open": 0.55, "fold": 0.45})
    today = date(2026, 1, 1)
    name = {srs.AGAIN: "Again", srs.HARD: "Hard", srs.GOOD: "Good", srs.EASY: "Easy"}
    rows: list[tuple[str, int, float]] = []
    for r in ratings:
        srs.update_card(card, r, today=today)
        rows.append((name[r], card.interval_days, card.ease_factor))
        today = date.fromisoformat(card.next_review)
    return rows


# ---------------------------------------------------------------------------
# FSRS side (py-fsrs 6.x, FSRS-6 default parameters)
# ---------------------------------------------------------------------------

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _new_scheduler(retention: float, cap: int) -> Scheduler:
    # learning_steps=() => first Good goes straight to a stability-based
    # interval (no 1-min/10-min same-session cram), so it is comparable to
    # SM-2's "first Good -> 1 day". relearning_steps=() => a lapse likewise
    # reschedules in days, not minutes. Fuzzing off for reproducibility.
    return Scheduler(
        parameters=Scheduler().parameters,   # FSRS-6 defaults, explicit for clarity
        desired_retention=retention,
        learning_steps=(),
        relearning_steps=(),
        maximum_interval=cap,
        enable_fuzzing=False,
    )


def _interval_days(card: FCard, now: datetime) -> int:
    return round((card.due - now).total_seconds() / 86400)


def fsrs_good_ladder(retention: float, cap: int, n: int,
                     seed_difficulty: float | None = None) -> list[int]:
    """
    Answer Good n times. If seed_difficulty is given, override FSRS difficulty
    after the first review (this is how we'd inject per-card difficulty from the
    strategy type at deck-build time — pure vs mixed). Stability is left at the
    first-Good value so all cards start equal and diverge only by difficulty.
    """
    sched = _new_scheduler(retention, cap)
    now = _START
    card = FCard()
    card, _ = sched.review_card(card, Rating.Good, review_datetime=now)
    if seed_difficulty is not None:
        card.difficulty = seed_difficulty
    now = card.due
    intervals = [_interval_days(card, _START)]
    for _ in range(n - 1):
        card, _ = sched.review_card(card, Rating.Good, review_datetime=now)
        intervals.append(_interval_days(card, now))
        now = card.due
    return intervals


def fsrs_pattern(ratings: list[Rating], retention: float, cap: int
                 ) -> list[tuple[str, int, float, float]]:
    """Apply ratings; return (label, interval_days, stability, difficulty)."""
    sched = _new_scheduler(retention, cap)
    now = _START
    card = FCard()
    rows: list[tuple[str, int, float, float]] = []
    for r in ratings:
        card, _ = sched.review_card(card, r, review_datetime=now)
        rows.append((r.name, _interval_days(card, now), card.stability, card.difficulty))
        now = card.due
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt(seq: list[int]) -> str:
    return "  ".join(f"{v:>5d}" for v in seq)


def main() -> None:
    n = 9
    print("=" * 74)
    print("FSRS-6 vs our SM-2 — review intervals (days). FSRS fuzzing OFF.")
    print("=" * 74)

    sm2, ease = sm2_good_ladder(n)
    print("\n[1] GOOD-ONLY LADDER  (review #):        "
          + "  ".join(f"{i+1:>5d}" for i in range(n)))
    print("-" * 74)
    print(f"SM-2 (ease stays {ease:.2f}, uncapped):  {_fmt(sm2)}")
    for R in (0.90, 0.95, 0.97):
        f = fsrs_good_ladder(R, cap=36500, n=n)
        print(f"FSRS R={R:.2f} (uncapped):             {_fmt(f)}")
    print("\nNote: SM-2's ×2.5 ladder tracks FSRS at R~0.95 early, but SM-2 keeps")
    print("multiplying forever (780, 1950, ...). FSRS R=0.90 default shoots to")
    print("years (498, 1348, ...) — meaningless for a grinder's horizon.")

    print("\n" + "=" * 74)
    print("[2] DIFFICULTY DIFFERENTIATION — the key result")
    print("=" * 74)
    print("Same horizon, target R=0.95, interval capped at 120 days.")
    print("SM-2 has no difficulty concept; under binary Again/Good its ease is")
    print("frozen at 2.5, so a PURE card and a CLOSE-MIX card get the SAME ladder:")
    print(f"  SM-2  pure AA  & mix A5s (identical):  {_fmt(sm2)}")
    print("\nFSRS with difficulty seeded from the strategy type:")
    for label, D in (("D=2  pure (AA RFI)        ", 2.0),
                     ("D=5  mid mix (3b 70/30)   ", 5.0),
                     ("D=8  close mix (55/45)    ", 8.0)):
        f = fsrs_good_ladder(0.95, cap=120, n=n, seed_difficulty=D)
        print(f"  {label}: {_fmt(f)}")
    print("\n=> The hard close-mix card is surfaced ~4x more often than the pure")
    print("   over the same window. SM-2 cannot express this. This is exactly the")
    print("   'init difficulty by strategy type' lever from CLAUDE.md #11 / A.4.")

    print("\n" + "=" * 74)
    print("[3] LAPSE RECOVERY  — pattern Good, Good, Good, Again, Good, Good")
    print("=" * 74)
    seq_sm2 = [srs.GOOD, srs.GOOD, srs.GOOD, srs.AGAIN, srs.GOOD, srs.GOOD]
    print("SM-2 (hard reset to 1 day on the miss, ease barely moves):")
    for name, iv, ez in sm2_pattern(seq_sm2):
        print(f"  {name:5s} -> {iv:4d}d   ease={ez:.2f}")
    seq_f = [Rating.Good, Rating.Good, Rating.Good, Rating.Again, Rating.Good, Rating.Good]
    print("FSRS R=0.95 cap120 (post-lapse stability kept, difficulty jumps up):")
    for name, iv, S, D in fsrs_pattern(seq_f, 0.95, 120):
        print(f"  {name:5s} -> {iv:4d}d   S={S:6.2f}  D={D:.2f}")
    print("\n=> SM-2 forgets the card was once strong and re-climbs from 1 day at")
    print("   the same rate. FSRS reschedules from a non-zero memory and slows")
    print("   future growth (difficulty rose) — the leaky card stays in rotation.")


if __name__ == "__main__":
    main()
