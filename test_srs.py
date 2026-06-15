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
    # With implicit-fold expansion (default), SB vs UTG now contains all 169
    # hands: AA and AKs from the explicit data, the other 167 auto-filled as
    # pure folds.
    assert len(sb_vs_utg) == 169
    by_hand = {c.hand: c.correct_strategy for c in sb_vs_utg}
    assert by_hand["AA"] == {"3bet": 1.0}
    assert by_hand["AKs"] == {"3bet": 0.6, "call": 0.4}


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


# --- Implicit-fold expansion (Variant B) ---

def test_all_169_hands_returns_complete_universe():
    hands = srs._all_169_hands()
    assert len(hands) == 169
    assert len(set(hands)) == 169          # all unique
    # Spot-check shape: 13 pairs, 78 suited, 78 offsuit
    pairs = [h for h in hands if len(h) == 2]
    suited = [h for h in hands if h.endswith("s")]
    offsuit = [h for h in hands if h.endswith("o")]
    assert len(pairs) == 13
    assert len(suited) == 78
    assert len(offsuit) == 78
    # Canonical notation: higher rank first, "AKs" not "KAs"
    assert "AKs" in hands and "KAs" not in hands
    assert "T9o" in hands and "9To" not in hands


def test_init_from_spots_expands_rfi_to_169_per_position():
    """Default behaviour: each populated RFI position gets all 169 hands —
    explicit ones from the data, the rest as pure-fold cards."""
    cards = srs.init_cards_from_spots({"RFI": SAMPLE_RANGES})
    utg = [c for c in cards if c.spot == "RFI" and c.position == "UTG"]
    btn = [c for c in cards if c.spot == "RFI" and c.position == "BTN"]
    assert len(utg) == 169, f"UTG: expected 169, got {len(utg)}"
    assert len(btn) == 169, f"BTN: expected 169, got {len(btn)}"
    # Total = 2 populated positions × 169
    rfi_cards = [c for c in cards if c.spot == "RFI"]
    assert len(rfi_cards) == 338
    # Explicit hands preserved; missing hands become pure folds
    by_hand = {c.hand: c.correct_strategy for c in utg}
    assert by_hand["AA"] == {"open": 1.0}                  # explicit pure-open
    assert by_hand["A5s"] == {"open": 0.7, "fold": 0.3}    # explicit mixed
    assert by_hand["72o"] == {"fold": 1.0}                 # auto-expanded fold


def test_init_from_spots_expands_per_villain_for_vs_rfi():
    """For vs_RFI, each (hero, villain) tuple gets its own 169-card expansion —
    they are independent decks, not collapsed into one per hero."""
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS, scope=("vs_RFI",))
    sb_vs_utg = [c for c in cards if c.position == "SB" and c.villain_position == "UTG"]
    bb_vs_btn = [c for c in cards if c.position == "BB" and c.villain_position == "BTN"]
    assert len(sb_vs_utg) == 169
    assert len(bb_vs_btn) == 169
    # Total vs_RFI cards = sum of (hero, villain) tuples × 169
    assert len([c for c in cards if c.spot == "vs_RFI"]) == 338


def test_init_from_spots_no_expansion_when_flag_off():
    """fill_implicit_fold=False reverts to legacy: only explicit entries."""
    cards = srs.init_cards_from_spots(SAMPLE_SPOTS, fill_implicit_fold=False)
    utg = [c for c in cards if c.spot == "RFI" and c.position == "UTG"]
    assert len(utg) == 4   # AA, AKs, A5s, KTo — exactly as written in SAMPLE_RANGES
    sb_vs_utg = [c for c in cards if c.spot == "vs_RFI"
                 and c.position == "SB" and c.villain_position == "UTG"]
    assert len(sb_vs_utg) == 2   # AA, AKs


