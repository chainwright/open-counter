"""A counter opened at /open is paid to the maker's own PayPal account (the order's payee), not the platform.
PayPal's answers are faked here; no network, no model."""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from opencounter import onboard, paypal, sample, shop, web


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(paypal, "configured", lambda: True)
    monkeypatch.delenv(onboard.SAMPLE_PAYEE_ENV, raising=False)
    shop.seed(force=True)


@pytest.fixture
def sent(monkeypatch):
    """Every body sent to PayPal's create-order endpoint; the catalog call answers with a product id."""
    calls = []

    def fake(method, path, json=None, request_id=None, retry=True):
        if path == "/v1/catalogs/products":
            return {"id": "PROD-1"}
        calls.append({"path": path, "body": json, "request_id": request_id})
        return {"id": f"PP-{len(calls)}", "links": [{"rel": "payer-action", "href": "https://sandbox.paypal.test/ok"}]}
    monkeypatch.setattr(paypal, "_call", fake)
    return calls


def photo():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def opened(email="rosa@clay.example.com"):
    return onboard.publish({"title": "Stoneware Mug", "short_description": "A mug."}, 32, 6, "TX", "Rosa Diaz",
                           "Clay & Kiln", photo(), "v1", email)


def unit(call):
    return call["body"]["purchase_units"][0]


def test_a_counter_with_a_paypal_email_pays_the_maker(sent):
    c = opened()
    out = onboard.checkout(c["slug"], 2, "OH", "v2")
    u = unit(sent[-1])
    assert u["payee"] == {"email_address": "rosa@clay.example.com"} and "soft_descriptor" not in u
    assert u["amount"]["value"] == "70.50" and out["paid_to"] == "Rosa Diaz's own PayPal account"
    o = shop.order(out["order_id"])
    assert o["payee_email"] == "rosa@clay.example.com" and "payee_email" not in web._mask_order(o)


def test_lenas_own_orders_and_counters_without_an_email_pay_the_platform(sent):
    c = opened(email="")
    out = onboard.checkout(c["slug"], 1, "OH")
    assert "payee" not in unit(sent[-1]) and unit(sent[-1])["soft_descriptor"] == "SMALLGARAGE"
    assert "demo merchant" in out["paid_to"]


