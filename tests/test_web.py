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
