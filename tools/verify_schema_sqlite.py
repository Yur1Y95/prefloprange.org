#!/usr/bin/env python3
"""
verify_schema_sqlite.py — prove the schema + feature queries are correct.

Why sqlite: the Cowork sandbox has no Postgres and no PyPI, but Python ships
sqlite3. sqlite is close enough to verify the *logic* of every feature query
(daily buckets, anti-farm session filter, streaks, goal progress, calendar).
The authoritative artifact is db/schema.sql (Postgres); the few PG-only bits
map as:
    ts at time zone tz   -> date(ts)        (harness runs everything in UTC)
    count(*) filter(...)  -> sum(case when ... )
    generate_series       -> recursive CTE
    bigint identity        -> integer autoincrement

Two parts:
  A) load the REAL migrated data (via tools/migrate_to_pg) and check the schema
     holds it + aggregates match an independent Python recount.
  B) load SYNTHETIC multi-day data and assert exact expected values for the
     anti-farm filter, streaks, goal progress, new_cards, and the calendar —
     real data is only one day, too thin to exercise streaks.

Run:  python3 tools/verify_schema_sqlite.py
Exit code != 0 on any failure (project test convention — plain scripts).
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migrate_to_pg as mig  # noqa: E402

FAILURES = []


def check(name, got, expected):
    ok = got == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} expected={expected!r}")
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Schema (sqlite flavour of db/schema.sql)
# ---------------------------------------------------------------------------

DDL = """
create table profiles (
    id text primary key,
    timezone text not null default 'UTC',
    session_min_hands int not null default 20
);
create table answers (
    id integer primary key autoincrement,
    user_id text not null,
    ts text not null,
    mode text not null,
    pack text not null,
    spot text not null,
    position text not null,
    villain text,
    hand text not null,
    action text,
    correct int not null,
    is_timeout int not null default 0,
    revealed int not null default 0,
    rating int,
    ev real,
    correct_action text,
    card_id text
);
create table cards (
    id integer primary key autoincrement,
    user_id text not null, pack text not null,
    hand text not null, position text not null, spot text not null,
    villain text not null default '',
    correct_strategy text not null default '{}',
    ease_factor real not null default 2.5,
    interval_days int not null default 0,
    next_review text, last_seen text,
    consecutive_correct int not null default 0,
    total_seen int not null default 0,
    total_correct int not null default 0,
    stability real, difficulty real,
    unique (user_id, pack, hand, position, spot, villain)
);
create table goals (
    id integer primary key autoincrement,
    user_id text not null, mode text not null,
    pack text, spot text, position text, villain text,
    period text not null, metric text not null default 'hands',
    target int not null, active int not null default 1
);
"""

ANSWER_COLS = ["user_id", "ts", "mode", "pack", "spot", "position", "villain",
               "hand", "action", "correct", "is_timeout", "revealed", "rating",
               "ev", "correct_action", "card_id"]
CARD_COLS = ["user_id", "pack", "hand", "position", "spot", "villain",
             "correct_strategy", "ease_factor", "interval_days", "next_review",
             "last_seen", "consecutive_correct", "total_seen", "total_correct",
             "stability", "difficulty"]


def insert_answer(con, **kw):
    kw.setdefault("villain", None)
    kw.setdefault("action", None)
    kw.setdefault("is_timeout", 0)
    kw.setdefault("revealed", 0)
    kw.setdefault("rating", None)
    kw.setdefault("ev", None)
    kw.setdefault("correct_action", "")
    kw.setdefault("card_id", None)
    con.execute(
        f"insert into answers ({','.join(ANSWER_COLS)}) "
        f"values ({','.join('?' for _ in ANSWER_COLS)})",
        [kw[c] for c in ANSWER_COLS],
    )


# Reusable SQL fragments (sqlite flavour) -----------------------------------

Q_SESSION_DAYS = """
select date(ts) as day, count(*) as hands
from answers
where user_id = ?
group by date(ts)
having count(*) >= (select session_min_hands from profiles where id = ?)
order by day
"""

Q_CURRENT_STREAK = """
with q(day) as (
    select date(ts) from answers where user_id = :u
    group by date(ts)
    having count(*) >= (select session_min_hands from profiles where id = :u)
),
seed(d) as (
    select max(day) from q where day in (date(:today), date(:today,'-1 day'))
),
walk(d, n) as (
    select d, 1 from seed where d is not null
    union all
    select date(w.d,'-1 day'), w.n + 1
    from walk w
    where date(w.d,'-1 day') in (select day from q)
)
select coalesce(max(n), 0) from walk
"""

Q_CALENDAR = """
with recursive span(day) as (
    select date(:from)
    union all
    select date(day,'+1 day') from span where day < date(:to)
),
act as (
    select date(ts) day, count(*) hands
    from answers where user_id = :u group by date(ts)
),
qual as (
    select date(ts) day from answers where user_id = :u
    group by date(ts)
    having count(*) >= (select session_min_hands from profiles where id = :u)
)
select span.day,
       coalesce(act.hands, 0) as hands,
       case when qual.day is not null then 1 else 0 end as trained
