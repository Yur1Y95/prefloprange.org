"""Unit tests for journal.py — the answers write-path field mapping.

Pure tests: they exercise the trainer-payload -> journal-row mapping and the
"no database configured" no-op. No Postgres/psycopg needed, so they run in any
stdlib environment (the live INSERT is verified separately against Supabase).

Run:  python3 test_journal.py
"""
import os
import uuid

import journal
import srs


# The exact column set the INSERT binds. Every row builder MUST produce these
# keys (and only these), or psycopg would raise on a missing/extra placeholder.
EXPECTED_COLUMNS = {
    "user_id", "mode", "pack", "spot", "position", "villain", "hand",
    "action", "correct", "is_timeout", "revealed", "rating", "ev",
    "correct_action", "card_id",
}

_failures = []


def check(cond, msg):
    if not cond:
        _failures.append(msg)
        print(f"  FAIL: {msg}")


# ---------------------------------------------------------------------------
# Drill mapping
# ---------------------------------------------------------------------------

def test_drill_rfi_correct_open():
    dh = {"spot": "RFI", "hero_position": "UTG", "villain_position": None,
          "hand": "AA", "pack": "GTOWNL10.json"}
    result = {"correct": True, "player_action": "open",
              "correct_action": "open", "ev": 2.31, "is_timeout": False}
    row = journal.drill_answer_row(dh, result)

    check(set(row) == EXPECTED_COLUMNS, "drill row must have exactly the INSERT columns")
    check(row["mode"] == "drill", "drill mode")
    check(row["pack"] == "GTOWNL10", "pack stem stripped of .json")
    check(row["spot"] == "RFI", "spot")
    check(row["position"] == "UTG", "hero position")
    check(row["villain"] is None, "RFI villain -> None")
    check(row["hand"] == "AA", "hand")
    check(row["action"] == "open", "action")
    check(row["correct"] is True, "correct")
    check(row["is_timeout"] is False, "is_timeout")
    check(row["revealed"] is False, "drill never revealed")
    check(row["rating"] is None, "drill has no SM-2 rating")
    check(row["ev"] == 2.31, "ev passthrough")
    check(row["correct_action"] == "open", "correct_action")
    check(row["card_id"] is None, "drill has no card_id")
    check(row["user_id"] == journal.DEV_USER_ID, "dev user id")


def test_drill_timeout_has_no_action():
    dh = {"spot": "RFI", "hero_position": "MP", "villain_position": None,
          "hand": "72o", "pack": "GTOWNL10"}
    result = {"correct": False, "player_action": "timeout",
              "correct_action": "fold", "ev": None, "is_timeout": True}
    row = journal.drill_answer_row(dh, result)

    check(row["action"] is None, "timeout -> action None (no choice was made)")
    check(row["is_timeout"] is True, "timeout flag")
    check(row["correct"] is False, "timeout is wrong")
    check(row["ev"] is None, "timeout has no ev")


def test_drill_vs_rfi_keeps_villain():
    dh = {"spot": "vs_RFI", "hero_position": "BTN", "villain_position": "CO",
          "hand": "A5s", "pack": "GTOWNL10"}
    result = {"correct": True, "player_action": "3bet",
              "correct_action": "call", "ev": None, "is_timeout": False}
    row = journal.drill_answer_row(dh, result)

    check(row["villain"] == "CO", "vs_RFI keeps villain position")
    check(row["action"] == "3bet", "action 3bet")
    check(row["ev"] is None, "no ev data -> None")


def test_drill_correct_fold_no_ev():
    dh = {"spot": "RFI", "hero_position": "UTG", "villain_position": None,
          "hand": "Q4o", "pack": "GTOWNL10"}
    result = {"correct": True, "player_action": "fold",
              "correct_action": "fold", "ev": None, "is_timeout": False}
    row = journal.drill_answer_row(dh, result)

    check(row["action"] == "fold", "fold is a real action (not None)")
    check(row["correct"] is True, "correct fold")
    check(row["ev"] is None, "fold carries no ev")


def test_drill_missing_pack_defaults():
    dh = {"spot": "RFI", "hero_position": "UTG", "villain_position": None, "hand": "AA"}
    result = {"correct": True, "player_action": "open",
              "correct_action": "open", "ev": 2.31, "is_timeout": False}
    row = journal.drill_answer_row(dh, result)

    check(row["pack"] == "(unknown)", "missing pack -> '(unknown)', row still insertable")


# ---------------------------------------------------------------------------
# Learn mapping
# ---------------------------------------------------------------------------

def _mixed_vs_rfi_card():
    return srs.Card(hand="AKs", position="SB", spot="vs_RFI",
                    villain_position="UTG",
                    correct_strategy={"call": 0.6, "3bet": 0.4})


