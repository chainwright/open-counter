"""The money paths besides the webhook capture (which has a logged sandbox run in the README): the automatic refund
when the last car sold during approval, and invoice payments moving a made-to-order build to 'deposit in' and
'paid'. PayPal's answers are faked here; no network."""
import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, shop, web


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)


def captured(state="TX"):
    return {"purchase_units": [{"payments": {"captures": [{"id": "CAP-1", "status": "COMPLETED"}]},
                                "shipping": {"name": {"full_name": "Sam Rivera"},
                                             "address": {"admin_area_2": "Austin", "admin_area_1": state}}}],
            "payer": {"name": {"given_name": "Sam"}}}


def waiting(lid="sg-015", qty=1):
    o = shop.new_order(lid, qty, "TX", "1 blue to Austin", "t")
    return shop.update_order(o["id"], paypal_order_id="PP-1")


def test_the_last_car_sold_during_approval_is_refunded_in_full(monkeypatch):
    o = waiting()
    shop.take_stock("sg-015", shop.listing("sg-015")["stock"])        # someone else bought the last one meanwhile
    refunds = []
    monkeypatch.setattr(paypal, "capture", lambda pp, oc: captured())
    monkeypatch.setattr(paypal, "refund", lambda cap, oc, amount_usd=None, note="": refunds.append((cap, oc, note)) or {})
    done = web._settle(o["id"])
    assert done["status"] == "refunded_out_of_stock" and refunds[0][:2] == ("CAP-1", o["id"])
    assert "Full refund" in refunds[0][2] and shop.listing("sg-015")["stock"] == 0
    assert web._settle(o["id"])["status"] == "refunded_out_of_stock" and len(refunds) == 1   # never twice


def test_a_normal_capture_takes_the_stock_and_follows_the_real_address(monkeypatch):
    o = waiting()
    before = shop.listing("sg-015")["stock"]
    monkeypatch.setattr(paypal, "capture", lambda pp, oc: captured(state="CA"))
    done = web._settle(o["id"])
    assert done["status"] == "paid" and done["ship_state"] == "CA" and done["agent_state"] == "TX"
    assert shop.listing("sg-015")["stock"] == before - 1


def test_invoice_payments_move_a_build_to_deposit_in_then_paid(monkeypatch):
    o = shop.new_commission_order([{"model": "fastback", "year": "1968", "body_colour": "grey",
                                    "interior_colour": "brown", "quantity": 12}], "TX", "Sam Rivera", "415-555-0134", "x", "t")
    shop.update_order(o["id"], invoice_id="INV2-X", deposit_usd=480.6)
    state = {"status": "PARTIALLY_PAID", "paid": "480.60"}
    monkeypatch.setattr(paypal, "get_invoice", lambda iid: {"status": state["status"],
                                                            "payments": {"paid_amount": {"value": state["paid"]}}})
    assert web._sync_invoice(o["id"])["status"] == "deposit_paid" and shop.order(o["id"])["paid_usd"] == 480.6
    state.update(status="PAID", paid="961.20")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    monkeypatch.setattr(paypal, "verify_webhook", lambda headers, event: True)
    r = TestClient(web.app).post("/paypal/webhook", json={"event_type": "INVOICING.INVOICE.PAID",
                                                          "resource": {"invoice": {"detail": {"invoice_number": o["id"]}}}})
    assert r.status_code == 200 and shop.order(o["id"])["status"] == "paid"
