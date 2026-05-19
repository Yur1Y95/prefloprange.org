from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
import os
import random as _random

from range_engine import load_range_file
from drill_engine import (
    get_drill_hand_rfi,
    get_drill_hand_vs_rfi,
    get_drill_hand_vs_3bet,
    check_answer,
)
from postflop_api import router as postflop_router
from equity_api import router as equity_router

app = FastAPI(title="NLH Range Trainer")
app.include_router(postflop_router)
app.include_router(equity_router)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
STATIC_DIR   = os.path.join(BASE_DIR, "static")
STATS_FILE   = os.path.join(BASE_DIR, "stats.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
HISTORY_MAX  = 200


def _list_range_files() -> list:
    if not os.path.exists(DATA_DIR):
        return []
    files = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(DATA_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("meta", {})
            files.append({
                "filename":    fn,
                "label":       meta.get("label", fn.replace(".json", "")),
                "game_type":   meta.get("game_type", "Unknown"),
                "table_size":  meta.get("table_size", ""),
                "stack_depth": meta.get("stack_depth", ""),
            })
        except Exception:
            continue
    return files


def _normalize_range_data(data: dict) -> dict:
    """Some legacy files use the key ``ranges`` instead of ``spots``.
    The frontend (visualizer, editor, drill hint) reads ``spots`` exclusively.
    Mirror one onto the other so every consumer sees the same shape regardless
    of which key the JSON file used."""
    if not isinstance(data, dict):
        return data
    spots  = data.get("spots")
    ranges = data.get("ranges")
    if isinstance(spots, dict) and not isinstance(ranges, dict):
        data["ranges"] = spots
    elif isinstance(ranges, dict) and not isinstance(spots, dict):
        data["spots"] = ranges
    return data


def _load_range(file: str = "") -> dict:
    if not file:
        files = _list_range_files()
        if not files:
            raise HTTPException(status_code=404, detail="No range files found in data/")
        file = files[0]["filename"]
    fn = file if file.endswith(".json") else file + ".json"
    path = os.path.join(DATA_DIR, fn)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Range file not found: {fn}")
    return _normalize_range_data(load_range_file(path))


def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"RFI": {}, "vs_RFI": {}, "vs_3bet": {}}


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)


def update_stats(stats, spot, key, correct, is_timeout):
    stats.setdefault(spot, {}).setdefault(key, {"correct": 0, "total": 0, "timeouts": 0})
    stats[spot][key]["total"] += 1
    if is_timeout:
        stats[spot][key]["timeouts"] += 1
    if correct:
        stats[spot][key]["correct"] += 1


def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[:HISTORY_MAX], f, indent=2, ensure_ascii=False)


class AnswerRequest(BaseModel):
    drill_hand: dict
    player_action: str
    is_timeout: bool = False


@app.get("/api/ranges/list")
def list_ranges():
    return _list_range_files()


@app.get("/api/ranges")
def get_ranges(file: str = Query("")):
    return _load_range(file)


@app.get("/api/config")
def get_config(file: str = Query("")):
    """Return the full range file with sane defaults merged into config.

    Previously this endpoint only returned the ``config`` dict plus a
    ``spots: [...]`` *list* — but the drill stores the whole response in
    ``state.rangeData`` and the Show Range hint then tries to read
    ``state.rangeData.spots.RFI[pos]``. Returning a list there broke the
    hint. Now we return the full normalized file so all consumers agree
    on the shape.
    """
    data = _load_range(file)
    cfg  = {
        "bb": 1.0, "sb": 0.5, "open_size": 2.5, "starting_stack": 100.0,
        **data.get("config", {}),
    }
    return { **data, "config": cfg }


@app.get("/api/drill/hand")
def get_drill_hand(
    spot: str = Query("RFI"),
    hero_position: str = Query("UTG"),
    villain_position: Optional[str] = Query(None),
    random_hero: bool = Query(False),
    random_villain: bool = Query(False),
    file: str = Query(""),
):
    range_data = _load_range(file)
    config = range_data["config"]

    if random_hero:
        hero_position = random_hero_select(config, spot)
        if not hero_position:
            raise HTTPException(status_code=400, detail="No hero positions for this spot")

    if random_villain:
        villain_position = random_villain_select(config, spot, hero_position)
        if not villain_position and spot in ("vs_RFI", "vs_3bet"):
            raise HTTPException(status_code=400, detail="No villain positions for this hero/spot")

    if spot == "RFI":
        if hero_position not in config["rfi_positions"]:
            raise HTTPException(status_code=400, detail=f"{hero_position} has no RFI range.")
        return get_drill_hand_rfi(range_data, hero_position)

    if spot == "vs_RFI":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_vs_rfi(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return result

    if spot == "vs_3bet":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_vs_3bet(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return result

    raise HTTPException(status_code=400, detail=f"Unknown spot: {spot}")


@app.post("/api/drill/answer")
def submit_answer(request: AnswerRequest):
    result = check_answer(request.drill_hand, request.player_action, request.is_timeout)
    dh = request.drill_hand
    stats_key = f"{dh.get('hero_position')}_vs_{dh.get('villain_position')}" if dh.get('villain_position') else dh.get('hero_position', '')
    stats = load_stats()
    update_stats(stats, dh.get("spot", ""), stats_key, result["correct"], result.get("is_timeout", False))
    save_stats(stats)
    history = load_history()
    entry = {
        "ts":               datetime.now().strftime("%H:%M:%S"),
        "spot":             dh.get("spot", ""),
        "hero_position":    dh.get("hero_position", ""),
        "villain_position": dh.get("villain_position"),
        "hand":             dh.get("hand", ""),
        "card1":            dh.get("card1", ""),
        "card2":            dh.get("card2", ""),
        "correct_action":   result.get("correct_action", ""),
        "player_action":    result.get("player_action", request.player_action),
        "correct":          result.get("correct", False),
        "ev":               result.get("ev", 0),
        "is_timeout":       result.get("is_timeout", False),
    }
    history.insert(0, entry)
    save_history(history)
    return result


@app.get("/api/stats")
def get_stats():
    return load_stats()


@app.post("/api/stats/reset")
def reset_stats():
    save_stats({"RFI": {}, "vs_RFI": {}, "vs_3bet": {}})
    return {"status": "reset"}


@app.get("/api/history")
def get_history(limit: int = Query(50)):
    return load_history()[:limit]


@app.post("/api/history/clear")
def clear_history():
    save_history([])
    return {"status": "cleared"}


def random_hero_select(config, spot):
    rfi_positions = config["rfi_positions"]
    if spot == "RFI":
        return _random.choice(rfi_positions) if rfi_positions else None
    options = config["vs_rfi_options"] if spot == "vs_RFI" else config.get("vs_3bet_options", {})
    valid = [h for h in rfi_positions if options.get(h)]
    return _random.choice(valid) if valid else None


def random_villain_select(config, spot, hero_position):
    if spot == "vs_RFI":
        villains = config["vs_rfi_options"].get(hero_position, [])
    elif spot == "vs_3bet":
        villains = config.get("vs_3bet_options", {}).get(hero_position, [])
    else:
        return None
    return _random.choice(villains) if villains else None


# serve frontend
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_files")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))