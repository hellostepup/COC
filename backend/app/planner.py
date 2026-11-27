"""Upgrade planning, account status and rotation logic.

Everything here is pure: it takes plain dicts (rows from the database) and returns
plain dicts, so the same code drives the live app and the simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RESOURCES = ("gold", "elixir", "dark")
BALANCE_FIELD = {"gold": "gold", "elixir": "elixir", "dark": "dark_elixir"}
MAX_FIELD = {"gold": "max_gold", "elixir": "max_elixir", "dark": "max_dark"}
COST_FIELD = {"gold": "cost_gold", "elixir": "cost_elixir", "dark": "cost_dark"}
MIN_FIELD = {"gold": "min_gold", "elixir": "min_elixir", "dark": "min_dark"}

STORAGE_FULL_PCT = 98.0
STORAGE_ALMOST_FULL_PCT = 90.0

ACTIVE_STATUSES = ("planned", "in_progress")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def balances(account: Dict[str, Any]) -> Dict[str, int]:
    return {r: int(account.get(BALANCE_FIELD[r]) or 0) for r in RESOURCES}


def capacities(account: Dict[str, Any]) -> Dict[str, int]:
    return {r: int(account.get(MAX_FIELD[r]) or 0) for r in RESOURCES}


def cost(upgrade: Dict[str, Any]) -> Dict[str, int]:
    return {r: int(upgrade.get(COST_FIELD[r]) or 0) for r in RESOURCES}


def storage_pct(account: Dict[str, Any]) -> Dict[str, Optional[float]]:
    bal, cap = balances(account), capacities(account)
    return {r: (round(100.0 * bal[r] / cap[r], 1) if cap[r] > 0 else None) for r in RESOURCES}


def builders(account: Dict[str, Any], upgrades: List[Dict[str, Any]]) -> Dict[str, int]:
    total = int(account.get("builders_total") or 0)
    tracked = sum(int(u.get("builders_required") or 1) for u in upgrades if u["status"] == "in_progress")
    busy = min(total, tracked + int(account.get("builders_busy_untracked") or 0))
    return {"total": total, "busy": busy, "free": max(0, total - busy)}


def remaining(need: Dict[str, int], have: Dict[str, int]) -> Dict[str, int]:
    return {r: max(0, need[r] - have[r]) for r in RESOURCES}


def upgrade_progress(upgrade: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Progress of an in-progress upgrade, from its start and completion timestamps."""
    if upgrade["status"] != "in_progress":
        return None
    now = now or utcnow()
    start, end = parse_ts(upgrade.get("started_at")), parse_ts(upgrade.get("completes_at"))
    if not start or not end:
        return {"percent": 0.0, "seconds_left": None, "completes_at": upgrade.get("completes_at")}
    total = max(1.0, (end - start).total_seconds())
    done = min(total, max(0.0, (now - start).total_seconds()))
    return {
        "percent": round(100.0 * done / total, 1),
        "seconds_left": int(max(0.0, (end - now).total_seconds())),
        "completes_at": upgrade.get("completes_at"),
    }


