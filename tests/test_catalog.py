"""Lena's listings and the sample counters are in PayPal Catalog Products and show it on their cards, without
anyone having to open a counter first (judge 29.10, N4). PayPal is a fake here: no network."""
import json

import pytest
from fastapi.testclient import TestClient

from opencounter import catalog, paypal, sample, shop, web


class FakeCatalog:
    """PayPal's catalog: GET a product by id (404 if unknown), POST to create one."""

    def __init__(self, existing=(), down=False):
        self.products, self.calls, self.down = set(existing), [], down

    def __call__(self, method, path, json=None, request_id=None, retry=True):
        self.calls.append((method, path, json, request_id))
        if self.down:
            raise paypal.PayPalError(503, {"name": "SERVICE_UNAVAILABLE"})
        if method == "GET":
            pid = path.rsplit("/", 1)[-1]
            if pid not in self.products:
                raise paypal.PayPalError(404, {"name": "RESOURCE_NOT_FOUND"})
            return {"id": pid}
        assert 6 <= len(json["id"]) <= 50 and json["type"] == "PHYSICAL" and request_id == "product-" + json["id"]
        self.products.add(json["id"])
        return {"id": json["id"], "name": json["name"]}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(paypal, "configured", lambda: True)
    shop.seed(force=True)
    sample.build()


def test_every_listing_and_sample_counter_is_registered_once_and_shown_on_its_card(monkeypatch):
    pp = FakeCatalog(existing={"OC-SG-015"})   # one already registered by an earlier start
    monkeypatch.setattr(paypal, "_call", pp)
    done = catalog.sync()
    assert done["sg-014"] == "OC-SG-014" and done["sg-015"] == "OC-SG-015" and done["clay-kiln-s1"] == "OC-CLAY-KILN-S1"
    creates = [c for c in pp.calls if c[0] == "POST"]
    assert len(creates) == 4 + 3 and not any(c[2]["id"] == "OC-SG-015" for c in creates)   # found, not duplicated
    c = TestClient(web.app)
    card = c.get("/c/small-garage.json").json()
    assert {x["id"]: x["paypal_catalog_product"] for x in card["listings"]}["sg-014"] == "OC-SG-014"
    assert c.get("/c/clay-kiln-s1.json").json()["listings"][0]["paypal_catalog_product"] == "OC-CLAY-KILN-S1"
    assert "PayPal catalog product OC-CLAY-KILN-S1" in c.get("/c/clay-kiln-s1").text
    assert all(x["paypal_catalog_product"] for x in c.get("/api/open/latest").json())
    assert all(x["paypal_catalog_product"] for x in c.get("/api/directory").json()["results"])
    pp.calls.clear()
    assert catalog.sync() == {} and pp.calls == []     # a restart with ids already on disk calls nothing


def test_stock_sold_while_paypal_answered_is_not_overwritten(monkeypatch):
    pp = FakeCatalog()

    def slow(method, path, json=None, request_id=None, retry=True):
        if method == "POST" and json["id"] == "OC-SG-014":
            shop.take_stock("sg-014", 1)    # a buyer's capture lands in between
        return pp(method, path, json, request_id, retry)
    monkeypatch.setattr(paypal, "_call", slow)
    before = shop.listing("sg-014")["stock"]
    catalog.sync()
    assert shop.listing("sg-014")["stock"] == before - 1 and shop.listing("sg-014")["paypal_catalog_product"]


def test_paypal_down_leaves_cards_without_an_id_and_nothing_breaks(monkeypatch):
    monkeypatch.setattr(paypal, "_call", FakeCatalog(down=True))
    assert catalog.sync() == {}
    card = TestClient(web.app).get("/c/small-garage.json").json()
    assert all(x["paypal_catalog_product"] is None for x in card["listings"])


def test_the_card_with_catalog_ids_still_matches_its_schema(monkeypatch):
    jsonschema = pytest.importorskip("jsonschema")
    monkeypatch.setattr(paypal, "_call", FakeCatalog())
    catalog.sync()
    card = TestClient(web.app).get("/c/small-garage.json").json()
    jsonschema.validate(card, json.loads((shop.ROOT / "web/static/schema/open-counter-card.v1.json").read_text()))
