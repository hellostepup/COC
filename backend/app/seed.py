"""Starter data matching the four accounts described in the requirements.

Costs and durations are placeholders in a realistic range, not official game numbers.
Edit them to match what the in-game upgrade screen shows.
"""
from __future__ import annotations

from .service import Service

DEMO_ACCOUNTS = [
    {
        "account": {"name": "Account 1", "town_hall": 13, "focus": "Gold Farming + Defense Upgrade",
                    "objective": "gold", "priority_gold": 80, "priority_elixir": 20, "priority_dark": 0,
                    "gold": 5_000_000, "elixir": 3_000_000, "dark_elixir": 80_000,
                    "max_gold": 10_000_000, "max_elixir": 10_000_000, "max_dark": 250_000,
                    "builders_total": 5, "defense_avoidance": "medium"},
        "upgrades": [
            {"building": "Cannon", "category": "defense", "current_level": 15, "target_level": 16,
             "cost_gold": 8_000_000, "duration_minutes": 8 * 24 * 60},
            {"building": "Archer Tower", "category": "defense", "current_level": 14, "target_level": 15,
             "cost_gold": 7_500_000, "duration_minutes": 9 * 24 * 60},
            {"building": "Air Defense", "category": "defense", "current_level": 10, "target_level": 11,
             "cost_gold": 8_200_000, "duration_minutes": 10 * 24 * 60},
        ],
    },
    {
        "account": {"name": "Account 2", "town_hall": 12, "focus": "Elixir Farming + Army Upgrade",
                    "objective": "elixir", "priority_gold": 20, "priority_elixir": 80, "priority_dark": 0,
                    "gold": 2_000_000, "elixir": 4_500_000, "dark_elixir": 40_000,
                    "max_gold": 8_000_000, "max_elixir": 8_000_000, "max_dark": 200_000,
                    "builders_total": 5, "defense_avoidance": "medium"},
        "upgrades": [
            {"building": "Laboratory", "category": "army", "current_level": 11, "target_level": 12,
             "cost_elixir": 6_500_000, "duration_minutes": 7 * 24 * 60},
            {"building": "Army Camp", "category": "army", "current_level": 9, "target_level": 10,
             "cost_elixir": 5_000_000, "duration_minutes": 6 * 24 * 60},
            {"building": "Wizard Tower", "category": "defense", "current_level": 11, "target_level": 12,
             "cost_gold": 6_000_000, "duration_minutes": 7 * 24 * 60},
        ],
    },
    {
        "account": {"name": "Account 3", "town_hall": 12, "focus": "Dark Elixir Farming + Hero Upgrade",
                    "objective": "dark", "priority_gold": 20, "priority_elixir": 30, "priority_dark": 50,
                    "gold": 3_000_000, "elixir": 3_000_000, "dark_elixir": 90_000,
                    "max_gold": 8_000_000, "max_elixir": 8_000_000, "max_dark": 200_000,
                    "builders_total": 5, "defense_avoidance": "high"},
        "upgrades": [
            {"building": "Barbarian King", "category": "hero", "current_level": 60, "target_level": 61,
             "cost_dark": 160_000, "duration_minutes": 6 * 24 * 60},
            {"building": "Archer Queen", "category": "hero", "current_level": 60, "target_level": 61,
             "cost_dark": 170_000, "duration_minutes": 6 * 24 * 60},
        ],
    },
    {
        "account": {"name": "Account 4", "town_hall": 11, "focus": "Balanced Farming",
                    "objective": "balanced", "priority_gold": 40, "priority_elixir": 40, "priority_dark": 20,
                    "gold": 1_500_000, "elixir": 1_500_000, "dark_elixir": 20_000,
                    "max_gold": 7_000_000, "max_elixir": 7_000_000, "max_dark": 160_000,
                    "builders_total": 5, "defense_avoidance": "low"},
        "upgrades": [
            {"building": "Gold Storage", "category": "resource", "current_level": 12, "target_level": 13,
             "cost_elixir": 3_000_000, "duration_minutes": 4 * 24 * 60},
            {"building": "Mortar", "category": "defense", "current_level": 10, "target_level": 11,
             "cost_gold": 3_500_000, "duration_minutes": 5 * 24 * 60},
            {"building": "Dark Elixir Drill", "category": "resource", "current_level": 6, "target_level": 7,
             "cost_elixir": 2_800_000, "duration_minutes": 4 * 24 * 60},
        ],
    },
]


def seed_demo(service: Service) -> None:
    for i, item in enumerate(DEMO_ACCOUNTS, start=1):
        acc = service.create_account({**item["account"], "rotation_order": i})
        for p, up in enumerate(item["upgrades"], start=1):
            service.create_upgrade(acc["id"], {**up, "priority": p})
    if service.list_accounts():
        service.set_current_account(service.list_accounts()[0]["id"])
