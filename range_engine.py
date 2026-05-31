import json


RANKS_ASC = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
RANKS_DESC = list(reversed(RANKS_ASC))

TOTAL_HOLDEM_COMBOS = 1326


def load_range_file(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def rank_value(rank):
    return RANKS_ASC.index(rank)


def normalize_hand(card1, card2, suffix=""):
    if card1 == card2:
        return card1 + card2

    if rank_value(card1) > rank_value(card2):
        return card1 + card2 + suffix

    return card2 + card1 + suffix


def combo_count(hand):
    if len(hand) == 2:
        return 6

    if hand.endswith("s"):
        return 4

    if hand.endswith("o"):
        return 12

    raise ValueError(f"Неизвестный формат руки: {hand}")


def expand_pair_plus(notation):
    start_rank = notation[0]
    result = []

    for rank in RANKS_ASC:
        if rank_value(rank) >= rank_value(start_rank):
            result.append(rank + rank)

    return result


def expand_pair_range(notation):
    start, end = notation.split("-")

    start_rank = start[0]
    end_rank = end[0]

    high_value = max(rank_value(start_rank), rank_value(end_rank))
    low_value = min(rank_value(start_rank), rank_value(end_rank))

    result = []

    for rank in RANKS_DESC:
        value = rank_value(rank)

        if low_value <= value <= high_value:
            result.append(rank + rank)

    return result


def expand_non_pair_plus(notation):
    high_card = notation[0]
    start_kicker = notation[1]
    suffix = notation[2]

    result = []

    high_card_value = rank_value(high_card)
    start_kicker_value = rank_value(start_kicker)

    for kicker in RANKS_ASC:
        kicker_value = rank_value(kicker)

        if start_kicker_value <= kicker_value < high_card_value:
            result.append(normalize_hand(high_card, kicker, suffix))

    return result


def expand_non_pair_range(notation):
    start, end = notation.split("-")

    start_high = start[0]
    start_kicker = start[1]
    start_suffix = start[2]

    end_high = end[0]
    end_kicker = end[1]
    end_suffix = end[2]

    if start_high != end_high:
        raise ValueError(f"Разные старшие карты в диапазоне: {notation}")

    if start_suffix != end_suffix:
        raise ValueError(f"Разные типы suited/offsuit в диапазоне: {notation}")

    high_value = max(rank_value(start_kicker), rank_value(end_kicker))
    low_value = min(rank_value(start_kicker), rank_value(end_kicker))

    result = []

    for kicker in RANKS_DESC:
        value = rank_value(kicker)

        if low_value <= value <= high_value:
            result.append(normalize_hand(start_high, kicker, start_suffix))

    return result


def expand_notation(notation):
    notation = notation.strip()

    # AA, KK, QQ
    if len(notation) == 2 and notation[0] == notation[1]:
        return [notation]

    # AKs, AKo
    if len(notation) == 3 and notation[2] in ["s", "o"]:
        return [notation]

    # 55+
    if len(notation) == 3 and notation[0] == notation[1] and notation[2] == "+":
        return expand_pair_plus(notation)

    # A2s+, KTs+, AJo+
    if len(notation) == 4 and notation[-1] == "+":
        return expand_non_pair_plus(notation)

    # 99-22, A5s-A2s
    if "-" in notation:
        start, end = notation.split("-")

        if len(start) == 2 and len(end) == 2:
            return expand_pair_range(notation)

        if len(start) == 3 and len(end) == 3:
            return expand_non_pair_range(notation)

    raise ValueError(f"Не удалось распознать запись диапазона: {notation}")


def expand_rfi_range(raw_range):
    """
    Supports two formats:
    - Old (cash): {notation: frequency}          → {hand: frequency}
    - New (MTT):  {notation: {action: frequency}} → {hand: {action: frequency}}
    """
    expanded = {}

    for notation, value in raw_range.items():
        hands = expand_notation(notation)

        if isinstance(value, dict):
            # New multi-action format
            for hand in hands:
                if hand not in expanded:
                    expanded[hand] = {}
                for action, frequency in value.items():
                    current = expanded[hand].get(action, 0)
                    expanded[hand][action] = max(current, frequency)
        else:
            # Old single-frequency format
            for hand in hands:
                if isinstance(expanded.get(hand), dict):
                    expanded[hand]['open'] = max(expanded[hand].get('open', 0), value)
                else:
                    current = expanded.get(hand, 0)
                    expanded[hand] = max(current, value)

    return expanded


def is_multiaction_rfi(expanded_range):
    """Return True if the RFI range uses the new multi-action format."""
    for v in expanded_range.values():
        return isinstance(v, dict)
    return False


def calculate_rfi_stats(expanded_range):
    total_combos = 0

    for hand, value in expanded_range.items():
        if isinstance(value, dict):
            # Sum all action frequencies, cap at 1.0
            freq = min(1.0, sum(value.values()))
        else:
            freq = value
        total_combos += combo_count(hand) * freq

    percent = total_combos / TOTAL_HOLDEM_COMBOS * 100

    return {
        "combos": round(total_combos, 1),
        "percent": round(percent, 2)
    }


def expand_action_range(raw_range):
    expanded = {}

    for notation, actions in raw_range.items():
        hands = expand_notation(notation)

        for hand in hands:
            if hand not in expanded:
                expanded[hand] = {}

            for action, frequency in actions.items():
                current_frequency = expanded[hand].get(action, 0)
                expanded[hand][action] = max(current_frequency, frequency)

    return expanded


def calculate_rfi_stats(expanded_range):
    total_combos = 0

    for hand, frequency in expanded_range.items():
        total_combos += combo_count(hand) * frequency

    percent = total_combos / TOTAL_HOLDEM_COMBOS * 100

    return {
        "combos": round(total_combos, 1),
        "percent": round(percent, 2)
    }


def calculate_action_stats(expanded_range, action):
    total_combos = 0

    for hand, actions in expanded_range.items():
        frequency = actions.get(action, 0)
        total_combos += combo_count(hand) * frequency

    percent = total_combos / TOTAL_HOLDEM_COMBOS * 100

    return {
        "action": action,
        "combos": round(total_combos, 1),
        "percent": round(percent, 2)
    }


# P-011: soft lookups — a position/villain that exists in `config` but has no
# data in `spots` returns an empty range ({}) instead of raising KeyError. The
# caller (drill_engine) treats {} as "no data" and surfaces a clean 404.
def get_rfi_range(data, position):
    raw_range = data.get("spots", {}).get("RFI", {}).get(position)
    if not raw_range:
        return {}
    return expand_rfi_range(raw_range)


def get_vs_rfi_range(data, hero_position, villain_position):
    key = f"vs_{villain_position}"
    raw_range = data.get("spots", {}).get("vs_RFI", {}).get(hero_position, {}).get(key)
    if not raw_range:
        return {}
    return expand_action_range(raw_range)


def get_vs_3bet_range(data, hero_position, villain_position):
    key = f"vs_{villain_position}"
    raw_range = data.get("spots", {}).get("vs_3bet", {}).get(hero_position, {}).get(key)
    if not raw_range:
        return {}
    return expand_action_range(raw_range)


def get_ev(data, spot, position, hand, villain_position=None):
    """
    Look up the precomputed GTO EV (in bb) of the profitable action for a hand.

    EV lives in an OPTIONAL top-level `ev` block kept separate from `spots`, so
    strategy iteration (combos, mixed-action resolution, the hint matrix) never
    sees it. Layout mirrors `spots`:

        "ev": {
          "RFI":    { "UTG": { "AA": 2.31, "AKs": 1.85, ... } },
          "vs_RFI": { "SB":  { "vs_UTG": { "AKs": 1.2, ... } } }
        }

    Returns the EV as float, or None when the file has no `ev` block, no entry
    for this spot/position, or no number for this hand. None means "show no EV"
    — the trainer falls back to plain correct/wrong feedback.
    """
    ev_block = data.get("ev")
    if not isinstance(ev_block, dict):
        return None

    spot_block = ev_block.get(spot)
    if not isinstance(spot_block, dict):
        return None

    pos_block = spot_block.get(position)
    if not isinstance(pos_block, dict):
        return None

    if spot == "RFI":
        value = pos_block.get(hand)
    else:
        if not villain_position:
            return None
        key = f"vs_{villain_position}"
        sub = pos_block.get(key)
        value = sub.get(hand) if isinstance(sub, dict) else None

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_action_view(expanded_range, action):
    view = {}

    for hand, actions in expanded_range.items():
        frequency = actions.get(action, 0)

        if frequency > 0:
            view[hand] = frequency

    return view