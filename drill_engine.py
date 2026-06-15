"""
Preflop drill engine for NLH Range Trainer.
Handles: RFI, vs_RFI, vs_3bet spots with full preflop action context.
"""

import random
from range_engine import (
    get_rfi_range, get_vs_rfi_range, get_vs_3bet_range,
    get_vs_4bet_range, get_iso_range, get_ev,
)

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
SUITS = ["s", "h", "d", "c"]
SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

# ----- Game constants -----
BB = 1.0               # big blind in bb
SB = 0.5               # small blind in bb
OPEN_SIZE = 2.5        # standard open raise size in bb
STARTING_STACK = 100.0 # starting stack in bb
THREEBET_MULT = 3.5    # 3-bet size as multiple of open (2.5 × 3.5 = 8.75)
FOURBET_MULT  = 2.5    # 4-bet size as multiple of 3-bet (8.75 × 2.5 ≈ 21.9)
ISO_SIZE = 4.0         # standard iso-raise size vs 1 limper (in bb)

# ----- EV policy -----
# There are NO synthetic EV constants. The EV pill shows ONLY a real number
# pulled from the optional top-level `ev` block of the range file (via
# range_engine.get_ev). No data for a hand → None → the frontend hides the pill.
# This holds for every spot (RFI / vs_RFI / vs_3bet) and for timeouts.


# ---------- helpers ----------

def all_hands():
    """Return a list of all 169 unique hand names."""
    hands = []
    for r in range(len(RANKS)):
        for c in range(len(RANKS)):
            if r == c:
                hands.append(RANKS[r] + RANKS[c])
            elif r < c:
                hands.append(RANKS[r] + RANKS[c] + "s")
            else:
                hands.append(RANKS[c] + RANKS[r] + "o")
    return hands


def generate_cards(hand):
    """
    Turn an abstract hand name (e.g. AKs, 77, QJo) into two
    concrete cards with suit symbols, e.g. ('A♠', 'K♠').
    """
    if len(hand) == 2:                   # pocket pair
        rank = hand[0]
        suits = random.sample(SUITS, 2)
        return f"{rank}{SUIT_SYMBOLS[suits[0]]}", f"{rank}{SUIT_SYMBOLS[suits[1]]}"

    rank1, rank2 = hand[0], hand[1]

    if hand.endswith("s"):               # suited
        suit = random.choice(SUITS)
        return f"{rank1}{SUIT_SYMBOLS[suit]}", f"{rank2}{SUIT_SYMBOLS[suit]}"

    # offsuit
    suits = random.sample(SUITS, 2)
    return f"{rank1}{SUIT_SYMBOLS[suits[0]]}", f"{rank2}{SUIT_SYMBOLS[suits[1]]}"


def resolve_mixed_action(actions, rng_fraction):
    """
    Given a dict of {action: frequency} and a random float [0, 1),
    return which action the RNG selects.
    Action order: 4bet → 3bet → call → open → fold.
    """
    priority = ["allin", "4bet", "3bet", "raise", "call", "open"]
    cumulative = 0.0
    for action in priority:
        freq = actions.get(action, 0)
        cumulative += freq
        if rng_fraction < cumulative:
            return action
    return "fold"


# ---------- strategy membership (Practice grading, decision #8 amended) ----------
# Practice now grades like Learn (decision #7): ANY action that is part of the
# mixed strategy (frequency > 0) is correct. The RNG roll (resolve_mixed_action)
# is kept only as an illustration of how the hand would be played this time — it
# no longer decides right/wrong. Rationale: a hand like 66 = {open: 0.27} is in
# the range; opening it should not be punished just because the dice said fold.

_ACTION_ORDER = ["open", "allin", "4bet", "3bet", "raise", "call", "fold"]


def strategy_with_fold(actions):
    """Return {action: freq} for the strategy, INCLUDING the implicit fold
    remainder when the explicit frequencies sum to < 1.0.

    {"open": 0.27}            -> {"open": 0.27, "fold": 0.73}
    {"open": 1.0}             -> {"open": 1.0}              (no implicit fold)
    {}                        -> {"fold": 1.0}              (hand not in range)
    {"call": 0.6, "3bet": .4} -> {"call": 0.6, "3bet": 0.4}
    """
    pool = {a: f for a, f in actions.items() if f > 0}
    implicit = round(1.0 - sum(actions.values()), 6)
    if implicit > 1e-6:
        pool["fold"] = round(pool.get("fold", 0) + implicit, 6)
    return pool


