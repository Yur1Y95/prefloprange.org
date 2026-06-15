"""
Spaced Repetition System for poker range training.

Implements an Anki-style SM-2 algorithm with 4 ratings:
  1 — Again (forgot completely; reset interval)
  2 — Hard  (recalled with effort; small growth)
  3 — Good  (normal recall; standard growth)
  4 — Easy  (instant recall; faster growth)

One card = one (hand, position, spot) tuple — a specific decision in a
specific situation. State is persisted to JSON for transparency and easy
debugging.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PURE_THRESHOLD = 0.95          # above this — strategy considered pure
DEFAULT_EASE = 2.5             # starting ease factor for every new card
MIN_EASE = 1.3                 # ease never goes below this floor
NEW_CARDS_PER_DAY = 15         # how many fresh cards to surface daily
LEARNED_THRESHOLD_DAYS = 21    # interval ≥ this = card is "in long-term memory"

# Rating values — exposed as module constants so callers don't pass magic numbers
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


# ---------------------------------------------------------------------------
# Hand universe — all 169 unique starting hands in canonical notation
# ---------------------------------------------------------------------------

# Ranks high to low. Same convention used everywhere else in the project:
# higher card first, then "s" or "o" for non-pairs ("AKs", "T9o", "22").
_RANKS = "AKQJT98765432"


def _all_169_hands() -> list[str]:
    """All 169 starting-hand classes in deck-friendly order.

    Returns pairs first (AA..22), then suited (AKs..32s), then offsuit
    (AKo..32o). Within each group, stronger hands (by high card) come first
    so that fresh-deck sessions naturally surface big hands before junk —
    a small UX nicety, not a correctness requirement.
    """
    pairs = [f"{r}{r}" for r in _RANKS]
    suited: list[str] = []
    offsuit: list[str] = []
    for i in range(len(_RANKS)):
        for j in range(i + 1, len(_RANKS)):
            hi, lo = _RANKS[i], _RANKS[j]
            suited.append(f"{hi}{lo}s")
            offsuit.append(f"{hi}{lo}o")
    return pairs + suited + offsuit


# ---------------------------------------------------------------------------
# Card model
# ---------------------------------------------------------------------------

@dataclass
class Card:
    """One unit of spaced repetition: a specific decision in a specific spot."""

    # Identity (immutable for a card's lifetime)
    hand: str                # "AKs", "T9o", "22"
    position: str            # hero position: "UTG", "MP", "CO", "BTN", "SB"
    spot: str                # "RFI" | "vs_RFI" | "vs_3bet"
    villain_position: str = ""   # empty for RFI, otherwise opener/3-bettor

    # The "answer" — frequency distribution from the trained range.
    # Action names depend on the spot:
    #   RFI:     {"open": ..., "fold": ...}
    #   vs_RFI:  {"call": ..., "3bet": ..., "fold": ...}
    #   vs_3bet: {"call": ..., "4bet": ..., "fold": ...}
    # default_factory=dict avoids the mutable-default trap; in practice the
    # dict is always populated by _make_card() or load_state().
    correct_strategy: dict[str, float] = field(default_factory=dict)

    # SRS scheduling state
    ease_factor: float = DEFAULT_EASE
    interval_days: int = 0           # 0 = new card, never reviewed
    next_review: str = ""            # ISO date; empty for new cards
    last_seen: str = ""              # ISO date; empty for new cards

    # Lifetime stats
    consecutive_correct: int = 0     # streak; reset to 0 on Again
    total_seen: int = 0
    total_correct: int = 0           # any rating ≥ HARD counts as correct

    # Per-review log. Each entry: {date, delta_days, rating, correct}.
    #   date         — ISO date of the review
    #   delta_days   — days since previous review (0 for first ever)
    #   rating       — 1=AGAIN, 2=HARD, 3=GOOD, 4=EASY
    #   correct      — True if rating > AGAIN (the user remembered it at all)
    # Written by ``update_card`` before any state mutation, so the entry
    # captures the *actual* interval that elapsed for this review, which is
    # what future FSRS calibration (Track A.4) will fit against.
    # Empty by default — old state files without this field load cleanly
    # thanks to ``default_factory``.
    history: list[dict] = field(default_factory=list)

    def is_new(self) -> bool:
        return self.total_seen == 0

    @property
    def card_id(self) -> str:
        """Deterministic, URL-safe identifier — used as the API handle."""
        if self.villain_position:
            return f"{self.hand}__{self.position}__{self.spot}__{self.villain_position}"
        return f"{self.hand}__{self.position}__{self.spot}"

    def classify(self) -> str:
        """
        Returns 'pure_<action>' if any single action has ≥ PURE_THRESHOLD freq,
        otherwise 'mixed'. Action-agnostic — works for open/call/3bet/4bet/etc.
        """
        if not self.correct_strategy:
            return "mixed"
        top_action, top_freq = max(self.correct_strategy.items(), key=lambda kv: kv[1])
        if top_freq >= PURE_THRESHOLD:
            return f"pure_{top_action}"
        return "mixed"

    def dominant_action(self) -> str:
        """Returns the action with the highest frequency."""
        return max(self.correct_strategy.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Card initialization from ranges
# ---------------------------------------------------------------------------

def _make_card(
    hand: str,
    position: str,
    spot: str,
    villain_position: str,
    strategy: dict,
) -> Card:
    """Build one Card with normalized strategy (implicit fold filled in)."""
    strategy = dict(strategy)  # don't mutate caller's data
    total = sum(strategy.values())
    if "fold" not in strategy and total < 1.0:
        strategy["fold"] = round(1.0 - total, 4)
    return Card(
        hand=hand,
        position=position,
        spot=spot,
        villain_position=villain_position,
        correct_strategy=strategy,
    )


def init_cards_from_spots(
    spots_data: dict,
    scope: tuple[str, ...] | None = None,
    fill_implicit_fold: bool = True,
) -> list[Card]:
    """
    Build a flat list of new Cards from the full ``spots`` dict of a range file.

    Handles all three spot types in one pass:

        RFI:      { position: { hand: {action: freq} } }
        vs_RFI:   { hero_pos: { "vs_<villain>": { hand: {action: freq} } } }
        vs_3bet:  { hero_pos: { "vs_<villain>": { hand: {action: freq} } } }

    Pass ``scope`` to restrict to specific spot types, e.g. ``("RFI",)`` for an
    RFI-only MVP deck. Default = all three spots.

    When ``fill_implicit_fold=True`` (default), every (position, spot[, villain])
    tuple that has at least one explicit entry is auto-completed to all 169
    starting hands — hands missing from the source range become pure-fold cards
    with strategy ``{"fold": 1.0}``. This makes Learn-mode decks cover both
    "remember to open" AND "remember to fold trash" decisions, which is closer
    to actual at-the-table demands than drilling only the open range.

    Set ``fill_implicit_fold=False`` to keep only explicit entries (legacy
    behaviour — used by ``init_cards_from_ranges`` and by tests that want the
    raw, non-expanded shape).

    An empty position block (e.g. ``{"UTG": {}}``) is treated as "undefined,
    skip" — we don't blow it up into 169 fold-cards because the user clearly
    hasn't decided what to put there yet.

    Hands with explicit fractional strategy are kept and normalized so
    frequencies sum to 1 (the existing ``_make_card`` behaviour, unchanged).
    """
    if scope is None:
        scope = ("RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso")

    cards: list[Card] = []
    all_hands = _all_169_hands() if fill_implicit_fold else ()

    def _expand(hero_pos: str, spot: str, villain_pos: str, explicit: set[str]) -> None:
        """Append fold-cards for every hand in the 169-universe not in ``explicit``."""
        for h in all_hands:
            if h not in explicit:
                cards.append(_make_card(h, hero_pos, spot, villain_pos, {"fold": 1.0}))

    # RFI — flat: position -> hand -> strategy
    if "RFI" in scope:
        for position, hands in spots_data.get("RFI", {}).items():
            if not hands:                       # empty block = "not defined yet"
                continue
            for hand, strategy in hands.items():
                cards.append(_make_card(hand, position, "RFI", "", strategy))
            if fill_implicit_fold:
                _expand(position, "RFI", "", set(hands.keys()))

    # vs_RFI, vs_3bet, vs_4bet, iso all share the same nested shape:
    #   hero_pos -> "vs_<villain>" -> hand -> strategy
    for spot_name in ("vs_RFI", "vs_3bet", "vs_4bet", "iso"):
        if spot_name not in scope:
            continue
        for hero_pos, vs_dict in spots_data.get(spot_name, {}).items():
            for vs_key, hands in vs_dict.items():
                if not hands:                   # empty (hero, villain) block — skip
                    continue
                # "vs_UTG" -> "UTG"
                villain_pos = vs_key[3:] if vs_key.startswith("vs_") else vs_key
                for hand, strategy in hands.items():
                    cards.append(_make_card(hand, hero_pos, spot_name, villain_pos, strategy))
                if fill_implicit_fold:
                    _expand(hero_pos, spot_name, villain_pos, set(hands.keys()))

    return cards


# Back-compat alias for the original narrow signature (RFI-only flat dict)
def init_cards_from_ranges(ranges: dict) -> list[Card]:
    """Legacy entry point: takes a flat ``{position: {hand: strategy}}`` dict
    and treats it as RFI scope. Prefer ``init_cards_from_spots`` for new code.

    Does NOT auto-expand missing hands to fold-cards — preserves the original
    "only explicit entries become cards" semantics so existing callers
    (and their tests) keep working.
    """
    return init_cards_from_spots({"RFI": ranges}, scope=("RFI",), fill_implicit_fold=False)


# ---------------------------------------------------------------------------
# Objective grading — bridges UI clicks to SM-2 ratings
# ---------------------------------------------------------------------------

def grade_answer(card: Card, user_action: str, marked_easy: bool = False) -> int:
    """
    Map an objective answer (the action the user clicked) to an SM-2 rating.

      - Action present in the strategy with > 0 frequency  → GOOD (or EASY if flagged)
      - Action with 0 frequency or unknown action          → AGAIN

    This is the Chessable/Duolingo-style binary grading we agreed on, with one
    optional self-rate shortcut ("Easy") for trivially known cards.
    """
    in_strategy = card.correct_strategy.get(user_action, 0) > 0
    if not in_strategy:
        return AGAIN
    if marked_easy:
        return EASY
    return GOOD


# ---------------------------------------------------------------------------
# SM-2 update logic — the heart of SRS
# ---------------------------------------------------------------------------

def update_card(card: Card, rating: int, today: date | None = None) -> Card:
    """
    Apply user rating (1=Again, 2=Hard, 3=Good, 4=Easy) and return the
    *same* (mutated) card with updated SRS state.

    Schedule rules:
      Again: reset to 1 day,        ease -= 0.20 (clamped to MIN_EASE), streak = 0
      Hard:  small growth (×1.2),   ease -= 0.15
      Good:  graduation step or interval × ease,  ease unchanged
      Easy:  interval × ease × 1.3, ease += 0.15
    """
    if rating not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"rating must be 1-4, got {rating}")

    if today is None:
        today = date.today()

    # Log this review BEFORE mutating last_seen — we need the previous
    # last_seen to compute delta_days (0 for first review). See Card.history
    # docstring for the entry shape.
    if card.last_seen:
        delta_days = (today - date.fromisoformat(card.last_seen)).days
    else:
        delta_days = 0
    card.history.append({
        "date":       today.isoformat(),
        "delta_days": delta_days,
        "rating":     rating,
        "correct":    rating > AGAIN,
    })

    card.total_seen += 1
    card.last_seen = today.isoformat()

    if rating == AGAIN:
        card.interval_days = 1
        card.ease_factor = max(MIN_EASE, card.ease_factor - 0.20)
        card.consecutive_correct = 0

    elif rating == HARD:
        card.total_correct += 1
        card.consecutive_correct += 1
        # Hard grows slowly: at least +1 day so the card moves forward
        if card.interval_days == 0:
            card.interval_days = 1
        else:
            card.interval_days = max(
                card.interval_days + 1,
                int(card.interval_days * 1.2),
            )
        card.ease_factor = max(MIN_EASE, card.ease_factor - 0.15)

    elif rating == GOOD:
        card.total_correct += 1
        card.consecutive_correct += 1
        # Graduation ladder: 0 -> 1 -> 3 -> normal SM-2 multiplication
        if card.interval_days == 0:
            card.interval_days = 1
        elif card.interval_days == 1:
            card.interval_days = 3
        else:
            card.interval_days = int(round(card.interval_days * card.ease_factor))
        # ease unchanged on Good — it's "as expected"

    elif rating == EASY:
        card.total_correct += 1
        card.consecutive_correct += 1
        if card.interval_days == 0:
            card.interval_days = 3   # skip graduation — straight to 3-day interval
        else:
            card.interval_days = int(round(
                card.interval_days * card.ease_factor * 1.3
            ))
        card.ease_factor = card.ease_factor + 0.15

    card.next_review = (today + timedelta(days=card.interval_days)).isoformat()
    return card


def upgrade_good_to_easy(card: Card, today: date | None = None) -> Card:
    """
    Upgrade a card's just-applied GOOD rating to EASY.

    Used when the user clicks "Easy" in the Learn reveal screen *after*
    already submitting an in-strategy action that was graded as GOOD by
    ``update_card``. We apply the multiplicative GOOD→EASY delta:

      - ``interval_days`` × 1.3 (clamped to at least +1 day so a trivial
        card actually moves forward; otherwise rounding could leave it
        unchanged on small intervals)
      - ``ease_factor`` + 0.15

    Notes:
      - This is intentionally approximate. Calling ``update_card(EASY)``
        from a fresh state vs.\ ``update_card(GOOD)`` then this upgrade
        can differ by ~1 day on the first review. We accept that — SM-2
        is a heuristic, and buffering pre-update state across two HTTP
        calls is more complexity than the precision is worth.
      - ``next_review`` is recomputed from ``today`` + new interval.
    """
    if today is None:
        today = date.today()
    card.interval_days = max(
        card.interval_days + 1,
        int(round(card.interval_days * 1.3)),
    )
    card.ease_factor = card.ease_factor + 0.15
    card.next_review = (today + timedelta(days=card.interval_days)).isoformat()

    # History fix-up: the most recent entry was logged as GOOD by update_card.
    # Conceptually the user just reclassified that answer as EASY, so we
    # mutate the last entry's rating rather than appending a new event —
    # otherwise calibration would see two reviews on the same day.
    if card.history:
        card.history[-1]["rating"]  = EASY
        card.history[-1]["correct"] = True

    return card


# ---------------------------------------------------------------------------
# Scheduling — which cards to show today
# ---------------------------------------------------------------------------

def get_due_cards(
    cards: list[Card],
    today: date | None = None,
    new_limit: int = NEW_CARDS_PER_DAY,
) -> list[Card]:
    """
    Returns cards to drill today, in priority order:
      1. Reviews due today or earlier (next_review <= today)
      2. New cards, capped so we never introduce more than ``new_limit``
         in a single day across the whole deck

    Per-day enforcement is derived from card state rather than stored
    separately: a card with ``last_seen == today AND total_seen == 1`` was
    introduced today (its first ever review happened today). We subtract
    that count from ``new_limit`` to get the remaining slots for fresh
    cards. No schema change needed.
    """
    if today is None:
        today = date.today()
    today_str = today.isoformat()

    due_reviews = [
        c for c in cards
        if not c.is_new() and c.next_review and c.next_review <= today_str
    ]

    introduced_today = sum(
        1 for c in cards
        if c.last_seen == today_str and c.total_seen == 1
    )
    remaining_new_slots = max(0, new_limit - introduced_today)
    # Introduce new cards in a *stable shuffled* order, not deck/JSON order.
    # Deck order is JSON order (pairs + top suited first), so a fixed daily cap
    # would always surface the same top-of-range hands and bury the marginal,
    # decision-heavy hands at the very end. Sorting by md5(card_id) gives a
    # deterministic pseudo-random order: stable across runs and days (md5 is
    # not salted, unlike the builtin hash()), independent of JSON order — so
    # each day introduces a different slice spread across the whole range.
    fresh = [c for c in cards if c.is_new()]
    fresh.sort(key=lambda c: hashlib.md5(c.card_id.encode()).hexdigest())
    new_cards = fresh[:remaining_new_slots]

    return due_reviews + new_cards


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_state(cards: list[Card], path: str | Path) -> None:
    """Write all cards to a JSON file (pretty-printed for easy inspection)."""
    path = Path(path)
    payload = [asdict(c) for c in cards]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_state(path: str | Path) -> list[Card]:
    """Read cards from a JSON file. Returns empty list if the file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Card(**item) for item in data]


# ---------------------------------------------------------------------------
# Summary — high-level stats for the UI/dashboard
# ---------------------------------------------------------------------------

def summarize(cards: list[Card], today: date | None = None) -> dict:
    """
    Returns a dashboard-friendly snapshot:
      total      — deck size
      new        — never seen
      due_today  — scheduled for today or overdue
      young      — seen but not yet "learned" (interval < LEARNED_THRESHOLD_DAYS)
      learned    — interval ≥ LEARNED_THRESHOLD_DAYS (in long-term memory)
    """
    if today is None:
        today = date.today()
    today_str = today.isoformat()

    total = len(cards)
    new = sum(1 for c in cards if c.is_new())
    due = sum(
        1 for c in cards
        if not c.is_new() and c.next_review and c.next_review <= today_str
    )
    learned = sum(1 for c in cards if c.interval_days >= LEARNED_THRESHOLD_DAYS)
    young = sum(1 for c in cards if 0 < c.interval_days < LEARNED_THRESHOLD_DAYS)

    return {
        "total": total,
        "new": new,
        "due_today": due,
        "young": young,
        "learned": learned,
    }
