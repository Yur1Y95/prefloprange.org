"""Unit tests for srs.py — verify SM-2 logic, scheduling, persistence."""

import tempfile
from datetime import date, timedelta
from pathlib import Path

import srs
from srs import Card, AGAIN, HARD, GOOD, EASY


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_RANGES = {
    "UTG": {
        "AA":  {"open": 1.0},
        "AKs": {"open": 1.0},
        "A5s": {"open": 0.7, "fold": 0.3},
        "KTo": {"open": 0.2, "fold": 0.8},
    },
    "BTN": {
        "AA":  {"open": 1.0},
        "72s": {"open": 0.4, "fold": 0.6},
    },
}

# Full-shape spots dict (mirrors the real range file format)
SAMPLE_SPOTS = {
    "RFI": SAMPLE_RANGES,
    "vs_RFI": {
        "SB": {
            "vs_UTG": {
                "AA":  {"3bet": 1.0},
                "AKs": {"3bet": 0.6, "call": 0.4},
            },
        },
        "BB": {
            "vs_BTN": {
                "ATs": {"call": 0.5, "3bet": 0.3, "fold": 0.2},
            },
        },
    },
    "vs_3bet": {
        "UTG": {
            "vs_SB": {
                "QQ":  {"4bet": 0.7, "call": 0.3},
            },
        },
    },
}

TODAY = date(2026, 5, 25)


def make_new_card() -> Card:
    return Card(
        hand="AA", position="UTG", spot="RFI",
        correct_strategy={"open": 1.0, "fold": 0.0},
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_init_creates_cards_for_every_hand_position():
    cards = srs.init_cards_from_ranges(SAMPLE_RANGES)
    assert len(cards) == 6  # 4 UTG + 2 BTN
    positions = {c.position for c in cards}
    assert positions == {"UTG", "BTN"}


def test_init_normalizes_strategy_with_implicit_fold():
    """Strategy summing to < 1.0 gets the fold remainder added explicitly."""
    cards = srs.init_cards_from_ranges({"UTG": {"A5s": {"open": 0.6}}})
    c = cards[0]
    assert c.correct_strategy["open"] == 0.6
    assert c.correct_strategy["fold"] == 0.4


def test_init_skips_implicit_fold_when_already_summing_to_one():
    """If strategy already sums to 1.0, don't add a redundant fold key."""
    cards = srs.init_cards_from_ranges({"UTG": {"AKs": {"open": 0.7, "fold": 0.3}}})
    c = cards[0]
    assert c.correct_strategy == {"open": 0.7, "fold": 0.3}


def test_init_creates_new_cards():
    cards = srs.init_cards_from_ranges(SAMPLE_RANGES)
    for c in cards:
        assert c.is_new()
        assert c.total_seen == 0
        assert c.interval_days == 0


# --- New: spots-aware init covering all three spot types ---

def test_init_from_spots_covers_all_spots():
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS)
    spots_seen = {c.spot for c in cards}
    assert spots_seen == {"RFI", "vs_RFI", "vs_3bet"}


def test_init_from_spots_attaches_villain_position():
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS)
    vs_rfi_cards = [c for c in cards if c.spot == "vs_RFI"]
    assert all(c.villain_position for c in vs_rfi_cards)
    sb_vs_utg = [c for c in vs_rfi_cards if c.position == "SB" and c.villain_position == "UTG"]
    assert len(sb_vs_utg) == 2  # AA, AKs


def test_init_from_spots_rfi_cards_have_no_villain():
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS, scope=("RFI",))
    for c in cards:
        assert c.villain_position == ""


def test_init_from_spots_scope_filter():
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS, scope=("RFI",))
    assert {c.spot for c in cards} == {"RFI"}


def test_init_from_spots_normalizes_multi_action_strategy():
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS)
    aks_vs_utg = next(c for c in cards if c.hand == "AKs" and c.spot == "vs_RFI")
    # 0.6 3bet + 0.4 call = 1.0 — no implicit fold needed
    assert "fold" not in aks_vs_utg.correct_strategy
    assert aks_vs_utg.correct_strategy["3bet"] == 0.6
    assert aks_vs_utg.correct_strategy["call"] == 0.4


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_pure_open():
    c = Card(hand="AA", position="UTG", spot="RFI",
             correct_strategy={"open": 1.0, "fold": 0.0})
    assert c.classify() == "pure_open"


