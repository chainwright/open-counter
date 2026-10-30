"""Dates follow the shop's clock (Columbus, Ohio), not the server's UTC: an evening shopper in the US must not see
tomorrow's dates (judge 29.10, N1)."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from opencounter import assistant, shop, shopper, web

# Thursday 29 Oct 2026, 8:30 pm in Ohio = already Friday 30 Oct, 00:30 on a UTC server
EVENING = datetime(2026, 10, 30, 0, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shop, "_clock", lambda: EVENING)
    monkeypatch.setattr(shopper, "_spent", {})
    shop.seed(force=True)


def test_today_is_the_shops_day_not_the_servers():
    assert EVENING.date() == date(2026, 10, 30) and shop.today() == date(2026, 10, 29)


def test_ship_and_arrival_dates_count_from_the_shops_day():
    est = shop.delivery_estimate("OH", need_by="Friday")
    assert est["today"] == "Thursday 2026-10-29"
    assert est["ships_on"] == "Friday 2026-10-30"        # UTC would have said Monday Nov 2
    assert est["need_by"] == "Friday 2026-10-30"           # "by Friday" is tomorrow, not a week away
    q = shop.commission_quote([{"model": "fastback", "year": "1968", "body_colour": "grey",
                                "interior_colour": "brown", "quantity": 1}])
    assert q["ready_to_ship_by"] == "Thursday 2026-11-05"


def test_the_daily_ai_budget_and_lenas_numbers_use_her_day(monkeypatch):
    shopper.add_spend(0.25)
    assert shopper._spent == {"2026-10-29": 0.25} and shopper.spent_today() == 0.25
    labels = TestClient(web.app).get("/api/maker/insights?days=7").json()["labels"]
    assert labels[-1] == "2026-10-29"
    o = shop.new_order("sg-014", 1, "OH", "x", "t")
    shop.update_order(o["id"], created=EVENING.timestamp() - 60)       # 8:29 pm on Thursday, Lena's time
    assert assistant.facts(EVENING.timestamp())["today"]["orders"] == 1