def action_in_strategy(actions, action):
    """True if `action` is part of the mixed strategy (freq > 0, fold implicit)."""
    return action in strategy_with_fold(actions)


def dominant_action(actions):
    """The highest-frequency action in the strategy (implicit fold counted).
    Used as the 'what you should do' line on wrong answers / timeouts."""
    pool = strategy_with_fold(actions)
    return max(pool, key=pool.get) if pool else "fold"


def mix_summary(actions):
    """Human-readable breakdown, e.g. 'open 27%, fold 73%'."""
    pool = strategy_with_fold(actions)
    items = sorted(pool.items(),
                   key=lambda kv: _ACTION_ORDER.index(kv[0]) if kv[0] in _ACTION_ORDER else 99)
    return ", ".join(f"{a} {int(round(f * 100))}%" for a, f in items)


def get_position_specific_data(hero_position):
    """
    Return blinds posted, stack, and any action that happened before hero.
    Simulates a 6-max preflop scenario where it's folded to the relevant actor.
    """
    positions = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    hero_idx = positions.index(hero_position)

    # Everyone starts with 100 BB
    stacks = {pos: STARTING_STACK for pos in positions}

    # Blinds
    stacks["SB"] -= SB
    stacks["BB"] -= BB
    pot = SB + BB  # 1.5 BB

    # Determine who acted before hero & what they did
    action_log = []
    open_raiser = None
    open_size = 0

    # SB and BB: special blind logic
    # For now, we assume everyone before hero folds.
    # Exception: in vs_RFI, the open_raiser is the villain.
    # We'll override this in the specific drill functions.

    return {
        "stacks": stacks,
        "pot": round(pot, 1),
        "action_log": action_log,
        "open_raiser": open_raiser,
        "open_size": open_size,
    }


# ---------- drill hand generators ----------

def get_drill_hand_rfi(range_data, hero_position):
    """Return a drill question for an RFI spot, or None if there's no data
    for this position (P-011 — caller surfaces a clean 404, not a 500)."""
    rfi_range = get_rfi_range(range_data, hero_position)
    if not rfi_range:
        return None

    hand = random.choice(all_hands())
    value = rfi_range.get(hand, 0)

    rng = random.randint(0, 99)

    # Handle both formats: single frequency and multi-action {open: f, call: f}
    if isinstance(value, dict):
        actions = value
        correct_action = resolve_mixed_action(actions, rng / 100.0)
        frequency = actions.get("open", 0)
        # Available actions depend on what's in the range
        available = list({a for a in actions if actions[a] > 0} | {"fold"})
        available_actions = sorted(available, key=lambda a: ["open","call","fold"].index(a) if a in ["open","call","fold"] else 99)
    else:
        frequency = value
        correct_action = "open" if rng < int(frequency * 100) else "fold"
        available_actions = ["open", "fold"]
        actions = {"open": frequency} if frequency > 0 else {}

    card1, card2 = generate_cards(hand)

    # Precomputed GTO EV of opening this hand (bb), or None if the file has no
    # `ev` data for it. Carried through to check_answer for the feedback line.
    gto_ev = get_ev(range_data, "RFI", hero_position, hand)

    # Build preflop context
    positions = list(range_data["config"]["positions"])
    hero_idx = positions.index(hero_position)

    stacks = {pos: STARTING_STACK for pos in positions}
    stacks["SB"] = round(stacks["SB"] - SB, 1)
    stacks["BB"] = round(stacks["BB"] - BB, 1)

    pot = round(SB + BB, 1)
    action_log = []

    for pos in positions[:hero_idx]:
        action_log.append(f"{pos} folds")

    if hero_position == "SB":
        action_log.append("SB posts 0.5 BB")
    elif hero_position == "BB":
        action_log.append("BB posts 1 BB")

    return {
        "spot": "RFI",
        "hero_position": hero_position,
        "villain_position": None,
        "hand": hand,
        "card1": card1,
        "card2": card2,
        "frequency": frequency,
        "actions": actions,
        "rng": rng,
        "correct_action": correct_action,
        "available_actions": available_actions,
        "gto_ev": gto_ev,
        "context": {
            "stacks": stacks,
            "pot": pot,
            "action_log": action_log,
            "open_raiser": None,
            "open_size": 0,
            "hero_stack": stacks[hero_position],
        }
    }