def plan_queue(account: Dict[str, Any], upgrades: List[Dict[str, Any]],
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """Evaluate the sequential upgrade queue for one account.

    Each planned task is checked against the current balance and free builders. Tasks are
    evaluated in priority order; if priority 1 cannot start, priority 2's readiness is still
    reported. ``next_ready`` is the highest-priority task that can start right now.
    """
    have = balances(account)
    cap = capacities(account)
    b = builders(account, upgrades)
    ordered = sorted(upgrades, key=lambda u: (int(u.get("priority") or 0), u["id"]))

    tasks = []
    planned_total = {r: 0 for r in RESOURCES}
    next_ready = None
    # Loot and builders not yet set aside for a higher-priority ready task.
    pool = dict(have)
    free_pool = b["free"]
    planned_either = [0]  # total loot still needed by "Gold or Elixir" tasks (e.g. walls)
    for u in ordered:
        c = cost(u)
        entry = {
            "id": u["id"],
            "building": u["building"],
            "priority": u["priority"],
            "status": u["status"],
            "cost": c,
            "remaining": {r: 0 for r in RESOURCES},
            "affordable": False,
            "builder_ok": False,
            "ready": False,
            "blockers": [],
            "progress": upgrade_progress(u, now),
        }
        if u["status"] == "planned" and int(u.get("cost_either") or 0) > 0:
            # A wall needs a free builder when you upgrade it, but no builder is held for it.
            _plan_either(u, entry, have, pool, b["free"], free_pool, planned_either)
            if entry["ready"] and next_ready is None:
                next_ready = entry
        elif u["status"] == "planned":
            for r in RESOURCES:
                planned_total[r] += c[r]
            need_b = int(u.get("builders_required") or 1)
            rem = remaining(c, have)
            entry["remaining"] = rem
            entry["affordable"] = not any(rem.values())
            entry["builder_ok"] = b["free"] >= need_b
            # Ready only if it still fits after the higher-priority ready tasks are paid for.
            rem_after = remaining(c, pool)
            entry["ready"] = not any(rem_after.values()) and free_pool >= need_b
            if entry["ready"]:
                for r in RESOURCES:
                    pool[r] -= c[r]
                free_pool -= need_b
            elif entry["affordable"] and entry["builder_ok"]:
                if any(rem_after.values()):
                    extra = ", ".join(f"{rem_after[r]:,} {label(r)}" for r in RESOURCES if rem_after[r])
                    entry["blockers"].append(f"loot is set aside for a higher-priority upgrade; need {extra} more for both")
                else:
                    entry["blockers"].append("free builders are set aside for higher-priority upgrades")
            for r in RESOURCES:
                if rem[r]:
                    entry["blockers"].append(f"need {rem[r]:,} more {label(r)}")
                if cap[r] and c[r] > cap[r]:
                    entry["blockers"].append(f"{label(r)} cost exceeds storage capacity ({cap[r]:,})")
            if not entry["builder_ok"]:
                entry["blockers"].append("no free builder")
            # Starting this before an unaffordable higher-priority task spends the same loot.
            entry["delays"] = [t["building"] for t in tasks if t["status"] == "planned" and not t["affordable"]
                               and any(c[r] and t["cost"][r] for r in RESOURCES)]
            if entry["ready"] and next_ready is None:
                next_ready = entry
        tasks.append(entry)

    total_remaining = remaining(planned_total, have)
    planned = [t for t in tasks if t["status"] == "planned"]
    in_progress = [t for t in tasks if t["status"] == "in_progress"]
    # The next thing to farm for: the highest-priority planned task that is not yet affordable.
    farming_for = next((t for t in planned if not t["affordable"]), None)

    # When every upgrade is done, optionally keep farming until the storages are full.
    filling = bool(account.get("fill_storage_when_done")) and not planned and not in_progress and \
        any(t["status"] == "completed" for t in tasks)
    fill_res = [r for r in RESOURCES if cap[r] > 0 and int(account.get(f"priority_{r}") or 0) > 0]

    targets = {}
    for r in RESOURCES:
        manual = int(account.get(MIN_FIELD[r]) or 0)
        from_queue = farming_for["cost"][r] if farming_for else 0
        target = max(manual, from_queue)
        if filling and r in fill_res:
            target = max(target, cap[r])
        targets[r] = {
            "target": target,
            "current": have[r],
            "remaining": max(0, target - have[r]),
            "percent": (100.0 if target == 0 else round(min(100.0, 100.0 * have[r] / target), 1)),
        }

    return {
        "tasks": tasks,
        "next_ready": next_ready,
        "farming_for": farming_for,
        "planned_count": len(planned),
        "in_progress_count": len(in_progress),
        "completed_count": sum(1 for t in tasks if t["status"] == "completed"),
        "total_required": planned_total,
        "total_remaining": total_remaining,
        # "Gold or Elixir" tasks: loot still needed beyond what can be paid now.
        "either_remaining": planned_either[0],
        "filling_storage": filling,
        "targets": targets,
        "builders": b,
    }


def _plan_either(u: Dict[str, Any], entry: Dict[str, Any], have: Dict[str, int], pool: Dict[str, int],
                 free_now: int, free_pool: int, planned_either: List[int]) -> None:
    """A multi-unit task where each unit is paid fully with Gold OR Elixir (walls).

    Each unit is bought with one resource, so leftovers of Gold and Elixir cannot be
    combined: with 2.5 units of Gold and 0.5 of Elixir you can do 2 units, not 3.
    """
    unit = int(u["cost_either"])
    total = max(1, int(u.get("quantity") or 1))
    done = min(total, int(u.get("done_count") or 0))
    left = total - done

    def units(bal: Dict[str, int]) -> Dict[str, int]:
        g = min(left, bal["gold"] // unit)
        e = min(left - g, bal["elixir"] // unit)
        return {"gold": g, "elixir": e}

    now = units(have)
    after = units(pool)
    can_now = now["gold"] + now["elixir"]
    can_after = after["gold"] + after["elixir"]
    short_units = left - can_now
    # Loot needed for the missing units, less the leftover Gold/Elixir that can be topped up.
    # Each leftover can grow into one more unit, so with 1 unit missing only the bigger one helps.
    need = 0
    if short_units:
        rg, re_ = have["gold"] - now["gold"] * unit, have["elixir"] - now["elixir"] * unit
        usable = rg + re_ if short_units >= 2 else max(rg, re_)
        need = max(0, short_units * unit - usable)
    planned_either[0] += need

    entry["either"] = {
        "unit_cost": unit, "total": total, "done": done, "left": left,
        "can_do_now": can_now, "pay_with_gold": now["gold"], "pay_with_elixir": now["elixir"],
        "short_units": short_units, "loot_needed": need,
        "percent": round(100.0 * done / total, 1),
    }
    entry["cost"] = {"gold": 0, "elixir": 0, "dark": 0}
    entry["affordable"] = short_units == 0
    entry["builder_ok"] = free_now >= 1
    entry["ready"] = can_after > 0 and free_pool >= 1
    entry["delays"] = []
    if entry["ready"]:
        pool["gold"] -= after["gold"] * unit
        pool["elixir"] -= after["elixir"] * unit
    if short_units:
        entry["blockers"].append(f"{short_units} more to go: need about {need:,} more Gold or Elixir")
    if not entry["builder_ok"]:
        entry["blockers"].append("no free builder")


def label(resource: str) -> str:
    return {"gold": "Gold", "elixir": "Elixir", "dark": "Dark Elixir"}[resource]


def account_flags(account: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """The account status flags from the requirements, plus one primary status."""
    pct = storage_pct(account)
    b = plan["builders"]
    any_planned = plan["planned_count"] > 0
    targets_met = all(t["remaining"] == 0 for t in plan["targets"].values()) and \
        not plan.get("either_remaining")
    filling = bool(plan.get("filling_storage"))
    storage_full = {r: (p is not None and p >= STORAGE_FULL_PCT) for r, p in pct.items()}
    almost_full = {r: (p is not None and p >= STORAGE_ALMOST_FULL_PCT) for r, p in pct.items()}

    # Only count storages that matter for the planned work, so a full dark storage
    # on a pure gold account does not block farming.
    needed = {r: plan["total_required"][r] > 0 or plan["targets"][r]["target"] > 0 for r in RESOURCES}
    relevant = [r for r in RESOURCES if needed[r]] or list(RESOURCES)
    relevant_full = all(storage_full[r] for r in relevant if pct[r] is not None) and \
        any(pct[r] is not None for r in relevant)

    flags = {
        "farming_required": (any_planned or filling) and not targets_met,
        "resource_target_reached": targets_met and (any_planned or any(
            t["target"] > 0 for t in plan["targets"].values())),
        "upgrade_ready": plan["next_ready"] is not None,
        "upgrade_in_progress": plan["in_progress_count"] > 0,
        "builder_busy": b["total"] > 0 and b["free"] == 0,
        "builder_available": b["free"] > 0,
        "storage_full": any(storage_full.values()),
        "storage_almost_full": {r: almost_full[r] for r in RESOURCES},
        "all_completed": (plan["planned_count"] == 0 and plan["in_progress_count"] == 0
                          and plan["completed_count"] > 0 and not (filling and not targets_met)),
    }

    if flags["all_completed"]:
        primary = "all_completed"
    elif filling:
        primary = "filling_storage"
    elif flags["upgrade_ready"]:
        primary = "upgrade_ready"
    elif plan["planned_count"] == 0 and plan["in_progress_count"] == 0:
        primary = "idle"
    elif not any_planned or (flags["builder_busy"] and (targets_met or relevant_full)):
        # Every builder is working and either nothing is left to start, or the loot for
        # the next task is saved / storage is full. Nothing more to do on this account now.
        primary = "target_completed"
    elif relevant_full:
        primary = "storage_full"
    elif flags["farming_required"]:
        primary = "farming_required"
    elif flags["builder_busy"]:
        primary = "builder_busy"
    else:
        primary = "resource_target_reached"
    flags["primary"] = primary
    return flags


PRIMARY_LABEL = {
    "upgrade_ready": "Upgrade Ready",
    "farming_required": "Farming Required",
    "resource_target_reached": "Resource Target Reached",
    "target_completed": "Target Completed",
    "builder_busy": "Builder Busy",
    "storage_full": "Storage Full",
    "all_completed": "All Planned Upgrades Completed",
    "filling_storage": "Upgrades Done · Filling Storage",
    "idle": "No Upgrades Planned",
}


def next_builder_free(plan: Dict[str, Any]) -> Optional[int]:
    secs = [t["progress"]["seconds_left"] for t in plan["tasks"]
            if t["status"] == "in_progress" and t["progress"] and t["progress"]["seconds_left"] is not None]
    return min(secs) if secs else None


def farming_score(account: Dict[str, Any], plan: Dict[str, Any]) -> float:
    """0..1, how close the account is to its next target (closer = more worth finishing)."""
    pcts = [t["percent"] for t in plan["targets"].values() if t["target"] > 0]
    return (sum(pcts) / len(pcts) / 100.0) if pcts else 0.0


def rotation(accounts: List[Dict[str, Any]], current_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Rank accounts by what is most useful to do next.

    ``accounts`` items are dicts with keys ``account``, ``plan`` and ``flags``.
    Order of usefulness:
      1. An upgrade can be started right now (a builder would otherwise sit idle).
      2. Farming is required and storage is not full (closer-to-target first).
      3. A builder frees soon and loot for the next task is already saved.
      4. Nothing to do (target completed, builders busy, all done).
    The currently selected account is kept if it still has useful work, so the user
    is not told to switch mid-session for a marginal gain.
    """
    ranked = []
    for item in accounts:
        acc, plan, flags = item["account"], item["plan"], item["flags"]
        primary = flags["primary"]
        free_in = next_builder_free(plan)
        if primary == "upgrade_ready":
            score, reason = 300.0, f"Start upgrade: {plan['next_ready']['building']}"
        elif primary == "filling_storage":
            score = 150.0 + 50.0 * farming_score(acc, plan)
            reason = "Upgrades done; farm until storage is full"
        elif primary == "farming_required":
            fs = farming_score(acc, plan)
            ft = plan["farming_for"]
            score = 200.0 + 50.0 * fs
            reason = f"Farm for {ft['building']}" if ft else "Farm resources"
        elif primary in ("resource_target_reached", "storage_full") and free_in is not None:
            score = 120.0 - min(100.0, free_in / 3600.0)
            reason = "Loot saved; builder frees in " + fmt_duration(free_in)
        elif primary == "resource_target_reached":
            score, reason = 110.0, "Loot saved for next upgrade"
        elif primary == "storage_full":
            score, reason = 20.0, "Storage full; wait for a builder"
        elif primary == "builder_busy":
            score, reason = 60.0, "Builders busy" + (f"; frees in {fmt_duration(free_in)}" if free_in else "")
        else:
            score, reason = 0.0, PRIMARY_LABEL.get(primary, primary)
        useful = score >= 100.0
        if current_id is not None and acc["id"] == current_id and useful:
            score += 25.0  # stickiness: finish the account you are on
        ranked.append({
            "account_id": acc["id"],
            "name": acc["name"],
            "status": primary,
            "status_label": PRIMARY_LABEL.get(primary, primary),
            "score": round(score, 2),
            "useful": useful,
            "reason": reason,
            "is_current": acc["id"] == current_id,
            "builder_frees_in": free_in,
        })
    ranked.sort(key=lambda x: (-x["score"], int(next((a["account"].get("rotation_order") or 0)
                                                       for a in accounts if a["account"]["id"] == x["account_id"])),
                               x["account_id"]))
    return ranked


def fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def notifications_for_change(account: Dict[str, Any], old: Dict[str, Any], new: Dict[str, Any],
                             plan: Dict[str, Any]) -> List[Dict[str, str]]:
    """Edge-triggered alerts: only fire when a flag turns on."""
    name = account["name"]
    out: List[Dict[str, str]] = []

    def turned_on(key: str) -> bool:
        return bool(new.get(key)) and not bool(old.get(key))

    if turned_on("upgrade_ready") and plan["next_ready"]:
        out.append({"kind": "upgrade_ready",
                    "message": f"{name}: Ready for next upgrade — {plan['next_ready']['building']}"})
    if turned_on("builder_available") and old:  # skip on first evaluation
        out.append({"kind": "builder_available", "message": f"{name}: Builder Available"})
    if turned_on("resource_target_reached"):
        out.append({"kind": "target_reached", "message": f"{name}: Resource Target Reached"})
    if turned_on("all_completed"):
        msg = (f"{name}: All upgrades done and storage is full. You can stop."
               if account.get("fill_storage_when_done") else f"{name}: All Planned Upgrades Completed")
        out.append({"kind": "all_completed", "message": msg})
    if new.get("primary") == "filling_storage" and old.get("primary") != "filling_storage":
        out.append({"kind": "filling_storage", "message": f"{name}: All upgrades done. Now farm until storage is full"})
    old_af = old.get("storage_almost_full") or {}
    for r, on in (new.get("storage_almost_full") or {}).items():
        if on and not old_af.get(r):
            out.append({"kind": "storage_almost_full", "message": f"{name}: {label(r)} Storage Almost Full"})
    # Specific resource needed (e.g. "Dark Elixir Required") when farming starts.
    if turned_on("farming_required") and plan["farming_for"]:
        rem = plan["farming_for"]["remaining"]
        need = [label(r) for r in RESOURCES if rem[r] > 0]
        either = plan["farming_for"].get("either")
        if either and either["loot_needed"]:
            out.append({"kind": "resource_required",
                        "message": f"{name}: {either['loot_needed']:,} Gold or Elixir needed for "
                                   f"{either['short_units']} more {plan['farming_for']['building']}"})
        elif need:
            out.append({"kind": "resource_required",
                        "message": f"{name}: {' & '.join(need)} Required for {plan['farming_for']['building']}"})
    return out
