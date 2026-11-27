"""Mock Clash of Clans environment for testing the full workflow offline.

Nothing here touches the real game. It generates fake bases, fakes noisy detections,
simulates an attack outcome and drives the real Service/planner code with a fake clock,
so the four-account loop (farm -> target -> upgrade -> rotate -> repeat) can be tested.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .db import Database
from .seed import seed_demo
from .service import Service
from .vision.strategy import DEFENSE_LABELS, RESOURCE_LABELS, analyze_layout

IMG = (1600, 900)
DEFENSE_POOL = sorted(DEFENSE_LABELS - {"defense"})


class FakeClock:
    def __init__(self, start: Optional[datetime] = None):
        self.now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


def generate_base(rng: random.Random, town_hall: int = 12) -> Dict[str, Any]:
    """A random base inside an isometric diamond, with loot stored in resource buildings."""
    cx, cy = IMG[0] / 2, IMG[1] / 2
    rx, ry = 520, 330
    scale = 1.0 + (town_hall - 8) * 0.25

    def place() -> Dict[str, float]:
        while True:
            u, v = rng.uniform(-1, 1), rng.uniform(-1, 1)
            if abs(u) + abs(v) <= 0.95:
                return {"x": cx + u * rx, "y": cy + v * ry}

    buildings: List[Dict[str, Any]] = []
    # Resource buildings tend to sit in a couple of clusters in a farming base.
    hubs = [place() for _ in range(rng.randint(2, 3))]
    counts = {"gold_mine": 6, "elixir_collector": 6, "dark_elixir_drill": 2,
              "gold_storage": 3, "elixir_storage": 3, "dark_elixir_storage": 1}
    for lbl, n in counts.items():
        for _ in range(n):
            hub = rng.choice(hubs)
            pos = {"x": hub["x"] + rng.gauss(0, 70), "y": hub["y"] + rng.gauss(0, 45)}
            res = RESOURCE_LABELS[lbl]
            base_loot = {"gold": 60000, "elixir": 60000, "dark": 900}[res]
            mult = 3.0 if "storage" in lbl else 1.0
            loot = int(base_loot * mult * scale * rng.uniform(0.3, 1.6))
            buildings.append({"label": lbl, **pos, "w": 60, "h": 50, "loot": loot, "resource": res})
    for _ in range(rng.randint(14, 22)):
        buildings.append({"label": rng.choice(DEFENSE_POOL), **place(), "w": 50, "h": 50})
    buildings.append({"label": "town_hall", "x": cx, "y": cy, "w": 80, "h": 80})
    for b in buildings:
        b["x"] = min(max(b["x"], 5), IMG[0] - 5)
        b["y"] = min(max(b["y"], 5), IMG[1] - 5)
    total = {"gold": 0, "elixir": 0, "dark": 0}
    for b in buildings:
        if "loot" in b:
            total[b["resource"]] += b["loot"]
    return {"buildings": buildings, "available_loot": total}


def noisy_detections(base: Dict[str, Any], rng: random.Random) -> List[Dict[str, Any]]:
    """Simulated vision output: misses some buildings, mislabels a few, adds jitter."""
    labels = list(RESOURCE_LABELS)
    out = []
    for b in base["buildings"]:
        if rng.random() < 0.08:
            continue  # missed
        label = b["label"]
        conf = rng.uniform(0.6, 0.98)
        if label in RESOURCE_LABELS and rng.random() < 0.05:
            label, conf = rng.choice(labels), rng.uniform(0.3, 0.55)  # wrong, low confidence
        out.append({"label": label, "x": b["x"] + rng.gauss(0, 4), "y": b["y"] + rng.gauss(0, 4),
                    "w": b["w"], "h": b["h"], "confidence": round(conf, 3)})
    return out


def simulate_attack(base: Dict[str, Any], deploy_points: List[Dict[str, float]], army_strength: float,
                    rng: random.Random) -> Dict[str, int]:
    """Loot gained: buildings near the deploy points and lightly defended are likelier to fall."""
    defenses = [b for b in base["buildings"] if b["label"] in DEFENSE_LABELS]
    gained = {"gold": 0, "elixir": 0, "dark": 0}
    for b in base["buildings"]:
        if "loot" not in b:
            continue
        dist = min(math.hypot(b["x"] - p["x"], b["y"] - p["y"]) for p in deploy_points)
        pressure = sum(1 for d in defenses if math.hypot(d["x"] - b["x"], d["y"] - b["y"]) < 180)
        p_destroy = army_strength * math.exp(-dist / 380.0) * (0.92 ** pressure)
        if rng.random() < min(0.97, p_destroy):
            gained[b["resource"]] += int(b["loot"] * rng.uniform(0.75, 1.0))
    return gained


def random_deploy(rng: random.Random) -> List[Dict[str, float]]:
    ang = rng.uniform(0, 2 * math.pi)
    x, y = IMG[0] / 2 + math.cos(ang) * 600, IMG[1] / 2 + math.sin(ang) * 380
    return [{"x": x, "y": y}]


def run_simulation(seed: int = 1, max_battles: int = 2000, use_strategy: bool = True,
                   army_strength: float = 0.9, battle_minutes: float = 12.0,
                   service: Optional[Service] = None, log_limit: int = 400) -> Dict[str, Any]:
    """Run the four-account workflow until every planned upgrade is done (or the limit hits)."""
    rng = random.Random(seed)
    clock = FakeClock()
    if service is None:
        service = Service(Database(":memory:"), clock=clock)
        seed_demo(service)
    else:
        service.clock = clock

    log: List[Dict[str, Any]] = []
    stats = {"battles": 0, "upgrades_started": 0, "upgrades_completed": 0, "switches": 0,
             "loot": {"gold": 0, "elixir": 0, "dark": 0}, "waits": 0, "searches": 0}
    current: Optional[int] = None

    def record(event: str, **kw: Any) -> None:
        if len(log) < log_limit:
            log.append({"t": clock.now.isoformat(), "event": event, **kw})

    for _ in range(max_battles * 3):
        stats["upgrades_completed"] += service.tick()
        dash = service.dashboard()
        if all(v["flags"]["primary"] in ("all_completed", "idle") for v in dash["accounts"]):
            record("done")
            break
        nxt = dash["next_recommended"]
        if nxt is None:
            # Nothing useful anywhere: wait for the soonest builder.
            frees = [r["builder_frees_in"] for r in dash["rotation"] if r["builder_frees_in"] is not None]
            wait = max(60, min(frees)) if frees else 3600
            clock.advance(seconds=wait)
            stats["waits"] += 1
            record("wait", seconds=wait)
            continue
        if nxt["account_id"] != current:
            current = nxt["account_id"]
            service.set_current_account(current)
            stats["switches"] += 1
            record("switch_account", account=nxt["name"], reason=nxt["reason"])

        view = service.account_view(current)
        acc = view["account"]
        if view["flags"]["upgrade_ready"]:
            task = view["plan"]["next_ready"]
            service.confirm_started(task["id"])
            stats["upgrades_started"] += 1
            record("start_upgrade", account=acc["name"], building=task["building"])
            continue

        # Farm one battle. Skip weak bases (the "next" button), like a player would.
        stats["battles"] += 1
        if stats["battles"] > max_battles:
            break
        weights = {"gold": acc["priority_gold"], "elixir": acc["priority_elixir"], "dark": acc["priority_dark"]}
        th = int(acc["town_hall"])
        for _ in range(8):
            base = generate_base(rng, th)
            stats["searches"] += 1
            want = sum(base["available_loot"][r] * weights[r] / 100.0 for r in weights)
            if want > 150000 * (1 + (th - 8) * 0.25):
                break
        if use_strategy:
            analysis = analyze_layout(noisy_detections(base, rng), IMG, priority=weights,
                                      defense_avoidance=acc["defense_avoidance"])
            points = analysis["recommendation"]["deploy_points"] if analysis["ok"] else random_deploy(rng)
        else:
            points = random_deploy(rng)
        loot = simulate_attack(base, points, army_strength, rng)
        service.adjust_resources(current, loot["gold"], loot["elixir"], loot["dark"])
        for r in loot:
            stats["loot"][r] += loot[r]
        clock.advance(minutes=battle_minutes)
        record("battle", account=acc["name"], loot=loot)

    final = service.dashboard()
    return {
        "stats": stats,
        "sim_hours": round((clock.now - datetime(2026, 1, 1, tzinfo=timezone.utc)).total_seconds() / 3600, 1),
        "accounts": [{"name": v["account"]["name"], "status": v["status_label"],
                      "completed": v["plan"]["completed_count"], "planned": v["plan"]["planned_count"],
                      "in_progress": v["plan"]["in_progress_count"]} for v in final["accounts"]],
        "all_completed": all(v["flags"]["primary"] in ("all_completed", "idle") for v in final["accounts"]),
        "log": log,
    }
