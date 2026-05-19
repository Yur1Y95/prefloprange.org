"""
equity_api.py — example of wiring equity.py into our FastAPI backend.

This is a drop-in router. In main.py you'd just do:

    from fastapi import FastAPI
    from equity_api import router as equity_router

    app = FastAPI()
    app.include_router(equity_router)

Then the frontend (drill.js / analyzer) can POST to /api/equity.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import equity  # our clean-room engine

router = APIRouter(prefix="/api", tags=["equity"])


class EquityRequest(BaseModel):
    hero: str                 # e.g. "AhKh"
    villain_range: list[str]  # e.g. ["22+", "ATs+", "AJo+"]  (or ["KhQd"] one combo)
    board: str = ""           # e.g. "Kh7s2d"  ("" for preflop)
    dead: str = ""            # folded/known cards to remove, optional
    iters: int = 8000         # 8k = ~0.15s, accuracy ~+-0.6%. Plenty for a trainer.


class EquityResponse(BaseModel):
    equity: float
    win: float
    tie: float
    loss: float
    samples: int
    method: str               # "exact" or "montecarlo"


@router.post("/equity", response_model=EquityResponse)
def calc_equity(req: EquityRequest):
    """Used by the postflop trainer: 'you have X on board Y vs villain's
    range — what's your equity?' The trainer compares the player's guess
    against this number to grade the answer."""
    try:
        # Cap iters so a user can't ask for a 10-minute computation on the server
        iters = max(1000, min(req.iters, 50000))
        result = equity.equity(
            hero=req.hero,
            villain_range=req.villain_range,
            board=req.board,
            dead=req.dead,
            iters=iters,
        )
        return result
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=f"Bad input: {e}")


# Quick local check without spinning up uvicorn:  python equity_api.py
if __name__ == "__main__":
    sample = EquityRequest(
        hero="AhKh",
        villain_range=["QQ+", "AKs"],
        board="Kc7d2s",
        iters=8000,
    )
    print(calc_equity(sample))