def test_classify_pure_fold():
    c = Card(hand="72o", position="UTG", spot="RFI",
             correct_strategy={"open": 0.0, "fold": 1.0})
    assert c.classify() == "pure_fold"


def test_classify_pure_3bet_for_vs_rfi_spot():
    c = Card(hand="AA", position="SB", spot="vs_RFI", villain_position="UTG",
             correct_strategy={"3bet": 1.0, "fold": 0.0})
    assert c.classify() == "pure_3bet"


def test_classify_mixed():
    c = Card(hand="A5s", position="UTG", spot="RFI",
             correct_strategy={"open": 0.7, "fold": 0.3})
    assert c.classify() == "mixed"


def test_classify_near_pure_treats_as_pure():
    # 96/4 is above the 95% threshold — counts as pure
    c = Card(hand="A5s", position="UTG", spot="RFI",
             correct_strategy={"open": 0.96, "fold": 0.04})
    assert c.classify() == "pure_open"


def test_dominant_action():
    c = Card(hand="A5s", position="UTG", spot="RFI",
             correct_strategy={"open": 0.7, "fold": 0.3})
    assert c.dominant_action() == "open"


def test_card_id_for_rfi():
    c = Card(hand="AA", position="UTG", spot="RFI",
             correct_strategy={"open": 1.0, "fold": 0.0})
    assert c.card_id == "AA__UTG__RFI"


def test_card_id_for_vs_rfi():
    c = Card(hand="AA", position="SB", spot="vs_RFI", villain_position="UTG",
             correct_strategy={"3bet": 1.0, "fold": 0.0})
    assert c.card_id == "AA__SB__vs_RFI__UTG"


# ---------------------------------------------------------------------------
# Objective grading (grade_answer) — UI bridge
# ---------------------------------------------------------------------------

def test_grade_correct_action_returns_good():
    c = make_new_card()  # AA UTG RFI, {open: 1.0}
    assert srs.grade_answer(c, "open") == GOOD


def test_grade_wrong_action_returns_again():
    c = make_new_card()
    assert srs.grade_answer(c, "fold") == AGAIN


def test_grade_easy_flag_returns_easy_when_correct():
    c = make_new_card()
    assert srs.grade_answer(c, "open", marked_easy=True) == EASY


def test_grade_easy_flag_ignored_when_wrong():
    """Easy is meaningless on a wrong answer — should still be Again."""
    c = make_new_card()
    assert srs.grade_answer(c, "fold", marked_easy=True) == AGAIN


def test_grade_mixed_any_in_strategy_action_counts_as_correct():
    """For a 70/30 mix, BOTH actions are in-strategy → both grade as Good."""
    c = Card(hand="A5s", position="UTG", spot="RFI",
             correct_strategy={"open": 0.7, "fold": 0.3})
    assert srs.grade_answer(c, "open") == GOOD
    assert srs.grade_answer(c, "fold") == GOOD


def test_grade_unknown_action_returns_again():
    """Action not present in the strategy at all → wrong."""
    c = make_new_card()
    assert srs.grade_answer(c, "raise") == AGAIN  # 'raise' isn't an RFI action here


def test_grade_action_with_zero_freq_returns_again():
    """Action present with 0% freq is the same as not present."""
    c = Card(hand="22", position="UTG", spot="RFI",
             correct_strategy={"open": 0.0, "fold": 1.0})
    assert srs.grade_answer(c, "open") == AGAIN


# ---------------------------------------------------------------------------
# SM-2 update logic — the most important tests
# ---------------------------------------------------------------------------

def test_good_on_new_card_sets_interval_1_day():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    assert c.interval_days == 1
    assert c.next_review == (TODAY + timedelta(days=1)).isoformat()
    assert c.consecutive_correct == 1
    assert c.total_correct == 1
    assert c.total_seen == 1


def test_good_twice_graduates_to_3_days():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=1))
    assert c.interval_days == 3


def test_good_third_time_uses_ease():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                       # -> 1
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=1))    # -> 3
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=4))    # -> 3 * 2.5 = 7.5 round 8
    assert c.interval_days == 8


def test_again_resets_interval_and_streak():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=1))
    assert c.interval_days == 3
    srs.update_card(c, AGAIN, today=TODAY + timedelta(days=4))
    assert c.interval_days == 1
    assert c.consecutive_correct == 0


