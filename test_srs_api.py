"""
End-to-end integration test for the SRS API.

Spins up a minimal FastAPI app mounting srs_api.router, simulates a full
session against the real MTT range file: init -> next -> answer -> next ...,
and verifies the contract every endpoint exposes.

Run:  python3 test_srs_api.py
"""

import os
import shutil
import tempfile

# Set up a sandbox project directory BEFORE importing srs_api so its BASE_DIR
# resolves to a clean throwaway location.
_TMP = tempfile.mkdtemp(prefix="srs_api_test_")
_DATA = os.path.join(_TMP, "data")
_STATE = os.path.join(_TMP, "srs_state")
os.makedirs(_DATA, exist_ok=True)

# Copy the real range file in, from the project's own data/ dir. Path is
# resolved relative to this test file so it works on any machine — per
# CLAUDE.md "no hardcoded paths" rule.
RANGE_FILE_NAME = "gto_100bb_mtt.json"
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
shutil.copy(
    os.path.join(_PROJECT_ROOT, "data", RANGE_FILE_NAME),
    os.path.join(_DATA, RANGE_FILE_NAME),
)

# Make srs_api see the sandbox
import srs_api
srs_api.BASE_DIR = _TMP
srs_api.DATA_DIR = _DATA
srs_api.SRS_DIR  = _STATE

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(srs_api.router)
client = TestClient(app)


def test_status_before_init():
    r = client.get("/api/srs/status", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 200
    body = r.json()
    assert body["initialized"] is False
    print("  PASS  status before init")


def test_next_before_init_404s():
    r = client.get("/api/srs/next", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 404
    print("  PASS  /next before /init returns 404")


def test_init_rfi_only():
    r = client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME,
        "scope": ["RFI"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["initialized"] is True
    assert body["total"] == 597, f"expected 597 RFI cards, got {body['total']}"
    print(f"  PASS  init RFI-only ({body['total']} cards)")


def test_init_again_rejects_without_force():
    r = client.post("/api/srs/init", json={"file": RANGE_FILE_NAME, "scope": ["RFI"]})
    assert r.status_code == 409
    print("  PASS  init refuses to clobber existing deck")


def test_init_force_overwrites():
    r = client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })
    assert r.status_code == 200
    print("  PASS  init force=true allows overwrite")


def test_status_after_init():
    r = client.get("/api/srs/status", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 200
    body = r.json()
    assert body["initialized"] is True
    assert body["total"] == 597
    assert body["new"] == 597        # all cards are new initially
    assert body["learned"] == 0
    print(f"  PASS  status reflects fresh deck (new={body['new']})")


def test_next_returns_card_without_revealing_answer():
    r = client.get("/api/srs/next", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 200
    body = r.json()
    card = body["card"]
    assert card is not None
    assert "hand" in card
    assert "position" in card
    assert "spot" in card
    assert card["spot"] == "RFI"
    # The answer should NOT be in the payload
    assert "correct_strategy" not in card
    assert "dominant_action" not in card
    print(f"  PASS  /next returns sanitized card (no answer leak): {card['hand']} {card['position']}")
    return card


def test_answer_correct_open_for_pure_hand():
    """Pick a pure-open RFI card and verify a correct answer is graded Good."""
    # Pull AA UTG via the API
    next_r = client.get("/api/srs/next", params={"file": RANGE_FILE_NAME})
    # Force a specific card: find AA UTG in the deck via list-like behavior
    # Easier — just send an answer with a known card_id
    card_id = "AA__UTG__RFI"
    r = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": card_id,
        "user_action": "open",
        "marked_easy": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    g = body["grading"]
    assert g["in_strategy"] is True
    assert g["rating"] == 3   # GOOD
    # Answer revealed in response
    assert body["card"]["correct_strategy"]["open"] == 1.0
    print("  PASS  correct answer on AA UTG -> in_strategy=True, rating=Good")


def test_answer_wrong_action_resets():
    """A wrong action (folding AA) is graded Again."""
    # Re-init to get fresh state for clean assertions
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })
    r = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
        "user_action": "fold",
    })
    body = r.json()
    g = body["grading"]
    assert g["in_strategy"] is False
    assert g["rating"] == 1   # AGAIN
    print("  PASS  folding AA UTG -> in_strategy=False, rating=Again")


