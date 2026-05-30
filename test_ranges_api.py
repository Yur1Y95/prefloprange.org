"""
Integration test for the range-save endpoint.

Run:  python3 test_ranges_api.py
"""

import json
import os
import shutil
import tempfile


# Sandbox the project's data directory BEFORE importing main, so that
# main's module-level DATA_DIR resolves to a clean throwaway.
_TMP  = tempfile.mkdtemp(prefix="ranges_api_test_")
_DATA = os.path.join(_TMP, "data")
os.makedirs(_DATA, exist_ok=True)

# Seed one existing file so list_ranges has something to start with —
# the suite mirrors how the editor will actually be used (load existing,
# save updated copy back).
_SEED = {
    "meta": {"game_type": "Cash", "table_size": "6max",
             "stack_depth": "100bb", "label": "Seed Cash 100bb"},
    "config": {
        "positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
        "rfi_positions": ["UTG", "MP", "CO", "BTN", "SB"],
        "vs_rfi_options": {},
        "vs_3bet_options": {},
    },
    "spots": {"RFI": {"UTG": {"AA": {"open": 1.0}}}},
}
with open(os.path.join(_DATA, "seed_cash_100bb.json"), "w") as f:
    json.dump(_SEED, f, indent=2)

import main
main.DATA_DIR = _DATA

from fastapi.testclient import TestClient
client = TestClient(main.app)


# ── List / read baseline ─────────────────────────────────────────────────

def test_list_picks_up_seed_file():
    r = client.get("/api/ranges/list")
    assert r.status_code == 200
    files = r.json()
    names = [f["filename"] for f in files]
    assert "seed_cash_100bb.json" in names, f"got {names}"
    print("  PASS  list returns seed file")


# ── Save: happy path ─────────────────────────────────────────────────────

def test_save_creates_new_file():
    payload = {
        "filename": "fresh_test_range",
        "data": {
            "meta": {"game_type": "MTT", "table_size": "8max",
                     "stack_depth": "100bb", "label": "Fresh"},
            "config": {"positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
                       "rfi_positions": ["UTG"],
                       "vs_rfi_options": {},
                       "vs_3bet_options": {}},
            "spots": {"RFI": {"UTG": {"AA": {"open": 1.0}}}},
        },
    }
    r = client.post("/api/ranges/save", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "fresh_test_range.json"

    # File now physically present
    saved_path = os.path.join(_DATA, "fresh_test_range.json")
    assert os.path.exists(saved_path)

    # And readable through the get endpoint
    r2 = client.get("/api/ranges", params={"file": "fresh_test_range.json"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["meta"]["label"] == "Fresh"
    print("  PASS  save → list → read roundtrip works")


def test_save_overwrites_existing():
    """Single-user workflow: saving over an existing file is the point.
    Editor opens a range, user edits, saves — must overwrite, no 409."""
    new_payload = {
        "filename": "seed_cash_100bb",
        "data": dict(_SEED, meta=dict(_SEED["meta"], label="Edited Cash 100bb")),
    }
    r = client.post("/api/ranges/save", json=new_payload)
    assert r.status_code == 200, r.text

    r2 = client.get("/api/ranges", params={"file": "seed_cash_100bb.json"})
    assert r2.json()["meta"]["label"] == "Edited Cash 100bb"
    print("  PASS  save overwrites the previous version")


def test_save_normalizes_filename_without_extension():
    """Caller can pass 'foo' or 'foo.json' — server normalizes to 'foo.json'."""
    r = client.post("/api/ranges/save", json={
        "filename": "no_extension_test",
        "data": _SEED,
    })
    assert r.json()["filename"] == "no_extension_test.json"
    assert os.path.exists(os.path.join(_DATA, "no_extension_test.json"))
    print("  PASS  filename without .json gets normalized")


# ── Save: validation / safety ────────────────────────────────────────────

def test_save_rejects_path_traversal():
    bad_names = [
        "../escape",            # dot-dot
        "../../etc/passwd",     # deeper escape
        "/abs/path/file",       # absolute
        "data/nested/file",     # forward slash
        "..\\windows",          # backslash
        ".hidden",              # leading dot
        "name with spaces",     # space
        "name;rm -rf /",        # shell injection chars
    ]
    for name in bad_names:
        r = client.post("/api/ranges/save", json={"filename": name, "data": _SEED})
        assert r.status_code == 400, \
            f"{name!r} should be 400, got {r.status_code}: {r.text}"
    print(f"  PASS  rejected {len(bad_names)} crafted unsafe filenames")


def test_save_rejects_empty_filename():
    r = client.post("/api/ranges/save", json={"filename": "  ", "data": _SEED})
    assert r.status_code == 400
    print("  PASS  empty filename rejected")


def test_save_rejects_non_dict_data():
    r = client.post("/api/ranges/save", json={
        "filename": "should_not_save",
        "data": "this is a string, not an object",
    })
    # Pydantic will catch this at parse time (422) — either 400 or 422 is
    # acceptable, just must not silently accept.
    assert r.status_code in (400, 422), r.text
    assert not os.path.exists(os.path.join(_DATA, "should_not_save.json"))
    print("  PASS  non-dict data rejected, no file created")


# ── Teardown ─────────────────────────────────────────────────────────────

def _teardown():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    import sys
    tests = [(k, v) for k, v in globals().items()
             if k.startswith("test_") and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            failed.append((name, e))
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    _teardown()
    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} FAILED")
        sys.exit(1)
    print(f"All {len(tests)} ranges-api tests passed")
