"""API smoke tests, including AC8 (manual correction of detections)."""
import os
import sys
import tempfile

os.environ["COC_MANAGER_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_dashboard_seed_and_upgrade_cycle():
    r = client.post("/api/seed-demo")
    assert r.status_code == 200
    dash = client.get("/api/dashboard").json()
    assert dash["overview"]["total_accounts"] == 4
    acc = dash["accounts"][0]
    aid = acc["account"]["id"]
    client.patch(f"/api/accounts/{aid}", json={"gold": 9_000_000})
    view = client.get(f"/api/accounts/{aid}").json()
    ready = view["plan"]["next_ready"]
    assert ready["building"] == "Cannon"
    view = client.post(f"/api/upgrades/{ready['id']}/start", json={}).json()
    assert view["upgrades"][0]["status"] == "in_progress"
    assert client.post(f"/api/upgrades/{ready['id']}/start", json={}).status_code == 409
    notes = client.get("/api/notifications?undelivered=true").json()
    assert any("Ready for next upgrade" in n["message"] for n in notes)
    client.post("/api/notifications/delivered", json={"ids": [n["id"] for n in notes]})
    assert client.get("/api/notifications?undelivered=true").json() == []


def test_vision_upload_correct_analyze():
    img = np.full((450, 800, 3), 60, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    r = client.post("/api/vision/upload", files={"file": ("s.png", buf.tobytes(), "image/png")},
                    data={"kind": "battle"})
    assert r.status_code == 200, r.text
    det = r.json()
    assert det["result"]["backend"] == "manual"
    fixed = [{"label": "gold_storage", "x": 600, "y": 300, "w": 40, "h": 40},
             {"label": "gold_mine", "x": 620, "y": 320, "w": 40, "h": 40},
             {"label": "cannon", "x": 200, "y": 100, "w": 40, "h": 40}]
    r = client.post(f"/api/vision/detections/{det['id']}/correct", json={"detections": fixed})
    assert r.json()["verified"] == 1
    a = client.post(f"/api/vision/detections/{det['id']}/analyze", json={}).json()
    assert a["ok"] and a["recommendation"]["deploy_points"]
    assert client.post(f"/api/vision/detections/{det['id']}/correct",
                       json={"detections": [{"label": "nope", "x": 1, "y": 1, "w": 1, "h": 1}]}).status_code == 400
    ds = client.post("/api/vision/export-dataset").json()
    assert ds["images"] >= 1


def test_backup_restore_and_simulation():
    r = client.get("/api/backup")
    assert r.status_code == 200 and len(r.content) > 0
    r = client.post("/api/restore", files={"file": ("b.db", r.content, "application/octet-stream")})
    assert r.json()["ok"]
    assert client.get("/api/dashboard").json()["overview"]["total_accounts"] == 4
    sim = client.post("/api/simulation/run", json={"seed": 2}).json()
    assert sim["all_completed"]
