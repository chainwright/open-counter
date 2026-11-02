"""The price the shopper was quoted is the price PayPal is asked for (judge-visible 'price locked · #…')."""
import pytest

from opencounter import paypal
from opencounter.counter import quote_lock, receipt


def _order(total=127.0):
    return {"id": "OC-TEST1", "title": "Fastback", "qty": 2, "unit_usd": 59.0, "shipping_usd": 9.0, "total_usd": total,
            "lines": [{"title": "Fastback, green", "qty": 2, "unit_usd": 59.0}]}


def test_receipt_carries_a_lock_that_changes_with_the_price():
    a = receipt(_order())["lock"]
    assert len(a) == 8 and a == receipt(_order())["lock"]          # stable for the same quote
    assert receipt(_order(total=128.0))["lock"] != a                # any cent changes it
    rows, extra = receipt(_order())["rows"], receipt(_order())["extra"]
    assert quote_lock("OC-TEST1", rows, extra, 127.0) == a


def test_paypal_is_never_asked_for_a_different_total(monkeypatch):
    called = []
    monkeypatch.setattr(paypal, "_call", lambda *a, **k: called.append(1) or {"id": "X", "links": []}, raising=False)
    listing = {"id": "l1", "title": "Fastback, green", "price_usd": 64.0}   # price changed after the quote
    with pytest.raises(paypal.PayPalError, match="differs from the quoted"):
        paypal.create_order(order_id="OC-TEST1", shop={"name": "Lena"}, listing=listing, qty=2, shipping_usd=9.0,
                            return_url="r", cancel_url="c", quoted_total_usd=127.0)
    assert not called
