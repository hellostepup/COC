"""Tests mapped to the acceptance criteria in the requirements (AC1..AC10)."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from app import planner  # noqa: E402
from app.db import Database  # noqa: E402
from app.seed import seed_demo  # noqa: E402
from app.service import InvalidState, Service  # noqa: E402
from app.simulation import FakeClock, generate_base, noisy_detections, run_simulation  # noqa: E402
from app.vision.strategy import RESOURCE_LABELS, analyze_layout  # noqa: E402


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def svc(clock):
    return Service(Database(":memory:"), clock=clock)


def make_account(svc, **kw):
    base = dict(name="A", gold=5_000_000, max_gold=10_000_000, max_elixir=10_000_000, max_dark=200_000,
                builders_total=2)
    base.update(kw)
    return svc.create_account(base)


def kinds(svc):
    return [n["kind"] for n in svc.notifications()]


# AC1: accounts are independent
def test_accounts_are_isolated(svc):
    seed_demo(svc)
    accs = svc.list_accounts()
    assert len(accs) == 4
    a1, a2 = accs[0]["id"], accs[1]["id"]
    before = svc.get_account(a2)["gold"]
    svc.adjust_resources(a1, gold=100_000)
    assert svc.get_account(a2)["gold"] == before
    assert all(u["account_id"] == a1 for u in svc.list_upgrades(a1))


# AC3 + AC5: separate targets, remaining resource maths
def test_remaining_resources_example_from_spec(svc):
    a = make_account(svc)
    svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 8_000_000})
    plan = svc.plan(a["id"])
    assert plan["tasks"][0]["remaining"]["gold"] == 3_000_000
    assert plan["targets"]["gold"]["target"] == 8_000_000
    assert plan["targets"]["gold"]["remaining"] == 3_000_000


def test_manual_minimum_target_and_queue_totals(svc):
    a = make_account(svc, min_elixir=2_000_000, elixir=500_000)
    svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 8_000_000})
    svc.create_upgrade(a["id"], {"building": "Archer Tower", "cost_gold": 7_000_000, "cost_elixir": 0})
    plan = svc.plan(a["id"])
    assert plan["total_required"]["gold"] == 15_000_000
    assert plan["total_remaining"]["gold"] == 10_000_000
    assert plan["targets"]["elixir"]["target"] == 2_000_000
    assert plan["targets"]["elixir"]["remaining"] == 1_500_000


# AC4: multiple tasks, sequential queue with fall-through to the next priority
def test_priority_fall_through(svc):
    a = make_account(svc, gold=4_000_000)
    svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 8_000_000, "priority": 1})
    svc.create_upgrade(a["id"], {"building": "Archer Tower", "cost_gold": 3_000_000, "priority": 2})
    plan = svc.plan(a["id"])
    assert plan["next_ready"]["building"] == "Archer Tower"
    assert not plan["tasks"][0]["ready"] and "need 4,000,000 more Gold" in plan["tasks"][0]["blockers"]


def test_ready_tasks_do_not_double_count_loot(svc):
    a = make_account(svc, elixir=7_000_000, builders_total=5)
    svc.create_upgrade(a["id"], {"building": "Laboratory", "cost_elixir": 6_500_000, "priority": 1})
    svc.create_upgrade(a["id"], {"building": "Army Camp", "cost_elixir": 5_000_000, "priority": 2})
    svc.create_upgrade(a["id"], {"building": "Wall", "cost_elixir": 400_000, "priority": 3})
    t = svc.plan(a["id"])["tasks"]
    assert [x["ready"] for x in t] == [True, False, True]
    assert "4,500,000 Elixir more for both" in t[1]["blockers"][0]
    assert svc.dashboard()["overview"]["upgrades_ready"] == 2


def test_ready_tasks_do_not_double_count_builders(svc):
    a = make_account(svc, gold=9_000_000, builders_total=1)
    svc.create_upgrade(a["id"], {"building": "A", "cost_gold": 1})
    svc.create_upgrade(a["id"], {"building": "B", "cost_gold": 1})
    assert [x["ready"] for x in svc.plan(a["id"])["tasks"]] == [True, False]


def test_start_and_complete_flow(svc, clock):
    a = make_account(svc, gold=9_000_000, builders_total=1)
    u = svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 8_000_000, "duration_minutes": 60})
    assert svc.account_view(a["id"])["flags"]["upgrade_ready"]
    svc.confirm_started(u["id"])
    assert svc.get_account(a["id"])["gold"] == 1_000_000
    view = svc.account_view(a["id"])
    assert view["upgrades"][0]["status"] == "in_progress"
    assert view["flags"]["builder_busy"]
    with pytest.raises(InvalidState):
        svc.confirm_started(u["id"])
    clock.advance(minutes=30)
    assert view["plan"]["tasks"][0]["progress"]["percent"] == 0.0
    assert svc.plan(a["id"])["tasks"][0]["progress"]["percent"] == 50.0
    clock.advance(minutes=31)
    assert svc.tick() == 1
    view = svc.account_view(a["id"])
    assert view["upgrades"][0]["status"] == "completed"
    assert view["flags"]["primary"] == "all_completed"


def test_no_start_without_free_builder(svc):
    a = make_account(svc, gold=9_000_000, builders_total=1, builders_busy_untracked=1)
    u = svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 1})
    with pytest.raises(InvalidState):
        svc.confirm_started(u["id"])


# AC6: notifications when a builder frees and when an upgrade is ready
def test_builder_available_and_ready_notifications(svc, clock):
    a = make_account(svc, gold=20_000_000, max_gold=30_000_000, builders_total=1)
    u1 = svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 8_000_000, "duration_minutes": 10})
    svc.create_upgrade(a["id"], {"building": "Archer Tower", "cost_gold": 8_000_000})
    assert "upgrade_ready" in kinds(svc)
    svc.confirm_started(u1["id"])
    n_before = len(svc.notifications())
    clock.advance(minutes=11)
    svc.tick()
    new = [n["kind"] for n in svc.notifications()[: len(svc.notifications()) - n_before]]
    assert "upgrade_completed" in new
    assert "builder_available" in new
    assert "upgrade_ready" in new


def test_storage_almost_full_and_target_reached_alerts(svc):
    a = make_account(svc, gold=1_000_000)
    svc.create_upgrade(a["id"], {"building": "Cannon", "cost_gold": 9_500_000})
    svc.adjust_resources(a["id"], gold=8_200_000)
    assert "storage_almost_full" in kinds(svc)
    svc.adjust_resources(a["id"], gold=1_000_000)
    assert "target_reached" in kinds(svc)
    # Edge-triggered: re-evaluating does not repeat alerts.
    count = len(svc.notifications())
    svc.evaluate(a["id"])
    assert len(svc.notifications()) == count


# AC7: rotation
def test_rotation_target_completed_moves_to_next_account(svc):
    a1 = make_account(svc, name="Account 1", gold=10_000_000, builders_total=3, rotation_order=1)
    for b in ("Cannon", "Archer Tower", "Air Defense"):
        u = svc.create_upgrade(a1["id"], {"building": b, "cost_gold": 1, "duration_minutes": 9999})
        svc.confirm_started(u["id"], deduct_cost=False)
    svc.update_account(a1["id"], {"gold": 10_000_000})  # storage full
    a2 = make_account(svc, name="Account 2", gold=0, builders_total=2, rotation_order=2)
    svc.create_upgrade(a2["id"], {"building": "Laboratory", "cost_gold": 5_000_000})
    svc.set_current_account(a1["id"])
    assert svc.account_view(a1["id"])["flags"]["primary"] == "target_completed"
    rot = svc.rotation()
    assert rot[0]["name"] == "Account 2"
    assert svc.dashboard()["next_recommended"]["name"] == "Account 2"


def test_rotation_prefers_ready_upgrade(svc):
    a1 = make_account(svc, name="farm", gold=0)
    svc.create_upgrade(a1["id"], {"building": "X", "cost_gold": 5_000_000})
    a2 = make_account(svc, name="ready", gold=6_000_000)
    svc.create_upgrade(a2["id"], {"building": "Y", "cost_gold": 5_000_000})
    assert svc.rotation()[0]["name"] == "ready"


# AC9: persistence across restart
def test_data_survives_restart(tmp_path, clock):
    path = str(tmp_path / "x.db")
    s1 = Service(Database(path), clock=clock)
    seed_demo(s1)
    u = s1.list_upgrades(s1.list_accounts()[0]["id"])[0]
    s1.update_account(u["account_id"], {"gold": 9_000_000})
    s1.confirm_started(u["id"])
    s1.db.close()
    s2 = Service(Database(path), clock=clock)
    assert len(s2.list_accounts()) == 4
    assert s2.get_upgrade(u["id"])["status"] == "in_progress"
    assert s2.get_account(u["account_id"])["gold"] == 1_000_000


# AC2: six resource building types are recognised by the layout analysis
def test_strategy_finds_rich_side():
    dets = []
    for i, lbl in enumerate(RESOURCE_LABELS):  # all six types clustered at the bottom
        dets.append({"label": lbl, "x": 780 + 30 * (i % 3), "y": 760 + 25 * (i // 3), "w": 40, "h": 40,
                     "confidence": 0.9})
    dets += [{"label": "cannon", "x": 800 + 40 * k, "y": 150 + 10 * k, "w": 40, "h": 40, "confidence": 0.9}
             for k in range(5)]
    dets.append({"label": "town_hall", "x": 800, "y": 450, "w": 60, "h": 60, "confidence": 0.95})
    res = analyze_layout(dets, (1600, 900), priority={"gold": 50, "elixir": 30, "dark": 20})
    assert res["ok"]
    assert "Bottom" in res["recommendation"]["side"]
    assert set(res["recommendation"]["target_cluster"]["buildings"]) == set(RESOURCE_LABELS)
    assert all(p["y"] > 450 for p in res["recommendation"]["deploy_points"])


def test_strategy_respects_priority_and_flags_uncertain():
    dets = [
        {"label": "gold_storage", "x": 200, "y": 450, "w": 40, "h": 40, "confidence": 0.9},
        {"label": "gold_mine", "x": 230, "y": 470, "w": 40, "h": 40, "confidence": 0.9},
        {"label": "dark_elixir_storage", "x": 1400, "y": 450, "w": 40, "h": 40, "confidence": 0.9},
        {"label": "dark_elixir_drill", "x": 1370, "y": 430, "w": 40, "h": 40, "confidence": 0.4},
        {"label": "town_hall", "x": 800, "y": 450, "w": 60, "h": 60, "confidence": 0.9},
    ]
    gold = analyze_layout(dets, (1600, 900), priority={"gold": 100, "elixir": 0, "dark": 0})
    dark = analyze_layout(dets, (1600, 900), priority={"gold": 0, "elixir": 0, "dark": 100})
    assert gold["recommendation"]["side"] == "Left"
    assert dark["recommendation"]["side"] == "Right"
    assert dark["needs_review"] and len(dark["uncertain"]) == 1


def test_strategy_without_resources_asks_for_correction():
    res = analyze_layout([{"label": "cannon", "x": 1, "y": 1, "w": 1, "h": 1}], (100, 100))
    assert not res["ok"] and "correct" in res["message"]


# AC10: complete farming + upgrade workflow in simulation
def test_full_four_account_simulation():
    result = run_simulation(seed=7, max_battles=3000)
    assert result["all_completed"], result["accounts"]
    assert result["stats"]["upgrades_started"] == 11
    assert result["stats"]["battles"] > 0 and result["stats"]["switches"] >= 4


def test_strategy_beats_random_deploy_in_simulation():
    rng = random.Random(3)
    from app.simulation import simulate_attack, random_deploy
    smart = rand = 0
    for _ in range(200):
        base = generate_base(rng, 12)
        a = analyze_layout(noisy_detections(base, rng), (1600, 900), priority={"gold": 50, "elixir": 50, "dark": 0})
        smart += sum(simulate_attack(base, a["recommendation"]["deploy_points"], 0.9, rng).values())
        rand += sum(simulate_attack(base, random_deploy(rng), 0.9, rng).values())
    assert smart > rand * 1.1


# Walls: many units, each paid with Gold OR Elixir, then fill storage.
def wall_account(svc, gold, elixir, **kw):
    a = make_account(svc, gold=gold, elixir=elixir, max_gold=21_000_000, max_elixir=19_500_000,
                     priority_gold=50, priority_elixir=50, priority_dark=0, builders_total=5, **kw)
    u = svc.create_upgrade(a["id"], {"building": "Wall", "category": "wall", "current_level": 14,
                                     "target_level": 15, "quantity": 10, "cost_either": 1_000_000})
    return a, u


def test_walls_count_what_you_can_pay_now(svc):
    a, u = wall_account(svc, gold=2_500_000, elixir=1_500_000)
    t = svc.plan(a["id"])["tasks"][0]
    e = t["either"]
    assert (e["pay_with_gold"], e["pay_with_elixir"], e["can_do_now"]) == (2, 1, 3)
    assert t["ready"] and not t["affordable"]
    # 7 short; leftovers 0.5M + 0.5M can each be topped up -> 7M - 1M = 6M more loot
    assert e["short_units"] == 7 and e["loot_needed"] == 6_000_000
    assert svc.account_view(a["id"])["flags"]["primary"] == "upgrade_ready"


def test_walls_one_left_uses_only_bigger_leftover(svc):
    a, u = wall_account(svc, gold=600_000, elixir=700_000)
    svc.update_upgrade(u["id"], {"quantity": 1})
    assert svc.plan(a["id"])["tasks"][0]["either"]["loot_needed"] == 300_000


def test_walls_flow_then_fill_storage(svc):
    a, u = wall_account(svc, gold=6_000_000, elixir=4_000_000, fill_storage_when_done=1)
    svc.record_units(u["id"], with_gold=6, with_elixir=3)
    acc = svc.get_account(a["id"])
    assert (acc["gold"], acc["elixir"]) == (0, 1_000_000)
    with pytest.raises(InvalidState):
        svc.record_units(u["id"], with_gold=2)  # only 1 left
    with pytest.raises(InvalidState):
        svc.confirm_started(u["id"])  # walls are recorded, not "started"
    svc.record_units(u["id"], with_elixir=1)
    view = svc.account_view(a["id"])
    assert view["upgrades"][0]["status"] == "completed"
    assert view["flags"]["primary"] == "filling_storage"
    assert view["plan"]["targets"]["gold"]["target"] == 21_000_000
    assert view["plan"]["targets"]["dark"]["target"] == 0  # dark priority 0: not filled
    assert any("farm until storage is full" in n["message"] for n in svc.notifications())
    svc.update_account(a["id"], {"gold": 21_000_000, "elixir": 19_500_000})
    assert svc.account_view(a["id"])["flags"]["primary"] == "all_completed"
    assert any("You can stop" in n["message"] for n in svc.notifications())


def test_migration_adds_columns_to_old_database(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE upgrades (id INTEGER PRIMARY KEY, account_id INTEGER, building TEXT)")
    c.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    c.commit(); c.close()
    db = Database(path)
    cols = {r["name"] for r in db.query("PRAGMA table_info(upgrades)")}
    assert {"quantity", "done_count", "cost_either"} <= cols
