"""SRS deck store — persistence for Learn-mode card *state*.

Track D, D.1-api-cards. This is the single place that knows WHERE the SRS
scheduling state ("what to show next") lives: a per-pack JSON file today, the
Postgres ``cards`` table when a database is configured.

Design (mirrors journal.py — "one module, one job"):
  * srs.py owns the SM-2 MATH and the ``Card`` model and is left untouched.
    This module only loads and saves Cards.
  * SOURCE OF TRUTH is selected by configuration (decision 2026-06-22):
      - DATABASE_URL set   -> Postgres ``cards`` is authoritative. JSON files
        are neither read nor written for Learn state.
      - DATABASE_URL unset -> the JSON files (srs_state/<pack>.srs.json) are
        authoritative, exactly as before. This is the mandated soft
        degradation: the current prod (which has no DATABASE_URL) keeps
        behaving byte-for-byte as it used to.
  * Unlike journal.py — an append-only LOG that is best-effort and swallows
    failures — ``cards`` is STATE. When the DB is the source of truth a failed
    write must NOT be swallowed: silently losing a card's new schedule would
    corrupt the user's progress. So DB errors here PROPAGATE; the endpoint
    surfaces a 500 rather than pretending the rep was saved.

The ``history[]`` array a JSON Card carries is intentionally NOT stored in the
``cards`` table (db_schema.md §3.1): those per-review events live in the
``answers`` journal. A card's history = ``SELECT ... FROM answers WHERE
card_id = ...``. SM-2 scheduling never reads ``history`` (only writes it), so
dropping it from the state table does not change any scheduling decision.

Security: the database URL/password is read only from the environment (inside
db.py). Nothing here logs connection details.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import db
import srs
# Reuse the one dev-user identity until real auth lands (D.2). Keeping a single
# source for it means the journal (`answers`) and the deck (`cards`) always
# agree on whose rows these are. `cards.user_id` has no FK, so a row loads fine
# without a matching profiles/auth row.
from journal import DEV_USER_ID


# ---------------------------------------------------------------------------
# Pure conversions: Card <-> a DB row dict. No I/O, trivially unit-testable.
# ---------------------------------------------------------------------------
# The column order the INSERT/UPSERT bind against.
_COLUMNS = (
    "user_id", "pack", "hand", "position", "spot", "villain", "correct_strategy",
    "ease_factor", "interval_days", "next_review", "last_seen",
    "consecutive_correct", "total_seen", "total_correct", "stability", "difficulty",
)


def _date_to_db(iso: str):
    """Card ISO-date string -> a ``date`` (or ``None`` for new/empty).

    Cards store ``next_review``/``last_seen`` as ISO strings, with ``''`` for a
    never-reviewed card. The DB columns are nullable ``date``; ``''`` maps to
    ``NULL``.
    """
    return date.fromisoformat(iso) if iso else None


def _date_from_db(value) -> str:
    """A DB date (or ``None``) -> Card's ISO string (``''`` for new/NULL).

    Keeping the empty-string convention matters: ``Card.is_new`` and
    ``get_due_cards`` test ``next_review``/``last_seen`` for truthiness, and an
    empty string is the "new card" sentinel. A ``None`` here would change the
    dataclass's declared ``str`` type, so we normalise back to ``''``.
    """
    if value is None:
        return ""
    # ``date`` from psycopg has .isoformat(); a sqlite/test value may be str.
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _card_to_row(card: srs.Card, *, pack: str, user_id=DEV_USER_ID) -> dict:
    """Card -> a plain row dict (strategy stays a dict; dates become date/None).

    The strategy is left as a plain ``dict`` so this function has no psycopg
    dependency; the jsonb wrapping happens at execution time in ``_bind``.
    ``stability``/``difficulty`` are FSRS-only columns with no Card field yet,
    so they are written ``NULL``.
    """
    return {
        "user_id":             str(user_id),
        "pack":                pack,
        "hand":                card.hand,
        "position":            card.position,
        "spot":                card.spot,
        "villain":             card.villain_position or "",
        "correct_strategy":    dict(card.correct_strategy),
        "ease_factor":         card.ease_factor,
        "interval_days":       card.interval_days,
        "next_review":         _date_to_db(card.next_review),
        "last_seen":           _date_to_db(card.last_seen),
        "consecutive_correct": card.consecutive_correct,
        "total_seen":          card.total_seen,
        "total_correct":       card.total_correct,
        "stability":           None,
        "difficulty":          None,
    }


def _row_to_card(row) -> srs.Card:
    """A DB row (dict keyed by column name) -> a Card.

    ``history`` is reconstructed as empty: it is not stored here (it lives in
    ``answers``), and SM-2 never reads it. ``correct_strategy`` arrives as a
    dict from psycopg's jsonb loader; a JSON-text fallback covers sqlite/tests.
    """
    strat = row["correct_strategy"]
    if isinstance(strat, str):
        import json
        strat = json.loads(strat)
    return srs.Card(
        hand=row["hand"],
        position=row["position"],
        spot=row["spot"],
        villain_position=row["villain"] or "",
        correct_strategy=dict(strat) if strat else {},
        ease_factor=row["ease_factor"],
        interval_days=row["interval_days"],
        next_review=_date_from_db(row["next_review"]),
        last_seen=_date_from_db(row["last_seen"]),
        consecutive_correct=row["consecutive_correct"],
        total_seen=row["total_seen"],
        total_correct=row["total_correct"],
        history=[],
    )


# ---------------------------------------------------------------------------
# SQL — placeholders are psycopg3 ``%(name)s`` style.
# ---------------------------------------------------------------------------
_INSERT = (
    "insert into cards (" + ", ".join(_COLUMNS) + ") "
    "values (" + ", ".join("%(" + c + ")s" for c in _COLUMNS) + ")"
)

# /answer and /upgrade_easy persist ONE mutated card. The card already exists
# (created at /init), so the conflict path runs and refreshes the mutable SM-2
# columns; identity columns never change.
_UPSERT = _INSERT + """
on conflict (user_id, pack, hand, position, spot, villain) do update set
    correct_strategy    = excluded.correct_strategy,
    ease_factor         = excluded.ease_factor,
    interval_days       = excluded.interval_days,
    next_review         = excluded.next_review,
    last_seen           = excluded.last_seen,
    consecutive_correct = excluded.consecutive_correct,
    total_seen          = excluded.total_seen,
    total_correct       = excluded.total_correct,
    stability           = excluded.stability,
    difficulty          = excluded.difficulty
