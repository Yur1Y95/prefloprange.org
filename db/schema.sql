-- ============================================================================
-- PreflopRange — Postgres schema (Track D, Stage 0 / D.1)
-- Target: Supabase Postgres. Auth (login, email, OAuth) is owned by Supabase
-- in the `auth` schema; this file owns the *application* data only.
--
-- Design principle (see docs/db_schema.md): ONE append-only event journal
-- (`answers`) is the source of truth for "what happened". Every metric the
-- product shows — daily activity, accuracy, streaks, goal progress, the old
-- stats.json / history.json — is a QUERY over `answers`. SRS scheduling state
-- ("what to show next") lives separately in `cards`.
--
-- Comments are in English to match the codebase convention (CLAUDE.md #10).
-- Narrative rationale (in Russian) lives in docs/db_schema.md.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- profiles — per-user application data, keyed to the Supabase auth user.
-- ----------------------------------------------------------------------------
-- In Supabase, `id` should reference auth.users(id):
--     id uuid primary key references auth.users(id) on delete cascade
-- We keep a plain uuid here so the file also loads on a vanilla Postgres for
-- local testing; add the FK in the Supabase migration (see docs/db_schema.md).
create table if not exists profiles (
    id                 uuid primary key,
    email              text,
    -- Day boundary for streaks/goals is the USER's local day, not UTC.
    -- All timestamps are stored UTC (timestamptz) and bucketed into days via
    -- (ts at time zone timezone)::date. IANA name, e.g. 'Europe/Moscow'.
    timezone           text        not null default 'UTC',
    -- Anti-farm threshold: a calendar day only counts as a real "training"
    -- once the user has answered at least this many hands that day.
    -- Configurable per user; default 20 (decision 2026-06-19).
    session_min_hands  int         not null default 20,
    created_at         timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- answers — append-only event journal. THE source of truth.
-- ----------------------------------------------------------------------------
-- One row per answered hand, from EITHER trainer (drill or learn). Never
-- updated, never deleted in normal use. Replaces both stats.json (aggregates)
-- and history.json (per-hand log), neither of which carried a real date.
create table if not exists answers (
    id             bigint generated always as identity primary key,
    user_id        uuid        not null,            -- -> profiles(id)
    ts             timestamptz not null default now(),

    -- What kind of training produced this answer.
    mode           text        not null check (mode in ('drill', 'learn')),

    -- The spot identity (mirrors the range-file shape used everywhere).
    pack           text        not null,            -- range file stem, e.g. 'GTOWNL10'
    spot           text        not null,            -- 'RFI','vs_RFI','vs_3bet','vs_4bet','iso','squeeze','vs_squeeze'
    position       text        not null,            -- hero position: UTG/MP/CO/BTN/SB/BB
    villain        text,                            -- opener/3-bettor, or pair-key for squeeze; NULL for RFI
    hand           text        not null,            -- canonical notation: 'AKs','T9o','22'

    -- The decision and its grading.
    action         text,                            -- action the user chose; NULL on a pure timeout with no choice
    correct        boolean     not null,
    is_timeout     boolean     not null default false,
    revealed       boolean     not null default false,  -- learn "Show answer" -> graded AGAIN
    rating         smallint    check (rating between 1 and 4),  -- SM-2/FSRS grade (learn); NULL for drill
    ev             real,                            -- GTO EV of the action in bb, if known
    correct_action text,                            -- what the trained range wanted (for review UI)

    -- Link back to the SRS card (learn only). Format mirrors srs.Card.card_id:
    --   'AA__UTG__RFI'  or  'AKs__SB__vs_RFI__UTG'
    card_id        text
);

-- Daily/range scans per user (calendar, streaks, "trained today").
create index if not exists answers_user_ts        on answers (user_id, ts);
-- Per spot/position aggregates (the stats panel).
create index if not exists answers_user_mode_spot on answers (user_id, mode, spot, position);
-- Per-card review sequence (FSRS fitting in Track A.4).
create index if not exists answers_user_card      on answers (user_id, card_id);

-- ----------------------------------------------------------------------------
-- cards — current SRS scheduling state, one row per (user, pack, card).
-- ----------------------------------------------------------------------------
-- This is the per-user, in-DB version of srs_state/<pack>.srs.json. It holds
-- only CURRENT state ("what to show next"). The per-review history[] array that
-- the JSON card carried is NOT duplicated here — those events live in `answers`
-- (a card's history = SELECT ... FROM answers WHERE card_id = ... ORDER BY ts).
create table if not exists cards (
    id                  bigint generated always as identity primary key,
    user_id             uuid not null,             -- -> profiles(id)
    pack                text not null,

    -- Identity (immutable for a card's lifetime). villain '' for RFI so the
    -- unique key stays NOT NULL-clean.
    hand                text not null,
    position            text not null,
    spot                text not null,
    villain             text not null default '',
    correct_strategy    jsonb not null default '{}'::jsonb,  -- {"open":0.7,"fold":0.3}

    -- SM-2 state (current production scheduler).
    ease_factor         real not null default 2.5,
    interval_days       int  not null default 0,   -- 0 = new card
    next_review         date,
    last_seen           date,
    consecutive_correct int  not null default 0,
    total_seen          int  not null default 0,
    total_correct       int  not null default 0,

    -- FSRS-6 state (Track A.4). Nullable now so the rollout needs NO migration
    -- later — we just start populating these when FSRS-lite goes live.
    stability           real,
    difficulty          real,

    unique (user_id, pack, hand, position, spot, villain)
);

-- Due-card scheduling lookup.
create index if not exists cards_user_pack_due on cards (user_id, pack, next_review);

-- ----------------------------------------------------------------------------
-- goals — the flexible "training plan".
-- ----------------------------------------------------------------------------
-- A goal is a target on a (mode, optional scope) over a period. NULL scope
-- columns mean "any" — so a goal can be as broad as "drill / any / 200 a day"
-- or as narrow as "drill / RFI / UTG / 100 a day". Both the user's example
-- ("100 opens per RFI position") and a cumulative course are expressible.
create table if not exists goals (
    id         bigint generated always as identity primary key,
    user_id    uuid not null,                       -- -> profiles(id)
    mode       text not null check (mode in ('drill', 'learn')),

    -- Scope: NULL = "any / aggregate".
    pack       text,
    spot       text,
    position   text,
    villain    text,

    -- 'daily' resets each day and feeds streaks; 'total' is a cumulative course.
    period     text not null check (period in ('daily', 'total')),
    -- What to count. 'hands' = answers; 'correct' = correct answers;
    -- 'new_cards' = cards seen for the first time (the FSRS-aware lever for
    -- learn, where you cannot force more reviews than are due).
    metric     text not null default 'hands'
               check (metric in ('hands', 'correct', 'new_cards')),
    target     int  not null check (target > 0),
    active     boolean     not null default true,
    created_at timestamptz not null default now()
);

create index if not exists goals_user on goals (user_id, active);

-- ============================================================================
-- Derived views — everything below is computed FROM `answers` (+ profiles).
-- These are the building blocks for the dashboard and the stats/history compat.
-- ============================================================================

-- Per-day activity per user/mode, bucketed in the user's local timezone.
create or replace view v_daily_activity as
select
    a.user_id,
    a.mode,
    (a.ts at time zone p.timezone)::date                              as day,
    count(*)                                                          as hands,
    count(*) filter (where a.correct)                                as correct,
    round(100.0 * count(*) filter (where a.correct) / count(*), 1)   as accuracy
from answers a
join profiles p on p.id = a.user_id
group by a.user_id, a.mode, (a.ts at time zone p.timezone)::date;

-- Days that QUALIFY as a real training (anti-farm): total hands that day
-- (across both modes) >= the user's session_min_hands. This is what colours
-- the calendar "trained" and what streaks are built from — one stray hand
-- does not light up the day.
create or replace view v_session_days as
select
    a.user_id,
    (a.ts at time zone p.timezone)::date as day,
    count(*)                             as hands
from answers a
join profiles p on p.id = a.user_id
group by a.user_id, (a.ts at time zone p.timezone)::date, p.session_min_hands
having count(*) >= p.session_min_hands;

-- Streaks over qualified days (gaps-and-islands). longest_streak is exact;
-- current_streak uses the server's current_date and so is only correct when
-- the server runs in the user's timezone — for a precise per-user value pass
-- the user's local "today" via the parameterized query in db/queries.sql.
create or replace view v_streaks as
with d as (
    select
        user_id,
        day,
        day - (row_number() over (partition by user_id order by day))::int as grp
    from v_session_days
),
runs as (
    select user_id, grp, count(*) as len, min(day) as start_day, max(day) as end_day
    from d
    group by user_id, grp
)
select
    user_id,
    coalesce(max(len) filter (where end_day >= current_date - 1), 0) as current_streak,
    coalesce(max(len), 0)                                            as longest_streak
from runs
group by user_id;

-- Backward-compat: reproduce the old stats.json shape (spot -> key -> counts).
-- key = 'UTG' for RFI, 'BTN_vs_MP' for vs-spots — matches the legacy format.
create or replace view v_stats as
select
    user_id,
    spot,
    case when villain is null then position else position || '_vs_' || villain end as key,
    count(*) filter (where correct)    as correct,
    count(*)                           as total,
    count(*) filter (where is_timeout) as timeouts
from answers
group by
    user_id,
    spot,
    case when villain is null then position else position || '_vs_' || villain end;
