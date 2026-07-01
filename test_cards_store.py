"""
Unit tests for cards_store.py — the Learn-deck persistence layer.

Stdlib only (no psycopg, no fastapi), so it runs in the Cowork sandbox like
test_srs.py. Two things are covered:

  1. The pure Card <-> row conversions (the bug-prone part: '' <-> NULL dates,
     dict <-> jsonb strategy, and the deliberate dropping of history[]).
  2. The JSON branch end-to-end, which is the exact contract srs_api depends on
     when DATABASE_URL is unset (the mandated soft degradation / current prod).

The DB branch is not exercised here (no Postgres/driver in the sandbox); its
SQL is verified live by the user. But because both branches funnel through the
same pure conversions, those conversions ARE tested here.

Run:  python3 test_cards_store.py
"""

import os
import tempfile

# Guarantee the JSON branch: a stray local .env with DATABASE_URL must not make
# these tests reach into a real database. db.get_pool() is None without it.
os.environ.pop("DATABASE_URL", None)

import srs
import db
import cards_store


# ---------------------------------------------------------------------------
# Pure conversions
# ---------------------------------------------------------------------------

def test_db_not_configured_in_sandbox():
    """Sanity: with no DATABASE_URL the store uses the JSON branch."""
    assert db.get_pool() is None
    assert db.database_configured() is False
    print("  PASS  no DATABASE_URL -> JSON branch active")


def test_new_card_round_trips_with_blank_dates():
    """A never-reviewed card: blank ISO dates -> NULL -> blank again, and the
    whole Card compares equal (history is [] on both sides)."""
    c = srs._make_card("AA", "UTG", "RFI", "", {"open": 1.0})
    assert c.next_review == "" and c.last_seen == ""
    row = cards_store._card_to_row(c, pack="P")
    assert row["next_review"] is None and row["last_seen"] is None
    assert row["villain"] == ""
    back = cards_store._row_to_card(row)
    assert back == c, f"{back!r} != {c!r}"
    print("  PASS  new card round-trips (blank dates -> NULL -> blank)")


def test_reviewed_card_round_trips_dates_and_drops_history():
    """A reviewed card keeps its schedule fields but its history is NOT stored
    (it lives in `answers`)."""
    from datetime import date
    c = srs._make_card("A5s", "UTG", "RFI", "", {"open": 0.7})  # mixed -> fold 0.3
    srs.update_card(c, srs.GOOD, today=date(2026, 6, 22))
    assert c.last_seen == "2026-06-22" and c.next_review == "2026-06-23"
    assert len(c.history) == 1                      # update logged one event

    row = cards_store._card_to_row(c, pack="P")
    assert row["last_seen"] == date(2026, 6, 22)
    assert row["next_review"] == date(2026, 6, 23)

    back = cards_store._row_to_card(row)
    # Scheduling/state fields preserved exactly...
    for fld in ("hand", "position", "spot", "villain_position", "correct_strategy",
                "ease_factor", "interval_days", "next_review", "last_seen",
                "consecutive_correct", "total_seen", "total_correct"):
        assert getattr(back, fld) == getattr(c, fld), f"field {fld} differs"
    # ...but history is intentionally dropped on the way through the table.
    assert back.history == []
    print("  PASS  reviewed card round-trips schedule; history dropped (lives in answers)")


def test_vs_spot_villain_and_mixed_strategy_round_trip():
    """villain populated + a mixed multi-action strategy survives the trip."""
    c = srs._make_card("AKs", "SB", "vs_RFI", "UTG", {"call": 0.4, "3bet": 0.6})
    row = cards_store._card_to_row(c, pack="GTOWNL10")
    assert row["villain"] == "UTG"
    assert row["correct_strategy"] == {"call": 0.4, "3bet": 0.6}
    back = cards_store._row_to_card(row)
    assert back == c
    print("  PASS  vs_RFI card: villain + mixed strategy round-trip")


def test_row_to_card_accepts_json_text_strategy():
    """jsonb arrives as a dict from psycopg, but a JSON-text value (sqlite/tests)
    is tolerated too."""
    c = srs._make_card("22", "BTN", "RFI", "", {"open": 1.0})
    row = cards_store._card_to_row(c, pack="P")
    row["correct_strategy"] = '{"open": 1.0}'      # simulate text-encoded jsonb
    back = cards_store._row_to_card(row)
    assert back.correct_strategy == {"open": 1.0}
    print("  PASS  _row_to_card tolerates JSON-text strategy")


# ---------------------------------------------------------------------------
# JSON branch end-to-end — the contract srs_api relies on under soft degradation
# ---------------------------------------------------------------------------

_SPOTS = {
    "RFI": {
        "UTG": {"AA": {"open": 1.0}, "A5s": {"open": 0.7}},
        "BTN": {"AA": {"open": 1.0}, "KK": {"open": 1.0}},
    }
}


def _fresh_paths():
    d = tempfile.mkdtemp(prefix="cards_store_test_")
    return os.path.join(d, "srs_state", "P.srs.json")


def test_json_exists_replace_load_delete_cycle():
    json_path = _fresh_paths()
    pack = "P"
    # exists() false before anything is written
    assert cards_store.deck_exists(pack, json_path) is False

    cards = srs.init_cards_from_spots(_SPOTS, scope=("RFI",))
    cards_store.replace_deck(pack, json_path, cards)
    assert os.path.exists(json_path)                       # file actually written
    assert cards_store.deck_exists(pack, json_path) is True

    loaded = cards_store.load_deck(pack, json_path)
    assert len(loaded) == len(cards)
    # A sampled card matches by identity + strategy
    aa = next(c for c in loaded if c.card_id == "AA__UTG__RFI")
    assert aa.correct_strategy == {"open": 1.0}

    cards_store.delete_deck(pack, json_path)
    assert cards_store.deck_exists(pack, json_path) is False
    print(f"  PASS  JSON cycle: exists/replace/load/delete ({len(cards)} cards)")


def test_json_save_card_persists_single_mutation():
    """Mirror /answer: load, mutate one card, save_card(deck), reload -> the
    mutation persisted and the rest of the deck is intact."""
    from datetime import date
    json_path = _fresh_paths()
    pack = "P"
    cards = srs.init_cards_from_spots(_SPOTS, scope=("RFI",))
    cards_store.replace_deck(pack, json_path, cards)

    deck = cards_store.load_deck(pack, json_path)
    target = next(c for c in deck if c.card_id == "AA__UTG__RFI")
    srs.update_card(target, srs.GOOD, today=date(2026, 6, 22))
    cards_store.save_card(pack, json_path, target, deck)   # whole deck rewritten in JSON mode

    reloaded = cards_store.load_deck(pack, json_path)
    again = next(c for c in reloaded if c.card_id == "AA__UTG__RFI")
    assert again.interval_days == 1 and again.next_review == "2026-06-23"
    assert again.total_seen == 1
    # An untouched card is still new
    other = next(c for c in reloaded if c.card_id == "KK__BTN__RFI")
    assert other.is_new()
    print("  PASS  JSON save_card persists one mutation, leaves the rest new")


def test_json_load_missing_deck_is_empty():
    json_path = _fresh_paths()
    assert cards_store.load_deck("P", json_path) == []
    print("  PASS  load_deck on a missing file returns []")


if __name__ == "__main__":
    import sys
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} FAILED")
        sys.exit(1)
    print(f"All {len(tests)} cards_store tests passed")