"""

# ORDER BY id reproduces insertion order (= init_cards_from_spots order, the
# deck order JSON had), so /next is deterministic across loads. Scheduling does
# not depend on it (new cards are md5-shuffled, reviews are all due), but a
# stable order keeps behaviour reproducible.
_SELECT = """
select hand, position, spot, villain, correct_strategy,
       ease_factor, interval_days, next_review, last_seen,
       consecutive_correct, total_seen, total_correct
from cards
where user_id = %(user_id)s and pack = %(pack)s
order by id
"""

_EXISTS = "select 1 from cards where user_id = %(user_id)s and pack = %(pack)s limit 1"
_DELETE = "delete from cards where user_id = %(user_id)s and pack = %(pack)s"


def _bind(row: dict) -> dict:
    """Wrap the strategy dict as jsonb just before execution (DB branch only)."""
    from psycopg.types.json import Jsonb
    out = dict(row)
    out["correct_strategy"] = Jsonb(out["correct_strategy"])
    return out


def _scope(pack: str, user_id=DEV_USER_ID) -> dict:
    return {"user_id": str(user_id), "pack": pack}


def _ensure_parent(json_path) -> None:
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Public store API. Each takes (pack, json_path, user_id): ``pack`` + ``user_id``
# key the DB rows (``user_id`` from the request's JWT — D.2; defaults to the dev
# user so JSON mode and unauthenticated callers behave exactly as before).
# ``json_path`` is the safe-resolved JSON file the caller already computed
# (used only by the JSON branch, ignored by the DB branch).
# ---------------------------------------------------------------------------

def deck_exists(pack: str, json_path, user_id=DEV_USER_ID) -> bool:
    """Is a deck initialized for this pack? (the /status and /init 409 gate)."""
    pool = db.get_pool()
    if pool is None:
        return os.path.exists(json_path)
    with pool.connection(timeout=10) as conn:
        row = conn.execute(_EXISTS, _scope(pack, user_id)).fetchone()
    return row is not None


def load_deck(pack: str, json_path, user_id=DEV_USER_ID) -> list[srs.Card]:
    """Load the whole deck (used by /status, /next, /answer, /summary, ...)."""
    pool = db.get_pool()
    if pool is None:
        return srs.load_state(json_path)
    from psycopg.rows import dict_row
    with pool.connection(timeout=15) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT, _scope(pack, user_id))
            rows = cur.fetchall()
    return [_row_to_card(r) for r in rows]


def replace_deck(pack: str, json_path, cards: list[srs.Card], user_id=DEV_USER_ID) -> None:
    """Wholesale write of a fresh deck (used by /init). DB: delete + bulk insert.

    DELETE-then-INSERT (not upsert-all) so a re-init with a *narrower* scope
    cannot leave orphaned rows from the previous, wider deck.
    """
    pool = db.get_pool()
    if pool is None:
        _ensure_parent(json_path)
        srs.save_state(cards, json_path)
        return
    params = [_bind(_card_to_row(c, pack=pack, user_id=user_id)) for c in cards]
    with pool.connection(timeout=30) as conn:
        conn.execute(_DELETE, _scope(pack, user_id))
        if params:
            with conn.cursor() as cur:
                cur.executemany(_INSERT, params)
        conn.commit()


def save_card(pack: str, json_path, card: srs.Card, deck: list[srs.Card],
              user_id=DEV_USER_ID) -> None:
    """Persist ONE mutated card (used by /answer, /upgrade_easy).

    DB branch upserts just ``card`` (cheap — no ~1800-row rewrite). JSON branch
    rewrites the whole file from ``deck``, which is exactly the old behaviour
    (``card`` is an element of ``deck``).
    """
    pool = db.get_pool()
    if pool is None:
        _ensure_parent(json_path)
        srs.save_state(deck, json_path)
        return
    with pool.connection(timeout=10) as conn:
        conn.execute(_UPSERT, _bind(_card_to_row(card, pack=pack, user_id=user_id)))
        conn.commit()


def delete_deck(pack: str, json_path, user_id=DEV_USER_ID) -> None:
    """Wipe a pack's deck (used by /reset)."""
    pool = db.get_pool()
    if pool is None:
        if os.path.exists(json_path):
            os.remove(json_path)
        return
    with pool.connection(timeout=10) as conn:
        conn.execute(_DELETE, _scope(pack, user_id))
        conn.commit()