def test_init_from_spots_empty_position_block_skipped():
    """Empty dict for a position = "not defined yet, don't drill it" — must NOT
    blow up into 169 fold-cards. Only populated positions are expanded."""
    spots = {"RFI": {"UTG": {}, "BTN": {"AA": {"open": 1.0}}}}
    cards = srs.init_cards_from_spots(spots)
    positions = {c.position for c in cards}
    assert positions == {"BTN"}, f"empty UTG should be skipped, got {positions}"
    assert len(cards) == 169


def test_init_from_spots_empty_villain_block_skipped():
    """Same skip behaviour for empty (hero, villain) blocks in vs_RFI / vs_3bet."""
    spots = {"vs_RFI": {"SB": {"vs_UTG": {}, "vs_CO": {"AA": {"3bet": 1.0}}}}}
    cards = srs.init_cards_from_spots(spots)
    villains = {c.villain_position for c in cards}
    assert villains == {"CO"}     # vs_UTG was empty, skipped
    assert len(cards) == 169


def test_init_from_spots_expanded_fold_cards_grade_correctly():
    """Auto-expanded fold-cards must grade 'fold' as GOOD and any other
    action as AGAIN — same path as any other pure-fold card."""
    cards = srs.init_cards_from_spots({"RFI": {"UTG": {"AA": {"open": 1.0}}}})
    trash = next(c for c in cards if c.hand == "72o")
    assert trash.correct_strategy == {"fold": 1.0}
    assert srs.grade_answer(trash, "fold") == GOOD
    assert srs.grade_answer(trash, "open") == AGAIN
    # And they classify as pure_fold for any downstream UI logic that asks
    assert trash.classify() == "pure_fold"


def test_init_cards_from_ranges_legacy_no_expansion():
    """The legacy entry point must keep its original semantics — no expansion —
    so older callers and their tests don't get 169-card decks unexpectedly."""
    cards = srs.init_cards_from_ranges(SAMPLE_RANGES)
    assert len(cards) == 6   # 4 UTG + 2 BTN, exactly as the explicit data


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
# Easy upgrade — Variant 2 of the reveal-screen flow.
#
# Action click submits with marked_easy=false → backend applies GOOD. If the
# user then clicks "Easy" in the reveal, this delta function bumps the
# already-saved card from GOOD to EASY without needing to buffer pre-update
# state across two HTTP calls.
# ---------------------------------------------------------------------------

def test_upgrade_good_to_easy_bumps_interval_and_ease():
    """Apply the GOOD→EASY delta on top of an already-graded card:
    interval × 1.3 (with a min +1 day), ease + 0.15."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                       # interval=1
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=1))   # interval=3
    srs.upgrade_good_to_easy(c, today=TODAY + timedelta(days=1))
    # max(3+1, round(3*1.3)=4) = 4
    assert c.interval_days == 4
    assert abs(c.ease_factor - 2.65) < 1e-9


def test_upgrade_good_to_easy_minimum_one_day_growth():
    """For very small intervals, naive rounding could leave the interval
    unchanged. We enforce at least +1 day so the upgrade is never a no-op
    on the very first review."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                       # interval=1
    srs.upgrade_good_to_easy(c, today=TODAY)
    # max(1+1, round(1*1.3)=1) = 2
    assert c.interval_days == 2
    assert abs(c.ease_factor - 2.65) < 1e-9


def test_upgrade_good_to_easy_recomputes_next_review_from_today():
    """next_review must be recomputed from `today` + new interval — never
    a stale value carried over from before the upgrade."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    srs.upgrade_good_to_easy(c, today=TODAY)
    expected = (TODAY + timedelta(days=c.interval_days)).isoformat()
    assert c.next_review == expected


def test_upgrade_good_to_easy_can_be_chained():
    """Applying the upgrade twice in a row keeps bumping interval and ease
    monotonically — no clamping or weird saturation behaviour."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)            # interval=1, ease=2.5
    srs.upgrade_good_to_easy(c, today=TODAY)         # → interval=2, ease=2.65
    srs.upgrade_good_to_easy(c, today=TODAY)         # → max(3, round(2.6)=3) = 3, ease=2.80
    assert c.interval_days == 3
    assert abs(c.ease_factor - 2.80) < 1e-9


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


