"""Progress dashboard read store — Track D, Stage 2 (личный кабинет).

Single responsibility: assemble the per-user progress dashboard (counters,
streaks, activity calendar, accuracy by spot/position) from the append-only
``answers`` journal plus the ``cards`` SRS table. READ-ONLY — it never writes.

Design (mirrors stats_store.py — "one module, one job"):
  * DB-ONLY FEATURE, with soft degradation. A streak / calendar / per-day bar
    chart cannot be reconstructed from the legacy JSON files: history.json
    stored a time WITHOUT a date (the whole reason the journal exists). So
    when DATABASE_URL is unset we return ``{"available": False}`` and the
    frontend shows a clean "needs the database" state. This is the honest
    degradation — never a half-built reconstruction, never a crash.
  * ONE round-trip, ONE payload. read_overview() runs a handful of queries on a
    single connection and returns everything the page needs, so the frontend
    makes exactly one request.
  * Pure helpers (_accuracy, _streaks, _window_days, _nest_by_spot) carry all
    the date/shape math and are unit-tested without a database.
  * SQL placeholders are psycopg3 ``%(name)s`` style (matches journal.py /
    cards_store.py / stats_store.py).

The "day" boundary — UTC for now, with ONE extension point:
  Every per-day bucket is ``(ts at time zone 'UTC')::date``. That literal
  ``'UTC'`` is the single place to swap for ``profiles.timezone`` when per-user
  timezones land (the schema's profiles.timezone already defaults to 'UTC', so
  the switch is seamless). Bucketing here in the query — rather than reusing the
  profiles-joining views (v_daily_activity etc.) — means the dashboard also
  works for a user without a profiles row yet (the anti-farm threshold falls
  back to a default), so it never mysteriously shows empty.

Security: the database URL/password is read only from the environment (inside
db.py). Nothing here logs connection details.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import db
# One dev user until/without auth (D.2) — the SAME id journal/cards write under,
# so reads line up with writes. The real user_id comes from the request's JWT.
from journal import DEV_USER_ID


# A card has entered long-term memory once its SRS interval reaches this many
# days (mirror of srs.LEARNED_THRESHOLD_DAYS — kept here as a literal rather than
# imported so this read store has no dependency on the SRS engine internals).
LEARNED_THRESHOLD_DAYS = 21

# Anti-farm default when the user has no profiles row yet (mirror of the schema
# default profiles.session_min_hands). A calendar day only counts as a real
# "training" once the user answered at least this many hands that day.
DEFAULT_SESSION_MIN_HANDS = 20

# Size of the activity window returned for the calendar + bar charts: 26 weeks.
# Streaks are computed over ALL history (not just this window); only the
# calendar/bars are clipped to it.
CALENDAR_DAYS = 182

# Spot display order (matches the trainers / range-file convention). Unknown
# spots sort last but stay visible.
_SPOT_ORDER = ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso", "squeeze", "vs_squeeze")


def _spot_rank(spot) -> tuple:
    try:
        return (0, _SPOT_ORDER.index(spot))
    except ValueError:
        return (1, 0)


# ---------------------------------------------------------------------------
# Pure conversions / math: rows + dates -> the shapes the frontend renders.
# No I/O, no database — all unit-tested in test_dashboard_store.py.
# ---------------------------------------------------------------------------

def _accuracy(correct: int, hands: int):
    """Percent correct rounded to 0.1, or None when there are no hands (so the
    UI can show a dash instead of a misleading 0%)."""
    if not hands:
        return None
    return round(100.0 * correct / hands, 1)


def _streaks(qualified_days, today) -> dict:
    """Current + longest streak over the set of QUALIFIED (anti-farm) days.

    * longest — the longest run of consecutive calendar days, anywhere in
      history.
    * current — the run ending at the most recent of {today, yesterday}. Seeding
      from yesterday too means an as-yet-untrained today does not zero a streak
      that was alive yesterday (mirrors db/queries.sql 5b). No qualified days
      => both 0.

    ``qualified_days`` is any iterable of ``date``; ``today`` is a ``date``.
    """
    qual = set(qualified_days)
    if not qual:
        return {"current": 0, "longest": 0}

    days = sorted(qual)
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev) == timedelta(days=1) else 1
        longest = max(longest, run)

    yesterday = today - timedelta(days=1)
    seed = today if today in qual else (yesterday if yesterday in qual else None)
    current = 0
    d = seed
    while d is not None and d in qual:
        current += 1
        d -= timedelta(days=1)

    return {"current": current, "longest": longest}


def _window_days(per_day: dict, today, days: int, threshold: int) -> list:
    """A dense list of the last ``days`` calendar days ending at ``today``.

    Every day in the window is present (missing days zero-filled) so the
    frontend can lay out a gap-free heatmap / bar series. ``per_day`` maps a
    ``date`` -> ``(hands, correct)``. ``trained`` marks an anti-farm-qualified
    day (>= threshold), which the calendar colours distinctly.
    """
    out = []
    start = today - timedelta(days=days - 1)
    d = start
    while d <= today:
        hands, correct = per_day.get(d, (0, 0))
        out.append({
            "day": d.isoformat(),
            "hands": hands,
            "correct": correct,
            "trained": hands >= threshold,
        })
        d += timedelta(days=1)
    return out


def _nest_by_spot(rows) -> list:
    """Flat ``(spot, position, villain, hands, correct)`` rows -> per-spot groups
    with a position/villain breakdown and accuracy at both levels.

    Output: ``[{spot, hands, correct, accuracy, rows:[{key, position, villain,
    hands, correct, accuracy}, ...]}, ...]`` ordered by the trainer spot order.
    ``key`` is ``'UTG'`` for RFI or ``'BTN_vs_MP'`` for vs-spots (same format the
    Drill stats panel uses).
    """
    spots: dict = {}
    for r in rows:
        spot = r["spot"]
        villain = r.get("villain")
        position = r["position"]
        hands = int(r["hands"])
        correct = int(r["correct"])
        key = position if not villain else f"{position}_vs_{villain}"
        bucket = spots.setdefault(spot, {"spot": spot, "hands": 0, "correct": 0, "rows": []})
        bucket["rows"].append({
            "key": key,
            "position": position,
            "villain": villain,
            "hands": hands,
            "correct": correct,
            "accuracy": _accuracy(correct, hands),
        })
        bucket["hands"] += hands
        bucket["correct"] += correct

    out = []
    for spot in sorted(spots, key=_spot_rank):
        bucket = spots[spot]
        bucket["accuracy"] = _accuracy(bucket["correct"], bucket["hands"])
        out.append(bucket)
    return out


# ---------------------------------------------------------------------------
# SQL — psycopg3 ``%(name)s`` placeholders. Every per-day bucket uses
# ``at time zone 'UTC'`` (the single tz extension point, see module docstring).
# ---------------------------------------------------------------------------

# Anti-farm threshold for this user, defaulting when there is no profiles row.
_THRESHOLD_SQL = """
select coalesce(
    (select session_min_hands from profiles where id = %(user_id)s),
    %(default_min)s
) as threshold
"""

# Per-day hands + correct over ALL history (powers streaks AND the window).
_PER_DAY_SQL = """
select (ts at time zone 'UTC')::date as day,
       count(*)::int                       as hands,
       count(*) filter (where correct)::int as correct
