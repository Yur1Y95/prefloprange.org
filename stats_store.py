"""Stats/History read store — Track D, D.1-api-reads.

Single responsibility: serve the Drill Stats/History panel from EITHER the
Postgres ``answers`` journal (when DATABASE_URL is set) or the legacy JSON files
(``stats.json`` / ``history.json``) otherwise. READ-ONLY — the write path
(``submit_answer`` in main.py) and the JSON write helpers there are untouched.

Design (mirrors cards_store.py — "one module, one job"):
  * SOURCE OF TRUTH selected by configuration, symmetric with cards_store and
    the rest of the DB layer:
      - DATABASE_URL set   -> read from the ``answers`` journal (the DB is
        authoritative for what the panel shows).
      - DATABASE_URL unset -> read the JSON files exactly as before. This is the
        mandated soft degradation: the current prod (no DATABASE_URL) keeps
        behaving byte-for-byte as it used to.
  * DRILL ONLY. This panel lives in the Practice tab and has always shown only
    Drill answers, so every DB query filters ``mode = 'drill'``. (The general
    ``v_stats`` view in db/schema.sql is mode-agnostic — using it here would mix
    Learn answers into the Drill panel. ``v_stats`` is left for a future
    combined / Learn stats screen, which is a separate chat.)
  * Pure conversion helpers (``_nest_stats``, ``_history_entry``, ``_fmt_ts``)
    carry all the shape logic and are unit-tested without a database.
  * SQL placeholders are psycopg3 ``%(name)s`` style (matches journal.py /
    cards_store.py). db/queries.sql section 6 is the human-readable cookbook;
    the only deviation here is the explicit ``mode = 'drill'`` filter.

Security: the database URL/password is read only from the environment (inside
db.py). Nothing here logs connection details.
"""
from __future__ import annotations

import json
import os

import db
# One dev user until auth lands (D.2) — the SAME id the journal writes under, so
# reads line up with writes. Imported from journal to keep a single source.
from journal import DEV_USER_ID


# Mirror main._SPOT_DEFAULTS so the response always carries every known spot key
# (the frontend iterates spots; an empty spot simply yields no rows). Kept here
# too rather than imported, because main.py imports THIS module — importing it
# back would be a circular import.
_SPOT_DEFAULTS = ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso")

# Sane ceiling for the DB history query. The JSON path was implicitly capped at
# 200 (HISTORY_MAX on write); the DB can serve more cheaply and history now
# carries real dates, so we allow a bit more but never an unbounded scan.
_HISTORY_MAX = 500


# ---------------------------------------------------------------------------
# Pure conversions: DB rows -> the shapes the frontend already renders. No I/O.
# ---------------------------------------------------------------------------

def _nest_stats(rows) -> dict:
    """Flat ``(spot, key, correct, total, timeouts)`` rows -> the nested
    ``{spot: {key: {correct, total, timeouts}}}`` shape stats.json used.

    Seeds every known spot first so the response shape is stable regardless of
    which spots have data; the frontend tolerates empty spots (it renders no
    rows for them). ``key`` is ``'UTG'`` for RFI or ``'BTN_vs_MP'`` for vs-spots,
    exactly the legacy format (see the CASE in the SQL below).
    """
    out = {spot: {} for spot in _SPOT_DEFAULTS}
    for r in rows:
        out.setdefault(r["spot"], {})[r["key"]] = {
            "correct":  int(r["correct"]),
            "total":    int(r["total"]),
            "timeouts": int(r["timeouts"]),
        }
    return out