def get_drill_hand_vs_rfi(range_data, hero_position, villain_position):
    """Return a drill question for a vs_RFI spot, or None if no data (P-011)."""
    expanded_range = get_vs_rfi_range(range_data, hero_position, villain_position)
    if not expanded_range:
        return None

    hand = random.choice(all_hands())
    actions = expanded_range.get(hand, {})

    rng = random.randint(0, 99)
    correct_action = resolve_mixed_action(actions, rng / 100.0)

    card1, card2 = generate_cards(hand)

    positions = list(range_data["config"]["positions"])
    hero_idx    = positions.index(hero_position)
    villain_idx = positions.index(villain_position)

    stacks = {pos: STARTING_STACK for pos in positions}
    stacks["SB"] = round(stacks["SB"] - SB, 1)
    stacks["BB"] = round(stacks["BB"] - BB, 1)

    pot = round(SB + BB, 1)
    action_log = []

    for pos in positions[:villain_idx]:
        action_log.append(f"{pos} folds")

    stacks[villain_position] = round(stacks[villain_position] - OPEN_SIZE, 1)
    pot = round(pot + OPEN_SIZE, 1)
    action_log.append(f"{villain_position} opens {OPEN_SIZE} BB")

    for pos in positions[villain_idx + 1:hero_idx]:
        action_log.append(f"{pos} folds")

    gto_ev = get_ev(range_data, "vs_RFI", hero_position, hand, villain_position)

    return {
        "spot": "vs_RFI",
        "hero_position": hero_position,
        "villain_position": villain_position,
        "hand": hand,
        "card1": card1,
        "card2": card2,
        "actions": actions,
        "rng": rng,
        "correct_action": correct_action,
        "available_actions": ["3bet", "call", "fold"],
        "gto_ev": gto_ev,
        "context": {
            "stacks": stacks,
            "pot": pot,
            "action_log": action_log,
            "open_raiser": villain_position,
            "open_size": OPEN_SIZE,
            "hero_stack": stacks[hero_position],
        }
    }


def get_drill_hand_vs_3bet(range_data, hero_position, villain_position):
    """Return a drill question for a vs_3bet spot, or None if no data (P-011)."""
    expanded_range = get_vs_3bet_range(range_data, hero_position, villain_position)
    if not expanded_range:
        return None

    hand = random.choice(all_hands())
    actions = expanded_range.get(hand, {})

    rng = random.randint(0, 99)
    correct_action = resolve_mixed_action(actions, rng / 100.0)

    card1, card2 = generate_cards(hand)

    positions   = list(range_data["config"]["positions"])
    hero_idx    = positions.index(hero_position)
    villain_idx = positions.index(villain_position)

    stacks = {pos: STARTING_STACK for pos in positions}
    stacks["SB"] = round(stacks["SB"] - SB, 1)
    stacks["BB"] = round(stacks["BB"] - BB, 1)

    pot = round(SB + BB, 1)
    action_log = []

    for pos in positions[:hero_idx]:
        action_log.append(f"{pos} folds")

    stacks[hero_position] = round(stacks[hero_position] - OPEN_SIZE, 1)
    pot = round(pot + OPEN_SIZE, 1)
    action_log.append(f"{hero_position} opens {OPEN_SIZE} BB")

    for pos in positions[hero_idx + 1:villain_idx]:
        action_log.append(f"{pos} folds")

    threebet_size = round(OPEN_SIZE * 3.5, 1)
    stacks[villain_position] = round(stacks[villain_position] - threebet_size, 1)
    pot = round(pot + threebet_size, 1)
    action_log.append(f"{villain_position} 3bets {threebet_size} BB")

    # Players after villain (if any before hero acts again) — none in standard case
    # Hero now acts

    gto_ev = get_ev(range_data, "vs_3bet", hero_position, hand, villain_position)

    return {
        "spot": "vs_3bet",
        "hero_position": hero_position,
        "villain_position": villain_position,
        "hand": hand,
        "card1": card1,
        "card2": card2,
        "actions": actions,
        "rng": rng,
        "correct_action": correct_action,
        "available_actions": ["4bet", "call", "fold"],
        "gto_ev": gto_ev,
        "context": {
            "stacks": stacks,
            "pot": pot,
            "action_log": action_log,
            "open_raiser": hero_position,
            "open_size": OPEN_SIZE,
            "threebet_raiser": villain_position,
            "threebet_size": threebet_size,
            "hero_stack": stacks[hero_position],
        }
    }


