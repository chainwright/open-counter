"""Every quantity on every order line is a whole number of at least 1, in code, before any money moves.
Final judge 08.11 P0-1: a made-to-order line of -2 offset a line of 3 and reached a PayPal invoice as quantity "-2"."""
import pytest

from opencounter import counter, mcp_server, paypal, shop


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)


def build(n, model="fastback"):
    return {"model": model, "year": "1967", "body_colour": "grey", "interior_colour": "brown", "quantity": n}


CUST = {"full_name": "Judge Test", "phone": "512-555-0142", "email": "j@example.com",
        "address_line_1": "100 Congress Ave", "city": "Austin", "state": "TX", "postal_code": "78701"}


@pytest.mark.parametrize("bad", [-5, 0, "0", "-1", 2.5, "2.5", "two", True, [2], {"n": 2}])
def test_a_made_to_order_quantity_must_be_a_whole_number_of_at_least_one(bad):
    with pytest.raises(ValueError, match="whole number|at least 1"):
        shop.commission_quote([build(bad)])


@pytest.mark.parametrize("good,n", [(3, 3), ("3", 3), (" 4 ", 4), (2.0, 2)])
def test_whole_numbers_still_quote(good, n):
    assert shop.commission_quote([build(good)])["total_cars"] == n


def test_a_missing_quantity_is_asked_for():
    spec = build(1)
    del spec["quantity"]
    with pytest.raises(ValueError, match="how many"):
        shop.commission_quote([spec])


def test_a_negative_line_cannot_offset_another_or_slip_past_the_car_limit():
    with pytest.raises(ValueError, match="at least 1"):
        shop.commission_quote([build(3), build(-2, "coupe")])     # was quoted as "1 car, $95.50"
    with pytest.raises(ValueError, match="at least 1"):
        shop.commission_quote([build(100), build(-90, "coupe")])  # was under commission_max_cars
    with pytest.raises(ValueError, match="at most 100"):
        shop.commission_quote([build(60), build(41, "coupe")])


def test_the_mcp_tools_refuse_a_negative_build_and_nothing_reaches_paypal(monkeypatch):
    sent = []
    monkeypatch.setattr(paypal, "configured", lambda: True)
    monkeypatch.setattr(paypal, "_call", lambda *a, **k: sent.append((a, k)) or {"id": "X", "links": []})
    q = mcp_server.quote_commission([build(-5)], "TX")
    assert q["ok"] is False and "at least 1" in q["reason"]
    out = mcp_server.start_commission_checkout([build(3), build(-2, "coupe")], "TX", "Judge Test", "512-555-0142",
                                               "3 fastbacks and -2 coupes", customer=CUST)
    assert out["ok"] is False and "at least 1" in out["reason"]
    assert sent == [] and shop.orders() == []


@pytest.mark.parametrize("bad", [-1, 0, 1.5, "1.5", "x"])
def test_a_stock_order_line_must_be_a_whole_number_too(monkeypatch, bad):
    sent = []
    monkeypatch.setattr(paypal, "configured", lambda: True)
    monkeypatch.setattr(paypal, "_call", lambda *a, **k: sent.append((a, k)) or {"id": "X", "links": []})
    out = mcp_server.start_checkout("sg-014", bad, "TX", "x")
    assert out["ok"] is False and ("whole number" in out["reason"] or "at least 1" in out["reason"])
    out = mcp_server.start_checkout("", 0, "TX", "x", items=[{"item_id": "sg-014", "quantity": 3},
                                                              {"item_id": "sg-014", "quantity": -2}])
    assert out["ok"] is False and "at least 1" in out["reason"]
    assert sent == [] and shop.orders() == []
