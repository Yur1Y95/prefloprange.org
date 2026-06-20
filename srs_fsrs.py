"""
srs_fsrs.py — FSRS-lite scheduler for Learn Mode (PARALLEL to srs.py's SM-2).

WHAT THIS IS
------------
An experimental, poker-tuned wrapper around py-fsrs (FSRS-6). It exists so we can
compare FSRS scheduling against our hand-tuned SM-2 on real data, and — if the
data later says SM-2 systematically misschedules — switch Learn Mode over to it.

It is NOT wired into srs_api and the live Learn flow does NOT import it. See
docs/fsrs_analysis.md §5 and CLAUDE.md decision #11 / roadmap A.4 for the why.

DESIGN DECISIONS (all from docs/fsrs_analysis.md)
-------------------------------------------------
1. Default FSRS-6 parameters — we do NOT fit our own yet. Fitting 21 params on a
   handful of binary answers would overfit to noise. Param fitting (the
   fsrs-optimizer package) is deferred until 2-3 weeks of real reviews exist.
2. Three poker tweaks on top of the defaults:
     - desired_retention = 0.95  (preflop ranges are used every hand; 0.90 default
       schedules reviews years out, meaningless for a grinder's horizon)
     - maximum_interval = 120 days ("keep it fresh while I play these stakes",
       not "remember for a year")
     - learning_steps = ()  (jump straight to a day-interval; no 1-min/10-min
       same-session cram that makes no sense for a poker decision)
3. Difficulty is SEEDED from the strategy's frequency spread (see seed_difficulty).
   This is the key lever: under binary Again/Good grading, neither our SM-2 ease
   nor FSRS difficulty moves on a correct answer, so a trivial pure card (AA open
   1.0) and a nasty close mix (A5s 55/45) would otherwise look identical. Seeding
   difficulty up front is the only way to tell them apart with a binary signal.

DEPENDENCY
----------
Requires py-fsrs:  pip install fsrs   (intentionally NOT in requirements.txt —
production never imports this module, so it stays a dev-only dependency.)

The fsrs import is lazy (inside _require_fsrs), so:
  - `import srs_fsrs` always works, even without fsrs installed;
  - seed_difficulty() is pure Python and needs no fsrs at all;
  - only make_scheduler()/replay() require the package, and they raise a clear,
    actionable error if it is missing.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Poker-tuned FSRS-lite configuration (docs/fsrs_analysis.md §3, §5)
# ---------------------------------------------------------------------------

DESIRED_RETENTION = 0.95   # target probability of recall at review time
MAXIMUM_INTERVAL  = 120    # days — practical "while I play these stakes" horizon

# Mirror srs.PURE_THRESHOLD so "pure" means the same thing in both engines.
PURE_THRESHOLD = 0.95

# Difficulty seed anchors on the FSRS 1..10 scale (10 = hardest):
#   pure card                       -> SEED_PURE
#   near-pure (dominant ~= 0.95)    -> SEED_NEARPURE_HI
#   even 2-way mix (dominant = 0.5) -> SEED_EVEN
# Between 0.5 and PURE_THRESHOLD we interpolate linearly on the dominant
# frequency; multi-way even splits (dominant < 0.5) push past SEED_EVEN and are
# clamped to the FSRS ceiling of 10.
SEED_PURE        = 2.0
SEED_NEARPURE_HI = 4.0
SEED_EVEN        = 8.0

# FSRS difficulty is defined on [1, 10]; never seed outside that.
FSRS_DIFFICULTY_MIN = 1.0
FSRS_DIFFICULTY_MAX = 10.0


# ---------------------------------------------------------------------------
# Lazy dependency guard
# ---------------------------------------------------------------------------

def _require_fsrs():
    """Import py-fsrs on demand. Raises a clear error if it isn't installed."""
    try:
        from fsrs import Scheduler, Card, Rating  # type: ignore
    except ImportError as exc:  # pragma: no cover - guidance path
        raise ImportError(
            "srs_fsrs needs py-fsrs, which is a dev-only dependency (not in "
            "requirements.txt because production never imports this module).\n"
            "Install it to use the FSRS-lite scheduler:  pip install fsrs"
        ) from exc
    return Scheduler, Card, Rating


# ---------------------------------------------------------------------------
# Difficulty seeding — the heart of FSRS-lite for poker
# ---------------------------------------------------------------------------