def get_drill_hand_vs_4bet(range_data, hero_position, villain_position):
    """Return a drill question for a vs_4bet spot, or None if no data.

    Scenario: villain (the original opener) 4-bets after hero's 3-bet.
    hero_position = 3-bettor;  villain_position = 4-bettor / opener.
    Available actions: allin (5-bet) / call / fold.
    """
    expanded_range = get_vs_4bet_range(range_data, hero_position, villain_position)
    if not expanded_range:
        return None

    hand = random.choice(all_hands())
    actions = expanded_range.get(hand, {})

    rng = random.randint(0, 99)
    correct_action = resolve_mixed_action(actions, rng / 100.0)

    card1, card2 = generate_cards(hand)

    positions    = list(range_data["config"]["positions"])
    hero_idx     = positions.index(hero_position)
    villain_idx  = positions.index(villain_position)

    stacks = {pos: STARTING_STACK for pos in positions}
    stacks["SB"] = round(stacks["SB"] - SB, 1)
    stacks["BB"] = round(stacks["BB"] - BB, 1)

    pot = round(SB + BB, 1)
    action_log = []

    # 1. Everyone before villain (opener) folds
    for pos in positions[:villain_idx]:
        action_log.append(f"{pos} folds")

    # 2. Villain opens
    stacks[villain_position] = round(stacks[villain_position] - OPEN_SIZE, 1)
    pot = round(pot + OPEN_SIZE, 1)
    action_log.append(f"{villain_position} opens {OPEN_SIZE} BB")

    # 3. Between villain and hero fold
    for pos in positions[villain_idx + 1:hero_idx]:
        action_log.append(f"{pos} folds")

    # 4. Hero 3-bets
    threebet_size = round(OPEN_SIZE * THREEBET_MULT, 1)
    stacks[hero_position] = round(stacks[hero_position] - threebet_size, 1)
    pot = round(pot + threebet_size, 1)
    action_log.append(f"{hero_position} 3bets {threebet_size} BB")

    # 5. Players after hero and before villain (wrapping) fold: positions[hero_idx+1:]
    #    plus positions[:villain_idx] (those fold, they were before villain in order)
    for pos in positions[hero_idx + 1:] + positions[:villain_idx]:
        action_log.append(f"{pos} folds")

    # 6. Villain 4-bets (total size from 100bb; additional chips beyond the open)
    fourbet_size = round(OPEN_SIZE * THREEBET_MULT * FOURBET_MULT, 1)
    fourbet_additional = round(fourbet_size - OPEN_SIZE, 1)
    stacks[villain_position] = round(stacks[villain_position] - fourbet_additional, 1)
    pot = round(pot + fourbet_additional, 1)
    action_log.append(f"{villain_position} 4bets {fourbet_size} BB")

    gto_ev = get_ev(range_data, "vs_4bet", hero_position, hand, villain_position)

    return {
        "spot": "vs_4bet",
        "hero_position": hero_position,
        "villain_position": villain_position,
        "hand": hand,
        "card1": card1,
        "card2": card2,
        "actions": actions,
        "rng": rng,
        "correct_action": correct_action,
        "available_actions": ["allin", "call", "fold"],
        "gto_ev": gto_ev,
        "context": {
            "stacks": stacks,
            "pot": round(pot, 1),
            "action_log": action_log,
            "open_raiser": hero_position,      # hero was the 3-bettor after villain opened
            "open_size": OPEN_SIZE,
            "threebet_raiser": hero_position,
            "threebet_size": threebet_size,
            "fourbet_raiser": villain_position,
            "fourbet_size": fourbet_size,
            "hero_stack": stacks[hero_position],
        }
    }


