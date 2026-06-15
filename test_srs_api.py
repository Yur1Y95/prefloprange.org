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
    assert body["total"] == 1183, f"expected 1183 RFI cards (7 positions × 169), got {body['total']}"
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
    assert body["total"] == 1183
    assert body["new"] == 1183       # all cards are new initially
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


def test_answer_reveal_forces_again():
    """'Показать ответ' (reveal=True): the user didn't know. Regardless of the
    correct strategy this must grade AGAIN and flag revealed=True — an honest
    'don't know' should never look like a correct guess."""
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })
    # AA UTG is a pure open — a real answer of "open" would be GOOD. With
    # reveal=True we expect AGAIN anyway, and user_action is irrelevant.
    r = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
        "reveal": True,
    })
    assert r.status_code == 200, r.text
    g = r.json()["grading"]
    assert g["in_strategy"] is False
    assert g["rating"] == 1          # AGAIN
    assert g["revealed"] is True
    # The correct strategy is still revealed so the UI can show it
    assert r.json()["card"]["correct_strategy"]["open"] == 1.0
    print("  PASS  reveal=True on AA UTG -> AGAIN, revealed=True, answer disclosed")


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
    # the 1183-card new pool as cards get answered, so size stays ~constant):
    # 1. The next card returned is DIFFERENT from the one we just answered
    next_card = body["next"]
    if next_card:
        assert next_card["card_id"] != card1_id
    # 2. Total deck is unchanged
    status = client.get("/api/srs/status", params={"file": RANGE_FILE_NAME}).json()
    assert status["total"] == 1183
    # 3. The card we answered is no longer "new"
    assert status["new"] == 1182
    print(f"  PASS  full flow: answered 1 card, deck now new=1182 (was 1183)")


def test_upgrade_easy_after_good_answer():
    """Reveal-screen Easy click: answer correctly (GOOD applied), then call
    /upgrade_easy and verify the card's interval and ease bumped per the
    GOOD→EASY delta."""
    # Fresh deck so AA UTG is new (interval=0, ease=2.5)
    client.post("/api/srs/init", json={
        "file": RANGE_FILE_NAME, "scope": ["RFI"], "force": True,
    })

    # Step 1: answer correctly to apply GOOD
    r1 = client.post("/api/srs/answer", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
        "user_action": "open",
        "marked_easy": False,
    })
    assert r1.status_code == 200, r1.text
    g = r1.json()["grading"]
    assert g["rating"] == 3, f"expected GOOD, got rating={g['rating']}"
    # After GOOD on a new card: interval=1, ease=2.5
    card_after_good = r1.json()["card"]
    assert card_after_good["interval_days"] == 1

    # Step 2: click Easy in the reveal — upgrade to EASY
    r2 = client.post("/api/srs/upgrade_easy", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
    })
    assert r2.status_code == 200, r2.text
    body = r2.json()
    # Delta: max(1+1, round(1*1.3)=1) = 2, ease 2.5 + 0.15 = 2.65
    assert body["interval_days"] == 2, f"expected 2, got {body['interval_days']}"
    assert abs(body["ease_factor"] - 2.65) < 1e-9
    print(f"  PASS  upgrade_easy: AA UTG GOOD→EASY, interval 1→{body['interval_days']}, ease 2.5→{body['ease_factor']:.2f}")


def test_upgrade_easy_on_uninitialized_deck_404s():
    """No deck → 404, never silently creates a card from thin air."""
    client.post("/api/srs/reset", params={"file": RANGE_FILE_NAME})
    r = client.post("/api/srs/upgrade_easy", json={
        "file": RANGE_FILE_NAME,
        "card_id": "AA__UTG__RFI",
    })
    assert r.status_code == 404, r.text
    print("  PASS  upgrade_easy on uninitialized deck returns 404")


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
