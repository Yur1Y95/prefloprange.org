"""
postflop_api.py — FastAPI router for the postflop cash trainer.

Wire into main.py with two lines:

    from postflop_api import router as postflop_router
    app.include_router(postflop_router)

Endpoints:
    GET  /api/postflop/spot?villain_type=fish   -> a new spot (no answer leaked)
    POST /api/postflop/answer                    -> grade fold/call

The spot returned to the browser deliberately OMITS the villain's
range — the player must read the villain TYPE. The server keeps the
range server-side and only reveals reasoning after the answer.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import secrets

import postflop_engine

router = APIRouter(prefix="/api/postflop", tags=["postflop"])

# In-memory store of live spots keyed by a token, so the answer can't
# be reverse-engineered from the client. Cleared on server restart;
# fine for a single-user local trainer. Swap for a real store later.
_LIVE_SPOTS: dict[str, dict] = {}
_MAX_LIVE = 500


class SpotOut(BaseModel):
    token: str
    hero: str
    board: str
    hero_pos: str
    villain_pos: str
    villain_label: str
    villain_desc: str
    pot: float
    to_call: float


class AnswerIn(BaseModel):
    token: str
    action: str  # "fold" | "call"


@router.get("/spot", response_model=SpotOut)
def new_spot(villain_type: str | None = None):
    """Deal a fresh flop spot. Villain range stays server-side."""
    try:
        spot = postflop_engine.generate_spot(villain_type=villain_type)
    except KeyError:
        raise HTTPException(400, f"Unknown villain_type: {villain_type}")

    token = secrets.token_urlsafe(12)
    # Bound memory: drop oldest if over cap
    if len(_LIVE_SPOTS) >= _MAX_LIVE:
        _LIVE_SPOTS.pop(next(iter(_LIVE_SPOTS)))
    _LIVE_SPOTS[token] = spot

    return SpotOut(
        token=token,
        hero=spot["hero"],
        board=spot["board"],
        hero_pos=spot["hero_pos"],
        villain_pos=spot["villain_pos"],
        villain_label=spot["villain_label"],
        villain_desc=spot["villain_desc"],
        pot=spot["pot"],
        to_call=spot["to_call"],
    )


@router.post("/answer")
def answer(payload: AnswerIn):
    """Grade the player's fold/call for a previously dealt spot."""
    spot = _LIVE_SPOTS.pop(payload.token, None)
    if spot is None:
        raise HTTPException(404, "Spot expired or already answered. "
                                 "Deal a new one.")
    act = payload.action.strip().lower()
    if act not in ("fold", "call"):
        raise HTTPException(400, "action must be 'fold' or 'call'")
    return postflop_engine.grade(spot, act)


if __name__ == "__main__":
    # Smoke test without uvicorn
    s = new_spot(villain_type="fish")
    print("dealt:", s.hero, s.board, s.villain_label, s.pot, s.to_call)
    r = answer(AnswerIn(token=s.token, action="call"))
    print("graded:", r["is_correct"], r["correct_action"],
          round(r["hero_equity"], 3), "-", r["explain"])