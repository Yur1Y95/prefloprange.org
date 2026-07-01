"""Database connection layer — Track D, D.1-api.

Single responsibility: hold ONE lazily-created psycopg (v3) connection pool to
the Supabase Postgres, configured entirely from the DATABASE_URL environment
variable.

Design notes (why it is written this defensively):
  * Nothing connects at import time. The pool is built on first real use.
  * A missing DATABASE_URL does NOT crash the app — ``ping()`` simply reports
    "not configured". This keeps the current JSON-backed app (and the live
    Railway deploy, which has no DATABASE_URL yet) working unchanged until we
    deliberately set the variable.
  * psycopg is imported lazily inside the builder, so merely importing this
    module never fails on an environment that has not installed the driver yet
    (e.g. the test sandbox).

Security: DATABASE_URL is read from the environment ONLY. Never hard-code it,
never log its value — it contains the database password.
"""
import os
import threading

# Load a local .env if python-dotenv is available. On Railway the variables are
# injected by the platform and there is no .env file, so this is a harmless
# no-op there. Wrapped so a missing package never breaks the import.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

_pool = None
_pool_lock = threading.Lock()


def database_configured() -> bool:
    """True if a DATABASE_URL is present in the environment."""
    return bool(os.environ.get("DATABASE_URL"))


def get_pool():
    """Return the shared connection pool, building it on first use.

    Returns None if DATABASE_URL is unset (so callers can degrade gracefully).
    Raises RuntimeError with a clear message if the driver is not installed.
    """
    global _pool
    if not database_configured():
        return None
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:          # re-check inside the lock
            return _pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "psycopg_pool is not installed — run "
                "`pip install -r requirements.txt`"
            ) from e
        # min_size=0: keep zero idle connections (gentle on Supabase free-tier
        # connection limits); the pool opens a connection only on demand. With
        # min_size=0 the constructor does not dial the DB, so a wrong/unreachable
        # DATABASE_URL fails later at checkout (bounded by the timeout in ping),
        # never at import — the rest of the app stays up.
        _pool = ConnectionPool(
            os.environ["DATABASE_URL"],
            min_size=0,
            max_size=5,
            open=True,
        )
        return _pool


def ping() -> dict:
    """Health probe: ``SELECT 1`` + the DB clock. Returns a JSON-friendly dict.

    Shapes:
      not configured -> {"ok": False, "configured": False, "detail": ...}
      reachable      -> {"ok": True,  "configured": True,  "db_time": ...}
    """
    pool = get_pool()
    if pool is None:
        return {
            "ok": False,
            "configured": False,
            "detail": "DATABASE_URL is not set",
        }
    # timeout: do not hang the request if the DB is unreachable.
    with pool.connection(timeout=10) as conn:
        row = conn.execute("select 1, now()").fetchone()
    return {
        "ok": True,
        "configured": True,
        "select_1": row[0],
        "db_time": row[1].isoformat(),
    }
