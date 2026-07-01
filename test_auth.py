"""Unit tests for auth.py — the pure core (gating, header parsing, sub->UUID).

Stdlib only, no pytest, no fastapi, no PyJWT — runnable in the sandbox as
``python3 test_auth.py``. The live ES256/JWKS verification (decode_claims) is
NOT covered here (needs PyJWT + network); it is exercised live. We test the
logic around it by injecting a fake decoder into resolve_user.
"""
import os
import uuid

import auth


# --- tiny harness -----------------------------------------------------------
_failures = []


def check(name, cond):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}")
        _failures.append(name)


class _env:
    """Temporarily set/unset SUPABASE_URL, restoring the previous value."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.prev = os.environ.get("SUPABASE_URL")
        if self.value is None:
            os.environ.pop("SUPABASE_URL", None)
        else:
            os.environ["SUPABASE_URL"] = self.value

    def __exit__(self, *a):
        if self.prev is None:
            os.environ.pop("SUPABASE_URL", None)
        else:
            os.environ["SUPABASE_URL"] = self.prev


# --- extract_bearer ---------------------------------------------------------

def test_extract_bearer():
    check("bearer token", auth.extract_bearer("Bearer abc.def.ghi") == "abc.def.ghi")
    check("scheme case-insensitive", auth.extract_bearer("bearer xyz") == "xyz")
    check("none header", auth.extract_bearer(None) is None)
    check("empty header", auth.extract_bearer("") is None)
    check("wrong scheme", auth.extract_bearer("Basic abc") is None)
    check("scheme only", auth.extract_bearer("Bearer") is None)
    check("empty token", auth.extract_bearer("Bearer   ") is None)
    check("extra spaces kept-token", auth.extract_bearer("Bearer   tok") == "tok")


# --- auth_enabled -----------------------------------------------------------

def test_auth_enabled():
    with _env(None):
        check("disabled when unset", auth.auth_enabled() is False)
    with _env("https://proj.supabase.co"):
        check("enabled when set", auth.auth_enabled() is True)
    with _env(""):
        check("disabled when empty", auth.auth_enabled() is False)


# --- resolve_user: JSON / no-auth mode --------------------------------------

def test_resolve_user_json_mode_returns_dev_user():
    with _env(None):
        # No header, any header — both yield the dev user, no decoding.
        check("no token -> dev user",
              auth.resolve_user(None) == journal_dev())
        check("ignores header in json mode",
              auth.resolve_user("Bearer whatever") == journal_dev())


def journal_dev():
    import journal
    return journal.DEV_USER_ID


# --- resolve_user: DB / auth-active mode ------------------------------------

def test_resolve_user_db_mode_requires_token():
    with _env("https://proj.supabase.co"):
        raised = False
        try:
            auth.resolve_user(None)
        except auth.AuthError as e:
            raised = True
            check("401 status on missing token", e.status_code == 401)
        check("missing token -> AuthError", raised)


def test_resolve_user_db_mode_valid_sub():
    uid = uuid.uuid4()

    def fake_decoder(token):
        check("decoder receives the token", token == "tok123")
        return {"sub": str(uid), "aud": "authenticated"}

    with _env("https://proj.supabase.co"):
        got = auth.resolve_user("Bearer tok123", decoder=fake_decoder)
        check("valid sub -> matching UUID", got == uid)


def test_resolve_user_db_mode_decoder_raises():
    def boom(token):
        raise ValueError("bad signature")

    with _env("https://proj.supabase.co"):
        raised = False
        try:
            auth.resolve_user("Bearer tok", decoder=boom)
        except auth.AuthError:
            raised = True
        check("decoder failure -> AuthError", raised)


def test_resolve_user_db_mode_autherror_passthrough():
    def deny(token):
        raise auth.AuthError("custom denial", status_code=403)

    with _env("https://proj.supabase.co"):
        code = None
        try:
            auth.resolve_user("Bearer tok", decoder=deny)
        except auth.AuthError as e:
            code = e.status_code
        check("decoder AuthError preserved (403)", code == 403)


def test_resolve_user_db_mode_non_uuid_sub():
    def decoder(token):
        return {"sub": "not-a-uuid"}

    with _env("https://proj.supabase.co"):
        raised = False
        try:
            auth.resolve_user("Bearer tok", decoder=decoder)
        except auth.AuthError:
            raised = True
        check("non-uuid sub -> AuthError", raised)


def test_resolve_user_db_mode_missing_sub():
    def decoder(token):
        return {"aud": "authenticated"}  # no sub

    with _env("https://proj.supabase.co"):
        raised = False
        try:
            auth.resolve_user("Bearer tok", decoder=decoder)
        except auth.AuthError:
            raised = True
        check("missing sub -> AuthError", raised)


def test_config_helpers():
    with _env("https://proj.supabase.co/"):  # trailing slash must be stripped
        check("issuer", auth._issuer() == "https://proj.supabase.co/auth/v1")
        check("jwks url",
              auth._jwks_url() == "https://proj.supabase.co/auth/v1/.well-known/jwks.json")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(tests)} auth test groups...\n")
    for t in tests:
        print(t.__name__)
        t()
    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): {_failures}")
        raise SystemExit(1)
    print("All auth checks passed.")
