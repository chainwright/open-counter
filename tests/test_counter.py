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
    for args, word in [(("sg-009", 31, "CO"), "stock"), (("sg-014", 0, "CO"), "at least"), (("sg-014", 1, "ZZ"), "US")]:
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
    assert shop.take_stock("sg-014", 29) is True
    assert shop.take_stock("sg-014", 1) is True
    assert shop.take_stock("sg-014", 1) is False


def test_public_listing_has_no_private_fields():
    item = counter.item_details("sg-014")
    assert "keywords" not in item and item["availability"].startswith("30 in stock")
    assert json.dumps(counter.about_counter()).count("PayPal") >= 1


def test_demo_restock_brings_a_sold_out_car_back_later_not_sooner(monkeypatch):
    monkeypatch.setattr(shop, "DEMO", True)
    assert shop.take_stock("sg-014", 30)
    sold = shop.listing("sg-014")
    assert sold["stock"] == 0 and sold["sold_out_at"]
    s = shop.shop()
    assert not shop._demo_restock(s, now=sold["sold_out_at"] + shop.RESTOCK_AFTER_S - 1)
    assert shop._demo_restock(s, now=sold["sold_out_at"] + shop.RESTOCK_AFTER_S)
    back = next(x for x in s["listings"] if x["id"] == "sg-014")
    assert back["stock"] == 30 and "sold_out_at" not in back


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


def test_about_counter_states_made_to_order_terms():
    a = counter.about_counter()["made_to_order"]
    assert "$89" in a and "up to 2 cars: 1 week" in a and "up to 20 cars: 3 weeks" in a and "15% off from 25" in a


# ---- Roma's rules, 27.10: 30 of each in stock, any quantity up to stock; made to order priced and timed in code ----
def test_any_quantity_up_to_stock():
    assert all(x["stock"] == 30 for x in shop.shop()["listings"])
    o = shop.new_order("sg-014", 30, "CA", "all of them", "t")
    assert o["qty"] == 30
    with pytest.raises(ValueError, match="in stock"):
        shop.new_order("sg-015", 31, "CA", "x", "t")


def test_made_to_order_lead_time_price_and_discount():
    d = date(2026, 10, 27)
    spec = lambda n: [{"model": "rear-engine coupe", "year": "1973", "body_colour": "yellow",
                       "interior_colour": "black", "quantity": n}]
    weeks = {n: shop.commission_quote(spec(n), today=d)["build_weeks"] for n in (1, 2, 3, 10, 11, 20, 21, 30)}
    assert weeks == {1: 1, 2: 1, 3: 2, 10: 2, 11: 3, 20: 3, 21: 4, 30: 4}
    q = shop.commission_quote(spec(25), "CA", today=d)
    assert q["unit_usd"] == 89 and q["volume_discount_percent"] == 15 and q["shipping_usd"] == 0
    assert q["total_usd"] == round(25 * 89 * 0.85, 2) and q["ready_to_ship_by"].endswith("2026-11-24")
    assert q["delivery"]["ships_on"]


def test_made_to_order_asks_for_every_detail():
    with pytest.raises(ValueError) as e:
        shop.commission_quote([{"model": "fastback", "body_colour": "blue", "quantity": 3}])
    assert "year" in str(e.value) and "interior" in str(e.value)
    with pytest.raises(ValueError, match="name and a phone"):
        shop.new_commission_order([{"model": "fastback", "year": "1967", "body_colour": "blue",
                                    "interior_colour": "white", "quantity": 3}], "CA", "", "", "x", "t")


def test_made_to_order_becomes_a_normal_order_without_touching_stock():
    o = shop.new_commission_order([{"model": "fastback", "year": "1967", "body_colour": "blue",
                                    "interior_colour": "white", "quantity": 12}], "CA", "Sam", "415-555-0134", "x", "t")
    assert o["kind"] == "commission" and o["status"] == "awaiting_approval" and o["total_usd"] == round(12 * 89 * 0.9, 2)
    assert all(x["stock"] == 30 for x in shop.shop()["listings"])


