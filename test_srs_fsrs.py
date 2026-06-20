"""
Tests for srs_fsrs.py (FSRS-lite scheduler).

Run as a plain script (project convention — no pytest):
    python3 test_srs_fsrs.py

Two tiers:
  - seed_difficulty() is pure Python and is ALWAYS tested.
  - Scheduler/replay tests need py-fsrs. If it isn't installed they are SKIPPED
    (not failed), because fsrs is a dev-only dependency.

A non-zero exit code means a real failure.
"""

import sys

import srs_fsrs as f

try:
    import fsrs  # noqa: F401
    HAVE_FSRS = True
except ImportError:
    HAVE_FSRS = False


# ---------------------------------------------------------------------------
# Tiny assertion harness
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_skipped = 0


def check(cond: bool, msg: str) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


def approx(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# seed_difficulty — pure Python, always runs
# ---------------------------------------------------------------------------

def test_seed_pure_action():
    check(approx(f.seed_difficulty({"open": 1.0}), 2.0), "pure open -> 2.0")
    check(approx(f.seed_difficulty({"3bet": 1.0}), 2.0), "pure 3bet -> 2.0")


def test_seed_pure_fold():
    # A trash hand expands to {"fold": 1.0} — folding it is trivial, must read pure.
    check(approx(f.seed_difficulty({"fold": 1.0}), 2.0), "pure fold -> 2.0")


def test_seed_action_agnostic():
    # Difficulty depends only on the spread, not on which action dominates.
    check(
        approx(f.seed_difficulty({"open": 1.0}), f.seed_difficulty({"fold": 1.0})),
        "pure open and pure fold seed identically",
    )


def test_seed_near_pure():
    d = f.seed_difficulty({"open": 0.9, "fold": 0.1})
    check(4.0 <= d <= 5.0, f"near-pure 0.9 -> 4..5 (got {d:.2f})")


def test_seed_even_mix():
    check(approx(f.seed_difficulty({"open": 0.5, "fold": 0.5}), 8.0),
          "even two-way mix -> 8.0")


def test_seed_close_mix():
    d = f.seed_difficulty({"3bet": 0.55, "call": 0.45})
    check(7.0 <= d <= 8.0, f"close mix 0.55 -> 7..8 (got {d:.2f})")


def test_seed_multiway_clamped():
    d = f.seed_difficulty({"call": 0.34, "3bet": 0.33, "fold": 0.33})
    check(8.0 < d <= 10.0, f"3-way even -> >8, clamped <=10 (got {d:.2f})")


def test_seed_empty_neutral():
    check(approx(f.seed_difficulty({}), 5.0), "empty strategy -> neutral 5.0")


def test_seed_bounds_and_monotonic():
    # Sweep the DOMINANT frequency from 1.0 down to 0.5 (the valid range for a
    # two-way mix — below 0.5 the other action becomes dominant, and difficulty
    # is symmetric around 0.5). Difficulty must stay in [1, 10] and never DECREASE
    # as the dominant action's share shrinks (the spot gets more ambiguous).
    prev = -1.0
    p = 1.0
    while p >= 0.50 - 1e-9:
        d = f.seed_difficulty({"a": round(p, 3), "b": round(1 - p, 3)})
        check(1.0 <= d <= 10.0, f"difficulty in [1,10] at p={p:.2f} (got {d:.2f})")
        check(d >= prev - 1e-9, f"monotonic non-decreasing at p={p:.2f} (got {d:.2f} < {prev:.2f})")
        prev = d
        p -= 0.05


def test_seed_symmetric_around_half():
    # The same two-way spot written either way must seed identically.
    check(approx(f.seed_difficulty({"a": 0.55, "b": 0.45}),
                 f.seed_difficulty({"a": 0.45, "b": 0.55})),
          "two-way mix is symmetric around 0.5")


# ---------------------------------------------------------------------------
# Scheduler / replay — need py-fsrs
# ---------------------------------------------------------------------------

def test_scheduler_config():
    s = f.make_scheduler()
    check(approx(s.desired_retention, 0.95), "scheduler retention 0.95")
    check(s.maximum_interval == 120, "scheduler max_interval 120")
    check(tuple(s.learning_steps) == (), "scheduler learning_steps empty")
    check(s.enable_fuzzing is False, "scheduler fuzzing off by default")


def test_good_ladder_caps_and_grows():
    ladder = f.good_ladder({"open": 1.0}, 9)  # pure AA, seed D=2
    check(all(ladder[i] <= ladder[i + 1] for i in range(len(ladder) - 1)),
          f"pure ladder non-decreasing (got {ladder})")
    check(max(ladder) <= 120, f"pure ladder respects 120 cap (got {ladder})")
    check(ladder[-1] == 120, f"pure ladder reaches the 120 cap (got {ladder})")


def test_difficulty_differentiation():
    # The headline property: a pure card is scheduled FURTHER OUT than a close
    # mix at the same review number (after they diverge), so the hard card is
    # surfaced more often. SM-2 cannot express this; FSRS-lite must.
    pure = f.good_ladder({"open": 1.0}, 9)          # seed D=2
    mix = f.good_ladder({"open": 0.5, "fold": 0.5}, 9)  # seed D=8
    check(all(p >= m for p, m in zip(pure, mix)),
          f"pure >= mix at every step (pure={pure}, mix={mix})")
    check(pure[-1] > mix[-1] * 2,
          f"by review 9 pure is much further out than mix (pure={pure[-1]}, mix={mix[-1]})")


def test_lapse_shortens_interval():
    # Good, Good, Good, Again, Good — the Again must pull the next interval back
    # down, and difficulty must not have dropped below the lapse moment.
    from srs import GOOD, AGAIN
    steps = [
        f.ReviewStep(0, GOOD),
        f.ReviewStep(3, GOOD),
        f.ReviewStep(8, GOOD),
        f.ReviewStep(20, AGAIN),
        f.ReviewStep(1, GOOD),
    ]
    card, intervals = f.replay({"open": 0.55, "fold": 0.45}, steps)
    check(intervals[3] < intervals[2],
          f"interval shrinks after a lapse (before={intervals[2]}, after={intervals[3]})")
    check(card.difficulty >= f.seed_difficulty({"open": 0.55, "fold": 0.45}) - 1e-6
          or card.difficulty >= 7.0,
          f"difficulty stayed high after a lapse (got {card.difficulty:.2f})")


def test_replay_deterministic():
    from srs import GOOD
    steps = [f.ReviewStep(0, GOOD), f.ReviewStep(2, GOOD), f.ReviewStep(5, GOOD)]
    a_card, a_iv = f.replay({"open": 0.7, "fold": 0.3}, steps)
    b_card, b_iv = f.replay({"open": 0.7, "fold": 0.3}, steps)
    check(a_iv == b_iv, f"replay intervals deterministic ({a_iv} vs {b_iv})")
    check(approx(a_card.difficulty, b_card.difficulty), "replay difficulty deterministic")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

PURE_TESTS = [
    test_seed_pure_action,
    test_seed_pure_fold,
    test_seed_action_agnostic,
    test_seed_near_pure,
    test_seed_even_mix,
    test_seed_close_mix,
    test_seed_multiway_clamped,
    test_seed_empty_neutral,
    test_seed_bounds_and_monotonic,
    test_seed_symmetric_around_half,
]

FSRS_TESTS = [
    test_scheduler_config,
    test_good_ladder_caps_and_grows,
    test_difficulty_differentiation,
    test_lapse_shortens_interval,
    test_replay_deterministic,
]


def main() -> None:
    global _skipped
    print("srs_fsrs tests")
    print("-" * 50)

    for t in PURE_TESTS:
        t()

    if HAVE_FSRS:
        for t in FSRS_TESTS:
            t()
    else:
        _skipped = len(FSRS_TESTS)
        print(f"  SKIP: {_skipped} scheduler tests (py-fsrs not installed; "
              "run `pip install fsrs` to include them)")

    print("-" * 50)
    print(f"passed={_passed}  failed={_failed}  skipped={_skipped}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