def test_learn_in_strategy_answer():
    card = _mixed_vs_rfi_card()
    row = journal.learn_answer_row(
        card, pack="GTOWNL10", user_action="3bet",
        rating=srs.GOOD, in_strategy=True, revealed=False,
    )

    check(set(row) == EXPECTED_COLUMNS, "learn row must have exactly the INSERT columns")
    check(row["mode"] == "learn", "learn mode")
    check(row["pack"] == "GTOWNL10", "pack")
    check(row["spot"] == "vs_RFI", "spot")
    check(row["position"] == "SB", "position")
    check(row["villain"] == "UTG", "villain")
    check(row["hand"] == "AKs", "hand")
    check(row["action"] == "3bet", "chosen action")
    check(row["correct"] is True, "in strategy -> correct")
    check(row["is_timeout"] is False, "learn never times out")
    check(row["revealed"] is False, "not revealed")
    check(row["rating"] == srs.GOOD, "SM-2 rating recorded")
    check(row["ev"] is None, "learn carries no ev (v1)")
    check(row["correct_action"] == "call", "dominant action 0.6 call > 0.4 3bet")
    check(row["card_id"] == "AKs__SB__vs_RFI__UTG", "card_id matches srs.Card.card_id")


def test_learn_rfi_villain_none():
    card = srs.Card(hand="AA", position="UTG", spot="RFI",
                    correct_strategy={"open": 1.0})
    row = journal.learn_answer_row(
        card, pack="GTOWNL10", user_action="open",
        rating=srs.GOOD, in_strategy=True, revealed=False,
    )
    check(row["villain"] is None, "RFI card (villain_position '') -> villain None")
    check(row["card_id"] == "AA__UTG__RFI", "RFI card_id has no villain segment")


def test_learn_reveal_is_again_no_action():
    card = _mixed_vs_rfi_card()
    row = journal.learn_answer_row(
        card, pack="GTOWNL10.json", user_action="",
        rating=srs.AGAIN, in_strategy=False, revealed=True,
    )
    check(row["revealed"] is True, "revealed flag set")
    check(row["correct"] is False, "reveal grades wrong")
    check(row["action"] is None, "reveal -> action None (user didn't choose)")
    check(row["rating"] == srs.AGAIN, "reveal rating is AGAIN")
    check(row["pack"] == "GTOWNL10", "pack stem stripped for learn too")


# ---------------------------------------------------------------------------
# record_answer — soft degradation when no DB is configured
# ---------------------------------------------------------------------------

def test_record_answer_noop_without_db():
    saved = os.environ.pop("DATABASE_URL", None)
    # The lazy pool may have been built in a prior call; reset it so the
    # "unconfigured" path is exercised cleanly.
    db_pool_was = getattr(__import__("db"), "_pool", None)
    import db
    db._pool = None
    try:
        row = journal.drill_answer_row(
            {"spot": "RFI", "hero_position": "UTG", "villain_position": None,
             "hand": "AA", "pack": "GTOWNL10"},
            {"correct": True, "player_action": "open",
             "correct_action": "open", "ev": 2.31, "is_timeout": False},
        )
        check(journal.record_answer(row) is False,
              "record_answer is a no-op (False) without DATABASE_URL, never raises")
        check(journal.record_drill_answer(
                  {"spot": "RFI", "hero_position": "UTG", "villain_position": None,
                   "hand": "AA", "pack": "GTOWNL10"},
                  {"correct": True, "player_action": "open",
                   "correct_action": "open", "ev": None, "is_timeout": False},
              ) is False, "record_drill_answer no-op without DB")
    finally:
        db._pool = db_pool_was
        if saved is not None:
            os.environ["DATABASE_URL"] = saved


def test_record_answer_swallows_pool_errors():
    """If acquiring the pool raises (e.g. DATABASE_URL set but driver missing),
    record_answer must return False, not propagate — training must never 500."""
    import db
    orig = db.get_pool

    def boom():
        raise RuntimeError("psycopg_pool is not installed")

    db.get_pool = boom
    try:
        row = journal.drill_answer_row(
            {"spot": "RFI", "hero_position": "UTG", "villain_position": None,
             "hand": "AA", "pack": "GTOWNL10"},
            {"correct": True, "player_action": "open",
             "correct_action": "open", "ev": 2.31, "is_timeout": False},
        )
        check(journal.record_answer(row) is False,
              "record_answer swallows a raising get_pool() and returns False")
    finally:
        db.get_pool = orig


def test_dev_user_id_is_uuid():
    check(isinstance(journal.DEV_USER_ID, uuid.UUID), "DEV_USER_ID is a uuid.UUID")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    print(f"Running {len(tests)} journal tests...\n")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        raise SystemExit(1)
    print("All journal tests passed.")


if __name__ == "__main__":
    run()