def test_due_per_day_limit_persists_across_calls():
    """
    NEW_CARDS_PER_DAY is a daily cap, not a per-call cap. Once 15 fresh cards
    have been introduced today, subsequent calls must return 0 new cards even
    if untouched cards remain in the deck.
    """
    # 15 cards that look like "introduced today" (one review, today)
    introduced = []
    for i in range(15):
        c = Card(hand=f"H{i}", position="UTG", spot="RFI",
                 correct_strategy={"open": 1.0, "fold": 0.0})
        srs.update_card(c, GOOD, today=TODAY)   # total_seen=1, last_seen=TODAY
        introduced.append(c)

    # 10 untouched cards in the same deck
    untouched = [
        Card(hand=f"X{i}", position="UTG", spot="RFI",
             correct_strategy={"open": 1.0, "fold": 0.0})
        for i in range(10)
    ]

    # Introduced cards are due TODAY+1, so 0 reviews due today.
    # The daily new-card budget (15) is fully spent → 0 new in the queue.
    due = srs.get_due_cards(introduced + untouched, today=TODAY, new_limit=15)
    new_in_due = [c for c in due if c.is_new()]
    assert len(new_in_due) == 0, \
        f"daily limit hit, expected 0 new cards, got {len(new_in_due)}"


def test_due_per_day_limit_allows_partial_fill():
    """If only 5 introduced today, the other 10 new slots are still open."""
    introduced = []
    for i in range(5):
        c = Card(hand=f"H{i}", position="UTG", spot="RFI",
                 correct_strategy={"open": 1.0, "fold": 0.0})
        srs.update_card(c, GOOD, today=TODAY)
        introduced.append(c)

    untouched = [
        Card(hand=f"X{i}", position="UTG", spot="RFI",
             correct_strategy={"open": 1.0, "fold": 0.0})
        for i in range(20)
    ]

    due = srs.get_due_cards(introduced + untouched, today=TODAY, new_limit=15)
    new_in_due = [c for c in due if c.is_new()]
    assert len(new_in_due) == 10, \
        f"15-5=10 slots remaining, got {len(new_in_due)}"


def test_new_cards_introduced_in_stable_shuffled_order():
    """New cards surface in a stable, shuffled order — not raw deck order.

    Deck order is JSON order (pairs + top broadways first); a fixed daily cap
    would always surface the same top-of-range hands. Sorting by md5(card_id)
    gives a deterministic, JSON-order-independent shuffle so each day covers a
    different slice of the range, identical across runs/days.
    """
    hands = ["AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55",
             "44", "33", "22", "AKs", "AQs", "AJs", "ATs", "KQs", "KJs", "QJs"]
    mk = lambda hs: [Card(hand=h, position="UTG", spot="RFI",
                          correct_strategy={"open": 1.0, "fold": 0.0}) for h in hs]

    order_fwd = [c.hand for c in srs.get_due_cards(mk(hands), today=TODAY, new_limit=15)]
    order_rev = [c.hand for c in srs.get_due_cards(mk(list(reversed(hands))),
                                                   today=TODAY, new_limit=15)]

    # Stable + independent of input order: same 15 hands in the same order.
    assert order_fwd == order_rev, "shuffle must not depend on deck/JSON order"
    # Actually shuffled: not just the matrix-order prefix (pairs first).
    assert order_fwd != hands[:15], "order should be shuffled, not raw deck order"
    # Still respects the daily cap.
    assert len(order_fwd) == 15


def test_default_card_has_empty_strategy_not_none():
    """
    Card() without explicit correct_strategy gives an empty dict (via
    default_factory), not None — so .get() in grade_answer never AttributeErrors.
    """
    c = Card(hand="AA", position="UTG", spot="RFI")
    assert c.correct_strategy == {}
    # Must grade safely (any action = not in strategy = AGAIN)
    assert srs.grade_answer(c, "open") == AGAIN