def test_answer_easy_flag_promotes_to_easy():
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })
    r = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
        "user_action": "open",
        "marked_easy": True,
    })
    assert r.json()["grading"]["rating"] == 4   # EASY
    print("  PASS  marked_easy=true on correct answer -> rating=Easy")


def test_answer_on_mixed_hand_either_action_counts():
    """For a mixed hand, BOTH allowed actions grade as correct."""
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })
    # Find a mixed RFI card from the real data — Q7o BTN was 0.38 open in our earlier survey
    # Try a known mixed: 33 UTG was 0.5 open
    for action in ("open", "fold"):
        # Re-init so each answer is on fresh state
        client.post("/api/srs/init", json={
            "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
        })
        r = client.post("/api/srs/answer", json={
            "file": RANGE_FILE_NAME,
            "card_id": "33__UTG__RFI",
            "user_action": action,
        })
        assert r.status_code == 200, r.text
        g = r.json()["grading"]
        assert g["in_strategy"] is True, f"action={action} should be in 50/50 strategy"
        assert g["rating"] == 3
    print("  PASS  mixed card: both 'open' AND 'fold' grade as correct on 33 UTG (50/50)")


def test_summary_endpoint():
    r = client.get("/api/srs/summary", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 200
    body = r.json()
    assert "total" in body and "new" in body and "due_today" in body
    print(f"  PASS  /summary returns {body}")


def test_reset_clears_state():
    r = client.post("/api/srs/reset", params={"file": RANGE_FILE_NAME})
    assert r.status_code == 200
    # Status should now report uninitialized
    r2 = client.get("/api/srs/status", params={"file": RANGE_FILE_NAME})
    assert r2.json()["initialized"] is False
    print("  PASS  reset wipes state, status reflects this")


def test_full_session_flow():
    """End-to-end: init, get card, answer it, get next, verify card advances."""
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })

    # First card
    r1 = client.get("/api/srs/next", params={"file": RANGE_FILE_NAME})
    queue1 = r1.json()["queue_size"]
    card1_id = r1.json()["card"]["card_id"]
    assert queue1 > 0

    # Answer it
    r2 = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": card1_id,
        "user_action": "open",
    })
    body = r2.json()
    assert "grading" in body
    assert "next" in body

    # Two correctness checks (no naive -1 assertion — the queue refills from
    # the 597-card new pool as cards get answered, so size stays ~constant):
    # 1. The next card returned is DIFFERENT from the one we just answered
    next_card = body["next"]
    if next_card:
        assert next_card["card_id"] != card1_id
    # 2. Total deck is unchanged
    status = client.get("/api/srs/status", params={"file": RANGE_FILE_NAME}).json()
    assert status["total"] == 597
    # 3. The card we answered is no longer "new"
    assert status["new"] == 596
    print(f"  PASS  full flow: answered 1 card, deck now new=596 (was 597)")


def test_path_traversal_rejected():
    """
    Crafted ``file`` values that try to escape DATA_DIR / SRS_DIR must be
    refused with 400 — never silently resolve to a path outside our sandbox.
    """
    bad_paths = [
        "../../etc/passwd",   # classic dot-dot escape
        "../outside",         # one level up
        "/etc/passwd",        # absolute path (os.path.join would discard the base)
    ]
    for p in bad_paths:
        r = client.get("/api/srs/status", params={"file": p})
        assert r.status_code == 400, \
            f"{p!r}: expected 400, got {r.status_code}: {r.text}"
    print(f"  PASS  path traversal blocked for {len(bad_paths)} crafted inputs")


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
    print()
    if failed:
        print(f"{len(failed)}/{len(tests)} FAILED")
        sys.exit(1)
    print(f"All {len(tests)} integration tests passed")

    # Clean up the tempdir
    shutil.rmtree(_TMP, ignore_errors=True)
