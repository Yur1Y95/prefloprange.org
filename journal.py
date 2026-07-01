"""Answer journal — the single write-path into the `answers` event log.

Track D, D.1-api-write. Both trainers (Drill and Learn) append one row per
answered hand here. This is the in-DB successor to stats.json + history.json:
every metric the product will show (daily activity, accuracy, streaks, goal
progress) is a QUERY over this journal — see db/queries.sql.

Design (why it is shaped this way):
  * ONE place writes to `answers` (`record_answer`). The two trainers only
    provide their own field mapping via the pure helpers `drill_answer_row` /
    `learn_answer_row`, which are trivial to unit-test without a database.
  * BEST-EFFORT, never fatal. If DATABASE_URL is unset, `db.get_pool()` returns
    None and we no-op (the app keeps working on JSON exactly as before — the
    mandated soft degradation). If the INSERT fails, the error is logged and
    swallowed so a flaky database can never break a training session. JSON
    persistence in the endpoints is the source of truth for the UI right now;
    this journal is populated in parallel until the read path moves to the DB.
  * SQL placeholders are psycopg3 style `%(name)s`. The `:name` form in
    db/queries.sql is the human-readable cookbook; this module is the runtime
    mirror of its section 0 (the write path).

Security: the database URL/password lives only in the environment (read inside
db.py). Nothing here logs connection details.
"""
from __future__ import annotations

import logging
import os
import uuid

import db

log = logging.getLogger("journal")

# ---------------------------------------------------------------------------
# Who owns these answers (until auth lands in D.2).
# ---------------------------------------------------------------------------
# There is no login yet, so every row is attributed to one fixed development
# user. `answers.user_id` has NO foreign key, so this works without a matching
# profiles/auth row. When real auth arrives (D.2), the user's id replaces this.
# Overridable via env so a tester can pick their own id without code changes.
_DEFAULT_DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def _resolve_dev_user_id() -> uuid.UUID:
    raw = os.environ.get("DEV_USER_ID", _DEFAULT_DEV_USER_ID)
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        log.warning("DEV_USER_ID %r is not a valid UUID; using the default.", raw)
        return uuid.UUID(_DEFAULT_DEV_USER_ID)


DEV_USER_ID = _resolve_dev_user_id()


# ---------------------------------------------------------------------------
# The INSERT — mirrors section 0 of db/queries.sql, in psycopg3 placeholders.
# ---------------------------------------------------------------------------
_INSERT_ANSWER = """
insert into answers
    (user_id, mode, pack, spot, position, villain, hand,
     action, correct, is_timeout, revealed, rating, ev, correct_action, card_id)
values
    (%(user_id)s, %(mode)s, %(pack)s, %(spot)s, %(position)s, %(villain)s, %(hand)s,
     %(action)s, %(correct)s, %(is_timeout)s, %(revealed)s, %(rating)s, %(ev)s,
     %(correct_action)s, %(card_id)s)
"""

# Columns the DB requires to be present and non-null. We default a missing pack
# (e.g. a stale browser tab posting a pre-D.1 drill_hand) rather than drop the
# row to a NOT NULL violation.
_UNKNOWN_PACK = "(unknown)"


def _stem(name) -> str:
    """Normalize a range-file reference to its bare stem (the pack identity).

    'GTOWNL10.json' -> 'GTOWNL10';  'GTOWNL10' -> 'GTOWNL10';  None -> '(unknown)'.
    """
    if not name:
        return _UNKNOWN_PACK
    return name[:-5] if name.endswith(".json") else name


# ---------------------------------------------------------------------------
# Pure field mappings: trainer payload -> one journal row. No DB, no I/O.
# ---------------------------------------------------------------------------

