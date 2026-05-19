"""
decision.py — postflop trainer decision logic (cash, fold/call only).

Builds on equity.py. Given a spot, it works out the mathematically correct
action by comparing the player's equity vs the pot odds being offered.

This is deliberately NOT a GTO solver. It answers exactly one question:
"Given hero's equity against villain's range, is calling +EV on a pure
pot-odds basis?" No fold equity, no implied odds, no future streets.
That is the right scope for grinding discipline at micro stakes.

Public API (what the FastAPI layer will call):

    grade_spot(spot, player_action) -> verdict dict

A `spot` is a plain dict:
    {
      "hero": "AhKh",
      "board": "Kc7d2s",
      "villain_range": ["22+", "ATs+", "AJo+"],   # notation list
      "pot": 10.0,          # chips/bb already in the middle
      "to_call": 5.0,       # what villain bet that hero must call
      "iters": 8000         # optional, MC accuracy knob
    }
"""

from __future__ import annotations
import equity


def required_equity(pot: float, to_call: float) -> float:
    """Pot odds as a break-even equity threshold.

    Hero invests `to_call` to win the current `pot` plus villain's bet
    (which is already part of `pot` if you defined pot as the total he'd
    win). We use the standard formulation: hero must win at least
        to_call / (pot + to_call)
    of the time for a call to break even, where `pot` is the size BEFORE
    hero puts his call in (i.e. it already includes villain's bet).
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


def grade_spot(spot: dict, player_action: str) -> dict:
    """Return a full verdict for the trainer UI.

    player_action: "fold" or "call"
    """
    action = player_action.strip().lower()
    if action not in ("fold", "call"):
        raise ValueError("player_action must be 'fold' or 'call'")

    pot = float(spot["pot"])
    to_call = float(spot["to_call"])
    if pot < 0 or to_call < 0:
        raise ValueError("pot and to_call must be non-negative")

    eq_result = equity.equity(
        hero=spot["hero"],
        villain_range=spot["villain_range"],
        board=spot.get("board", ""),
        dead=spot.get("dead", ""),
        iters=int(spot.get("iters", 8000)),
    )
    hero_eq = eq_result["equity"]
    need = required_equity(pot, to_call)

    correct_action = "call" if hero_eq >= need else "fold"
    is_correct = (action == correct_action)

    # EV of calling, in the same chip unit as pot/to_call.
    # Win -> gain `pot`; lose -> lose `to_call`. (Ties handled via equity
    # already folding tie/2 into hero_eq, which is a fair approximation
    # for chip EV at the pot-odds level we operate on.)
    ev_call = hero_eq * pot - (1.0 - hero_eq) * to_call
    # Folding is the zero baseline (hero forfeits only money already in
    # the pot, which is sunk and not counted here).
    ev_fold = 0.0

    # EV of *the player's actual decision*, measured against the alternative
    # they could have picked. This is what we want to surface in the UI:
    #   right choice  → positive (how much you gained by playing correctly)
    #   wrong choice  → negative (how much you lost by playing incorrectly)
    # Always equals ±|ev_call - ev_fold|, signed by whether the action matched.
    if action == "call":
        ev_decision = ev_call - ev_fold
    else:
        ev_decision = ev_fold - ev_call

    edge = hero_eq - need  # how much equity to spare (negative = should fold)

    return {
        "correct_action": correct_action,
        "player_action": action,
        "is_correct": is_correct,
        "hero_equity": round(hero_eq, 4),
        "required_equity": round(need, 4),
        "equity_edge": round(edge, 4),
        "ev_call": round(ev_call, 3),
        "ev_fold": ev_fold,
        "ev_decision": round(ev_decision, 3),
        "method": eq_result["method"],
        "samples": eq_result["samples"],
        "explain": _explain(hero_eq, need, correct_action, pot, to_call),
    }


def _explain(hero_eq: float, need: float, correct: str,
             pot: float, to_call: float) -> str:
    """Plain-language feedback string shown to the player after answering."""
    eq_pct = hero_eq * 100
    need_pct = need * 100
    if correct == "call":
        return (f"Call is correct. You need {need_pct:.1f}% equity to call "
                f"{to_call:g} into {pot:g}, and you have ~{eq_pct:.1f}% "
                f"against this range — a profitable call.")
    return (f"Fold is correct. Calling {to_call:g} into {pot:g} needs "
            f"{need_pct:.1f}% equity, but you only have ~{eq_pct:.1f}% "
            f"against this range — calling loses money long-term.")


# --- local sanity check: python decision.py ---
if __name__ == "__main__":
    spots = [
        # Strong hand, small bet -> clear call
        {"name": "Top set vs flush draw, half pot",
         "hero": "KsKh", "board": "Ks7d2h",
         "villain_range": ["AhQh", "JhTh", "9h8h", "AdKd"],
         "pot": 10, "to_call": 5},
        # Weak hand vs tight range, big bet -> clear fold
        {"name": "2nd pair vs nit jam",
         "hero": "Ad9d", "board": "Kc9s4h",
         "villain_range": ["KK", "99", "44", "AK", "KQs"],
         "pot": 12, "to_call": 24},
        # Marginal -> tests the threshold
        {"name": "Flush draw, getting 3:1",
         "hero": "Ah5h", "board": "Kh8h2c",
         "villain_range": ["KQ", "KJ", "KT", "AK", "88", "22"],
         "pot": 15, "to_call": 5},
    ]
    for s in spots:
        name = s.pop("name")
        v = grade_spot(s, "call")
        print(f"{name}")
        print(f"  hero eq {v['hero_equity']*100:5.1f}%  "
              f"need {v['required_equity']*100:5.1f}%  "
              f"-> correct: {v['correct_action'].upper()}  "
              f"[{v['method']}]")
        print(f"  {v['explain']}\n")