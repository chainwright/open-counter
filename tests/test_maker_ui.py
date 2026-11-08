"""Lena's order feed (live check 08.11 P1-3): a made-to-order card shows a picture, never an empty <img src="">, and a
second "request the balance" within the hour says why instead of "Couldn't send". maker.js runs in node with a stub page."""
import json
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, shop, web

ROOT = shop.ROOT
LISTINGS = [{"id": "sg-014", "title": "Green American Fastback, 1968", "photo_url": "/media/green_fastback.jpg",
             "stock": 3, "price_usd": 59.0},
            {"id": "sg-012", "title": "Red American Convertible, 1965", "photo_url": "/media/red_convertible.jpg",
             "stock": 2, "price_usd": 59.0}]
MTO = {"id": "OC-MTO1", "kind": "commission", "listing_id": "", "title": "Made to order: 2 × fastback (1967), grey body",
       "status": "deposit_paid", "mine": True, "has_invoice": True, "paid_usd": 92.25, "total_usd": 184.5,
       "created": time.time(), "channel": "demo-shopper", "qty": 2, "ship_state": "TX",
       "quote": {"build_weeks": 1, "ready_to_ship_by": "Monday 2026-11-16", "cars": [{"model": "fastback"}]}}


def feed(orders, status=200, detail=""):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    fx = {"orders": orders, "listings": LISTINGS, "balance_status": status, "balance_detail": detail}
    out = subprocess.run([node, str(ROOT / "tests" / "js" / "maker_orders.js"), str(ROOT / "web" / "static" / "maker.js"),
                          json.dumps(fx)], capture_output=True, text=True, timeout=20)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_made_to_order_card_shows_the_shelf_car_of_its_body_style_not_a_broken_image():
    shown = feed([MTO])["feed"]
    assert 'src=""' not in shown and 'src="/media/green_fastback.jpg"' in shown
    other = feed([{**MTO, "title": "Made to order: 1 × spaceship", "quote": {**MTO["quote"], "cars": [{"model": "spaceship"}]}}])
    assert 'src="/media/hero.jpg"' in other["feed"]


def test_the_balance_button_says_why_a_second_reminder_waits():
    assert "Cars ready: request the balance" in feed([MTO])["feed"]
    assert feed([MTO], 429, "A reminder already went out in the last hour.")["clicked"] == "Already reminded within the last hour"
    assert feed([MTO], 200)["clicked"] == "Reminder sent via PayPal"
    just = feed([{**MTO, "balance_requested": time.time() - 60}])["feed"]
    assert "Reminder sent · again in an hour" in just and 'data-balance="OC-MTO1"' not in just


def test_the_server_refuses_a_second_reminder_within_the_hour_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)
    sent = []
    monkeypatch.setattr(paypal, "remind_invoice", lambda inv, note: sent.append(inv))
    orders = shop.orders() + [{"id": "OC-MTO1", "kind": "commission", "invoice_id": "INV2-X", "status": "deposit_paid",
                               "visitor": "v-lena", "created": time.time(), "events": [], "total_usd": 184.5}]
    shop._save_orders(orders)
    c = TestClient(web.app)
    assert c.post("/api/maker/orders/OC-MTO1/balance", headers={"x-visitor": "v-lena"}).status_code == 200
    again = c.post("/api/maker/orders/OC-MTO1/balance", headers={"x-visitor": "v-lena"})
    assert again.status_code == 429 and "last hour" in again.json()["detail"] and sent == ["INV2-X"]
