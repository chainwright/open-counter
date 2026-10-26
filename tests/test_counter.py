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
