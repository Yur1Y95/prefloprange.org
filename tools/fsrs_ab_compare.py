"""
fsrs_ab_compare.py — A/B comparison of FSRS-lite vs our live SM-2 on REAL data.

WHY THIS EXISTS
---------------
Track A.4 asks: would FSRS schedule Learn-Mode cards better than our hand-tuned
SM-2? This harness replays each card's *actual logged review history*
(srs_state/<deck>.srs.json) through BOTH schedulers and prints the results side
by side, so the A.4 decision can be made on numbers from your own decks.

It is an ANALYSIS / DEV tool, not part of the app runtime:
  - imports the real production srs.py (SM-2) and srs_fsrs.py (FSRS-lite);
  - reads srs_state but never writes it;
  - needs py-fsrs (dev-only):  pip install fsrs

HONEST CAVEAT
-------------
With only a day or two of practice each reviewed card has ~1 logged review, so
the "next interval" columns barely diverge yet — both schedulers are near their
start. The signal you CAN read today is the difficulty-seed spread (a property
of the strategy, not of history) and the forward projection, which show how
FSRS-lite separates trivial folds from close mixes while SM-2 gives them the
identical ladder. The real verdict needs 2-3 weeks of reviews (roadmap A.2).

Run:
    python3 tools/fsrs_ab_compare.py              # all decks in srs_state/
    python3 tools/fsrs_ab_compare.py GTOWNL10     # one deck (stem or filename)
"""

from __future__ import annotations

import glob
import os
import sys
from datetime import date

# Make the repo root importable so we exercise the real production modules.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import srs        # noqa: E402  production SM-2 engine
import srs_fsrs   # noqa: E402  FSRS-lite scheduler

SRS_DIR = os.path.join(_REPO_ROOT, "srs_state")


# ---------------------------------------------------------------------------
# SM-2 side — drive the REAL srs.update_card
# ---------------------------------------------------------------------------

def sm2_replay_from_history(card: srs.Card) -> tuple[int, float]:
    """Replay a card's logged history through real SM-2; return (interval, ease)."""
    fresh = srs.Card(
        hand=card.hand, position=card.position, spot=card.spot,
        villain_position=card.villain_position,
        correct_strategy=dict(card.correct_strategy),
    )
    for entry in card.history:
        srs.update_card(fresh, entry["rating"], today=date.fromisoformat(entry["date"]))
    return fresh.interval_days, fresh.ease_factor


def sm2_good_ladder(strategy: dict, n: int) -> list[int]:
    """SM-2 interval ladder for n consecutive Good answers from a fresh card.

    Note: under binary grading SM-2's ease stays frozen at 2.5, so this ladder
    is IDENTICAL for every card regardless of `strategy` — that is exactly the
    defect FSRS-lite fixes (see the forward-projection output)."""
    fresh = srs.Card(hand="x", position="UTG", spot="RFI",
                     correct_strategy=dict(strategy))
    today = date(2026, 1, 1)
    out: list[int] = []
    for _ in range(n):
        srs.update_card(fresh, srs.GOOD, today=today)
        out.append(fresh.interval_days)
        today = date.fromisoformat(fresh.next_review)
    return out


# ---------------------------------------------------------------------------
# FSRS-lite side
# ---------------------------------------------------------------------------

def fsrs_replay_from_history(card: srs.Card) -> tuple[int, float, float]:
    """Replay logged history through FSRS-lite; return (interval, stability, difficulty)."""
    steps = [srs_fsrs.ReviewStep(delta_days=e["delta_days"], rating=e["rating"])
             for e in card.history]
    fcard, intervals = srs_fsrs.replay(card.correct_strategy, steps)
    return intervals[-1], fcard.stability, fcard.difficulty


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _bucket(d: float) -> str:
    if d <= 2.0 + 1e-6:
        return "pure (incl. pure-fold)"
    if d < 6.0:
        return "near / mid mix"
    if d < 8.0:
        return "close mix"
    return "even / multi-way"

_BUCKET_ORDER = [
    "pure (incl. pure-fold)",
    "near / mid mix",
    "close mix",
    "even / multi-way",
]


def _spot_label(card: srs.Card) -> str:
    if card.villain_position:
        return f"{card.hand} {card.position} {card.spot} v{card.villain_position}"
    return f"{card.hand} {card.position} {card.spot}"


def _fmt_ladder(seq: list[int]) -> str:
    return " ".join(f"{v:>3d}" for v in seq)


# ---------------------------------------------------------------------------
# Per-deck report
# ---------------------------------------------------------------------------

