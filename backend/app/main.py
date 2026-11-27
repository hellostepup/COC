"""FastAPI backend for the COC Farming & Upgrade Manager."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

import cv2
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Database, default_data_dir
from .seed import seed_demo
from .service import InvalidState, NotFound, Service
from .simulation import run_simulation
from .vision import capture as cap
from .vision import ocr
from .vision.detector import Detector, decode_image, export_yolo_dataset
from .vision.strategy import ALL_LABELS, analyze_layout

DATA_DIR = default_data_dir()
SHOT_DIR = os.path.join(DATA_DIR, "screenshots")
LOG_DIR = os.path.join(DATA_DIR, "logs")
for d in (DATA_DIR, SHOT_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)

log = logging.getLogger("cocmanager")
if not log.handlers:
    h = RotatingFileHandler(os.path.join(LOG_DIR, "backend.log"), maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)

db = Database(os.environ.get("COC_MANAGER_DB", os.path.join(DATA_DIR, "coc_manager.db")))
svc = Service(db)
detector = Detector(DATA_DIR)

app = FastAPI(title="COC Farming & Upgrade Manager", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(NotFound)
async def _nf(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidState)
async def _inv(_: Request, exc: InvalidState):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _err(_: Request, exc: Exception):
    log.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})


async def _ticker() -> None:
    while True:
        try:
            svc.tick()
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(30)


@app.on_event("startup")
async def _startup() -> None:
    svc.tick()
    asyncio.get_event_loop().create_task(_ticker())
    log.info("backend started, data dir %s", DATA_DIR)


# ---------------- models ----------------
class AccountIn(BaseModel):
    name: Optional[str] = None
    player_tag: Optional[str] = None
    town_hall: Optional[int] = Field(None, ge=1, le=20)
    focus: Optional[str] = None
    objective: Optional[str] = Field(None, pattern="^(gold|elixir|dark|balanced)$")
    priority_gold: Optional[int] = Field(None, ge=0, le=100)
    priority_elixir: Optional[int] = Field(None, ge=0, le=100)
    priority_dark: Optional[int] = Field(None, ge=0, le=100)
    min_gold: Optional[int] = Field(None, ge=0)
    min_elixir: Optional[int] = Field(None, ge=0)
    min_dark: Optional[int] = Field(None, ge=0)
    troop_composition: Optional[str] = None
    defense_avoidance: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    gold: Optional[int] = Field(None, ge=0)
    elixir: Optional[int] = Field(None, ge=0)
    dark_elixir: Optional[int] = Field(None, ge=0)
    max_gold: Optional[int] = Field(None, ge=0)
    max_elixir: Optional[int] = Field(None, ge=0)
    max_dark: Optional[int] = Field(None, ge=0)
    builders_total: Optional[int] = Field(None, ge=0, le=7)
    builders_busy_untracked: Optional[int] = Field(None, ge=0, le=7)
    rotation_order: Optional[int] = None
    fill_storage_when_done: Optional[bool] = None


class UpgradeIn(BaseModel):
    building: Optional[str] = None
    category: Optional[str] = None
    current_level: Optional[int] = Field(None, ge=0)
    target_level: Optional[int] = Field(None, ge=0)
    cost_gold: Optional[int] = Field(None, ge=0)
    cost_elixir: Optional[int] = Field(None, ge=0)
    cost_dark: Optional[int] = Field(None, ge=0)
    duration_minutes: Optional[int] = Field(None, ge=0)
    builders_required: Optional[int] = Field(None, ge=1, le=7)
    priority: Optional[int] = None
    notes: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=1, le=1000)
    done_count: Optional[int] = Field(None, ge=0, le=1000)
    cost_either: Optional[int] = Field(None, ge=0)


def _clean(m: BaseModel) -> Dict[str, Any]:
    return {k: v for k, v in m.model_dump().items() if v is not None}


# ---------------- core ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "data_dir": DATA_DIR}


@app.get("/api/dashboard")
def dashboard():
    return svc.dashboard()


@app.post("/api/seed-demo")
def seed():
    if svc.list_accounts():
        raise HTTPException(409, "Accounts already exist")
    seed_demo(svc)
    return svc.dashboard()


@app.get("/api/accounts")
def accounts():
    return [svc.account_view(a["id"]) for a in svc.list_accounts()]


@app.post("/api/accounts")
def create_account(body: AccountIn):
    acc = svc.create_account(_clean(body))
    return svc.account_view(acc["id"])


@app.get("/api/accounts/{account_id}")
def get_account(account_id: int):
    return svc.account_view(account_id)


@app.patch("/api/accounts/{account_id}")
def update_account(account_id: int, body: AccountIn):
    svc.update_account(account_id, _clean(body))
    return svc.account_view(account_id)


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int):
    svc.delete_account(account_id)
    return {"ok": True}


@app.post("/api/accounts/{account_id}/loot")
def add_loot(account_id: int, gold: int = Body(0), elixir: int = Body(0), dark: int = Body(0)):
    svc.adjust_resources(account_id, gold, elixir, dark)
    return svc.account_view(account_id)


@app.post("/api/accounts/{account_id}/select")
def select_account(account_id: int):
    svc.set_current_account(account_id)
    return {"ok": True, "current_account_id": account_id}


@app.post("/api/accounts/{account_id}/upgrades")
def create_upgrade(account_id: int, body: UpgradeIn):
    svc.create_upgrade(account_id, _clean(body))
    return svc.account_view(account_id)


@app.post("/api/accounts/{account_id}/upgrades/reorder")
def reorder(account_id: int, ids: List[int] = Body(..., embed=True)):
    svc.reorder_upgrades(account_id, ids)
    return svc.account_view(account_id)


@app.patch("/api/upgrades/{upgrade_id}")
def update_upgrade(upgrade_id: int, body: UpgradeIn):
    u = svc.update_upgrade(upgrade_id, _clean(body))
    return svc.account_view(u["account_id"])


@app.delete("/api/upgrades/{upgrade_id}")
def delete_upgrade(upgrade_id: int):
    u = svc.get_upgrade(upgrade_id)
    svc.delete_upgrade(upgrade_id)
    return svc.account_view(u["account_id"])


@app.post("/api/upgrades/{upgrade_id}/start")
def start_upgrade(upgrade_id: int, deduct_cost: bool = Body(True, embed=True),
                  duration_minutes: Optional[int] = Body(None, embed=True)):
    u = svc.confirm_started(upgrade_id, deduct_cost, duration_minutes)
    return svc.account_view(u["account_id"])


@app.post("/api/upgrades/{upgrade_id}/units")
def record_units(upgrade_id: int, with_gold: int = Body(0, embed=True), with_elixir: int = Body(0, embed=True),
                 deduct_cost: bool = Body(True, embed=True)):
    u = svc.record_units(upgrade_id, with_gold, with_elixir, deduct_cost)
    return svc.account_view(u["account_id"])


@app.post("/api/upgrades/{upgrade_id}/complete")
def complete_upgrade(upgrade_id: int):
    u = svc.mark_completed(upgrade_id)
    return svc.account_view(u["account_id"])


@app.post("/api/upgrades/{upgrade_id}/revert")
def revert_upgrade(upgrade_id: int):
    u = svc.revert_to_planned(upgrade_id)
    return svc.account_view(u["account_id"])


@app.get("/api/rotation")
def rotation():
    return svc.rotation()


@app.get("/api/notifications")
def notifications(undelivered: bool = False):
    return svc.notifications(undelivered_only=undelivered)


@app.post("/api/notifications/delivered")
def delivered(ids: List[int] = Body(..., embed=True)):
    svc.mark_delivered(ids)
    return {"ok": True}


@app.post("/api/notifications/read-all")
def read_all():
    svc.mark_all_read()
    return {"ok": True}


# ---------------- settings, backup ----------------
@app.get("/api/settings")
def get_settings():
    return {
        "ocr_regions": db.get_setting("ocr_regions", {k: list(v) for k, v in ocr.DEFAULT_REGIONS.items()}),
        "notifications_enabled": db.get_setting("notifications_enabled", True),
        "data_dir": DATA_DIR,
    }


@app.put("/api/settings")
def put_settings(body: Dict[str, Any] = Body(...)):
    for key in ("ocr_regions", "notifications_enabled"):
        if key in body:
            db.set_setting(key, body[key])
    return get_settings()


@app.get("/api/backup")
def backup():
    path = os.path.join(tempfile.mkdtemp(), "coc_manager_backup.db")
    db.backup_to(path)
    return FileResponse(path, filename="coc_manager_backup.db", media_type="application/octet-stream")


@app.post("/api/restore")
async def restore(file: UploadFile = File(...)):
    tmp = os.path.join(tempfile.mkdtemp(), "restore.db")
    with open(tmp, "wb") as f:
        f.write(await file.read())
    try:
        Database(tmp).close()  # validates it is a usable SQLite file with our schema
    except Exception as exc:
        raise HTTPException(400, f"Not a valid backup: {exc}")
    safety = os.path.join(DATA_DIR, "pre_restore_backup.db")
    db.backup_to(safety)
    db.restore_from(tmp)
    log.info("restored backup; previous data saved to %s", safety)
    return {"ok": True, "previous_data_saved_to": safety}


@app.get("/api/logs")
def logs(lines: int = 200):
    path = os.path.join(LOG_DIR, "backend.log")
    if not os.path.exists(path):
        return {"lines": []}
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"lines": f.readlines()[-lines:]}


# ---------------- vision ----------------
@app.get("/api/vision/status")
def vision_status():
    return {**detector.status(), "ocr_available": ocr.tesseract_available(),
            "capture_supported": os.name == "nt", "labels": ALL_LABELS}


@app.get("/api/vision/windows")
def vision_windows():
    return cap.list_windows()


def _store_image(img) -> str:
    path = os.path.join(SHOT_DIR, f"{uuid.uuid4().hex}.png")
    cv2.imwrite(path, img)
    return path


def _process(img, kind: str, account_id: Optional[int]) -> Dict[str, Any]:
    h, w = img.shape[:2]
    path = _store_image(img)
    if kind == "battle":
        result = detector.detect(img)
    elif kind == "home":
        result = ocr.read_counters(img, db.get_setting("ocr_regions"))
    else:
        raise HTTPException(400, "kind must be 'battle' or 'home'")
    det = svc.save_detection(kind, result, account_id, path, (w, h))
    log.info("vision %s: id=%s backend=%s", kind, det["id"], result.get("backend"))
    return det


@app.post("/api/vision/upload")
async def vision_upload(file: UploadFile = File(...), kind: str = Form("battle"),
                        account_id: Optional[int] = Form(None)):
    img = decode_image(await file.read())
    if img is None:
        raise HTTPException(400, "Could not read image")
    return _process(img, kind, account_id)


@app.post("/api/vision/capture")
def vision_capture(kind: str = Body("battle", embed=True), account_id: Optional[int] = Body(None, embed=True)):
    if os.name != "nt":
        raise HTTPException(400, "Window capture works on Windows only; upload a screenshot instead.")
    try:
        img = cap.capture()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    if img is None:
        raise HTTPException(404, "BlueStacks window not found")
    return _process(img, kind, account_id)


@app.get("/api/vision/detections/{detection_id}")
def get_detection(detection_id: int):
    return svc.get_detection(detection_id)


@app.get("/api/vision/detections/{detection_id}/image")
def detection_image(detection_id: int):
    d = svc.get_detection(detection_id)
    if not d["image_path"] or not os.path.exists(d["image_path"]):
        raise HTTPException(404, "image missing")
    return FileResponse(d["image_path"])


@app.post("/api/vision/detections/{detection_id}/correct")
def correct_detection(detection_id: int, detections: List[Dict[str, Any]] = Body(..., embed=True)):
    for d in detections:
        if d.get("label") not in ALL_LABELS:
            raise HTTPException(400, f"unknown label {d.get('label')}")
        d["confidence"] = 1.0  # human-verified
        d["source"] = d.get("source") or "manual"
    return svc.correct_detection(detection_id, {"detections": detections})


@app.post("/api/vision/detections/{detection_id}/analyze")
def analyze(detection_id: int, account_id: Optional[int] = Body(None, embed=True)):
    d = svc.get_detection(detection_id)
    dets = (d["corrected"] or d["result"]).get("detections", [])
    acc_id = account_id or d["account_id"] or svc.current_account_id()
    kwargs: Dict[str, Any] = {}
    if acc_id:
        a = svc.get_account(acc_id)
        kwargs = {"priority": {"gold": a["priority_gold"], "elixir": a["priority_elixir"], "dark": a["priority_dark"]},
                  "objective": a["objective"], "defense_avoidance": a["defense_avoidance"]}
    return analyze_layout(dets, (d["image_width"], d["image_height"]), **kwargs)


class CounterConfirm(BaseModel):
    account_id: int
    gold: Optional[int] = Field(None, ge=0)
    elixir: Optional[int] = Field(None, ge=0)
    dark_elixir: Optional[int] = Field(None, ge=0)
    builders_free: Optional[int] = Field(None, ge=0)
    builders_total: Optional[int] = Field(None, ge=0)


@app.post("/api/vision/detections/{detection_id}/apply-counters")
def apply_counters(detection_id: int, body: CounterConfirm):
    """User-confirmed OCR values -> account balances."""
    svc.get_detection(detection_id)
    data = {k: v for k, v in body.model_dump().items() if v is not None and k in ("gold", "elixir", "dark_elixir")}
    if body.builders_total is not None:
        data["builders_total"] = body.builders_total
    if body.builders_free is not None:
        total = body.builders_total if body.builders_total is not None else svc.get_account(body.account_id)["builders_total"]
        tracked = svc.plan(body.account_id)["builders"]["busy"] - svc.get_account(body.account_id)["builders_busy_untracked"]
        data["builders_busy_untracked"] = max(0, int(total) - int(body.builders_free) - int(tracked))
    svc.update_account(body.account_id, data)
    svc.correct_detection(detection_id, {"applied": body.model_dump()})
    return svc.account_view(body.account_id)


@app.post("/api/vision/verify-account")
async def verify_account(file: Optional[UploadFile] = File(None), expected_account_id: Optional[int] = Form(None)):
    """After switching accounts in BlueStacks, check which account is on screen."""
    if file is not None:
        img = decode_image(await file.read())
    elif os.name == "nt":
        img = cap.capture()
    else:
        img = None
    if img is None:
        raise HTTPException(400, "No screenshot available")
    regions = db.get_setting("ocr_regions") or {}
    text, conf = ocr.read_player_name(img, regions.get("player_name"))
    match = ocr.match_account(text, svc.list_accounts())
    match.update({"read_text": text, "ocr_confidence": conf, "ocr_available": ocr.tesseract_available()})
    if expected_account_id is not None:
        match["matches_expected"] = match["account_id"] == expected_account_id and match["confident"]
    return match


@app.post("/api/vision/export-dataset")
def export_dataset():
    out = os.path.join(DATA_DIR, "dataset")
    shutil.rmtree(out, ignore_errors=True)
    return export_yolo_dataset(svc.verified_samples(), out)


# ---------------- simulation ----------------
@app.post("/api/simulation/run")
def simulation(seed: int = Body(1, embed=True), use_strategy: bool = Body(True, embed=True),
               max_battles: int = Body(2000, embed=True)):
    """Runs on a throwaway in-memory database with the starter accounts; real data is untouched."""
    return run_simulation(seed=seed, use_strategy=use_strategy, max_battles=min(max_battles, 5000))


# ---------------- static frontend ----------------
_static = os.environ.get("COC_MANAGER_STATIC") or os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")
