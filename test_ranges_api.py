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


# ── Ordering: natural sort by NL stake ───────────────────────────────────

def test_sort_key_orders_by_stake_ascending():
    """The pack list must read low stake -> high stake, not lexicographically
    (which put GTOWNL1000 right after GTOWNL100). Stake-less packs come last."""
    raw = [
        "GTOWNL1000.json", "GTOWNL10.json", "GTOWNL100.json", "GTOWNL10000.json",
        "GTOWNL200.json", "GTOWNL2000.json", "GTOWNL50.json", "GTOWNL500.json",
        "GTOWNL5000.json", "NL25GTOW.json", "WizardParseNL10.json",
        "cash_6max_100bb.json", "cash_greenline_micro.json", "cash_micro_100bb.json",
        "mtt_8max_15bb.json",
    ]
    ordered = [f[:-5] for f in sorted(raw, key=main._range_sort_key)]
    assert ordered == [
        "GTOWNL10", "WizardParseNL10",   # both stake 10 -> alphabetical tiebreak
        "NL25GTOW",                       # stake 25 slots between 10 and 50
        "GTOWNL50",
        "GTOWNL100",
        "GTOWNL200",
        "GTOWNL500",
        "GTOWNL1000",
        "GTOWNL2000",
        "GTOWNL5000",
        "GTOWNL10000",
        # stake-less packs last, alphabetical (case-insensitive)
        "cash_6max_100bb", "cash_greenline_micro", "cash_micro_100bb",
        "mtt_8max_15bb",
    ], f"got {ordered}"
    print("  PASS  sort key orders packs by NL stake, stake-less last")


def test_stakeless_packs_not_misparsed_as_nl():
    """'greenline' contains 'nl' but no digit follows, and '15bb' is a stack
    depth, not a stake. Both must bucket as stake-less (key[0] == 1), or they'd
    sort into the wrong place."""
    assert main._range_sort_key("cash_greenline_micro.json")[0] == 1
    assert main._range_sort_key("mtt_8max_15bb.json")[0] == 1
    assert main._range_sort_key("gto_100bb_mtt.json")[0] == 1
    # And a real NL pack buckets as a stake (key[0] == 0) with the right number.
    assert main._range_sort_key("GTOWNL50.json")[:2] == (0, 50)
    assert main._range_sort_key("NL25GTOW.json")[:2] == (0, 25)
    print("  PASS  stake-less packs not misparsed; NL packs read correct stake")


def test_list_endpoint_returns_stake_order():
    """End-to-end: the actual /api/ranges/list response is in stake order."""
    for stem in ("GTOWNL500", "GTOWNL50", "GTOWNL100"):
        with open(os.path.join(_DATA, stem + ".json"), "w") as f:
            json.dump(_SEED, f)
    names = [f["filename"][:-5] for f in client.get("/api/ranges/list").json()]
    i50, i100, i500 = (names.index("GTOWNL50"),
                       names.index("GTOWNL100"),
                       names.index("GTOWNL500"))
    assert i50 < i100 < i500, f"got {names}"
    print("  PASS  /api/ranges/list returns packs in ascending stake order")


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