def process_deck(path: str) -> None:
    cards = srs.load_state(path)
    name = os.path.basename(path)
    reviewed = [c for c in cards if c.total_seen > 0]
    new = len(cards) - len(reviewed)

    print("=" * 78)
    print(f"  {name}   |   {len(cards)} cards   {len(reviewed)} reviewed   {new} new")
    print("=" * 78)

    # --- Difficulty-seed spread across the WHOLE deck ----------------------
    counts = {b: 0 for b in _BUCKET_ORDER}
    for c in cards:
        counts[_bucket(srs_fsrs.seed_difficulty(c.correct_strategy))] += 1
    total = len(cards) or 1
    print("\nDifficulty-seed spread (all cards, from strategy frequencies):")
    for b in _BUCKET_ORDER:
        n = counts[b]
        pct = 100.0 * n / total
        bar = "#" * round(pct / 2.5)
        print(f"  {b:<26s} {n:>5d}  ({pct:4.1f}%)  {bar}")

    if not reviewed:
        print("\n(no reviewed cards yet — nothing to replay; come back after some practice)\n")
        return

    # --- Reviewed cards: SM-2 vs FSRS-lite, replayed from history ----------
    print("\nReviewed cards — replayed through both schedulers from logged history:")
    print(f"  {'card':<28s} {'class':<7s} {'Dseed':>5s}   "
          f"{'SM-2 next':<16s} {'FSRS-lite next':<22s}")
    print("  " + "-" * 76)
    reviewed.sort(key=lambda c: -srs_fsrs.seed_difficulty(c.correct_strategy))
    for c in reviewed:
        dseed = srs_fsrs.seed_difficulty(c.correct_strategy)
        sm_iv, sm_ease = sm2_replay_from_history(c)
        fs_iv, fs_S, fs_D = fsrs_replay_from_history(c)
        cls = c.classify().replace("pure_", "p:")
        print(f"  {_spot_label(c):<28s} {cls:<7s} {dseed:>5.1f}   "
              f"{(str(sm_iv) + 'd  ease' + format(sm_ease, '.2f')):<16s} "
              f"{(str(fs_iv) + 'd  S' + format(fs_S, '.1f') + ' D' + format(fs_D, '.1f')):<22s}")

    # --- Forward projection on representative reviewed cards ---------------
    # Pick the most pure and the most mixed reviewed card to show the divergence.
    by_d = sorted(reviewed, key=lambda c: srs_fsrs.seed_difficulty(c.correct_strategy))
    sample = []
    seen_labels = set()
    for c in (by_d[0], by_d[-1]):  # easiest and hardest reviewed
        if _spot_label(c) not in seen_labels:
            sample.append(c)
            seen_labels.add(_spot_label(c))

    n_steps = 9
    print("\nForward projection — if every future answer is Good (interval ladder, days):")
    print(f"  {'card':<28s} {'Dseed':>5s}   SM-2 (uncapped)        FSRS-lite (R.95 cap120)")
    print("  " + "-" * 76)
    for c in sample:
        dseed = srs_fsrs.seed_difficulty(c.correct_strategy)
        sm = sm2_good_ladder(c.correct_strategy, n_steps)
        fs = srs_fsrs.good_ladder(c.correct_strategy, n_steps)
        print(f"  {_spot_label(c):<28s} {dseed:>5.1f}   {_fmt_ladder(sm)}")
        print(f"  {'':<28s} {'':>5s}   {_fmt_ladder(fs)}   <- FSRS-lite")
    print("\n  ^ SM-2 ladders are IDENTICAL regardless of strategy (ease frozen at 2.5")
    print("    under binary grading); FSRS-lite surfaces the harder card more often.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Fail fast with a clear message if py-fsrs isn't installed.
    try:
        srs_fsrs.make_scheduler()
    except ImportError as exc:
        sys.exit(str(exc))

    args = sys.argv[1:]
    if args:
        paths = []
        for a in args:
            stem = a[:-9] if a.endswith(".srs.json") else (a[:-5] if a.endswith(".json") else a)
            p = os.path.join(SRS_DIR, f"{stem}.srs.json")
            if not os.path.exists(p):
                sys.exit(f"No such deck: {p}")
            paths.append(p)
    else:
        paths = sorted(glob.glob(os.path.join(SRS_DIR, "*.srs.json")))

    if not paths:
        sys.exit(f"No srs_state/*.srs.json decks found under {SRS_DIR}")

    print("FSRS-lite config: retention "
          f"{srs_fsrs.DESIRED_RETENTION}, max_interval {srs_fsrs.MAXIMUM_INTERVAL}, "
          "learning_steps=()")
    for p in paths:
        process_deck(p)


if __name__ == "__main__":
    main()
