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
    assert q["ready_to_ship_by"] == "Friday 2026-11-06"     # built Thu 5 Nov, it ships on the next shipping day


def test_the_quotes_ready_date_and_the_cards_ship_date_are_one_date(monkeypatch):
    # live check 08.11 (a Sunday): the quote said "ready to ship 2026-11-15" (Sunday), the card "ships Monday 2026-11-16"
    monkeypatch.setattr(shop, "_clock", lambda: datetime(2026, 11, 8, 16, 46, tzinfo=timezone.utc))
    car = [{"model": "fastback", "year": "1967", "body_colour": "grey", "interior_colour": "brown", "quantity": 2}]
    q, qs = shop.commission_quote(car), shop.commission_quote(car, "TX")
    assert q["ready_to_ship_by"] == qs["ready_to_ship_by"] == qs["delivery"]["ships_on"] == "Monday 2026-11-16"
    assert "ready 2026-11-16" in shopper._summary("quote_commission", q)
    for weeks_from in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"):
        d = date.fromisoformat(weeks_from)
        a = shop.commission_quote(car, "OH", today=d)
        assert a["ready_to_ship_by"] == a["delivery"]["ships_on"] and a["ready_to_ship_by"].split()[0] not in ("Saturday", "Sunday")


def test_the_daily_ai_budget_and_lenas_numbers_use_her_day(monkeypatch):
    shopper.add_spend(0.25)
    assert shopper._spent == {"2026-10-29": 0.25} and shopper.spent_today() == 0.25
    labels = TestClient(web.app).get("/api/maker/insights?days=7").json()["labels"]
    assert labels[-1] == "2026-10-29"
    o = shop.new_order("sg-014", 1, "OH", "x", "t")
    shop.update_order(o["id"], created=EVENING.timestamp() - 60)       # 8:29 pm on Thursday, Lena's time
    assert assistant.facts(EVENING.timestamp())["today"]["orders"] == 1


def test_a_weekday_the_shopper_typed_in_lowercase_is_written_properly():
    steps = [{"tool": "delivery_estimate", "result": "ships Mon · by next friday: on time"}]
    assert "in time for next Friday." in shopper._must_say("Sure.", "Will it arrive by next friday?", steps)
    late = [{"tool": "delivery_estimate", "result": "ships Mon · by this saturday: too late"}]
    assert "won't arrive by this Saturday." in shopper._must_say("Sure.", "by this saturday?", late)
    assert shopper._day_name("oct 30") == "oct 30" and shopper._day_name(" next sunday ") == "next Sunday"