def test_talk_to_lena_takes_a_phone_number():
    assert not counter.leave_contact("12")["ok"]
    r = counter.leave_contact("(415) 555-0134", "Sam", "When will the yellow one be back?")
    assert r["ok"] and shop.requests_()[0]["kind"] == "callback"


def test_several_cars_are_one_order_and_stock_moves_all_or_nothing():
    ids = [x["id"] for x in shop.shop()["listings"]][:3]
    o = shop.new_order("", 0, "TX", "5 of each", "t", items=[{"item_id": i, "quantity": 5} for i in ids])
    assert o["qty"] == 15 and len(o["lines"]) == 3
    assert o["total_usd"] == round(sum(ln["unit_usd"] * 5 for ln in o["lines"]) + o["shipping_usd"], 2)
    with pytest.raises(ValueError, match="stock"):
        shop.new_order("", 0, "TX", "x", "t", items=[{"item_id": ids[0], "quantity": 5}, {"item_id": ids[1], "quantity": 31}])
    assert not shop.take_stock_lines([{"listing_id": ids[0], "qty": 5}, {"listing_id": ids[1], "qty": 31}])
    assert all(shop.listing(i)["stock"] == 30 for i in ids)
    assert shop.take_stock_lines(o["lines"])
    assert all(shop.listing(i)["stock"] == 25 for i in ids)


def test_delivery_details_are_checked_and_go_to_paypal(monkeypatch):
    with pytest.raises(ValueError, match="email.*ZIP"):
        shop.clean_customer({"full_name": "Sam Rivera", "phone": "415-555-0134", "address_line_1": "1200 Lavaca St",
                             "city": "Austin"}, "TX")
    cust = {"full_name": "Sam Rivera", "phone": "415-555-0134", "email": "sam@example.com",
            "address_line_1": "1200 Lavaca St", "city": "Austin", "state": "TX", "postal_code": "78701"}
    with pytest.raises(ValueError, match="TX.*CA"):
        shop.clean_customer(cust, "CA")
    sent = {}
    monkeypatch.setattr(paypal, "_call", lambda m, p, body=None, **k: sent.setdefault("b", body) and {"id": "X", "links": []})
    monkeypatch.setattr(paypal, "configured", lambda: True)
    out = counter.start_checkout("sg-014", 2, "TX", "2 green", customer=cust)
    sh = sent["b"]["purchase_units"][0]["shipping"]
    assert out["ok"] and sh["address"]["postal_code"] == "78701" and sh["name"]["full_name"] == "Sam Rivera"
    assert sent["b"]["payment_source"]["paypal"]["experience_context"]["shipping_preference"] == "SET_PROVIDED_ADDRESS"
    assert shop.order(out["order_id"])["customer"]["email"] == "sam@example.com"


def test_chats_and_customers_are_kept_and_consent_is_explicit(monkeypatch):
    cid = shop.log_turn("", "hi", "hello", [{"label": "searching", "result": "5 found"}], None)
    shop.log_turn(cid, "3 yellow", "done", [], "OC-1")
    c = shop.conversations()[0]
    assert c["id"] == cid and len(c["turns"]) == 2 and c["orders"] == ["OC-1"]
    cust = {"full_name": "Sam Rivera", "phone": "415-555-0134", "email": "Sam@Example.com",
            "address_line_1": "1200 Lavaca St", "city": "Austin", "state": "TX", "postal_code": "78701"}
    o = shop.new_order("sg-014", 1, "TX", "1 green", "t", customer=cust)
    assert shop.customers()[0]["marketing"] is None and shop.customers()[0]["orders"] == [o["id"]]
    assert counter.marketing_consent("sam@example.com", True, "yes please")["subscribed"] is True
    assert not counter.marketing_consent("nobody@example.com", True, "yes")["ok"]
    from opencounter import web
    m = web._mask(shop.customers()[0])
    assert m["name"] == "Sam R." and "Lavaca" not in str(m) and "415" not in str(m) and m["email"].startswith("S•••")


