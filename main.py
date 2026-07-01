from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
import os
import re
import random as _random

from range_engine import load_range_file
from drill_engine import (
    get_drill_hand_rfi,
    get_drill_hand_vs_rfi,
    get_drill_hand_vs_3bet,
    get_drill_hand_vs_4bet,
    get_drill_hand_iso,
    check_answer,
)
from postflop_api import router as postflop_router
from equity_api import router as equity_router
from srs_api import router as srs_router
from db_api import router as db_router
from auth_api import router as auth_router
from dashboard_api import router as dashboard_router
import db            # Track D, D.1-api-reads: detect DB mode (database_configured)
import journal       # Track D, D.1-api-write: append each Drill answer to the journal
import stats_store   # Track D, D.1-api-reads: read Stats/History from DB or JSON
import auth          # Track D, D.2: resolve the request's user_id from its JWT

app = FastAPI(title="NLH Range Trainer")
app.include_router(postflop_router)
app.include_router(equity_router)
app.include_router(srs_router)
app.include_router(db_router)  # Track D, D.1-api: /api/db/health
app.include_router(auth_router)  # Track D, D.2: /api/auth/config
app.include_router(dashboard_router)  # Track D, Stage 2: /api/dashboard/overview

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
STATIC_DIR   = os.path.join(BASE_DIR, "static")
CARDS_DIR    = os.path.join(BASE_DIR, "cards")
STATS_FILE   = os.path.join(BASE_DIR, "stats.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
HISTORY_MAX  = 200


def _range_sort_key(filename: str):
    """Order range packs by NL stake (ascending); stake-less packs go last.

    The dropdown in every tab (Drill / Learn / Visualizer / Editor) is built
    verbatim from the order this returns, so sorting here fixes ordering
    everywhere in one place.

    Why not a plain string sort: ``"GTOWNL1000" < "GTOWNL200"`` lexicographically,
    because strings compare char-by-char and ``'1' < '2'``. We pull the integer
    stake out of the ``NL<digits>`` token and compare numerically instead, so the
    list reads 10 -> 25 -> 50 -> 100 -> ... -> 10000.

    Why not rename the files: a pack's file stem is its identity key for
    ``srs_state/<stem>.srs.json`` and per-pack stats — renaming would orphan
    saved SRS progress. Sorting touches none of that.

    Returns ``(no_stake, stake, name)``:
      * ``no_stake`` (0/1) pushes packs without an ``NL<digits>`` token
        (``cash_*``, MTT depth packs) to the bottom;
      * ``stake`` orders NL packs numerically;
      * ``name`` breaks ties alphabetically (case-insensitive), e.g. two packs
        at the same stake like ``GTOWNL10`` and ``WizardParseNL10``.

    Note ``re.search`` requires digits right after ``NL``, so ``greenline`` (the
    ``nl`` has no digit after it) and depth tokens like ``15bb`` are correctly
    treated as stake-less.
    """
    m = re.search(r"NL(\d+)", filename, re.IGNORECASE)
    if m:
        return (0, int(m.group(1)), filename.lower())
    return (1, 0, filename.lower())


def _list_range_files() -> list:
    if not os.path.exists(DATA_DIR):
        return []
    files = []
    for fn in sorted(os.listdir(DATA_DIR), key=_range_sort_key):
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


_SPOT_DEFAULTS = {"RFI": {}, "vs_RFI": {}, "vs_3bet": {}, "vs_4bet": {}, "iso": {}}


def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure new spots are present without touching existing data
        for spot in _SPOT_DEFAULTS:
            data.setdefault(spot, {})
        return data
    return dict(_SPOT_DEFAULTS)


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


class SaveRangeRequest(BaseModel):
    filename: str            # "cash_6max_100bb" or "cash_6max_100bb.json"
    data:     dict           # full payload: {meta, config, spots}


def _safe_data_filename(filename: str) -> str:
    """
    Resolve ``filename`` to a sanitized basename inside ``DATA_DIR``.

    Rejects path-traversal (``..``), separators (``/``, ``\\``), absolute
    paths, hidden files (leading ``.``), and exotic characters. Ensures the
    ``.json`` suffix. Returns just the basename — callers join with ``DATA_DIR``.
    """
    fn = filename.strip()
    if not fn:
        raise HTTPException(400, detail="filename is required")
    # Strip a single trailing .json for the pattern check, re-add at the end.
    bare = fn[:-5] if fn.endswith(".json") else fn
    # Allow letters, digits, underscore, dash. No dots, slashes, spaces.
    if not _SAFE_NAME_RE.match(bare):
        raise HTTPException(
            400,
            detail=f"Invalid filename: {filename!r}. "
                   f"Allowed: letters, digits, underscore, dash. No paths.",
        )
    return bare + ".json"


# Module-level regex so we compile it once.
import re as _re
_SAFE_NAME_RE = _re.compile(r"^[A-Za-z0-9_\-]+$")


@app.get("/api/ranges/list")
def list_ranges():
    return _list_range_files()


@app.get("/api/ranges")
def get_ranges(file: str = Query("")):
    return _load_range(file)


@app.post("/api/ranges/save")
def save_range(req: SaveRangeRequest):
    """
    Persist a range file to ``data/<filename>.json``. Overwrites existing
    files silently — this is a single-user authoring tool, no version control
    in the loop. Editor is the configurator of your own JSON; that's the
    intended workflow.

    Filename is sanitized (no traversal, no exotic chars). Data must be a
    dict — anything else is a 400. We don't deep-validate the shape here;
    the editor is expected to produce a well-formed ``{meta, config, spots}``
    payload, and downstream consumers (range_engine, srs.init_cards_from_spots)
    handle their own validation.
    """
    if not isinstance(req.data, dict):
        raise HTTPException(400, detail="data must be a JSON object")

    fn   = _safe_data_filename(req.filename)
    path = os.path.join(DATA_DIR, fn)

    # Make sure DATA_DIR exists in case the user blew it away — saving a
    # range should always succeed regardless of current dir state.
    os.makedirs(DATA_DIR, exist_ok=True)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(req.data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise HTTPException(500, detail=f"Failed to write {fn}: {e}")

    return {"status": "saved", "filename": fn}


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

    # Pack identity rides inside the returned drill_hand so it round-trips back
    # to /api/drill/answer for the journal — the frontend echoes the whole hand
    # verbatim, so no frontend change is needed. journal._stem() strips ".json".
    pack_file = file or _list_range_files()[0]["filename"]

    def _tag(result: dict) -> dict:
        result["pack"] = pack_file
        return result

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
        result = get_drill_hand_rfi(range_data, hero_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"No RFI data for {hero_position} in this pack.")
        return _tag(result)

    if spot == "vs_RFI":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_vs_rfi(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return _tag(result)

    if spot == "vs_3bet":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_vs_3bet(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"Range not found: {hero_position} vs {villain_position}.")
        return _tag(result)

    if spot == "vs_4bet":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_vs_4bet(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"No vs_4bet data: {hero_position} vs {villain_position}.")
        return _tag(result)

    if spot == "iso":
        if not villain_position:
            raise HTTPException(status_code=400, detail="villain_position required.")
        result = get_drill_hand_iso(range_data, hero_position, villain_position)
        if not result:
            raise HTTPException(status_code=404, detail=f"No iso data: {hero_position} vs {villain_position}.")
        return _tag(result)

    raise HTTPException(status_code=400, detail=f"Unknown spot: {spot}")


@app.post("/api/drill/answer")
def submit_answer(request: AnswerRequest, user=Depends(auth.get_current_user)):
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

    # Track D, D.1-api-write: append this answer to the DB journal, in parallel
    # with the JSON above. Best-effort and a no-op without DATABASE_URL, so the
    # current prod (JSON-only) is unaffected. `dh` carries `pack`, stamped at
    # /api/drill/hand time and echoed back by the frontend. `user` is the JWT
    # subject in DB mode (D.2), or the dev user when auth is off.
    journal.record_drill_answer(dh, result, user_id=user)

    return result


@app.get("/api/stats")
def get_stats(user=Depends(auth.get_current_user)):
    # Track D, D.1-api-reads: served from the `answers` journal when a database
    # is configured, otherwise from stats.json (soft degradation). Drill-only.
    # `user` (D.2): the JWT subject in DB mode, or the dev user when auth is off.
    return stats_store.read_stats(STATS_FILE, user_id=user)


@app.post("/api/stats/reset")
def reset_stats():
    # In DB mode `answers` is an append-only journal — never wipe it from here
    # (it also holds Learn history and future FSRS-fit data). The frontend hides
    # this button when the DB is configured; a real per-user "soft reset"
    # (cutoff marker) belongs to the account/dashboard chat. JSON mode: reset the
    # legacy file as before.
    if db.database_configured():
        return {"status": "noop", "reason": "stats are an append-only journal in DB mode"}
    save_stats(dict(_SPOT_DEFAULTS))
    return {"status": "reset"}


@app.get("/api/history")
def get_history(limit: int = Query(50), user=Depends(auth.get_current_user)):
    # Track D, D.1-api-reads: from the journal (newest first) in DB mode, else
    # from history.json. stats_store clamps the limit.
    return stats_store.read_history(HISTORY_FILE, limit, user_id=user)


@app.post("/api/history/clear")
def clear_history():
    # Append-only journal in DB mode — see reset_stats above. JSON mode: clear
    # the legacy file as before.
    if db.database_configured():
        return {"status": "noop", "reason": "history is an append-only journal in DB mode"}
    save_history([])
    return {"status": "cleared"}


_SPOT_OPTIONS_KEY = {
    "vs_RFI":   "vs_rfi_options",
    "vs_3bet":  "vs_3bet_options",
    "vs_4bet":  "vs_4bet_options",
    "iso":      "iso_options",
}


def random_hero_select(config, spot):
    rfi_positions = config["rfi_positions"]
    if spot == "RFI":
        return _random.choice(rfi_positions) if rfi_positions else None
    opts_key = _SPOT_OPTIONS_KEY.get(spot)
    if not opts_key:
        return None
    options = config.get(opts_key, {})
    valid = [h for h in options if options.get(h)]
    return _random.choice(valid) if valid else None


def random_villain_select(config, spot, hero_position):
    opts_key = _SPOT_OPTIONS_KEY.get(spot)
    if not opts_key:
        return None
    villains = config.get(opts_key, {}).get(hero_position, [])
    return _random.choice(villains) if villains else None


# serve frontend
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static_files")
# Recolored 4-color SVG card assets (see docs/roadmap.md B.1-cards)
if os.path.isdir(CARDS_DIR):
    app.mount("/cards", StaticFiles(directory=CARDS_DIR), name="card_assets")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Lets `python3 main.py` start the dev server, matching CLAUDE.md.
# Pass the app as an import string so --reload-style auto-reload works.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)