"""FastAPI router for the progress dashboard — Track D, Stage 2 (личный кабинет).

One job: expose GET /api/dashboard/overview — the per-user progress page data
(counters, streaks, activity calendar, accuracy by spot/position).

Follows the project convention "one module, one job": a router in its own file,
wired into main.py with a single include_router() line.

Auth: protected by Depends(auth.get_current_user). In auth mode the user_id is
the JWT subject (data is isolated per user); with auth off it is the dev user.
The frontend's fetch wrapper (auth_client.js) attaches the Bearer token because
this path is in its protected set.
"""
from fastapi import APIRouter, Depends

import auth
import dashboard_store

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(user=Depends(auth.get_current_user)) -> dict:
    """Everything the Progress page renders, in one payload.

    Returns ``{"available": False}`` when no database is configured (the
    dashboard is inherently DB-only — see dashboard_store). The endpoint itself
    never needs to special-case that; the store decides.
    """
    return dashboard_store.read_overview(user_id=user)
