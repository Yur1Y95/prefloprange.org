"""FastAPI router for database health — Track D, D.1-api.

One job: expose GET /api/db/health so we can confirm the app can reach the
Supabase Postgres. Read-only; returns no secrets.

Follows the project convention "one module, one job": a router in its own file,
wired into main.py with a single include_router() line.
"""
from fastapi import APIRouter

import db

router = APIRouter(prefix="/api/db", tags=["db"])


@router.get("/health")
def db_health() -> dict:
    """Report whether the DB is configured and reachable.

    Never raises: on any driver/connection error we return ok=False with the
    error text (psycopg does not include the password in its error messages),
    so the endpoint is safe to hit from a browser while wiring things up.
    """
    try:
        return db.ping()
    except Exception as e:
        return {
            "ok": False,
            "configured": db.database_configured(),
            "error": f"{type(e).__name__}: {e}",
        }
