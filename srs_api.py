"""
Study Mode API — spaced repetition endpoints.

Mounts under /api/srs. State is persisted per range file at:
    srs_state/<range_file_stem>.srs.json

So a user can have separate decks for cash vs MTT ranges, and resetting one
doesn't touch the others.

Public endpoints:
    GET  /api/srs/status   — is the deck initialized? high-level counts
    POST /api/srs/init     — create deck from a range file (idempotent)
    GET  /api/srs/next     — get the next due card (sanitized: no answer)
    POST /api/srs/answer   — submit answer, get grading + next card
    GET  /api/srs/summary  — dashboard counters
    POST /api/srs/reset    — wipe deck state for a range file
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

import srs
import journal      # Track D, D.1-api-write: append each Learn answer to the journal
import cards_store  # Track D, D.1-api-cards: deck state persistence (DB or JSON)
import auth          # Track D, D.2: resolve the request's user_id from its JWT


# ---------------------------------------------------------------------------
# Paths and conventions
# ---------------------------------------------------------------------------

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
SRS_DIR      = os.path.join(BASE_DIR, "srs_state")

# Allowed scope values for /api/srs/init — anything else is rejected
VALID_SPOTS = {"RFI", "vs_RFI", "vs_3bet", "vs_4bet", "iso"}


def _safe_path_in(base_dir: str, filename: str) -> str:
    """
    Resolve ``filename`` under ``base_dir`` and refuse anything that escapes
    the directory (path traversal via ``..``, absolute paths, symlinks).

    ``realpath`` collapses ``..`` and follows symlinks on both sides so the
    containment check is correct even when ``base_dir`` itself is a symlink.
    """
    base_real = os.path.realpath(base_dir)
    candidate = os.path.realpath(os.path.join(base_dir, filename))
    # Containment check: candidate must equal base or live strictly below it.
    if candidate != base_real and not candidate.startswith(base_real + os.sep):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file path (outside allowed directory): {filename}",
        )
    return candidate


def _state_path_for(range_file: str) -> str:
    """Map a range file name (with or without .json) to its SRS state path."""
    stem = range_file[:-5] if range_file.endswith(".json") else range_file
    return _safe_path_in(SRS_DIR, f"{stem}.srs.json")


def _range_path_for(range_file: str) -> str:
    fn = range_file if range_file.endswith(".json") else f"{range_file}.json"
    return _safe_path_in(DATA_DIR, fn)


def _load_range_spots(range_file: str) -> dict:
    path = _range_path_for(range_file)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Range file not found: {range_file}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Tolerate both "spots" and legacy "ranges" key — same as main.py normalizer
    spots = data.get("spots") or data.get("ranges")
    if not isinstance(spots, dict):
        raise HTTPException(status_code=400, detail=f"Range file has no spots: {range_file}")
    return spots


def _pack_stem(range_file: str) -> str:
    """Bare pack identity ('GTOWNL10.json' -> 'GTOWNL10') — keys the cards rows."""
    return range_file[:-5] if range_file.endswith(".json") else range_file


# Persistence delegates to cards_store, which picks DB-vs-JSON by configuration
# (Track D, D.1-api-cards). srs_api still owns the *safe* JSON path (via
# _state_path_for -> _safe_path_in, preserving the path-traversal guard), and
# passes the pack stem (the DB row key), that path (JSON branch only), and the
# user_id (D.2 — the JWT subject in DB mode, or the dev user when auth is off).
def _deck_exists(range_file: str, user_id) -> bool:
    return cards_store.deck_exists(_pack_stem(range_file), _state_path_for(range_file),
                                   user_id=user_id)


def _load_deck(range_file: str, user_id) -> list[srs.Card]:
    return cards_store.load_deck(_pack_stem(range_file), _state_path_for(range_file),
                                 user_id=user_id)


def _replace_deck(range_file: str, cards: list[srs.Card], user_id) -> None:
    cards_store.replace_deck(_pack_stem(range_file), _state_path_for(range_file), cards,
                             user_id=user_id)


def _save_card(range_file: str, card: srs.Card, deck: list[srs.Card], user_id) -> None:
    cards_store.save_card(_pack_stem(range_file), _state_path_for(range_file), card, deck,
                          user_id=user_id)


def _delete_deck(range_file: str, user_id) -> None:
    cards_store.delete_deck(_pack_stem(range_file), _state_path_for(range_file),
                            user_id=user_id)


def _find_card(cards: list[srs.Card], card_id: str) -> srs.Card:
    for c in cards:
        if c.card_id == card_id:
            return c
    raise HTTPException(status_code=404, detail=f"Card not found: {card_id}")


# ---------------------------------------------------------------------------
# Request/response shapes
# ---------------------------------------------------------------------------

class InitRequest(BaseModel):
    file: str
    scope: Optional[list[str]] = None  # ["RFI"], or None = all spots
    force: bool = False                # overwrite an existing deck if True


class AnswerRequest(BaseModel):
    file: str
    card_id: str
    user_action: str = ""
    marked_easy: bool = False
    reveal: bool = False   # "Показать ответ" — user didn't know; force AGAIN
    new_limit: int = srs.NEW_CARDS_PER_DAY  # daily new-card cap for the follow-up queue


class UpgradeEasyRequest(BaseModel):
    file: str
    card_id: str


def _card_for_ui(card: srs.Card, *, reveal_strategy: bool) -> dict:
    """
    Serialize a card for the frontend.

    `reveal_strategy=False` is the "question" view — no answer in the payload.
    `reveal_strategy=True` is the "answer revealed" view, sent after grading.
    """
    payload = {
        "card_id":          card.card_id,
        "hand":             card.hand,
        "position":         card.position,
        "spot":             card.spot,
        "villain_position": card.villain_position,
        "is_new":           card.is_new(),
        "interval_days":    card.interval_days,
    }
    if reveal_strategy:
        payload["correct_strategy"] = card.correct_strategy
        payload["classify"]         = card.classify()
        payload["dominant_action"]  = card.dominant_action()
    return payload


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/srs", tags=["srs"])


@router.get("/status")
def srs_status(file: str = Query(...), user=Depends(auth.get_current_user)):
    """Lightweight check: does this range have an initialized deck?"""
    if not _deck_exists(file, user):
        return {"initialized": False, "file": file}
    cards = _load_deck(file, user)
    summary = srs.summarize(cards, today=date.today())
    return {"initialized": True, "file": file, **summary}


@router.post("/init")
def srs_init(req: InitRequest, user=Depends(auth.get_current_user)):
    """
    Build the deck from the range file's `spots`. Idempotent unless `force=True`:
    on an already-initialized deck this returns a 409 to prevent accidentally
    wiping someone's review history.
    """
    if _deck_exists(req.file, user) and not req.force:
        raise HTTPException(
            status_code=409,
            detail="Deck already initialized for this range. Pass force=true to overwrite.",
        )

    spots = _load_range_spots(req.file)

    scope: Optional[tuple[str, ...]] = None
    if req.scope:
        bad = [s for s in req.scope if s not in VALID_SPOTS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {bad}")
        scope = tuple(req.scope)

    cards = srs.init_cards_from_spots(spots, scope=scope)
    _replace_deck(req.file, cards, user)
    return {
        "initialized": True,
        "file": req.file,
        "total": len(cards),
        "scope": list(scope) if scope else list(VALID_SPOTS),
    }


@router.get("/next")
def srs_next(file: str = Query(...),
             new_limit: int = Query(srs.NEW_CARDS_PER_DAY, ge=0),
             user=Depends(auth.get_current_user)):
    """Returns the next due card (or null if queue is empty for today).

    ``new_limit`` caps how many *new* cards enter today's queue (reviews that
    are due are always served regardless). The frontend passes the user's pick
    (10/15/30/50, or a large number for "unlimited"); the default matches
    NEW_CARDS_PER_DAY so any caller that omits it behaves as before.
    """
    cards = _load_deck(file, user)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized. Call /api/srs/init first.")
    due = srs.get_due_cards(cards, today=date.today(), new_limit=new_limit)
    if not due:
        return {"card": None, "queue_size": 0}
    return {"card": _card_for_ui(due[0], reveal_strategy=False),
            "queue_size": len(due)}


@router.post("/answer")
def srs_answer(req: AnswerRequest, user=Depends(auth.get_current_user)):
    """
    Submit the user's action. Returns:
      - grading: was the action in-strategy, what SM-2 rating got applied,
                 and the full correct strategy (so UI can reveal the truth)
      - next:    the next due card (or null if queue empty)
    """
    cards = _load_deck(req.file, user)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized. Call /api/srs/init first.")

    card = _find_card(cards, req.card_id)

    # Two paths:
    #   reveal=True  → the user pressed "Показать ответ" (didn't know). We force
    #                  AGAIN so the card comes back soon — an honest "don't know"
    #                  must not masquerade as a correct guess. user_action is
    #                  irrelevant here; in_strategy is False by definition.
    #   reveal=False → normal answer: objective grading by strategy membership.
    if req.reveal:
        rating = srs.AGAIN
        in_strategy = False
    else:
        rating = srs.grade_answer(card, req.user_action, marked_easy=req.marked_easy)
        in_strategy = card.correct_strategy.get(req.user_action, 0) > 0
    srs.update_card(card, rating, today=date.today())
    # Persist the one mutated card (DB upsert, or whole-file JSON rewrite under
    # soft degradation). Unlike the best-effort journal below, this is STATE: if
    # the DB write fails it propagates (500) rather than silently losing the rep.
    _save_card(req.file, card, cards, user)

    # Track D, D.1-api-write: append this Learn answer to the DB journal, in
    # parallel with the SRS-state saved just above. Best-effort and a no-op
    # without DATABASE_URL, so prod (JSON-only) is unaffected. `user` is the JWT
    # subject in DB mode (D.2), or the dev user when auth is off.
    journal.record_learn_answer(
        card, pack=req.file, user_action=req.user_action,
        rating=rating, in_strategy=in_strategy, revealed=req.reveal,
        user_id=user,
    )

    # Reveal the answer to the UI now that grading is done
    answer_view = _card_for_ui(card, reveal_strategy=True)

    # Find the next card to drill (excluding this one since we just updated it)
    due = srs.get_due_cards(cards, today=date.today(), new_limit=req.new_limit)
    due = [c for c in due if c.card_id != card.card_id]
    next_card = _card_for_ui(due[0], reveal_strategy=False) if due else None

    return {
        "grading": {
            "in_strategy":  in_strategy,
            "rating":       rating,           # 1=Again, 3=Good, 4=Easy
            "user_action":  req.user_action,
            "marked_easy":  req.marked_easy,
            "revealed":     req.reveal,        # True → user pressed "Показать ответ"
        },
        "card":  answer_view,
        "next":  next_card,
        "queue_size": len(due),
    }


@router.get("/summary")
def srs_summary(file: str = Query(...), user=Depends(auth.get_current_user)):
    """Dashboard counters: total, new, due today, young, learned."""
    cards = _load_deck(file, user)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized.")
    return srs.summarize(cards, today=date.today())


@router.post("/reset")
def srs_reset(file: str = Query(...), user=Depends(auth.get_current_user)):
    """Wipe the deck for this range file. Caller must re-init afterwards."""
    _delete_deck(file, user)
    return {"status": "reset", "file": file}


@router.post("/upgrade_easy")
def srs_upgrade_easy(req: UpgradeEasyRequest, user=Depends(auth.get_current_user)):
    """
    Upgrade a card's most-recent GOOD answer to EASY.

    Called from the Learn reveal screen when the user clicks the Easy button
    after a correct (in-strategy) answer. We apply the GOOD→EASY delta:
    interval × 1.3 (at least +1 day), ease + 0.15. The card has already been
    persisted with the GOOD result by ``/answer`` — this endpoint mutates and
    re-saves it. See ``srs.upgrade_good_to_easy`` for the math and trade-offs.
    """
    cards = _load_deck(req.file, user)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized.")
    card = _find_card(cards, req.card_id)
    srs.upgrade_good_to_easy(card, today=date.today())
    _save_card(req.file, card, cards, user)
    return {
        "ok":            True,
        "card_id":       card.card_id,
        "interval_days": card.interval_days,
        "ease_factor":   card.ease_factor,
        "next_review":   card.next_review,
    }
