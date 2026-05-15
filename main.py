from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pydantic import BaseModel
from typing import Optional
import json
import os

from range_engine import load_range_file
from drill_engine import (
    get_drill_hand_rfi,
    get_drill_hand_vs_rfi,
    get_drill_hand_vs_3bet,
    check_answer,
)

app = FastAPI(title="NLH Range Trainer")

RANGE_FILE   = "cash_micro_100bb.json"
STATS_FILE   = "stats.json"
HISTORY_FILE = "history.json"
HISTORY_MAX  = 200  # keep last N hands

range_data = load_range_file(RANGE_FILE)


def _load_range(file: str = "") -> dict:
    """Load range by filename — checks root first, then data/."""
    if not file:
        return range_data
    fn = file if file.endswith(".json") else file + ".json"
    if os.path.exists(fn):
        return load_range_file(fn)
    data_path = os.path.join("data", fn)
    if os.path.exists(data_path):
        return load_range_file(data_path)
    raise FileNotFoundError(fn)

def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    empty = {}
    for spot in ("RFI", "vs_RFI", "vs_3bet"):
        empty[spot] = {}
    return empty


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


# ---------- history helpers ----------

def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def add_history_entry(drill_hand: dict, result: dict):
    from datetime import datetime
    history = load_history()
    entry = {
        "ts":               datetime.now().strftime("%H:%M:%S"),
        "spot":             drill_hand.get("spot", ""),
        "hero_position":    drill_hand.get("hero_position", ""),
        "villain_position": drill_hand.get("villain_position"),
        "hand":             drill_hand.get("hand", ""),
        "card1":            drill_hand.get("card1", ""),
        "card2":            drill_hand.get("card2", ""),
        "correct_action":   result.get("correct_action", ""),
        "player_action":    result.get("player_action", ""),
        "correct":          result.get("correct", False),
        "ev":               result.get("ev", 0),
        "is_timeout":       result.get("is_timeout", False),
    }
    history.insert(0, entry)
    history = history[:HISTORY_MAX]
    save_history(history)


def update_stats(stats: dict, spot: str, key: str, correct: bool, is_timeout: bool):
    if spot not in stats:
        stats[spot] = {}
    if key not in stats[spot]:
        stats[spot][key] = {"correct": 0, "total": 0, "timeouts": 0}

    stats[spot][key]["total"] += 1

    if is_timeout:
        stats[spot][key]["timeouts"] += 1

    if correct:
        stats[spot][key]["correct"] += 1


# ---------- request models ----------

class AnswerRequest(BaseModel):
    drill_hand: dict
    player_action: str
    is_timeout: bool = False


# ---------- API routes ----------

