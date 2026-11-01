"""Every public endpoint answers, and the ones that change something refuse what they should. No PayPal, no model."""
import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, sample, shop, shopper, web


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)
    monkeypatch.setattr(paypal, "configured", lambda: False)


@pytest.fixture
def c():
    return TestClient(web.app)


@pytest.mark.parametrize("path", ["/", "/maker", "/open", "/c/small-garage", "/api/health", "/c/small-garage.json",
                                  "/.well-known/open-counter.json", "/api/search?q=green", "/api/delivery/CO",
                                  "/api/maker/orders", "/api/maker/conversations", "/api/maker/insights",
                                  "/api/maker/coach", "/api/maker/customers", "/api/maker/requests",
                                  "/api/paypal/config", "/static/schema/open-counter-card.v1.json"])
def test_pages_and_reads_answer(c, path):
    assert c.get(path).status_code == 200


def test_card_follows_its_schema(c):
    card = c.get("/c/small-garage.json").json()
    assert card["$schema"].endswith("open-counter-card.v1.json")
    assert {"listings", "mcp"} <= card.keys() and card["listings"]


def test_unknown_things_are_refused(c):
    assert c.get("/api/orders/OC-NOPE").status_code in (404, 200) and "No order" in c.get("/api/orders/OC-NOPE").text
    assert c.get("/thanks/OC-NOPE").status_code == 404
    assert c.get("/paypal/return?oc=OC-NOPE&token=X").status_code == 410
    assert c.post("/api/paypal/approved", json={"order_id": "OC-NOPE", "paypal_order_id": "X"}).status_code == 404
    assert c.get("/c/no-such-counter.json").status_code == 404


def test_empty_chat_message_is_refused(c):
    assert c.post("/api/shopper", json={"messages": [{"role": "user", "content": "  "}]}).status_code == 400


def test_sample_orders_cannot_be_shipped_by_a_visitor(c):
    sample.build()
    one = next(o for o in shop.orders() if o.get("sample"))
    r = c.post(f"/api/maker/orders/{one['id']}/tracking", json={"tracking": "9400100000000000000000"},
               headers={"x-visitor": "v-test"})
    assert r.status_code == 403


def test_news_list_needs_lenas_key(c):
    assert c.get("/api/maker/news-list.csv").status_code in (401, 403)


