"""FastAPI router for auth configuration — Track D, D.2.

One job: expose GET /api/auth/config so the frontend knows whether login is
active and, if so, how to initialise supabase-js.

Everything returned here is PUBLIC by design:
  * url       — the project's Supabase URL (the project ref is visible in the
                dashboard URL; not a secret).
  * anon_key  — the anon / publishable key, which Supabase ships specifically
                for use in client code. NOT the service_role key (that one is a
                secret and is never read or returned anywhere).

When SUPABASE_URL is unset the app runs single-user with no login (the mandated
soft degradation), so this returns ``enabled: false`` and the frontend skips the
login gate entirely — current prod (no SUPABASE_URL) is unaffected.

Follows the project convention "one module, one job": a router in its own file,
wired into main.py with a single include_router() line.
"""
import os

from fastapi import APIRouter

import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    """Public Supabase config for the frontend (no secrets).

    ``enabled`` mirrors the backend's enforcement gate (auth.auth_enabled(),
    keyed on SUPABASE_URL): when true, protected endpoints require a valid JWT,
    so the frontend must show the login gate. ``anon_key`` may be empty if it was
    not configured — that is a deploy misconfiguration the frontend surfaces
    rather than silently bypassing login.
    """
    if not auth.auth_enabled():
        return {"enabled": False}
    return {
        "enabled":  True,
        "url":      os.environ["SUPABASE_URL"].rstrip("/"),
        "anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
    }