def seed_difficulty(strategy: dict[str, float]) -> float:
    """
    Map a card's correct-strategy frequency spread to an FSRS difficulty seed.

    Intuition: the harder a spot is to *memorize*, the more often we want to see
    it. A pure decision (always open AA; always fold 72o) is trivial. A close mix
    (open 55% / fold 45%) is the hardest — you must remember it's a mix AND its
    rough ratio. So difficulty rises as the dominant action's frequency falls
    from 1.0 (pure) toward 0.5 (maximally ambiguous two-way split).

    Why seed at all? Under our binary Again/Good grading a correct answer leaves
    both SM-2 ease and FSRS difficulty essentially frozen (see fsrs_analysis.md
    §2.2/§4). Without an up-front seed, every card you "know" looks equally easy,
    and the close mixes — exactly the ones worth drilling — never get surfaced
    more often. Seeding from the strategy is how we inject "this one is hard".

    Returns a float on the FSRS [1, 10] scale. Action-agnostic: a pure fold and a
    pure open both read as pure (dominant frequency ~= 1.0).

    Examples:
        {"open": 1.0}              -> 2.0   (pure)
        {"fold": 1.0}              -> 2.0   (pure fold — trivial trash hand)
        {"open": 0.9, "fold": 0.1} -> ~4.4  (near-pure)
        {"3bet": 0.55, "call": 0.45} -> ~7.6 (close mix)
        {"open": 0.5, "fold": 0.5} -> 8.0   (even mix)
        {} (unknown)               -> 5.0   (neutral fallback)
    """
    if not strategy:
        return 5.0  # no information — sit in the middle

    dominant = max(strategy.values())

    if dominant >= PURE_THRESHOLD:
        return SEED_PURE

    # Linear interpolation on the dominant frequency:
    #   dominant = PURE_THRESHOLD -> SEED_NEARPURE_HI
    #   dominant = 0.5            -> SEED_EVEN
    # frac is 0 at the near-pure end and 1 at an even two-way split. Multi-way
    # even splits (dominant < 0.5) give frac > 1, i.e. harder than a two-way mix,
    # which is then clamped to the FSRS ceiling.
    frac = (PURE_THRESHOLD - dominant) / (PURE_THRESHOLD - 0.5)
    difficulty = SEED_NEARPURE_HI + frac * (SEED_EVEN - SEED_NEARPURE_HI)
    return max(FSRS_DIFFICULTY_MIN, min(FSRS_DIFFICULTY_MAX, difficulty))


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------

def make_scheduler(
    *,
    retention: float = DESIRED_RETENTION,
    maximum_interval: int = MAXIMUM_INTERVAL,
    enable_fuzzing: bool = False,
):
    """
    Build a py-fsrs Scheduler with our poker-tuned config on FSRS-6 defaults.

    enable_fuzzing defaults to False for deterministic, reproducible scheduling
    (handy for tests and the A/B harness). A real deployment would flip it on so
    that large decks don't pile all their reviews onto the same day.
    """
    Scheduler, _, _ = _require_fsrs()
    return Scheduler(
        desired_retention=retention,
        learning_steps=(),      # straight to day-intervals, no same-session cram
        relearning_steps=(),    # a lapse reschedules in days, not minutes
        maximum_interval=maximum_interval,
        enable_fuzzing=enable_fuzzing,
    )


# ---------------------------------------------------------------------------
# Replay — drive a card through a sequence of reviews
# ---------------------------------------------------------------------------

@dataclass
class ReviewStep:
    """One review event, in the same shape srs.py logs to Card.history."""
    delta_days: int   # days since the previous review (0 for the first ever)
    rating: int       # srs rating: 1=AGAIN, 2=HARD, 3=GOOD, 4=EASY
                      # (Learn's binary input only ever produces AGAIN or GOOD)


def replay(
    strategy: dict[str, float],
    steps: list[ReviewStep],
    *,
    retention: float = DESIRED_RETENTION,
    maximum_interval: int = MAXIMUM_INTERVAL,
):
    """
    Replay a sequence of reviews through FSRS-lite for one card.

    The card's difficulty is seeded from ``strategy`` right after the first
    review. (FSRS only assigns a difficulty once it has seen a rating, and the
    first interval is driven by stability, not difficulty — so seeding after the
    first review changes nothing about that first interval but takes effect for
    every review afterward. This mirrors tools/fsrs_interval_sim.py.)

    Returns ``(fsrs_card, intervals)`` where ``intervals[i]`` is the scheduled
    day-gap to the next review after step i. The final fsrs_card carries
    ``.stability`` and ``.difficulty`` for inspection.
    """
    from datetime import datetime, timedelta, timezone

    Scheduler, Card, Rating = _require_fsrs()
    rating_map = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}

    sched = make_scheduler(retention=retention, maximum_interval=maximum_interval)
    seed = seed_difficulty(strategy)

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    card = Card()
    intervals: list[int] = []

    for i, step in enumerate(steps):
        if i > 0:
            now = now + timedelta(days=step.delta_days)
        card, _ = sched.review_card(card, rating_map[step.rating], review_datetime=now)
        if i == 0:
            card.difficulty = seed  # inject our seed once FSRS has initialized it
        intervals.append(round((card.due - now).total_seconds() / 86400))

    return card, intervals


def good_ladder(
    strategy: dict[str, float],
    n: int,
    *,
    retention: float = DESIRED_RETENTION,
    maximum_interval: int = MAXIMUM_INTERVAL,
) -> list[int]:
    """
    Projection: the interval ladder for ``n`` consecutive Good answers, with
    difficulty seeded from ``strategy``. Unlike replay() (which is driven by the
    real, logged gaps between reviews), here we answer exactly on each due date —
    "if I keep getting this right, when do I see it again?". This is the loop
    used in tools/fsrs_interval_sim.py and is what makes the pure-vs-mix
    difficulty divergence visible.
    """
    from datetime import datetime, timezone

    from srs import GOOD  # local import to avoid a hard module-load coupling

    Scheduler, Card, Rating = _require_fsrs()
    sched = make_scheduler(retention=retention, maximum_interval=maximum_interval)
    seed = seed_difficulty(strategy)

    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    now = start
    card = Card()
    intervals: list[int] = []
    for i in range(n):
        card, _ = sched.review_card(card, Rating.Good, review_datetime=now)
        if i == 0:
            card.difficulty = seed
        intervals.append(round((card.due - now).total_seconds() / 86400))
        now = card.due  # answer exactly on the due date
    return intervals