def test_webhook_without_a_valid_signature_changes_nothing(c, monkeypatch):
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    monkeypatch.setattr(paypal, "verify_webhook", lambda headers, body: False, raising=False)
    before = [o["status"] for o in shop.orders()]
    r = c.post("/paypal/webhook", json={"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "X"}})
    assert r.status_code in (200, 400, 401)
    assert [o["status"] for o in shop.orders()] == before


def test_daily_spend_survives_a_restart(monkeypatch):
    monkeypatch.setattr(shopper, "_spent", {})
    shopper.add_spend(0.25)
    shopper.add_spend(0.5)
    monkeypatch.setattr(shopper, "_spent", {})    # a restart: memory is gone, the disk isn't
    assert abs(shopper.spent_today() - 0.75) < 1e-9


def test_one_search_covers_every_counter(c):
    sample.build()
    r = c.get("/api/directory?q=green").json()
    assert r["counters"] >= 2 and r["results"]
    assert any("small-garage" in x["card"] for x in r["results"])
    every = c.get("/api/directory").json()["results"]
    assert len({x["card"] for x in every}) >= 2     # Lena's shop and the counters other makers opened
    assert all(x["price_usd"] <= 60 for x in c.get("/api/directory?max_price=60").json()["results"])


def test_contacts_are_hidden_on_public_pages_in_any_phone_format():
    t = web._hide_contact("Kim / +12796657833 / 4155550134 / (415) 555-0134 / kim@example.com / 95608")
    assert not any(x in t for x in ("2796657833", "4155550134", "555-0134", "kim@", "95608"))


def test_full_ship_to_only_for_the_browser_that_ordered(c, monkeypatch):
    o = shop.new_order("sg-014", 1, "IL", "x", "t")
    shop.update_order(o["id"], visitor="v-buyer", customer={"full_name": "Mia Cole", "phone": "+13125550177",
                      "email": "mia@example.com", "address_line_1": "233 S Wacker Dr", "city": "Chicago",
                      "state": "IL", "postal_code": "60606"})
    assert "+13125550177" in c.get(f"/api/orders/{o['id']}/ship-to", headers={"x-visitor": "v-buyer"}).json()["ship_to"]
    assert c.get(f"/api/orders/{o['id']}/ship-to", headers={"x-visitor": "someone-else"}).status_code == 404
    assert c.get(f"/api/orders/{o['id']}/ship-to").status_code == 404


def test_only_lenas_key_marks_a_call_back_done(c, monkeypatch):
    monkeypatch.setenv("MAKER_KEY", "lena-secret")
    rq = shop.new_callback("614-555-0188", "Sam", "Call me about a build", "a build", "demo-shopper")
    url = f"/api/maker/requests/{rq['id']}"
    assert c.post(url, json={"status": "called"}).status_code == 403
    assert c.post(url, json={"status": "called"}, headers={"x-visitor": "v1", "x-maker-key": "wrong"}).status_code == 403
    assert next(r for r in shop.requests_() if r["id"] == rq["id"])["status"] == "to_call"
    r = c.post(url, json={"status": "called"}, headers={"x-maker-key": "lena-secret"})
    assert r.status_code == 200 and r.json()["status"] == "called"


def test_a_makers_counter_page_loads_the_fonts_its_stylesheet_names(c):
    sample.build()
    from opencounter import onboard
    slug = next(iter(onboard._counters()))
    page = c.get(f"/c/{slug}").text
    assert "fonts.googleapis.com/css2?family=Big+Shoulders+Display" in page and "family=Geist:" in page
    assert page.index("fonts.googleapis.com/css2") < page.index("/static/open.css")


def test_the_home_page_says_the_payments_are_sandbox(c):
    page = c.get("/").text
    assert "real PayPal sandbox payments" in page and "the payments are real." not in page


def test_agent_sales_strip_counts_orders_by_who_sold_them(monkeypatch):
    import time
    from opencounter import web, shop
    now = time.time()
    orders = [{"id": "A", "created": now - 100, "status": "paid", "channel": "mcp"},
              {"id": "B", "created": now - 50, "status": "awaiting_approval", "channel": "mcp"},
              {"id": "C", "created": now - 80, "status": "paid", "channel": "demo-shopper"},
              {"id": "D", "created": now - 90, "status": "paid", "channel": "demo-shopper", "kind": "commission"},
              {"id": "E", "created": now - 30, "status": "cancelled", "channel": "mcp"},
              {"id": "F", "created": now - 10 * 86400, "status": "paid", "channel": "mcp"}]
    monkeypatch.setattr(shop, "orders", lambda: orders)
    out = web.maker_agent_sales(days=7)
    assert (out["via_mcp"], out["her_chat"], out["made_to_order"]) == (2, 1, 1)
    assert out["last_mcp"] == {"id": "B", "status": "awaiting_approval", "paypal": "APPROVAL PENDING"}


def test_daily_counts_chats_and_live_orders_per_day(monkeypatch):
    import time
    from opencounter import web, shop
    now = time.time()
    monkeypatch.setattr(shop, "conversations", lambda: [{"started": now - 60}, {"started": now - 120}, {"started": now - 40 * 86400}])
    monkeypatch.setattr(shop, "orders", lambda: [{"created": now - 30, "status": "paid"}, {"created": now - 30, "status": "cancelled"}])
    rows = web.maker_daily(days=14)
    assert len(rows) == 14 and rows[-1]["chats"] == 2 and rows[-1]["orders"] == 1
    assert sum(r["chats"] for r in rows) == 2