def test_again_reduces_ease_by_0_20():
    c = make_new_card()
    srs.update_card(c, AGAIN, today=TODAY)
    assert abs(c.ease_factor - 2.30) < 1e-9


def test_ease_clamped_at_minimum():
    c = make_new_card()
    for _ in range(20):
        srs.update_card(c, AGAIN, today=TODAY)
    assert c.ease_factor == srs.MIN_EASE


def test_easy_grows_faster_and_raises_ease():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                       # -> 1, ease 2.5
    srs.update_card(c, EASY, today=TODAY + timedelta(days=1))    # -> 1*2.5*1.3=3.25 round 3
    assert c.interval_days == 3
    assert abs(c.ease_factor - 2.65) < 1e-9


def test_hard_grows_slowly_and_reduces_ease():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                       # -> 1
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=1))    # -> 3
    srs.update_card(c, HARD, today=TODAY + timedelta(days=4))    # -> max(4, int(3*1.2)=3) = 4
    assert c.interval_days == 4
    assert abs(c.ease_factor - 2.35) < 1e-9


def test_invalid_rating_raises():
    c = make_new_card()
    try:
        srs.update_card(c, 5, today=TODAY)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def test_due_caps_new_cards_at_limit():
    cards = [make_new_card() for _ in range(20)]
    due = srs.get_due_cards(cards, today=TODAY, new_limit=15)
    assert len(due) == 15


def test_due_includes_overdue_reviews():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)  # next_review = TODAY + 1
    # Five days later, this card is overdue
    due = srs.get_due_cards([c], today=TODAY + timedelta(days=5), new_limit=15)
    assert len(due) == 1


def test_due_excludes_future_reviews():
    c = make_new_card()
    srs.update_card(c, EASY, today=TODAY)  # next_review is 3 days out
    due = srs.get_due_cards([c], today=TODAY + timedelta(days=1), new_limit=15)
    assert len(due) == 0


def test_due_mixes_reviews_and_new():
    seen = make_new_card()
    srs.update_card(seen, GOOD, today=TODAY)  # interval = 1, due TODAY+1

    new_cards = [
        Card(hand=h, position="UTG", spot="RFI",
             correct_strategy={"raise": 1.0, "fold": 0.0})
        for h in ["AKs", "KK", "QQ"]
    ]
    # On TODAY+2: seen is overdue (1 day), plus 3 new
    due = srs.get_due_cards([seen] + new_cards,
                            today=TODAY + timedelta(days=2),
                            new_limit=15)
    assert len(due) == 4


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip():
    cards = srs.init_cards_from_ranges(SAMPLE_RANGES)
    srs.update_card(cards[0], GOOD, today=TODAY)
    srs.update_card(cards[1], HARD, today=TODAY)

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.json"
        srs.save_state(cards, path)
        loaded = srs.load_state(path)

    assert len(loaded) == len(cards)
    assert loaded[0].interval_days == cards[0].interval_days
    assert loaded[0].next_review == cards[0].next_review
    assert abs(loaded[1].ease_factor - cards[1].ease_factor) < 1e-9


def test_load_missing_file_returns_empty():
    assert srs.load_state("/tmp/definitely_nonexistent_srs_state_xyz.json") == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_summary_counts_states_correctly():
    cards = [make_new_card() for _ in range(5)]
    srs.update_card(cards[0], GOOD, today=TODAY)   # interval 1  -> young
    srs.update_card(cards[1], EASY, today=TODAY)   # interval 3  -> young

    # Simulate a learned card manually (interval >= 21)
    cards[2].total_seen = 5
    cards[2].interval_days = 30
    cards[2].next_review = (TODAY + timedelta(days=30)).isoformat()

    summary = srs.summarize(cards, today=TODAY)
    assert summary["total"] == 5
    assert summary["new"] == 2       # cards[3], cards[4]
    assert summary["young"] == 2     # cards[0], cards[1]
    assert summary["learned"] == 1   # cards[2]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    tests = [(k, v) for k, v in globals().items()
             if k.startswith("test_") and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed.append(name)
            print(f"  ERR   {name}: {type(e).__name__}: {e}")

    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} FAILED")
        sys.exit(1)
    print(f"All {len(tests)} tests passed")
