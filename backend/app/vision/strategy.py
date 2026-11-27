"""Battle layout analysis: turns building detections into a suggested farming approach.

Input detections use image pixel coordinates (x, y = box centre, y grows downward).
Output is a suggestion only; the user searches, deploys and ends the battle in the game.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

RESOURCE_LABELS = {
    "gold_mine": "gold",
    "gold_storage": "gold",
    "elixir_collector": "elixir",
    "elixir_storage": "elixir",
    "dark_elixir_drill": "dark",
    "dark_elixir_storage": "dark",
}
# Storages hold far more loot than collectors in a typical farming base.
LABEL_WEIGHT = {
    "gold_mine": 1.0, "elixir_collector": 1.0, "dark_elixir_drill": 1.2,
    "gold_storage": 2.0, "elixir_storage": 2.0, "dark_elixir_storage": 2.5,
}
DEFENSE_LABELS = {
    "cannon", "archer_tower", "mortar", "wizard_tower", "air_defense", "hidden_tesla",
    "bomb_tower", "xbow", "inferno_tower", "eagle_artillery", "scattershot", "defense",
}
OTHER_LABELS = {"town_hall", "clan_castle"}
ALL_LABELS = sorted(set(RESOURCE_LABELS) | DEFENSE_LABELS | OTHER_LABELS)

SECTORS = ["Top", "Top-Right", "Right", "Bottom-Right", "Bottom", "Bottom-Left", "Left", "Top-Left"]
AVOIDANCE_FACTOR = {"low": 0.3, "medium": 0.7, "high": 1.2}
LOW_CONFIDENCE = 0.5

OBJECTIVE_WEIGHTS = {
    "gold": {"gold": 1.0, "elixir": 0.2, "dark": 0.2},
    "elixir": {"gold": 0.2, "elixir": 1.0, "dark": 0.2},
    "dark": {"gold": 0.1, "elixir": 0.1, "dark": 1.0},
    "balanced": {"gold": 1.0, "elixir": 1.0, "dark": 1.0},
}


def resource_weights(priority: Optional[Dict[str, float]] = None, objective: str = "balanced") -> Dict[str, float]:
    """Per-resource weights from the account's priority percentages (preferred) or objective."""
    if priority and sum(priority.values()) > 0:
        total = float(sum(priority.values()))
        return {r: float(priority.get(r, 0)) / total for r in ("gold", "elixir", "dark")}
    w = OBJECTIVE_WEIGHTS.get(objective, OBJECTIVE_WEIGHTS["balanced"])
    total = sum(w.values())
    return {r: v / total for r, v in w.items()}