# ---------------------------------------------------------------------------
# History logging (Track A.1) — per-review log on each Card.
#
# Each entry: {date, delta_days, rating, correct}. Written by update_card
# BEFORE mutating last_seen so delta_days reflects the *actual* elapsed
# interval, which is what future FSRS calibration will fit against.
# ---------------------------------------------------------------------------

def test_history_starts_empty_on_new_card():
    c = make_new_card()
    assert c.history == []


def test_update_card_appends_one_history_entry():
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    assert len(c.history) == 1
    entry = c.history[0]
    assert entry["date"]       == TODAY.isoformat()
    assert entry["rating"]     == GOOD
    assert entry["correct"]    is True
    assert entry["delta_days"] == 0     # first review — no previous to delta from


def test_history_records_actual_delta_between_reviews():
    """Second review should record delta_days = days since last_seen at time
    of THIS review (not the scheduled interval — the *actual* elapsed time)."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                          # review 1
    srs.update_card(c, GOOD, today=TODAY + timedelta(days=5))      # review 2
    assert len(c.history) == 2
    assert c.history[0]["delta_days"] == 0
    assert c.history[1]["delta_days"] == 5
    assert c.history[1]["date"] == (TODAY + timedelta(days=5)).isoformat()


def test_history_marks_again_as_not_correct():
    """An AGAIN rating logs correct=False even though it's still a review event.
    Future calibration uses this binary flag as r_i ∈ {0, 1} in the
    SSP-MMC dataset format."""
    c = make_new_card()
    srs.update_card(c, AGAIN, today=TODAY)
    assert c.history[0]["correct"] is False
    assert c.history[0]["rating"]  == AGAIN


def test_history_logs_easy_separately_from_good():
    c = make_new_card()
    srs.update_card(c, EASY, today=TODAY)
    assert c.history[0]["rating"]  == EASY
    assert c.history[0]["correct"] is True


def test_upgrade_good_to_easy_rewrites_last_history_entry():
    """upgrade_good_to_easy mutates the most recent history entry's rating
    rather than appending a new one — semantically the user reclassified
    the same review event, not added a second one."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)                          # rating=GOOD
    assert c.history[-1]["rating"] == GOOD                         # baseline
    srs.upgrade_good_to_easy(c, today=TODAY)
    assert len(c.history) == 1                                     # still ONE entry
    assert c.history[-1]["rating"]  == EASY                        # promoted
    assert c.history[-1]["correct"] is True


def test_history_persists_through_save_load():
    """History survives JSON round-trip — without this, every restart wipes
    the very data we're collecting for calibration."""
    c = make_new_card()
    srs.update_card(c, GOOD, today=TODAY)
    srs.update_card(c, AGAIN, today=TODAY + timedelta(days=2))

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.json"
        srs.save_state([c], path)
        loaded = srs.load_state(path)

    assert len(loaded[0].history) == 2
    assert loaded[0].history[0]["rating"]     == GOOD
    assert loaded[0].history[1]["rating"]     == AGAIN
    assert loaded[0].history[1]["delta_days"] == 2


def test_history_loads_cleanly_when_field_missing_in_json():
    """Old state files saved before A.1 don't have a `history` key.
    load_state must give them an empty list (not crash, not omit the field)."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "state.json"
        # Write a state file in the pre-A.1 shape — no history field
        legacy = [{
            "hand": "AA", "position": "UTG", "spot": "RFI",
            "villain_position": "",
            "correct_strategy": {"open": 1.0},
            "ease_factor": 2.5, "interval_days": 1,
            "next_review": "", "last_seen": "",
            "consecutive_correct": 0,
            "total_seen": 1, "total_correct": 1,
        }]
        path.write_text(__import__("json").dumps(legacy), encoding="utf-8")

        loaded = srs.load_state(path)

    assert loaded[0].history == []   # default_factory kicks in cleanly


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