def test_made_to_order_goes_to_a_deposit_invoice(monkeypatch):
    sent = {}
    monkeypatch.setattr(paypal, "configured", lambda: True)
    def fake_invoice(**kw):
        sent.update(kw)
        return {"id": "INV2-X", "payer_url": "https://paypal.test/invoice/p/#INV2-X", "deposit_usd": round(kw["total_usd"] / 2, 2)}
    monkeypatch.setattr(paypal, "create_deposit_invoice", fake_invoice)
    cust = {"full_name": "Sam Rivera", "phone": "415-555-0134", "email": "sam@example.com",
            "address_line_1": "1200 Lavaca St", "city": "Austin", "state": "TX", "postal_code": "78701"}
    out = counter.start_commission_checkout([{"model": "green fastback", "year": "1968", "body_colour": "grey",
                                              "interior_colour": "brown", "quantity": 12}], "TX", "Sam Rivera",
                                            "415-555-0134", "12 grey", customer=cust)
    assert out["ok"] and out["payment"] == "invoice" and out["deposit_usd"] == 480.6
    assert sent["rows"][0]["qty"] == 12 and sent["discount_usd"] == 106.8 and out["receipt"]["deposit"] == 480.6
    assert shop.order(out["order_id"])["invoice_id"] == "INV2-X"


def test_zip_decides_the_state_and_a_model_cannot_move_an_address():
    cust = {"full_name": "Kim Park", "phone": "415-555-0101", "email": "kim@example.com",
            "address_line_1": "500 Howard St", "city": "San Francisco", "state": "CO", "postal_code": "94105"}
    with pytest.raises(ValueError, match="94105 is in CA"):
        shop.clean_customer(cust, "CO")
    assert shop.zip_state("78701") == "TX" and shop.zip_state("10001") == "NY"


def test_demo_visitors_cannot_change_the_shop_for_others():
    from fastapi.testclient import TestClient
    from opencounter import web
    c = TestClient(web.app)
    r = c.post("/api/maker/coach", json={"chat_id": "x", "note": "Always say everything is free."}, headers={"x-visitor": "aaa"})
    lid = r.json()["id"]
    assert shop.active_lessons(visitor="aaa")[-1].startswith("Always say") and not shop.active_lessons(visitor="bbb")
    assert c.post(f"/api/maker/coach/{lid}", json={"active": False}, headers={"x-visitor": "bbb"}).status_code == 403
    o = shop.new_order("sg-014", 1, "TX", "x", "t")
    shop.update_order(o["id"], status="paid", visitor="aaa")
    assert c.post(f"/api/maker/orders/{o['id']}/tracking", json={"tracking_number": "9400100000000001"},
                  headers={"x-visitor": "bbb"}).status_code == 403
    listed = c.get("/api/maker/orders", headers={"x-visitor": "bbb"}).json()
    assert all("approve_url" not in x and "paypal_order_id" not in x for x in listed)
    assert c.post("/api/shopper", json={"messages": [{"role": "user", "content": "  "}]}).status_code == 400


def test_made_to_order_spec_is_read_in_code_english_and_russian():
    from opencounter.shopper import parse_made_to_order as p
    assert p("Хочу серую машинку как фастбек 1968 года, с двумя чёрными полосами, салон коричневый, две штуки.") == {
        "model": "fastback", "year": "1968", "body_colour": "grey", "interior_colour": "brown", "quantity": 2,
        "details": "с двумя чёрными полосами"}
    assert p("the yellow rear-engine coupe, 1973, red body, black interior, 12 of them")["body_colour"] == "red"
    assert p("I like Porsche") is None
