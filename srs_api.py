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
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import srs


# ---------------------------------------------------------------------------
# Paths and conventions
# ---------------------------------------------------------------------------

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
SRS_DIR      = os.path.join(BASE_DIR, "srs_state")

# Allowed scope values for /api/srs/init — anything else is rejected
VALID_SPOTS = {"RFI", "vs_RFI", "vs_3bet"}


def _ensure_srs_dir() -> None:
    Path(SRS_DIR).mkdir(parents=True, exist_ok=True)


def _state_path_for(range_file: str) -> str:
    """Map a range file name (with or without .json) to its SRS state path."""
    stem = range_file[:-5] if range_file.endswith(".json") else range_file
    return os.path.join(SRS_DIR, f"{stem}.srs.json")


def _range_path_for(range_file: str) -> str:
    fn = range_file if range_file.endswith(".json") else f"{range_file}.json"
    return os.path.join(DATA_DIR, fn)


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


def _load_deck(range_file: str) -> list[srs.Card]:
    return srs.load_state(_state_path_for(range_file))


def _save_deck(range_file: str, cards: list[srs.Card]) -> None:
    _ensure_srs_dir()
    srs.save_state(cards, _state_path_for(range_file))


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
    user_action: str
    marked_easy: bool = False


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
def srs_status(file: str = Query(...)):
    """Lightweight check: does this range have an initialized deck?"""
    state_path = _state_path_for(file)
    if not os.path.exists(state_path):
        return {"initialized": False, "file": file}
    cards = _load_deck(file)
    summary = srs.summarize(cards, today=date.today())
    return {"initialized": True, "file": file, **summary}


@router.post("/init")
def srs_init(req: InitRequest):
    """
    Build the deck from the range file's `spots`. Idempotent unless `force=True`:
    on an already-initialized deck this returns a 409 to prevent accidentally
    wiping someone's review history.
    """
    state_path = _state_path_for(req.file)
    if os.path.exists(state_path) and not req.force:
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
    _save_deck(req.file, cards)
    return {
        "initialized": True,
        "file": req.file,
        "total": len(cards),
        "scope": list(scope) if scope else list(VALID_SPOTS),
    }


@router.get("/next")
def srs_next(file: str = Query(...)):
    """Returns the next due card (or null if queue is empty for today)."""
    cards = _load_deck(file)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized. Call /api/srs/init first.")
    due = srs.get_due_cards(cards, today=date.today())
    if not due:
        return {"card": None, "queue_size": 0}
    return {"card": _card_for_ui(due[0], reveal_strategy=False),
            "queue_size": len(due)}


@router.post("/answer")
def srs_answer(req: AnswerRequest):
    """
    Submit the user's action. Returns:
      - grading: was the action in-strategy, what SM-2 rating got applied,
                 and the full correct strategy (so UI can reveal the truth)
      - next:    the next due card (or null if queue empty)
    """
    cards = _load_deck(req.file)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized. Call /api/srs/init first.")

    card = _find_card(cards, req.card_id)

    # Objective grading -> SM-2 rating -> apply
    rating = srs.grade_answer(card, req.user_action, marked_easy=req.marked_easy)
    in_strategy = card.correct_strategy.get(req.user_action, 0) > 0
    srs.update_card(card, rating, today=date.today())
    _save_deck(req.file, cards)

    # Reveal the answer to the UI now that grading is done
    answer_view = _card_for_ui(card, reveal_strategy=True)

    # Find the next card to drill (excluding this one since we just updated it)
    due = srs.get_due_cards(cards, today=date.today())
    due = [c for c in due if c.card_id != card.card_id]
    next_card = _card_for_ui(due[0], reveal_strategy=False) if due else None

    return {
        "grading": {
            "in_strategy":  in_strategy,
            "rating":       rating,           # 1=Again, 3=Good, 4=Easy
            "user_action":  req.user_action,
            "marked_easy":  req.marked_easy,
        },
        "card":  answer_view,
        "next":  next_card,
        "queue_size": len(due),
    }


@router.get("/summary")
def srs_summary(file: str = Query(...)):
    """Dashboard counters: total, new, due today, young, learned."""
    cards = _load_deck(file)
    if not cards:
        raise HTTPException(status_code=404, detail="Deck not initialized.")
    return srs.summarize(cards, today=date.today())


@router.post("/reset")
def srs_reset(file: str = Query(...)):
    """Wipe the deck for this range file. Caller must re-init afterwards."""
    state_path = _state_path_for(file)
    if os.path.exists(state_path):
        os.remove(state_path)
    return {"status": "reset", "file": file}
