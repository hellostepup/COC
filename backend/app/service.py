"""Application logic on top of the database. Used by the API and by the simulation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from . import planner
from .db import Database

ACCOUNT_FIELDS = {
    "name", "player_tag", "town_hall", "focus", "objective", "priority_gold", "priority_elixir",
    "priority_dark", "min_gold", "min_elixir", "min_dark", "troop_composition", "defense_avoidance",
    "gold", "elixir", "dark_elixir", "max_gold", "max_elixir", "max_dark", "builders_total",
    "builders_busy_untracked", "rotation_order", "fill_storage_when_done",
}
UPGRADE_FIELDS = {
    "building", "category", "current_level", "target_level", "cost_gold", "cost_elixir", "cost_dark",
    "duration_minutes", "builders_required", "priority", "notes", "quantity", "done_count", "cost_either",
}
UPGRADE_STATUSES = ("planned", "in_progress", "completed")


class NotFound(Exception):
    pass


class InvalidState(Exception):
    pass


class Service:
    def __init__(self, db: Database, clock: Callable[[], datetime] = planner.utcnow):
        self.db = db
        self.clock = clock

    # ---------- accounts ----------
    def list_accounts(self) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM accounts ORDER BY rotation_order, id")

    def get_account(self, account_id: int) -> Dict[str, Any]:
        acc = self.db.one("SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not acc:
            raise NotFound(f"account {account_id} not found")
        return acc

    def create_account(self, data: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: v for k, v in data.items() if k in ACCOUNT_FIELDS}
        row.setdefault("name", "New Account")
        if "rotation_order" not in row:
            mx = self.db.one("SELECT COALESCE(MAX(rotation_order), 0) AS m FROM accounts")
            row["rotation_order"] = int(mx["m"]) + 1
        row["updated_at"] = self.clock().isoformat()
        acc_id = self.db.insert("accounts", row)
        self.evaluate(acc_id)
        return self.get_account(acc_id)

    def update_account(self, account_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        self.get_account(account_id)
        row = {k: v for k, v in data.items() if k in ACCOUNT_FIELDS and v is not None}
        for k in ("gold", "elixir", "dark_elixir"):
            if k in row:
                row[k] = max(0, int(row[k]))
        row["updated_at"] = self.clock().isoformat()
        self.db.update("accounts", account_id, row)
        self.evaluate(account_id)
        return self.get_account(account_id)

    def delete_account(self, account_id: int) -> None:
        self.get_account(account_id)
        self.db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if self.current_account_id() == account_id:
            self.set_current_account(None)

    def adjust_resources(self, account_id: int, gold: int = 0, elixir: int = 0, dark: int = 0) -> Dict[str, Any]:
        """Add loot (or subtract spending); balances are clamped to [0, storage capacity]."""
        acc = self.get_account(account_id)
        new = {}
        for field, mx, delta in (("gold", "max_gold", gold), ("elixir", "max_elixir", elixir),
                                 ("dark_elixir", "max_dark", dark)):
            val = max(0, int(acc[field]) + int(delta))
            if int(acc[mx]) > 0:
                val = min(val, int(acc[mx]))
            new[field] = val
        return self.update_account(account_id, new)

    # ---------- current account ----------
    def current_account_id(self) -> Optional[int]:
        row = self.db.one("SELECT value FROM app_state WHERE key = 'current_account'")
        return json.loads(row["value"]) if row else None

    def set_current_account(self, account_id: Optional[int]) -> None:
        if account_id is not None:
            self.get_account(account_id)
        self.db.execute("INSERT INTO app_state (key, value) VALUES ('current_account', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(account_id),))

    # ---------- upgrades ----------
    def list_upgrades(self, account_id: int) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM upgrades WHERE account_id = ? ORDER BY priority, id", (account_id,))

    def get_upgrade(self, upgrade_id: int) -> Dict[str, Any]:
        u = self.db.one("SELECT * FROM upgrades WHERE id = ?", (upgrade_id,))
        if not u:
            raise NotFound(f"upgrade {upgrade_id} not found")
        return u

    def create_upgrade(self, account_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        self.get_account(account_id)
        row = {k: v for k, v in data.items() if k in UPGRADE_FIELDS}
        if not row.get("building"):
            raise InvalidState("building is required")
        if "priority" not in row:
            mx = self.db.one("SELECT COALESCE(MAX(priority), 0) AS m FROM upgrades WHERE account_id = ? "
                             "AND status != 'completed'", (account_id,))
            row["priority"] = int(mx["m"]) + 1
        row["account_id"] = account_id
        row["status"] = "planned"
        uid = self.db.insert("upgrades", row)
        self.evaluate(account_id)
        return self.get_upgrade(uid)

    def update_upgrade(self, upgrade_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        u = self.get_upgrade(upgrade_id)
        row = {k: v for k, v in data.items() if k in UPGRADE_FIELDS and v is not None}
        self.db.update("upgrades", upgrade_id, row)
        self.evaluate(u["account_id"])
        return self.get_upgrade(upgrade_id)

    def delete_upgrade(self, upgrade_id: int) -> None:
        u = self.get_upgrade(upgrade_id)
        self.db.execute("DELETE FROM upgrades WHERE id = ?", (upgrade_id,))
        self.evaluate(u["account_id"])

    def reorder_upgrades(self, account_id: int, ordered_ids: List[int]) -> None:
        own = {u["id"] for u in self.list_upgrades(account_id)}
        with self.db.tx() as c:
            for i, uid in enumerate(ordered_ids, start=1):
                if uid in own:
                    c.execute("UPDATE upgrades SET priority = ? WHERE id = ?", (i, uid))
        self.evaluate(account_id)

    def confirm_started(self, upgrade_id: int, deduct_cost: bool = True,
                        duration_minutes: Optional[int] = None) -> Dict[str, Any]:
        """The user started this upgrade in the game; record it and (optionally) spend the cost."""
        u = self.get_upgrade(upgrade_id)
        if u["status"] != "planned":
            raise InvalidState(f"upgrade is {u['status']}, not planned")
        if int(u.get("cost_either") or 0) > 0:
            raise InvalidState("record walls with 'I upgraded walls' instead")
        acc = self.get_account(u["account_id"])
        plan = planner.plan_queue(acc, self.list_upgrades(acc["id"]), self.clock())
        if plan["builders"]["free"] < int(u["builders_required"] or 1):
            raise InvalidState("no free builder for this upgrade")
        minutes = int(duration_minutes if duration_minutes is not None else u["duration_minutes"])
        now = self.clock()
        self.db.update("upgrades", upgrade_id, {
            "status": "in_progress", "started_at": now.isoformat(),
            "completes_at": (now + timedelta(minutes=minutes)).isoformat(),
            "duration_minutes": minutes,
        })
        if deduct_cost:
            self.adjust_resources(acc["id"], -int(u["cost_gold"]), -int(u["cost_elixir"]), -int(u["cost_dark"]))
        else:
            self.evaluate(acc["id"])
        return self.get_upgrade(upgrade_id)

    def record_units(self, upgrade_id: int, with_gold: int = 0, with_elixir: int = 0,
                     deduct_cost: bool = True) -> Dict[str, Any]:
        """The user upgraded some walls in the game, paying each with Gold or Elixir."""
        u = self.get_upgrade(upgrade_id)
        unit = int(u.get("cost_either") or 0)
        if unit <= 0:
            raise InvalidState("this upgrade is not a Gold-or-Elixir task")
        if u["status"] != "planned":
            raise InvalidState(f"upgrade is {u['status']}")
        with_gold, with_elixir = max(0, int(with_gold)), max(0, int(with_elixir))
        count = with_gold + with_elixir
        left = int(u["quantity"]) - int(u["done_count"])
        if count <= 0:
            raise InvalidState("enter how many you upgraded")
        if count > left:
            raise InvalidState(f"only {left} left in this task")
        acc = self.get_account(u["account_id"])
        if deduct_cost and (with_gold * unit > int(acc["gold"]) or with_elixir * unit > int(acc["elixir"])):
            raise InvalidState("tracked balance is too low for that; update your Gold/Elixir first "
                               "or untick 'subtract cost'")
        done = int(u["done_count"]) + count
        self.db.update("upgrades", upgrade_id, {"done_count": done})
        if deduct_cost:
            self.adjust_resources(acc["id"], gold=-with_gold * unit, elixir=-with_elixir * unit)
        if done >= int(u["quantity"]):
            return self.mark_completed(upgrade_id)
        self.evaluate(acc["id"])
        return self.get_upgrade(upgrade_id)

    def mark_completed(self, upgrade_id: int) -> Dict[str, Any]:
        u = self.get_upgrade(upgrade_id)
        if u["status"] == "completed":
            return u
        self.db.update("upgrades", upgrade_id, {"status": "completed", "completed_at": self.clock().isoformat()})
        self.notify(u["account_id"], "upgrade_completed",
                    f"{self.get_account(u['account_id'])['name']}: Upgrade Completed — {u['building']} "
                    f"(Lv {u['target_level']})")
        self.evaluate(u["account_id"])
        return self.get_upgrade(upgrade_id)

    def revert_to_planned(self, upgrade_id: int) -> Dict[str, Any]:
        u = self.get_upgrade(upgrade_id)
        self.db.update("upgrades", upgrade_id, {"status": "planned", "started_at": None,
                                                "completes_at": None, "completed_at": None})
        self.evaluate(u["account_id"])
        return self.get_upgrade(upgrade_id)

    def tick(self) -> int:
        """Complete in-progress upgrades whose timer has run out. Returns how many completed."""
        now = self.clock()
        done = 0
        for u in self.db.query("SELECT * FROM upgrades WHERE status = 'in_progress' AND completes_at IS NOT NULL"):
            end = planner.parse_ts(u["completes_at"])
            if end and end <= now:
                self.mark_completed(u["id"])
                done += 1
        return done

    # ---------- evaluation & notifications ----------
    def plan(self, account_id: int) -> Dict[str, Any]:
        acc = self.get_account(account_id)
        return planner.plan_queue(acc, self.list_upgrades(account_id), self.clock())

    def evaluate(self, account_id: int) -> Dict[str, Any]:
        acc = self.get_account(account_id)
        plan = planner.plan_queue(acc, self.list_upgrades(account_id), self.clock())
        flags = planner.account_flags(acc, plan)
        old = json.loads(acc.get("last_flags") or "{}")
        for n in planner.notifications_for_change(acc, old, flags, plan):
            self.notify(account_id, n["kind"], n["message"])
        self.db.execute("UPDATE accounts SET last_flags = ? WHERE id = ?", (json.dumps(flags), account_id))
        return flags

    def notify(self, account_id: Optional[int], kind: str, message: str) -> None:
        self.db.insert("notifications", {"account_id": account_id, "kind": kind, "message": message,
                                         "created_at": self.clock().isoformat()})

    def notifications(self, undelivered_only: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        where = "WHERE delivered = 0" if undelivered_only else ""
        return self.db.query(f"SELECT * FROM notifications {where} ORDER BY id DESC LIMIT ?", (limit,))

    def mark_delivered(self, ids: List[int]) -> None:
        with self.db.tx() as c:
            c.executemany("UPDATE notifications SET delivered = 1 WHERE id = ?", [(i,) for i in ids])

    def mark_all_read(self) -> None:
        self.db.execute("UPDATE notifications SET read = 1, delivered = 1")

    # ---------- views ----------
    def account_view(self, account_id: int) -> Dict[str, Any]:
        acc = self.get_account(account_id)
        ups = self.list_upgrades(account_id)
        plan = planner.plan_queue(acc, ups, self.clock())
        flags = planner.account_flags(acc, plan)
        acc = {k: v for k, v in acc.items() if k != "last_flags"}
        return {
            "account": acc,
            "upgrades": ups,
            "plan": plan,
            "flags": flags,
            "status_label": planner.PRIMARY_LABEL.get(flags["primary"], flags["primary"]),
            "storage_pct": planner.storage_pct(acc),
        }

    def rotation(self) -> List[Dict[str, Any]]:
        items = []
        for acc in self.list_accounts():
            plan = planner.plan_queue(acc, self.list_upgrades(acc["id"]), self.clock())
            items.append({"account": acc, "plan": plan, "flags": planner.account_flags(acc, plan)})
        return planner.rotation(items, self.current_account_id())

    def dashboard(self) -> Dict[str, Any]:
        views = [self.account_view(a["id"]) for a in self.list_accounts()]
        rot = self.rotation()
        return {
            "overview": {
                "total_accounts": len(views),
                "accounts_needing_resources": sum(1 for v in views if v["flags"]["farming_required"]),
                "upgrades_ready": sum(1 for v in views for t in v["plan"]["tasks"] if t["ready"]),
                "builders_available": sum(v["plan"]["builders"]["free"] for v in views),
                "upgrades_in_progress": sum(v["plan"]["in_progress_count"] for v in views),
                "completed_upgrades": sum(v["plan"]["completed_count"] for v in views),
            },
            "accounts": views,
            "rotation": rot,
            "next_recommended": next((r for r in rot if r["useful"]), None),
            "current_account_id": self.current_account_id(),
            "now": self.clock().isoformat(),
        }

    # ---------- detections ----------
    def save_detection(self, kind: str, result: Dict[str, Any], account_id: Optional[int] = None,
                       image_path: Optional[str] = None, size: Optional[tuple] = None) -> Dict[str, Any]:
        did = self.db.insert("detections", {
            "account_id": account_id, "kind": kind, "image_path": image_path,
            "image_width": size[0] if size else None, "image_height": size[1] if size else None,
            "result_json": json.dumps(result), "created_at": self.clock().isoformat(),
        })
        return self.get_detection(did)

    def get_detection(self, detection_id: int) -> Dict[str, Any]:
        d = self.db.one("SELECT * FROM detections WHERE id = ?", (detection_id,))
        if not d:
            raise NotFound(f"detection {detection_id} not found")
        d["result"] = json.loads(d.pop("result_json") or "{}")
        d["corrected"] = json.loads(d.pop("corrected_json")) if d.get("corrected_json") else None
        return d

    def correct_detection(self, detection_id: int, corrected: Dict[str, Any]) -> Dict[str, Any]:
        self.get_detection(detection_id)
        self.db.update("detections", detection_id, {"corrected_json": json.dumps(corrected), "verified": 1})
        return self.get_detection(detection_id)

    def verified_samples(self) -> List[Dict[str, Any]]:
        out = []
        for d in self.db.query("SELECT id FROM detections WHERE verified = 1 AND kind = 'battle'"):
            det = self.get_detection(d["id"])
            det["detections"] = (det["corrected"] or det["result"]).get("detections", [])
            out.append(det)
        return out
