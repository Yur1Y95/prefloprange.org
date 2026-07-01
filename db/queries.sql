-- ============================================================================
-- PreflopRange — query cookbook (Track D, Stage 0 / D.1)
-- Parameterized queries the API layer will run. Placeholders are :name style.
-- Pair with db/schema.sql. Rationale: docs/db_schema.md.
--
-- These are the concrete answers to the three features requested 2026-06-19:
--   (A) training plan / goals      -> sections 1-2
--   (B) honest session / anti-farm -> baked into v_session_days + section 5
--   (C) dashboard week/month       -> sections 3-4
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. THE WRITE PATH — append one event. (Both trainers call this.)
-- ----------------------------------------------------------------------------
-- Drill: rating/card_id NULL. Learn: rating set, card_id set, may be revealed.
insert into answers
    (user_id, mode, pack, spot, position, villain, hand,
     action, correct, is_timeout, revealed, rating, ev, correct_action, card_id)
values
    (:user_id, :mode, :pack, :spot, :position, :villain, :hand,
     :action, :correct, :is_timeout, :revealed, :rating, :ev, :correct_action, :card_id);

-- ----------------------------------------------------------------------------
-- 1. GOAL PROGRESS — generic (metric 'hands' or 'correct').
-- ----------------------------------------------------------------------------
-- One row per active goal with progress + whether it is met. For 'daily' goals
-- only today's (user-local) answers count; for 'total' the whole history counts.
select
    g.id, g.mode, g.pack, g.spot, g.position, g.villain,
    g.period, g.metric, g.target,
    coalesce(cnt.n, 0)              as progress,
    coalesce(cnt.n, 0) >= g.target  as met
from goals g
left join lateral (
    select count(*) as n
    from answers a
    join profiles p on p.id = a.user_id
    where a.user_id = g.user_id
      and a.mode    = g.mode
      and (g.pack     is null or a.pack     = g.pack)
      and (g.spot     is null or a.spot     = g.spot)
      and (g.position is null or a.position = g.position)
      and (g.villain  is null or a.villain  = g.villain)
      and (g.metric  <> 'correct' or a.correct)
      and (
            g.period = 'total'
            or (a.ts at time zone p.timezone)::date
               = (now() at time zone p.timezone)::date
          )
) cnt on true
where g.user_id = :user_id
  and g.active
  and g.metric in ('hands', 'correct');

-- ----------------------------------------------------------------------------
-- 2. GOAL PROGRESS — learn 'new_cards' (FSRS-aware lever).
-- ----------------------------------------------------------------------------
-- You cannot force more reviews than are due, so the learn daily goal counts
-- NEW cards introduced today = cards whose FIRST-EVER answer is today.
select
    g.id, g.spot, g.position, g.villain, g.target,
    coalesce(nc.n, 0)             as new_cards_today,
    coalesce(nc.n, 0) >= g.target as met
from goals g
left join lateral (
    select count(*) as n
    from (
        select a.card_id, min(a.ts) as first_ts
        from answers a
        where a.user_id = g.user_id
          and a.mode = 'learn'
          and (g.pack     is null or a.pack     = g.pack)
          and (g.spot     is null or a.spot     = g.spot)
          and (g.position is null or a.position = g.position)
          and (g.villain  is null or a.villain  = g.villain)
        group by a.card_id
    ) firsts
    join profiles p on p.id = g.user_id
    where (firsts.first_ts at time zone p.timezone)::date
        = (now() at time zone p.timezone)::date
) nc on true
where g.user_id = :user_id
  and g.active
  and g.mode = 'learn'
  and g.metric = 'new_cards';

-- ----------------------------------------------------------------------------
-- 3. CALENDAR HEATMAP — one row per day in a window, empty days included.
-- ----------------------------------------------------------------------------
-- `hands` = all answers that day (any volume); `trained` = qualified day
-- (>= session_min_hands) so the UI can colour "real training" vs "a few hands".
select
    d::date                         as day,
    coalesce(act.hands, 0)          as hands,
    coalesce(act.correct, 0)        as correct,
    (sd.day is not null)            as trained
