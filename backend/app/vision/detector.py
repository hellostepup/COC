"""Building detection.

Two backends, tried in order:
  1. YOLO (ultralytics) if a trained model exists at ``<data>/models/coc_buildings.pt``.
  2. OpenCV multi-scale template matching against crops in ``<data>/templates/<label>/*.png``.

There is no public, trustworthy Clash of Clans model, so the app ships without one. Start
with templates (crop a few buildings from your own screenshots), correct detections in the
Vision page, then export the corrected set as a YOLO dataset and train (see ``train_yolo.py``).
"""
from __future__ import annotations

import glob
import os
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from .strategy import ALL_LABELS


def _nms(dets: List[Dict[str, Any]], iou_thresh: float = 0.4) -> List[Dict[str, Any]]:
    dets = sorted(dets, key=lambda d: -d["confidence"])
    keep: List[Dict[str, Any]] = []
    for d in dets:
        if all(_iou(d, k) < iou_thresh for k in keep):
            keep.append(d)
    return keep


def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax1, ay1, ax2, ay2 = a["x"] - a["w"] / 2, a["y"] - a["h"] / 2, a["x"] + a["w"] / 2, a["y"] + a["h"] / 2
    bx1, by1, bx2, by2 = b["x"] - b["w"] / 2, b["y"] - b["h"] / 2, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    iw, ih = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


class Detector:
    def __init__(self, data_dir: str):
        self.model_path = os.path.join(data_dir, "models", "coc_buildings.pt")
        self.template_dir = os.path.join(data_dir, "templates")
        os.makedirs(self.template_dir, exist_ok=True)
        self._yolo = None

    def status(self) -> Dict[str, Any]:
        templates = {lbl: len(glob.glob(os.path.join(self.template_dir, lbl, "*.png")))
                     for lbl in ALL_LABELS}
        return {
            "yolo_model": os.path.exists(self.model_path),
            "yolo_installed": _has_ultralytics(),
            "model_path": self.model_path,
            "template_dir": self.template_dir,
            "templates": {k: v for k, v in templates.items() if v},
            "backend": self.backend(),
        }

    def backend(self) -> str:
        if os.path.exists(self.model_path) and _has_ultralytics():
            return "yolo"
        if any(glob.glob(os.path.join(self.template_dir, "*", "*.png"))):
            return "template"
        return "manual"

    def detect(self, image: np.ndarray) -> Dict[str, Any]:
        backend = self.backend()
        if backend == "yolo":
            dets = self._detect_yolo(image)
        elif backend == "template":
            dets = self._detect_templates(image)
        else:
            dets = []
        msg = None
        if backend == "manual":
            msg = ("No detection model or templates yet. Mark buildings by hand on the screenshot; "
                   "your corrections are saved and can be exported to train a model.")
        return {"backend": backend, "detections": dets, "message": msg}

    def _detect_yolo(self, image: np.ndarray) -> List[Dict[str, Any]]:
        if self._yolo is None:
            from ultralytics import YOLO  # type: ignore
            self._yolo = YOLO(self.model_path)
        res = self._yolo.predict(image, verbose=False, conf=0.25)[0]
        names = res.names
        out = []
        for box, cls, conf in zip(res.boxes.xywh.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()):
            x, y, w, h = box
            out.append({"label": names[int(cls)], "x": x, "y": y, "w": w, "h": h,
                        "confidence": round(float(conf), 3), "source": "yolo"})
        return out

    def _detect_templates(self, image: np.ndarray, threshold: float = 0.72) -> List[Dict[str, Any]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        found: List[Dict[str, Any]] = []
        for path in glob.glob(os.path.join(self.template_dir, "*", "*.png")):
            label = os.path.basename(os.path.dirname(path))
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is None:
                continue
            for scale in (0.7, 0.85, 1.0, 1.15, 1.3):
                t = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                th, tw = t.shape[:2]
                if th >= gray.shape[0] or tw >= gray.shape[1] or th < 8 or tw < 8:
                    continue
                res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(res >= threshold)
                for x, y in zip(xs.tolist(), ys.tolist()):
                    found.append({"label": label, "x": x + tw / 2.0, "y": y + th / 2.0, "w": float(tw),
                                  "h": float(th), "confidence": round(float(res[y, x]), 3),
                                  "source": "template"})
        return _nms(found)


def _has_ultralytics() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("ultralytics") is not None
    except Exception:
        return False


def export_yolo_dataset(samples: List[Dict[str, Any]], out_dir: str) -> Dict[str, Any]:
    """Write verified detections as a YOLO dataset (images/, labels/, data.yaml)."""
    import shutil
    img_dir, lbl_dir = os.path.join(out_dir, "images"), os.path.join(out_dir, "labels")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(lbl_dir, exist_ok=True)
    classes = list(ALL_LABELS)
    count = 0
    for s in samples:
        src, w, h = s["image_path"], s["image_width"], s["image_height"]
        if not src or not os.path.exists(src) or not w or not h:
            continue
        stem = f"sample_{s['id']}"
        shutil.copy(src, os.path.join(img_dir, stem + os.path.splitext(src)[1]))
        lines = []
        for d in s["detections"]:
            if d["label"] not in classes:
                continue
            lines.append(f"{classes.index(d['label'])} {d['x'] / w:.6f} {d['y'] / h:.6f} "
                         f"{d['w'] / w:.6f} {d['h'] / h:.6f}")
        with open(os.path.join(lbl_dir, stem + ".txt"), "w") as f:
            f.write("\n".join(lines))
        count += 1
    with open(os.path.join(out_dir, "data.yaml"), "w") as f:
        f.write(f"path: {os.path.abspath(out_dir)}\ntrain: images\nval: images\n")
        f.write("names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(classes)))
    return {"images": count, "path": os.path.abspath(out_dir), "classes": classes}


def decode_image(data: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