def _fmt_ts(value) -> str:
    """A journal ``ts`` -> a ``'YYYY-MM-DD HH:MM'`` display string.

    The DB returns a tz-aware datetime (UTC); we render date + time so the
    History panel finally carries a date (the whole reason for the journal).
    Precise per-user timezone display is a dashboard-chat concern
    (profiles.timezone); for now this is UTC. A ``str`` input (sqlite/tests)
    is normalised (drop the 'T', trim to minutes); ``None`` -> ``''``.
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16].replace("T", " ")


def _history_entry(row) -> dict:
    """A journal row -> the history entry shape ``drill.js`` renders.

    Field remap to the legacy keys the frontend reads:
      position -> hero_position, villain -> villain_position, action ->
      player_action.

    Two journal facts the panel must accommodate:
      * The two dealt cards (``card1``/``card2``) were never journaled — only the
        hand notation (``'AKs'``). We return them empty; ``drill.js`` falls back
        to ``e.hand`` when ``card1`` is absent.
      * On a timeout the journal stored ``action = NULL``; restore the
        ``'timeout'`` sentinel so the player-action badge matches JSON mode.
    """
    is_timeout = bool(row["is_timeout"])
    action = row["action"]
    if is_timeout and not action:
        action = "timeout"
    return {
        "ts":               _fmt_ts(row["ts"]),
        "spot":             row["spot"],
        "hero_position":    row["position"],
        "villain_position": row["villain"],   # None for RFI
        "hand":             row["hand"],
        "card1":            "",                # not journaled -> drill.js shows e.hand
        "card2":            "",
        "correct_action":   row["correct_action"] or "",
        "player_action":    action or "",
        "correct":          bool(row["correct"]),
        "ev":               row["ev"],
        "is_timeout":       is_timeout,
    }


# ---------------------------------------------------------------------------
# SQL — psycopg3 ``%(name)s`` placeholders. Mirrors db/queries.sql section 6
# but adds the explicit ``mode = 'drill'`` scope (the Drill panel is drill-only).
# ---------------------------------------------------------------------------
_STATS_SQL = """
select spot,
       case when villain is null then position
            else position || '_vs_' || villain end as key,
       count(*) filter (where correct)    as correct,
       count(*)                            as total,
       count(*) filter (where is_timeout) as timeouts
from answers
where user_id = %(user_id)s and mode = 'drill'
group by spot,
         case when villain is null then position
              else position || '_vs_' || villain end
"""

_HISTORY_SQL = """
select ts, spot, position, villain, hand,
       action, correct_action, correct, ev, is_timeout
from answers
where user_id = %(user_id)s and mode = 'drill'
order by ts desc
limit %(limit)s
"""


# ---------------------------------------------------------------------------
# JSON branch — the legacy file readers (used when DATABASE_URL is unset). These
# reproduce main.load_stats / main.load_history exactly; kept here (not imported)
# to avoid a circular import with main.
# ---------------------------------------------------------------------------

def _read_stats_json(stats_file) -> dict:
    out = {spot: {} for spot in _SPOT_DEFAULTS}
    if os.path.exists(stats_file):
        with open(stats_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for spot, keys in data.items():
            out.setdefault(spot, {}).update(keys)
    return out


def _read_history_json(history_file, limit) -> list:
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            return json.load(f)[:limit]
    return []


# ---------------------------------------------------------------------------
# Public read API. Each takes the legacy JSON path the caller already knows
# (used only by the JSON branch, ignored by the DB branch). DB errors propagate
# (like cards_store) — a configured-but-broken DB is a real error to surface;
# the frontend's loadStats/loadHistory swallow it so the panel just doesn't
# update (no crash).
# ---------------------------------------------------------------------------

def read_stats(stats_file, user_id=DEV_USER_ID) -> dict:
    """Stats panel data: ``{spot: {key: {correct, total, timeouts}}}``.

    ``user_id`` comes from the request's JWT (D.2); defaults to the dev user so
    JSON mode (where it is ignored) and unauthenticated callers are unchanged.
    """
    pool = db.get_pool()
    if pool is None:
        return _read_stats_json(stats_file)
    from psycopg.rows import dict_row
    with pool.connection(timeout=10) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_STATS_SQL, {"user_id": str(user_id)})
            rows = cur.fetchall()
    return _nest_stats(rows)


def read_history(history_file, limit, user_id=DEV_USER_ID) -> list:
    """Recent Drill answers, newest first — the History panel feed."""
    limit = max(1, min(int(limit), _HISTORY_MAX))
    pool = db.get_pool()
    if pool is None:
        return _read_history_json(history_file, limit)
    from psycopg.rows import dict_row
    with pool.connection(timeout=10) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_HISTORY_SQL, {"user_id": str(user_id), "limit": limit})
            rows = cur.fetchall()
    return [_history_entry(r) for r in rows]
