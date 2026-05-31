"""
Preflop drill engine for NLH Range Trainer.
Handles: RFI, vs_RFI, vs_3bet spots with full preflop action context.
"""

import random
from range_engine import get_rfi_range, get_vs_rfi_range, get_vs_3bet_range, get_ev

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
SUITS = ["s", "h", "d", "c"]
SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

# ----- Game constants -----
BB = 1.0               # big blind in bb
SB = 0.5               # small blind in bb
OPEN_SIZE = 2.5        # standard open raise size in bb
STARTING_STACK = 100.0 # starting stack in bb

# ----- EV estimates (simplified, in bb) -----
EV_CORRECT_OPEN   =  0.15   # winning the blinds
EV_CORRECT_FOLD   =  0.0    # folding = 0 EV
EV_WRONG_FOLD     = -0.35   # folding a hand you should have played
EV_WRONG_PLAY     = -0.50   # playing a hand you should have folded
EV_TIMEOUT        = -0.25   # time out penalty


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
    priority = ["4bet", "3bet", "call", "open"]
    cumulative = 0.0
    for action in priority:
        freq = actions.get(action, 0)
        cumulative += freq
        if rng_fraction < cumulative:
            return action
    return "fold"


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


# ---------- answer checker ----------

def check_answer(drill_hand, player_action, is_timeout=False):
    """
    Compare the player's action to the correct one.
    Returns a result dict with correctness, EV and a feedback message.
    """
    correct_action = drill_hand["correct_action"]
    spot = drill_hand["spot"]

    # Timeout always counts as wrong
    if is_timeout:
        return {
            "correct": False,
            "player_action": "timeout",
            "correct_action": correct_action,
            "ev": EV_TIMEOUT,
            "message": f"⏰ Time out! Correct: {correct_action}.",
            "is_timeout": True,
        }

    correct = player_action == correct_action

    if spot == "RFI":
        # GTO EV display rules (locked with user):
        #   correct open  → show real GTO EV (None when the file has no data)
        #   correct fold  → no EV (folding is always 0 EV — nothing to show)
        #   any wrong     → no EV (we only store EV of the profitable action)
        # ev=None means the frontend hides the EV pill entirely.
        gto_ev = drill_hand.get("gto_ev")  # float bb, or None when no EV data

        if correct:
            if correct_action == "open":
                ev = gto_ev
                message = "Correct — open."
            else:
                ev = None
                message = "Correct — fold."
        else:
            ev = None
            message = f"Wrong — correct action: {correct_action}."

    elif spot in ("vs_RFI", "vs_3bet"):
        actions = drill_hand.get("actions", {})
        parts = [f"{a} {int(f * 100)}%" for a, f in actions.items() if f > 0]
        range_str = ", ".join(parts) if parts else "fold 100%"

        if correct:
            ev = EV_CORRECT_OPEN
            message = f"Correct — {correct_action}. Range: {range_str}."
        else:
            ev = EV_WRONG_PLAY if player_action != "fold" else EV_WRONG_FOLD
            message = f"Wrong — {correct_action}. Range: {range_str}."

    else:
        correct = False
        ev = 0.0
        message = "Unknown spot."

    return {
        "correct": correct,
        "player_action": player_action,
        "correct_action": correct_action,
        "ev": round(ev, 2) if ev is not None else None,
        "message": message,
        "is_timeout": False,
    }