@app.get("/api/ranges")
def get_ranges(file: str = Query("", description="Range filename (without .json). Empty = default cash file.")):
    """Return full range data for the given file."""
    try:
        return _load_range(file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Range file not found: {file}")


@app.get("/api/config")
def get_config(file: str = Query("", description="Range filename. Empty = default cash file.")):
    """Return game configuration for the given range file."""
    try:
        data = _load_range(file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Range file not found: {file}")
    cfg = data["config"]
    return {
        "bb": 1.0,
        "sb": 0.5,
        "open_size": 2.5,
        "starting_stack": 100.0,
        "positions":       cfg["positions"],
        "rfi_positions":   cfg["rfi_positions"],
        "vs_rfi_options":  cfg["vs_rfi_options"],
        "vs_3bet_options": cfg.get("vs_3bet_options", {}),
        "spots":           ["RFI", "vs_RFI", "vs_3bet"],
    }


@app.get("/api/drill/available-positions")
def get_available_positions(
    spot: str = Query("RFI", description="RFI, vs_RFI, or vs_3bet"),
    hero_position: str = Query("UTG", description="Hero's seat"),
):
    """Return lists of hero positions and villain positions available for a spot."""
    config = range_data["config"]
    rfi_positions = config["rfi_positions"]
    vs_rfi_options = config["vs_rfi_options"]
    vs_3bet_options = config.get("vs_3bet_options", {})

    hero_positions = rfi_positions  # all RFI positions are valid hero seats

    if spot == "RFI":
        villain_positions = []
    elif spot == "vs_RFI":
        villain_positions = vs_rfi_options.get(hero_position, [])
    elif spot == "vs_3bet":
        villain_positions = vs_3bet_options.get(hero_position, [])
    else:
        raise HTTPException(status_code=400, detail=f"Unknown spot: {spot}")

    return {
        "spot": spot,
        "hero_positions": hero_positions,
        "villain_positions_for_selected_hero": villain_positions,
    }


@app.get("/api/drill/hand")
def get_drill_hand(
    spot: str = Query("RFI"),
    hero_position: str = Query("UTG"),
    villain_position: Optional[str] = Query(None),
    random_hero: bool = Query(False),
    random_villain: bool = Query(False),
    file: str = Query("", description="Range filename. Empty = default cash file."),
):
    try:
        data = _load_range(file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Range file not found: {file}")

    config = data["config"]

    if random_hero:
        hero_position = random_hero_select(config, spot)
        if hero_position is None:
            raise HTTPException(status_code=400, detail="No hero positions for this spot")

    if random_villain:
        villain_position = random_villain_select(config, spot, hero_position)
        if villain_position is None and spot in ("vs_RFI", "vs_3bet"):
            raise HTTPException(status_code=400, detail="No villain positions for this hero/spot")

    if spot == "RFI":
        if hero_position not in config["rfi_positions"]:
            raise HTTPException(status_code=400, detail=f"{hero_position} has no RFI range.")
        return get_drill_hand_rfi(data, hero_position)

    if spot == "vs_RFI":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position is required for vs_RFI.")
        result = get_drill_hand_vs_rfi(data, hero_position, villain_position)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return result

    if spot == "vs_3bet":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position is required for vs_3bet.")
        result = get_drill_hand_vs_3bet(data, hero_position, villain_position)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return result

    raise HTTPException(status_code=400, detail=f"Unknown spot: {spot}")


@app.post("/api/drill/answer")
def submit_answer(request: AnswerRequest):
    """Check the player's answer, update stats and return feedback."""
    result = check_answer(request.drill_hand, request.player_action, request.is_timeout)

    drill_hand = request.drill_hand
    spot = drill_hand.get("spot", "")
    hero = drill_hand.get("hero_position", "")
    villain = drill_hand.get("villain_position")

    stats_key = f"{hero}_vs_{villain}" if villain else hero

    stats = load_stats()
    update_stats(stats, spot, stats_key, result["correct"], result.get("is_timeout", False))
    save_stats(stats)

    add_history_entry(drill_hand, result)

    return result


@app.get("/api/stats")
def get_stats():
    """Return the current session statistics."""
    return load_stats()


@app.post("/api/stats/reset")
def reset_stats():
    """Reset all statistics."""
    empty = {}
    for spot in ("RFI", "vs_RFI", "vs_3bet"):
        empty[spot] = {}
    save_stats(empty)
    return {"status": "reset"}


@app.get("/api/history")
def get_history(limit: int = 100):
    """Return the last N hands played."""
    return load_history()[:limit]


@app.post("/api/history/clear")
def clear_history():
    """Clear hand history."""
    save_history([])
    return {"status": "cleared"}


# ---------- helpers ----------

import random as _random

def random_hero_select(config: dict, spot: str) -> Optional[str]:
    """Return a random valid hero position for the given spot."""
    rfi_positions = config["rfi_positions"]
    if spot == "RFI":
        return _random.choice(rfi_positions) if rfi_positions else None
    # For vs_RFI and vs_3bet, hero can be any position that has at least one villain option
    if spot == "vs_RFI":
        options = config["vs_rfi_options"]
    elif spot == "vs_3bet":
        options = config.get("vs_3bet_options", {})
    else:
        return None
    valid_heroes = [h for h in rfi_positions if len(options.get(h, [])) > 0]
    return _random.choice(valid_heroes) if valid_heroes else None


def random_villain_select(config: dict, spot: str, hero_position: str) -> Optional[str]:
    """Return a random valid villain position for the given spot and hero."""
    if spot == "vs_RFI":
        villains = config["vs_rfi_options"].get(hero_position, [])
    elif spot == "vs_3bet":
        villains = config.get("vs_3bet_options", {}).get(hero_position, [])
    else:
        return None

    # Filter out empty lists
    valid_villains = [v for v in villains]
    return _random.choice(valid_villains) if valid_villains else None


# ---------- range editor endpoints ----------

import glob as _glob
import re as _re


@app.get("/api/ranges/list")
def list_ranges():
    """List all available range files (root + data/ directory)."""
    os.makedirs("data", exist_ok=True)
    result = []

    # Always include the default cash file from root
    if os.path.exists(RANGE_FILE):
        try:
            data = load_range_file(RANGE_FILE)
            meta = data.get("meta", {})
            result.append({
                "filename":    RANGE_FILE,
                "game_type":   meta.get("game_type",   "Cash"),
                "table_size":  meta.get("table_size",  "6max"),
                "stack_depth": meta.get("stack_depth", "100bb"),
                "label":       meta.get("label", "Cash 6-max 100bb"),
            })
        except Exception:
            pass

    # Files in data/ directory
    for f in sorted(_glob.glob("data/*.json")):
        name = os.path.basename(f)
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            meta = data.get("meta", {})
            result.append({
                "filename":    name,
                "game_type":   meta.get("game_type",   "Unknown"),
                "table_size":  meta.get("table_size",  "Unknown"),
                "stack_depth": meta.get("stack_depth", "Unknown"),
                "label":       meta.get("label", name.replace(".json", "")),
            })
        except Exception:
            result.append({"filename": name, "label": name, "game_type": "Unknown"})

    return result


class SaveRangeRequest(BaseModel):
    filename: str
    range_data: dict


@app.post("/api/ranges/save")
def save_range_file(request: SaveRangeRequest):
    """Save a range JSON file to the data directory."""
    filename = _re.sub(r"[^a-zA-Z0-9_\-]", "_", request.filename)
    if not filename.endswith(".json"):
        filename += ".json"
    os.makedirs("data", exist_ok=True)
    filepath = os.path.join("data", filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(request.range_data, f, indent=2, ensure_ascii=False)
    return {"status": "saved", "filename": filename}


# ---------- serve frontend ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_files")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))