def drill_answer_row(drill_hand: dict, result: dict, *, user_id: uuid.UUID | None = None) -> dict:
    """Build a journal row from a Drill hand + its check_answer() result.

    Notes on the non-obvious fields:
      * villain  -> None for RFI (drill_hand['villain_position'] is None there).
      * action   -> None on a timeout (the player made no choice; result's
                    'player_action' is the sentinel 'timeout' in that case).
      * rating / card_id -> None: those are Learn-only (SM-2 grade, SRS card).
      * ev       -> the real number from check_answer (already None unless a
                    correct non-fold action with EV data); no synthetic values.
    """
    is_timeout = bool(result.get("is_timeout"))
    return {
        "user_id":        user_id or DEV_USER_ID,
        "mode":           "drill",
        "pack":           _stem(drill_hand.get("pack")),
        "spot":           drill_hand.get("spot"),
        "position":       drill_hand.get("hero_position"),
        "villain":        drill_hand.get("villain_position") or None,
        "hand":           drill_hand.get("hand"),
        "action":         None if is_timeout else result.get("player_action"),
        "correct":        bool(result.get("correct")),
        "is_timeout":     is_timeout,
        "revealed":       False,
        "rating":         None,
        "ev":             result.get("ev"),
        "correct_action": result.get("correct_action"),
        "card_id":        None,
    }


def learn_answer_row(card, *, pack: str, user_action: str, rating: int,
                     in_strategy: bool, revealed: bool,
                     user_id: uuid.UUID | None = None) -> dict:
    """Build a journal row from a Learn (SRS) answer.

    Notes on the non-obvious fields:
      * villain  -> None for RFI (card.villain_position is '' there).
      * action   -> None when the user pressed "Показать ответ" (revealed) or
                    made no real choice; otherwise the action they picked.
      * correct  -> in_strategy (already False on a reveal, set by srs_api).
      * ev       -> None: Learn does not compute EV (the deck has no range file
                    loaded). EV stays a Drill feature for now.
      * correct_action -> the dominant line of the card's strategy (review UI).
    """
    return {
        "user_id":        user_id or DEV_USER_ID,
        "mode":           "learn",
        "pack":           _stem(pack),
        "spot":           card.spot,
        "position":       card.position,
        "villain":        card.villain_position or None,
        "hand":           card.hand,
        "action":         None if (revealed or not user_action) else user_action,
        "correct":        bool(in_strategy),
        "is_timeout":     False,
        "revealed":       bool(revealed),
        "rating":         int(rating),
        "ev":             None,
        "correct_action": card.dominant_action(),
        "card_id":        card.card_id,
    }


# ---------------------------------------------------------------------------
# The one write. Best-effort: returns True on a committed insert, False on a
# no-op (DB not configured) or a swallowed failure. Never raises.
# ---------------------------------------------------------------------------

def record_answer(row: dict) -> bool:
    # Acquiring the pool can itself raise (e.g. DATABASE_URL is set but the
    # psycopg driver isn't installed) — that must NOT break a training session,
    # so it is inside the guard too.
    try:
        pool = db.get_pool()
    except Exception as e:
        log.warning("journal: pool unavailable (%s: %s)", type(e).__name__, e)
        return False
    if pool is None:
        # No DATABASE_URL — soft degradation. The endpoint's JSON write already
        # persisted this answer; the journal simply isn't active yet.
        return False
    try:
        # Short timeout: a slow/unreachable DB must not stall the answer flow.
        with pool.connection(timeout=5) as conn:
            conn.execute(_INSERT_ANSWER, row)
            conn.commit()
        return True
    except Exception as e:
        # Swallow: a journal failure is never worth breaking training over.
        # Log type+message only (psycopg does not put the password in these).
        log.warning("journal insert failed (%s: %s)", type(e).__name__, e)
        return False


# ---------------------------------------------------------------------------
# Thin adapters the endpoints call (keeps main.py / srs_api.py edits to 1 line).
# ---------------------------------------------------------------------------

def record_drill_answer(drill_hand: dict, result: dict,
                        user_id: uuid.UUID | None = None) -> bool:
    # user_id from the request's JWT (D.2). None -> DEV_USER_ID inside the row
    # builder, so JSON mode / unauthenticated dev keeps the old behaviour.
    return record_answer(drill_answer_row(drill_hand, result, user_id=user_id))


def record_learn_answer(card, *, pack: str, user_action: str, rating: int,
                        in_strategy: bool, revealed: bool,
                        user_id: uuid.UUID | None = None) -> bool:
    return record_answer(learn_answer_row(
        card, pack=pack, user_action=user_action, rating=rating,
        in_strategy=in_strategy, revealed=revealed, user_id=user_id,
    ))
