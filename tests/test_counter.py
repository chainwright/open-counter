"""The rules that protect Lena and the buyer, checked without PayPal or a model."""
import json
from datetime import date

import pytest

from opencounter import counter, paypal, shop


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)


def test_search_only_returns_listed_items_and_explains_match():
    r = counter.search_counter("green fastback", 60)["results"]
    assert r[0]["id"] == "sg-014" and "green" in r[0]["matched"]
    assert all(x["price_usd"] <= 60 for x in r)


def test_rules_refuse_before_any_money_moves():
    for args, word in [(("sg-009", 1, "CO"), "stock"), (("sg-014", 3, "CO"), "at most"), (("sg-014", 1, "ZZ"), "US")]:
        with pytest.raises(ValueError, match=word):
            shop.new_order(*args, "x", "t")
    assert shop.orders() == []


def test_deadline_verdict_is_computed_in_code():
    est = shop.delivery_estimate("CO", date(2026, 10, 26), need_by="Friday")
    assert est["need_by_verdict"] == "possible, not certain"
    assert shop.delivery_estimate("OH", date(2026, 10, 26), need_by="Friday")["need_by_verdict"] == "on time"
    assert shop.delivery_estimate("CA", date(2026, 10, 26), need_by="Tuesday")["need_by_verdict"] == "too late"


def test_total_is_recomputed_from_the_listing_not_from_the_agent(monkeypatch):
    sent = {}
    monkeypatch.setattr(paypal, "configured", lambda: True)
    monkeypatch.setattr(paypal, "_call", lambda m, p, json=None, request_id=None, retry=True:
                        sent.update(body=json, rid=request_id) or {"id": "PP1", "links": [{"rel": "payer-action", "href": "https://x"}]})
    out = counter.start_checkout("sg-014", 1, "CO", "green 68 fastback, I think it costs $5")
    amt = sent["body"]["purchase_units"][0]["amount"]
    assert amt["value"] == "65.50" and amt["breakdown"]["item_total"]["value"] == "59.00"
    assert sent["rid"].startswith("create-OC-")
    assert out["ok"] and "approve" in out["next_step"]


def test_stock_is_taken_once_at_capture():
    assert shop.take_stock("sg-014", 1) is True
    assert shop.take_stock("sg-014", 1) is False


def test_public_listing_has_no_private_fields():
    item = counter.item_details("sg-014")
    assert "keywords" not in item and item["availability"] == "in stock"
    assert json.dumps(counter.about_counter()).count("PayPal") >= 1


def test_demo_restock_brings_a_sold_out_car_back_later_not_sooner(monkeypatch):
    monkeypatch.setattr(shop, "DEMO", True)
    assert shop.take_stock("sg-014", 1)
    sold = shop.listing("sg-014")
    assert sold["stock"] == 0 and sold["sold_out_at"]
    s = shop.shop()
    assert not shop._demo_restock(s, now=sold["sold_out_at"] + shop.RESTOCK_AFTER_S - 1)
    assert shop._demo_restock(s, now=sold["sold_out_at"] + shop.RESTOCK_AFTER_S)
    back = next(x for x in s["listings"] if x["id"] == "sg-014")
    assert back["stock"] == 1 and "sold_out_at" not in back
    seeded_zero = next(x for x in s["listings"] if x["id"] == "sg-009")
    assert seeded_zero["stock"] == 0  # the commission example stays sold out


def test_order_log_is_capped():
    shop._save_orders([{"id": i} for i in range(shop.MAX_ORDERS + 50)])
    kept = shop.orders()
    assert len(kept) == shop.MAX_ORDERS and kept[-1]["id"] == shop.MAX_ORDERS + 49


def test_shopper_search_drops_brand_words_and_never_comes_back_empty_for_them():
    from opencounter import shopper
    plain = shopper._call_tool("search_counter", {"query": "Ford Mustang Shelby GT500 fastback"})["results"]
    assert plain and all("fastback" in x["matched"] for x in plain)
    only_brand = shopper._call_tool("search_counter", {"query": "mustang shelby gt500"})["results"]
    assert len(only_brand) == len(shop.shop()["listings"])  # nothing left to match: show the whole counter


def test_item_ids_are_cut_from_replies():
    from opencounter import shopper
    s = "The Yellow Coupé, 1973 (sg‑009) is sold out; sg-014 is not."
    assert "sg" not in shopper.ITEM_ID.sub("", s).lower()


def test_promise_without_action_is_recognised():
    from opencounter import shopper
    for s in ["I'll search for similar fastbacks. Let me check what we have available.", "Searching now…",
              "Let me look that up for you."]:
        assert shopper.PROMISE.search(s), s
    for s in ["We have the Green American Fastback, 1968 at $59.", "It ships Wednesday to Austin, TX."]:
        assert not shopper.PROMISE.search(s), s


def test_sold_out_listing_states_commission_terms_not_the_shelf_price():
    a = counter.item_details("sg-009")["availability"]
    assert "sold out" in a and "$89" in a and "3 weeks" in a


# ---- commissions (Roma's test 27.10: the agent made up prices, lead times and agreed to 50 cars) ----
def test_commission_price_discount_and_lead_time_come_from_the_rules():
    d = date(2026, 10, 27)
    one = shop.commission_quote([{"item_id": "sg-009", "colour": "yellow", "quantity": 1}], "CA", today=d)
    assert one["unit_usd"] == 89 and one["volume_discount_percent"] == 0 and one["build_weeks"] == 3
    assert one["shipping_usd"] == 6.5 and one["total_usd"] == 95.5
    mix = [{"item_id": "sg-009", "colour": "yellow", "quantity": 15},
           {"item_id": "sg-009", "colour": "light blue", "quantity": 5},
           {"item_id": "sg-012", "colour": "red", "quantity": 5}]
    q = shop.commission_quote(mix, "CA", today=d)
    assert q["total_cars"] == 25 and q["volume_discount_percent"] == 15 and q["shipping_usd"] == 0
    assert q["total_usd"] == round(25 * 89 * 0.85, 2)
    assert q["build_weeks"] == 3 + 8                       # 23 cars beyond the first two, 3 a week
    ten = shop.commission_quote([{"body": "fastback", "colour": "blue", "quantity": 10}], today=d)
    assert ten["volume_discount_percent"] == 10 and ten["shipping_usd"] == 0


def test_commission_refuses_missing_colour_and_too_many_cars():
    with pytest.raises(ValueError, match="colour"):
        shop.commission_quote([{"item_id": "sg-014", "quantity": 2}])
    with pytest.raises(ValueError, match="at most 40"):
        shop.commission_quote([{"item_id": "sg-014", "colour": "green", "quantity": 50}])


def test_commission_request_needs_contact_and_charges_nothing():
    cars = [{"item_id": "sg-015", "colour": "highland blue", "quantity": 3}]
    r = counter.request_commission("Sam", "", "555", "1 Main St, Fresno, CA 93701", "CA", cars)
    assert not r["ok"] and "email" in r["reason"]
    r = counter.request_commission("Sam", "sam@example.com", "555-0100", "1 Main St, Fresno, CA 93701", "CA", cars)
    assert r["ok"] and r["request_id"].startswith("CR-") and "invoice" in r["next_step"]
    assert shop.orders() == [] and len(shop.requests_()) == 1


def test_sold_out_listing_says_when_the_next_batch_is():
    yellow = counter.item_details("sg-009")
    assert yellow["next_batch"] == "2026-11-20" and "next small batch" in yellow["availability"]