def get_drill_hand_iso(range_data, hero_position, villain_position):
    """Return a drill question for an iso spot, or None if no data.

    Scenario: villain limps (calls 1 BB), hero can iso-raise, over-limp, or fold.
    hero_position = iso-raiser candidate;  villain_position = limper.
    Available actions: raise (iso) / call (over-limp) / fold.
    """
    expanded_range = get_iso_range(range_data, hero_position, villain_position)
    if not expanded_range:
        return None

    hand = random.choice(all_hands())
    actions = expanded_range.get(hand, {})

    rng = random.randint(0, 99)
    correct_action = resolve_mixed_action(actions, rng / 100.0)

    card1, card2 = generate_cards(hand)

    positions   = list(range_data["config"]["positions"])
    hero_idx    = positions.index(hero_position)
    villain_idx = positions.index(villain_position)

    stacks = {pos: STARTING_STACK for pos in positions}
    stacks["SB"] = round(stacks["SB"] - SB, 1)
    stacks["BB"] = round(stacks["BB"] - BB, 1)

    pot = round(SB + BB, 1)
    action_log = []

    # 1. Players before the limper fold
    for pos in positions[:villain_idx]:
        action_log.append(f"{pos} folds")

    # 2. Villain limps (calls 1 BB)
    stacks[villain_position] = round(stacks[villain_position] - BB, 1)
    pot = round(pot + BB, 1)
    action_log.append(f"{villain_position} limps {BB} BB")

    # 3. Players between limper and hero fold
    for pos in positions[villain_idx + 1:hero_idx]:
        action_log.append(f"{pos} folds")

    gto_ev = get_ev(range_data, "iso", hero_position, hand, villain_position)

    return {
        "spot": "iso",
        "hero_position": hero_position,
        "villain_position": villain_position,
        "hand": hand,
        "card1": card1,
        "card2": card2,
        "actions": actions,
        "rng": rng,
        "correct_action": correct_action,
        "available_actions": ["raise", "call", "fold"],
        "gto_ev": gto_ev,
        "context": {
            "stacks": stacks,
            "pot": round(pot, 1),
            "action_log": action_log,
            "open_raiser": villain_position,   # limper is the "raiser" for chip rendering
            "open_size": BB,                   # limp = 1 BB
            "hero_stack": stacks[hero_position],
        }
    }


# ---------- answer checker ----------

def check_answer(drill_hand, player_action, is_timeout=False):
    """
    Grade the player's action against the strategy.

    Decision #8 (amended) / #7: Practice grades by STRATEGY MEMBERSHIP, not by
    the RNG roll. Any action with frequency > 0 (implicit fold included) is
    correct. `dominant_action` gives the main line shown on a wrong answer.
    """
    spot = drill_hand["spot"]
    actions = drill_hand.get("actions", {})
    main_line = dominant_action(actions)
    gto_ev = drill_hand.get("gto_ev")   # real EV from the json `ev` block, or None

    # Timeout always counts as wrong (you let the clock run out). No EV pill.
    if is_timeout:
        return {
            "correct": False,
            "player_action": "timeout",
            "correct_action": main_line,
            "ev": None,
            "message": f"⏰ Time out! Correct: {main_line}.",
            "is_timeout": True,
        }

    correct = action_in_strategy(actions, player_action)
    mixed = len(strategy_with_fold(actions)) > 1

    # EV pill: ONLY a real number from the file's `ev` block, and only on a
    # correct non-fold action (fold EV is always 0 → nothing to show). No data
    # → None → the frontend hides the pill. No synthetic placeholders anywhere.
    ev = gto_ev if (correct and player_action != "fold") else None

    if spot == "RFI":
        if correct:
            message = (f"Correct — {player_action}. Mix: {mix_summary(actions)}."
                       if mixed else f"Correct — {player_action}.")
        else:
            message = (f"Wrong — not in strategy. Mix: {mix_summary(actions)}."
                       if mixed else f"Wrong — correct action: {main_line}.")

    elif spot in ("vs_RFI", "vs_3bet", "vs_4bet", "iso"):
        range_str = mix_summary(actions) if actions else "fold 100%"
        if correct:
            message = f"Correct — {player_action}. Range: {range_str}."
        else:
            message = f"Wrong — {main_line}. Range: {range_str}."

    else:
        correct = False
        ev = None
        message = "Unknown spot."

    return {
        "correct": correct,
        "player_action": player_action,
        "correct_action": main_line,
        "ev": round(ev, 2) if ev is not None else None,
        "message": message,
        "is_timeout": False,
    }