def test_a_made_up_email_falls_back_to_the_demo_merchant_only_in_the_sandbox(monkeypatch, sent):
    c = opened(email="nobody@nowhere.example.com")
    real = paypal._call

    def refuse_payee(method, path, json=None, request_id=None, retry=True):
        if json and json.get("purchase_units", [{}])[0].get("payee"):
            raise paypal.PayPalError(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYEE_ACCOUNT_INVALID"}]})
        return real(method, path, json, request_id, retry)
    monkeypatch.setattr(paypal, "_call", refuse_payee)
    out = onboard.checkout(c["slug"], 1, "OH")
    assert "payee" not in unit(sent[-1]) and sent[-1]["request_id"] == f"create-{out['order_id']}"
    assert "demo merchant" in out["paid_to"] and "didn't accept" in out["note"]
    assert shop.order(out["order_id"])["payee_email"] == ""
    monkeypatch.setattr(paypal, "BASE", "https://api-m.paypal.com")    # live PayPal: never redirect a maker's money
    with pytest.raises(paypal.PayPalError):
        onboard.checkout(c["slug"], 1, "OH")


def test_a_bad_email_is_refused_when_the_counter_opens(sent):
    with pytest.raises(ValueError, match="PayPal email"):
        opened(email="rosa at clay")


def test_the_sample_counters_pay_the_second_sandbox_merchant_when_it_is_set(monkeypatch, sent):
    sample.build()
    onboard.checkout("clay-kiln-s1", 1, "OH")
    assert "payee" not in unit(sent[-1])
    monkeypatch.setenv(onboard.SAMPLE_PAYEE_ENV, "maker-two@business.example.com")
    out = onboard.checkout("clay-kiln-s1", 1, "OH")
    assert unit(sent[-1])["payee"]["email_address"] == "maker-two@business.example.com"
    assert out["paid_to"] == "Rosa Diaz's own PayPal account"


def test_the_page_card_and_publish_say_where_the_money_goes_without_showing_the_email(sent):
    tc = TestClient(web.app)
    r = tc.post("/api/open/publish", json={"listing": {"title": "Stoneware Mug"}, "price_usd": 32, "stock": 6,
                                           "ships_from": "TX", "maker": "Rosa Diaz", "shop_name": "Clay & Kiln",
                                           "image": photo(), "paypal_email": "rosa@clay.example.com"})
    assert r.status_code == 200 and r.json()["payment_goes_to"] == "Rosa Diaz's own PayPal account"
    slug = r.json()["slug"]
    card = tc.get(f"/c/{slug}.json").json()
    assert card["checkout"]["payment_goes_to"] == "Rosa Diaz's own PayPal account" and "rosa@" not in str(card)
    page = tc.get(f"/c/{slug}").text
    assert "names Rosa Diaz's own PayPal account as the payee" in page and "rosa@" not in page


def test_a_sold_out_maker_order_asks_her_to_refund_when_the_platform_cannot(monkeypatch, sent):
    c = opened()
    out = onboard.checkout(c["slug"], 1, "OH")
    shop.update_order(out["order_id"], paypal_order_id="PP-1")
    onboard.take(c["slug"], 6)                                        # sold out while the buyer was in PayPal
    monkeypatch.setattr(paypal, "capture", lambda pp, oc: {"purchase_units": [{"payments": {"captures": [
        {"id": "CAP-9", "status": "COMPLETED"}]}}]})

    def no_permission(cap, oc, amount_usd=None, note=""):
        raise paypal.PayPalError(403, {"name": "NOT_AUTHORIZED", "details": [{"issue": "PERMISSION_DENIED"}]})
    monkeypatch.setattr(paypal, "refund", no_permission)
    o = web._settle(out["order_id"])
    assert o["status"] == "refund_due" and "refund this buyer" in o["note"]
    assert web._settle(out["order_id"])["status"] == "refund_due"    # settled once, not again


def test_an_email_the_sandbox_cannot_pay_is_screened_before_paypal(monkeypatch, sent):
    """The sandbox accepts any payee when the order is created and fails later, at approval or capture (checked live
    30.10: a made-up payee got PAYER_ACTION_REQUIRED). So a non-sandbox email pays the demo merchant from the start."""
    c = opened(email="rosa.diaz@gmail.com")
    out = onboard.checkout(c["slug"], 1, "OH")
    assert "payee" not in unit(sent[-1]) and unit(sent[-1])["soft_descriptor"] == "SMALLGARAGE"
    assert "isn't a PayPal sandbox account" in out["paid_to"]
    page = TestClient(web.app).get(f"/c/{c['slug']}").text
    assert "isn't a PayPal sandbox account" in page and "On live PayPal" in page and "gmail" not in page
    monkeypatch.setattr(paypal, "BASE", "https://api-m.paypal.com")    # live PayPal pays any real account
    out = onboard.checkout(c["slug"], 1, "OH")
    assert unit(sent[-1])["payee"] == {"email_address": "rosa.diaz@gmail.com"}
    assert out["paid_to"] == "Rosa Diaz's own PayPal account"


def test_publish_says_when_the_email_is_not_a_sandbox_account(sent):
    r = TestClient(web.app).post("/api/open/publish", json={
        "listing": {"title": "Stoneware Mug"}, "price_usd": 32, "stock": 6, "ships_from": "TX", "maker": "Rosa Diaz",
        "shop_name": "Clay & Kiln", "image": photo(), "paypal_email": "rosa@realshop.com"})
    assert r.status_code == 200 and "isn't a PayPal sandbox account" in r.json()["payment_goes_to"]


def test_a_payee_refused_at_capture_shows_a_clear_page_and_charges_nothing(monkeypatch, sent):
    c = opened()
    out = onboard.checkout(c["slug"], 1, "OH")
    pp = shop.order(out["order_id"])["paypal_order_id"]

    def refuse(pp_id, oc):
        raise paypal.PayPalError(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYEE_ACCOUNT_RESTRICTED"}]})
    monkeypatch.setattr(paypal, "capture", refuse)
    r = TestClient(web.app).get(f"/paypal/return?oc={out['order_id']}&token={pp}")
    assert r.status_code == 502 and "couldn't pay this maker" in r.text and "Nothing was charged" in r.text
    assert shop.order(out["order_id"])["status"] == "error"