def _sector_of(dx: float, dy: float) -> int:
    # Angle measured clockwise from "up" on screen.
    ang = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
    return int(((ang + 22.5) % 360.0) // 45.0)


def _cluster(points: List[Dict[str, Any]], radius: float) -> List[List[Dict[str, Any]]]:
    """Single-link clustering of resource buildings that sit within ``radius`` of each other."""
    clusters: List[List[Dict[str, Any]]] = []
    unassigned = list(points)
    while unassigned:
        seed = unassigned.pop(0)
        group = [seed]
        changed = True
        while changed:
            changed = False
            for p in list(unassigned):
                if any(math.hypot(p["x"] - q["x"], p["y"] - q["y"]) <= radius for q in group):
                    group.append(p)
                    unassigned.remove(p)
                    changed = True
        clusters.append(group)
    return clusters


def analyze_layout(detections: List[Dict[str, Any]], image_size: Tuple[int, int],
                   priority: Optional[Dict[str, float]] = None, objective: str = "balanced",
                   defense_avoidance: str = "medium") -> Dict[str, Any]:
    width, height = image_size
    dets = [d for d in detections if d.get("label") in RESOURCE_LABELS or d.get("label") in DEFENSE_LABELS
            or d.get("label") in OTHER_LABELS]
    uncertain = [d for d in detections if float(d.get("confidence", 1.0)) < LOW_CONFIDENCE]
    weights = resource_weights(priority, objective)
    avoid = AVOIDANCE_FACTOR.get(defense_avoidance, AVOIDANCE_FACTOR["medium"])

    resources = [d for d in dets if d["label"] in RESOURCE_LABELS]
    defenses = [d for d in dets if d["label"] in DEFENSE_LABELS]
    if not resources:
        return {
            "ok": False,
            "message": "No resource buildings detected. Add or correct detections, then analyze again.",
            "uncertain": uncertain, "sectors": [], "clusters": [], "recommendation": None,
        }

    # Base centre and extent from every detected building.
    cx = sum(d["x"] for d in dets) / len(dets)
    cy = sum(d["y"] for d in dets) / len(dets)
    extent = max(math.hypot(d["x"] - cx, d["y"] - cy) for d in dets) or 1.0
    radius = max(40.0, 0.22 * extent)

    def value(d: Dict[str, Any]) -> float:
        return LABEL_WEIGHT[d["label"]] * weights[RESOURCE_LABELS[d["label"]]] * float(d.get("confidence", 1.0))

    def defense_pressure(x: float, y: float) -> float:
        # Defenses close to a point count more; anything beyond ~2 radii counts little.
        return sum(float(d.get("confidence", 1.0)) * math.exp(-(math.hypot(d["x"] - x, d["y"] - y) / (2 * radius)) ** 2)
                   for d in defenses)

    sectors = [{"name": n, "resource_score": 0.0, "defense_score": 0.0,
                "counts": {"gold": 0, "elixir": 0, "dark": 0}, "defenses": 0} for n in SECTORS]
    for d in resources:
        s = sectors[_sector_of(d["x"] - cx, d["y"] - cy)]
        s["resource_score"] += value(d)
        s["counts"][RESOURCE_LABELS[d["label"]]] += 1
    for d in defenses:
        s = sectors[_sector_of(d["x"] - cx, d["y"] - cy)]
        s["defense_score"] += float(d.get("confidence", 1.0))
        s["defenses"] += 1
    for s in sectors:
        s["net_score"] = round(s["resource_score"] - avoid * 0.5 * s["defense_score"], 3)
        s["resource_score"] = round(s["resource_score"], 3)
        s["defense_score"] = round(s["defense_score"], 3)

    clusters_out = []
    for group in _cluster(resources, radius):
        gx = sum(p["x"] for p in group) / len(group)
        gy = sum(p["y"] for p in group) / len(group)
        loot = sum(value(p) for p in group)
        pressure = defense_pressure(gx, gy)
        # Distance from the edge: resources near the outside are cheaper to reach.
        depth = 1.0 - min(1.0, math.hypot(gx - cx, gy - cy) / extent)
        score = loot - avoid * 0.6 * pressure - 0.4 * depth * loot
        clusters_out.append({
            "center": {"x": round(gx, 1), "y": round(gy, 1)},
            "buildings": [p["label"] for p in group],
            "loot_score": round(loot, 3),
            "defense_pressure": round(pressure, 3),
            "depth": round(depth, 3),
            "score": round(score, 3),
            "sector": SECTORS[_sector_of(gx - cx, gy - cy)],
        })
    clusters_out.sort(key=lambda c: -c["score"])

    best_sector = max(sectors, key=lambda s: s["net_score"])
    target = clusters_out[0]
    deploy_points = _deploy_points(target["center"], (cx, cy), extent, (width, height))
    top_res = max(("gold", "elixir", "dark"), key=lambda r: target_count(target, r))
    weakest = min(sectors, key=lambda s: s["defense_score"])

    summary = (
        f"Most weighted loot is on the {best_sector['name']} side. Best target group: "
        f"{len(target['buildings'])} resource buildings on the {target['sector']} side "
        f"(mostly {pretty(top_res)}), defense pressure {target['defense_pressure']:.1f}. "
        f"Deploy from the {target['sector']} edge at the marked points."
    )
    return {
        "ok": True,
        "base_center": {"x": round(cx, 1), "y": round(cy, 1)},
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "sectors": sectors,
        "clusters": clusters_out,
        "least_defended_side": weakest["name"],
        "recommendation": {
            "side": target["sector"],
            "richest_side": best_sector["name"],
            "target_cluster": target,
            "deploy_points": deploy_points,
            "objective": f"Collect {pretty(top_res)} from the {target['sector']} group, then end the battle",
            "summary": summary,
        },
        "uncertain": uncertain,
        "needs_review": bool(uncertain),
    }


def target_count(cluster: Dict[str, Any], resource: str) -> int:
    return sum(1 for b in cluster["buildings"] if RESOURCE_LABELS.get(b) == resource)


def pretty(resource: str) -> str:
    return {"gold": "Gold", "elixir": "Elixir", "dark": "Dark Elixir"}[resource]


def _deploy_points(target: Dict[str, float], center: Tuple[float, float], extent: float,
                   size: Tuple[int, int]) -> List[Dict[str, float]]:
    """Three points just outside the base, on the line from the centre through the target."""
    cx, cy = center
    dx, dy = target["x"] - cx, target["y"] - cy
    norm = math.hypot(dx, dy)
    if norm < 1e-6:
        dx, dy, norm = 0.0, 1.0, 1.0
    ux, uy = dx / norm, dy / norm
    px, py = -uy, ux  # perpendicular, to spread the deploy points
    r = extent * 1.12
    w, h = size
    pts = []
    for off in (-0.18, 0.0, 0.18):
        x = cx + ux * r + px * off * extent
        y = cy + uy * r + py * off * extent
        pts.append({"x": round(min(max(x, 0.0), w - 1.0), 1), "y": round(min(max(y, 0.0), h - 1.0), 1)})
    return pts
