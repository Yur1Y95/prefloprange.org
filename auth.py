"""Auth — verify Supabase JWTs and resolve the request's user_id.

Track D, D.2. Single responsibility: turn an incoming request's Authorization
header into a trusted user UUID. This is the one place that decides "whose data
is this request about". The storage layer (journal / cards_store / stats_store)
takes that UUID instead of the fixed dev user.

Two modes, gated by the SUPABASE_URL env var (mirrors db.py's DATABASE_URL gate):
  * SUPABASE_URL set   -> auth ACTIVE. Every protected endpoint requires a valid
    Bearer JWT signed by this Supabase project. We verify the signature with the
    project's PUBLIC JWKS key (asymmetric ES256 — there is NO secret to hold),
    check issuer / audience / expiry, and return the token's `sub` claim as the
    user_id. A missing or invalid token -> 401.
  * SUPABASE_URL unset -> auth INACTIVE (the mandated soft degradation).
    resolve_user returns the fixed dev user (journal.DEV_USER_ID), so a local
    run and the current Railway prod (which has no SUPABASE_URL) keep working
    with no login, exactly as before. The same kind of single env-var switch
    that db.py uses for storage.

Why asymmetric / JWKS and not a shared secret: Supabase signs new projects'
tokens with ES256 (public-key crypto) by default. We fetch the PUBLIC key from
the project's JWKS endpoint and verify locally — so the backend holds no JWT
secret at all. The project ref / URL / anon key that this needs are all public
by design. The DB password (DATABASE_URL) and service_role key are real secrets
and live only in the environment; neither is read here.

Design for testability: the only part that needs PyJWT + network (decode_claims)
is isolated behind a thin function, and resolve_user accepts an injectable
`decoder`. So the gating, header parsing and claim-to-UUID logic are pure and
unit-testable with the stdlib (the sandbox has neither fastapi nor PyJWT); the
real ES256/JWKS verification is exercised live.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Callable, Optional

import journal  # reuse the single dev-user identity for the no-auth fallback

log = logging.getLogger("auth")

# FastAPI is present in the app runtime but NOT in the test sandbox. Import it
# guarded so `import auth` works either way; the dependency below only needs it
# at request time (and the route wiring resolves the Request annotation then).
try:  # pragma: no cover - trivial import guard
    from fastapi import Request, HTTPException
except ImportError:  # sandbox / pure-logic tests
    Request = None        # type: ignore
    HTTPException = None   # type: ignore


# Supabase puts this fixed audience on a logged-in user's access token.
_EXPECTED_AUDIENCE = "authenticated"
# Asymmetric algorithms only. NEVER list HS256 here: the JWKS key is a PUBLIC
# key, and allowing a symmetric alg alongside it opens an algorithm-confusion
# attack. Supabase's asymmetric default is ES256; RS256 is included for safety.
_ALLOWED_ALGS = ["ES256", "RS256"]


class AuthError(Exception):
    """Raised by the pure core when a request is not authenticated.

    Kept framework-free (no fastapi import) so the core is testable in the
    sandbox; the FastAPI dependency translates it into an HTTPException.
    """

    def __init__(self, detail: str, status_code: int = 401):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Configuration (all public — no secrets). Read live so tests can toggle env.
# ---------------------------------------------------------------------------

def auth_enabled() -> bool:
    """True when SUPABASE_URL is set — i.e. login is required and enforced."""
    return bool(os.environ.get("SUPABASE_URL"))


def _supabase_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/")


def _issuer() -> str:
    """The `iss` claim Supabase stamps on its tokens."""
    return f"{_supabase_url()}/auth/v1"


def _jwks_url() -> str:
    """Public JWKS discovery endpoint — serves the verification public key."""
    return f"{_supabase_url()}/auth/v1/.well-known/jwks.json"


# ---------------------------------------------------------------------------
# Pure helpers (no fastapi, no PyJWT) — unit-tested in the sandbox.
# ---------------------------------------------------------------------------

def extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Pull the token out of an ``Authorization: Bearer <token>`` header.

    Case-insensitive scheme; returns None for anything that is not a non-empty
    bearer token (missing header, wrong scheme, empty token).
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


# ---------------------------------------------------------------------------
# The thin PyJWT/JWKS path — verifies signature + claims. Not unit-tested in the
# sandbox (needs PyJWT + network); exercised live.
# ---------------------------------------------------------------------------

_jwks_client = None  # PyJWKClient caches keys internally; we cache the client.


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient  # lazy: PyJWT only needed when auth is live
        _jwks_client = PyJWKClient(_jwks_url())
    return _jwks_client


def decode_claims(token: str) -> dict:
    """Verify a Supabase JWT and return its claims, or raise.

    Looks up the right public key by the token's `kid` via JWKS, then verifies
    the ES256/RS256 signature, audience, issuer and expiry locally.
    """
    import jwt  # PyJWT (+ cryptography for ES256); lazy for the same reason
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_ALLOWED_ALGS,
        audience=_EXPECTED_AUDIENCE,
        issuer=_issuer(),
        options={"require": ["exp", "sub"]},
    )


# ---------------------------------------------------------------------------
# The core resolver. Pure except for the injected decoder; raises AuthError.
# ---------------------------------------------------------------------------

def resolve_user(
    authorization: Optional[str],
    *,
    decoder: Optional[Callable[[str], dict]] = None,
) -> uuid.UUID:
    """Resolve the request's user UUID from its Authorization header.

    * Auth inactive (no SUPABASE_URL) -> the fixed dev user (no login needed).
    * Auth active -> require a valid bearer JWT; return its `sub` as a UUID.
      Missing token / bad signature / bad claims / non-UUID sub -> AuthError(401).

    `decoder` is injectable so tests can stand in for the live PyJWT/JWKS path.
    """
    if not auth_enabled():
        return journal.DEV_USER_ID

    token = extract_bearer(authorization)
    if not token:
        raise AuthError("Missing or malformed Authorization bearer token")

    decode = decoder or decode_claims
    try:
        claims = decode(token)
    except AuthError:
        raise
    except Exception as e:  # PyJWT verification errors, network, etc.
        # Log type+message only; tokens/keys are never logged.
        log.warning("JWT verification failed (%s: %s)", type(e).__name__, e)
        raise AuthError("Invalid or expired token")

    sub = claims.get("sub") if isinstance(claims, dict) else None
    try:
        return uuid.UUID(str(sub))
    except (ValueError, AttributeError, TypeError):
        raise AuthError("Token has no valid subject (sub) claim")


# ---------------------------------------------------------------------------
# The FastAPI dependency. Thin wrapper: read the header, translate AuthError to
# an HTTP 401. Uses Request (not a Header default) so the module imports cleanly
# even where fastapi is absent (deferred annotations keep `Request` unresolved
# until FastAPI wires the route in the real app).
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> uuid.UUID:
    """FastAPI dependency: the authenticated user's UUID (or the dev user)."""
    try:
        return resolve_user(request.headers.get("authorization"))
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