from span
left join act  on act.day  = span.day
left join qual on qual.day = span.day
order by span.day
"""


# ---------------------------------------------------------------------------
# Part A — real migrated data
# ---------------------------------------------------------------------------

def part_a(con):
    print("\nPart A — real migrated data (srs_state/*.json + history.json)")
    cards, answers = mig.extract_all()
    for r in cards:
        con.execute(
            f"insert into cards ({','.join(CARD_COLS)}) "
            f"values ({','.join('?' for _ in CARD_COLS)})",
            [r[c] for c in CARD_COLS],
        )
    for r in answers:
        insert_answer(con, **{k: r[k] for k in ANSWER_COLS})
    con.commit()

    # Schema holds everything we extracted.
    n_cards = con.execute("select count(*) from cards").fetchone()[0]
    n_ans = con.execute("select count(*) from answers").fetchone()[0]
    check("cards loaded == extracted", n_cards, len(cards))
    check("answers loaded == extracted", n_ans, len(answers))

    # Independent recount: learn answers per day == SQL daily aggregate.
    py_daily = Counter((r["ts"][:10], r["mode"]) for r in answers if r["ts"])
    sql_daily = {
        (d, m): h for d, m, h in con.execute(
            "select date(ts), mode, count(*) from answers group by date(ts), mode"
        ).fetchall()
    }
    check("daily aggregate matches Python recount",
          sql_daily, dict(py_daily))

    # Learn rows carry a rating (FSRS-fittable); drill rows do not.
    learn_with_rating = con.execute(
        "select count(*) from answers where mode='learn' and rating is not null"
    ).fetchone()[0]
    learn_total = con.execute(
        "select count(*) from answers where mode='learn'"
    ).fetchone()[0]
    check("every learn answer has a rating", learn_with_rating, learn_total)

    # A card's history == its answers ordered by ts (no data lost moving
    # history out of cards into the journal).
    sample = con.execute(
        "select card_id, count(*) from answers where mode='learn' and card_id is not null "
        "group by card_id order by count(*) desc limit 1"
    ).fetchone()
    if sample:
        cid, n = sample
        print(f"  (sample card {cid} -> {n} journal row(s) reconstructable as its history)")


# ---------------------------------------------------------------------------
# Part B — synthetic multi-day data (exercises streaks/goals/calendar)
# ---------------------------------------------------------------------------

def part_b(con):
    print("\nPart B — synthetic multi-day data")
    U = "TESTUSER"
    con.execute("insert into profiles (id, timezone, session_min_hands) values (?,?,?)",
                (U, "UTC", 20))

    def bulk(day, n, spot="RFI", mode="drill", correct_n=None, hand="AA"):
        cn = n if correct_n is None else correct_n
        for i in range(n):
            insert_answer(con, user_id=U, ts=f"{day}T12:00:{i % 60:02d}+00:00",
                          mode=mode, pack="P", spot=spot, position="UTG",
                          hand=hand, correct=1 if i < cn else 0)

    # Qualified (>=20): 06-01, 06-02, 06-03 (consecutive run of 3), 06-05.
    # Sub-threshold: 05-31 has 5 hands -> NOT a training (anti-farm).
    # Gap: 06-04 has 0 hands.
    bulk("2026-05-31", 5)            # below min -> excluded
    bulk("2026-06-01", 25, correct_n=20)
    bulk("2026-06-02", 25)
    bulk("2026-06-03", 25)
    bulk("2026-06-05", 25)
    con.commit()

    qdays = [d for d, _ in con.execute(Q_SESSION_DAYS, (U, U)).fetchall()]
    check("anti-farm: sub-threshold day excluded",
          qdays, ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-05"])

    # Longest streak = 3 (06-01..06-03). Use the gaps-and-islands view logic.
    rows = con.execute(
        """
        with q as (
            select date(ts) day from answers where user_id=?
            group by date(ts)
            having count(*) >= (select session_min_hands from profiles where id=?)
        ),
        d as (select day, julianday(day) - row_number() over (order by day) as grp from q),
        runs as (select grp, count(*) len from d group by grp)
        select max(len) from runs
        """, (U, U)).fetchone()
    check("longest streak", rows[0], 3)

    # Current streak, today=06-05 (trained) -> just 06-05 (06-04 is a gap) = 1.
    cs_today = con.execute(Q_CURRENT_STREAK, {"u": U, "today": "2026-06-05"}).fetchone()[0]
    check("current streak (today trained, after a gap)", cs_today, 1)

    # Current streak, today=06-04 (NOT trained) -> seed yesterday 06-03,
    # walk 06-03,06-02,06-01 = 3. (Untrained today must not break the streak.)
    cs_gap = con.execute(Q_CURRENT_STREAK, {"u": U, "today": "2026-06-04"}).fetchone()[0]
    check("current streak (today untrained -> counts thru yesterday)", cs_gap, 3)

    # Calendar 05-31..06-05: hands present on 5 days, trained-flag only on the 4
    # qualified ones (anti-farm again, now in the calendar layer).
    cal = con.execute(Q_CALENDAR, {"u": U, "from": "2026-05-31", "to": "2026-06-05"}).fetchall()
    check("calendar spans every day in window", [r[0] for r in cal],
          ["2026-05-31", "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"])
    check("calendar trained-flags (anti-farm)",
          [r[2] for r in cal], [0, 1, 1, 1, 0, 1])
    check("calendar hand counts", [r[1] for r in cal], [5, 25, 25, 25, 0, 25])

    # Goal — daily drill RFI, target 20, today 06-05: progress = 25 -> met.
    con.execute("insert into goals (user_id,mode,spot,period,metric,target) "
                "values (?,?,?,?,?,?)", (U, "drill", "RFI", "daily", "hands", 20))
    prog_daily = con.execute(
        """
        select count(*) from answers a
        where a.user_id=? and a.mode='drill' and a.spot='RFI'
          and date(a.ts)=date(?)
        """, (U, "2026-06-05")).fetchone()[0]
    check("daily goal progress (today)", prog_daily, 25)
    check("daily goal met", prog_daily >= 20, True)

    # Total goal — all RFI drill hands = 5+25+25+25+25 = 105.
    prog_total = con.execute(
        "select count(*) from answers where user_id=? and mode='drill' and spot='RFI'",
        (U,)).fetchone()[0]
    check("total goal progress (cumulative)", prog_total, 105)

    # new_cards metric (learn): A1 first-seen 06-02, A2 first-seen 06-03.
    # new cards on 06-03 = 1 (A2 only).
    insert_answer(con, user_id=U, ts="2026-06-02T12:00:00+00:00", mode="learn",
                  pack="P", spot="RFI", position="UTG", hand="A1", correct=1,
                  rating=3, card_id="A1__UTG__RFI")
    insert_answer(con, user_id=U, ts="2026-06-03T12:00:00+00:00", mode="learn",
                  pack="P", spot="RFI", position="UTG", hand="A1", correct=1,
                  rating=3, card_id="A1__UTG__RFI")
    insert_answer(con, user_id=U, ts="2026-06-03T12:00:00+00:00", mode="learn",
                  pack="P", spot="RFI", position="UTG", hand="A2", correct=1,
                  rating=3, card_id="A2__UTG__RFI")
    con.commit()
    new_cards_0603 = con.execute(
        """
        select count(*) from (
            select card_id, min(date(ts)) first_day
            from answers where user_id=? and mode='learn'
            group by card_id
        ) where first_day = date(?)
        """, (U, "2026-06-03")).fetchone()[0]
    check("learn new_cards introduced today", new_cards_0603, 1)


def main():
    con = sqlite3.connect(":memory:")
    con.executescript(DDL)
    # Real-data user profile (single-user migration id) for Part A.
    con.execute("insert into profiles (id, timezone, session_min_hands) values (?,?,?)",
                (mig.DEFAULT_USER, "UTC", 20))
    part_a(con)
    part_b(con)

    print("\n" + ("ALL CHECKS PASSED" if not FAILURES
                   else f"{len(FAILURES)} FAILED: {FAILURES}"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
