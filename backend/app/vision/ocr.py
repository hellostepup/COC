"""Reading numbers and text from screenshots (resource counters, builders, account name).

Uses Tesseract through ``pytesseract`` when available. Regions are fractions of the image
(x1, y1, x2, y2) so they work at any BlueStacks resolution; calibrate them in Settings.
Every result carries a confidence and is shown to the user to confirm before it is saved.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Approximate home-village positions at 16:9. Calibrate in Settings if your layout differs.
DEFAULT_REGIONS: Dict[str, Tuple[float, float, float, float]] = {
    "gold": (0.80, 0.025, 0.935, 0.075),
    "elixir": (0.80, 0.105, 0.935, 0.155),
    "dark": (0.80, 0.185, 0.935, 0.235),
    "builders": (0.43, 0.02, 0.53, 0.07),
    "player_name": (0.05, 0.02, 0.25, 0.06),
}


def tesseract_available() -> bool:
    try:
        import pytesseract  # type: ignore
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def crop(image: np.ndarray, region: Tuple[float, float, float, float]) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = region
    return image[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]


def preprocess(img: np.ndarray) -> np.ndarray:
    """COC counters are white text with a dark outline: keep bright pixels, upscale."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(th) < 127:  # make text dark on light background for Tesseract
        th = 255 - th
    return th


def parse_int(text: str) -> Optional[int]:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else None


def parse_builders(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _ocr(img: np.ndarray, config: str) -> Tuple[str, float]:
    import pytesseract  # type: ignore
    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
    words = [(t, float(c)) for t, c in zip(data["text"], data["conf"]) if str(t).strip() and float(c) >= 0]
    text = " ".join(t for t, _ in words)
    conf = (sum(c for _, c in words) / len(words) / 100.0) if words else 0.0
    return text, round(conf, 3)


def read_counters(image: np.ndarray, regions: Optional[Dict[str, List[float]]] = None) -> Dict[str, Any]:
    regions = {**DEFAULT_REGIONS, **{k: tuple(v) for k, v in (regions or {}).items()}}
    if not tesseract_available():
        return {"ok": False, "message": "Tesseract OCR is not installed. Install it and pytesseract, "
                                        "or enter values by hand.", "fields": {}}
    fields: Dict[str, Any] = {}
    for key in ("gold", "elixir", "dark"):
        text, conf = _ocr(preprocess(crop(image, regions[key])), "--psm 7 -c tessedit_char_whitelist=0123456789 ")
        fields[key] = {"value": parse_int(text), "raw": text, "confidence": conf}
    text, conf = _ocr(preprocess(crop(image, regions["builders"])), "--psm 7 -c tessedit_char_whitelist=0123456789/")
    b = parse_builders(text)
    fields["builders"] = {"value": {"free": b[0], "total": b[1]} if b else None, "raw": text, "confidence": conf}
    for f in fields.values():
        f["needs_review"] = f["value"] is None or f["confidence"] < 0.75
    return {"ok": True, "fields": fields}


def read_player_name(image: np.ndarray, region: Optional[List[float]] = None) -> Tuple[str, float]:
    if not tesseract_available():
        return "", 0.0
    r = tuple(region) if region else DEFAULT_REGIONS["player_name"]
    return _ocr(preprocess(crop(image, r)), "--psm 7")


def match_account(name: str, accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fuzzy-match OCR'd text against account names and tags."""
    best, best_score = None, 0.0
    norm = (name or "").strip().lower()
    for a in accounts:
        for candidate in (a.get("name") or "", a.get("player_tag") or ""):
            if not candidate:
                continue
            score = difflib.SequenceMatcher(None, norm, candidate.strip().lower()).ratio()
            if score > best_score:
                best, best_score = a, score
    return {
        "account_id": best["id"] if best else None,
        "account_name": best["name"] if best else None,
        "score": round(best_score, 3),
        "confident": best_score >= 0.8,
    }