from generate_series(:from_date::date, :to_date::date, interval '1 day') d
left join (
    select (a.ts at time zone p.timezone)::date as day,
           count(*) as hands,
           count(*) filter (where a.correct) as correct
    from answers a
    join profiles p on p.id = a.user_id
    where a.user_id = :user_id
    group by (a.ts at time zone p.timezone)::date
) act on act.day = d::date
left join v_session_days sd
       on sd.user_id = :user_id and sd.day = d::date
order by day;

-- ----------------------------------------------------------------------------
-- 4. BARS — per-day and per-week volume + accuracy (for the bar charts).
-- ----------------------------------------------------------------------------
-- 4a. Daily bars over a window:
select day, sum(hands) as hands,
       round(100.0 * sum(correct) / nullif(sum(hands), 0), 1) as accuracy
from v_daily_activity
where user_id = :user_id and day between :from_date and :to_date
group by day order by day;

-- 4b. Weekly bars (ISO week start) over a window:
select date_trunc('week', day)::date as week,
       sum(hands) as hands,
       round(100.0 * sum(correct) / nullif(sum(hands), 0), 1) as accuracy
from v_daily_activity
where user_id = :user_id and day between :from_date and :to_date
group by date_trunc('week', day) order by week;

-- ----------------------------------------------------------------------------
-- 5. STREAK + "trained today?" banner.
-- ----------------------------------------------------------------------------
-- 5a. Longest streak (exact, from the view):
select longest_streak from v_streaks where user_id = :user_id;

-- 5b. Current streak, precise in the user's timezone (pass :today as their
--     local date). Seed = the most recent qualified day among {today, yesterday}
--     (so an as-yet-untrained today does not break yesterday's streak), then
--     walk backwards counting consecutive qualified days. No rows => 0.
with recursive q as (
    select day from v_session_days where user_id = :user_id
),
seed as (
    select max(day) as d from q where day in (:today::date, :today::date - 1)
),
walk(d, n) as (
    select d, 1 from seed where d is not null
    union all
    select w.d - 1, w.n + 1 from walk w where (w.d - 1) in (select day from q)
)
select coalesce(max(n), 0) as current_streak from walk;
-- The same walk is trivial in app code (loop back from :today while the day is
-- in v_session_days); the verification harness implements that plain version.

-- 5c. Banner check — did the user train today (qualified)?
select exists (
    select 1 from v_session_days
    where user_id = :user_id
      and day = (now() at time zone (select timezone from profiles where id = :user_id))::date
) as trained_today;

-- ----------------------------------------------------------------------------
-- 6. STATS / HISTORY backward-compat (replace stats.json / history.json reads).
-- ----------------------------------------------------------------------------
-- 6a. Stats panel (old stats.json shape).
-- NOTE: v_stats is mode-AGNOSTIC (it aggregates drill + learn). The Drill panel
-- has always been drill-only, so stats_store.py does NOT use v_stats — it runs
-- the mode-scoped query in 6a' below. v_stats is kept for a future combined /
-- Learn stats screen.
select spot, key, correct, total, timeouts
from v_stats where user_id = :user_id order by spot, key;

-- 6a'. Drill-only stats (what stats_store.read_stats actually runs):
select spot,
       case when villain is null then position
            else position || '_vs_' || villain end as key,
       count(*) filter (where correct)    as correct,
       count(*)                            as total,
       count(*) filter (where is_timeout) as timeouts
from answers
where user_id = :user_id and mode = 'drill'
group by spot,
         case when villain is null then position
              else position || '_vs_' || villain end
order by spot, key;

-- 6b. Recent history (old history.json, but now properly dated).
-- The Drill History panel is drill-only, so stats_store.read_history adds
-- `and mode = 'drill'` (shown here). Drop that filter for a combined feed.
select ts, spot, position, villain, hand,
       action, correct_action, correct, ev, is_timeout
from answers
where user_id = :user_id and mode = 'drill'
order by ts desc
limit :limit;