from answers
where user_id = %(user_id)s
group by (ts at time zone 'UTC')::date
order by day
"""

# Lifetime totals, split by trainer.
_TOTALS_SQL = """
select
    count(*)::int                              as hands,
    count(*) filter (where correct)::int       as correct,
    count(*) filter (where mode = 'drill')::int as drill_hands,
    count(*) filter (where mode = 'learn')::int as learn_hands
from answers
where user_id = %(user_id)s
"""

# SRS deck size + how many cards have reached long-term memory.
_CARDS_SQL = """
select
    count(*)::int                                        as total,
    count(*) filter (where interval_days >= %(learned)s)::int as learned
from cards
where user_id = %(user_id)s
"""

# Accuracy by spot + hero position (+ villain for vs-spots), all modes.
_BY_SPOT_SQL = """
select spot, position, villain,
       count(*)::int                       as hands,
       count(*) filter (where correct)::int as correct
from answers
where user_id = %(user_id)s
group by spot, position, villain
order by spot, position, villain
"""


# ---------------------------------------------------------------------------
# Public read API. DB errors propagate (like stats_store / cards_store) — a
# configured-but-broken DB is a real error to surface; the frontend swallows it
# and shows the empty state.
# ---------------------------------------------------------------------------

def read_overview(user_id=DEV_USER_ID) -> dict:
    """The whole progress dashboard in one payload.

    Returns ``{"available": False, ...}`` when no database is configured (the
    dashboard is inherently DB-only). Otherwise ``available`` is True and the
    payload carries ``totals``, ``streak``, ``days`` (calendar/bars window) and
    ``by_spot``. ``user_id`` comes from the request's JWT (D.2); defaults to the
    dev user so an unauthenticated/dev run lines up with the journal writes.
    """
    pool = db.get_pool()
    if pool is None:
        return {"available": False, "reason": "database not configured"}

    from psycopg.rows import dict_row
    uid = str(user_id)
    today = datetime.now(timezone.utc).date()

    with pool.connection(timeout=10) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_THRESHOLD_SQL, {"user_id": uid, "default_min": DEFAULT_SESSION_MIN_HANDS})
            row = cur.fetchone() or {}
            threshold = int(row.get("threshold") or DEFAULT_SESSION_MIN_HANDS)

            cur.execute(_PER_DAY_SQL, {"user_id": uid})
            per_day_rows = cur.fetchall()

            cur.execute(_TOTALS_SQL, {"user_id": uid})
            totals_row = cur.fetchone() or {}

            cur.execute(_CARDS_SQL, {"user_id": uid, "learned": LEARNED_THRESHOLD_DAYS})
            cards_row = cur.fetchone() or {}

            cur.execute(_BY_SPOT_SQL, {"user_id": uid})
            spot_rows = cur.fetchall()

    per_day: dict = {}
    qualified = set()
    for r in per_day_rows:
        day = r["day"]                       # psycopg returns a date object
        hands = int(r["hands"])
        correct = int(r["correct"])
        per_day[day] = (hands, correct)
        if hands >= threshold:
            qualified.add(day)

    total_hands = int(totals_row.get("hands") or 0)
    total_correct = int(totals_row.get("correct") or 0)

    return {
        "available": True,
        "today": today.isoformat(),
        "threshold": threshold,
        "totals": {
            "hands":       total_hands,
            "correct":     total_correct,
            "accuracy":    _accuracy(total_correct, total_hands),
            "drill_hands": int(totals_row.get("drill_hands") or 0),
            "learn_hands": int(totals_row.get("learn_hands") or 0),
            "cards_total": int(cards_row.get("total") or 0),
            "learned":     int(cards_row.get("learned") or 0),
        },
        "streak":  _streaks(qualified, today),
        "days":    _window_days(per_day, today, CALENDAR_DAYS, threshold),
        "by_spot": _nest_by_spot(spot_rows),
    }
