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
    out = mcp_server.start_checkout("TX", "x", item_id="sg-014", quantity=bad)
    assert out["ok"] is False and ("whole number" in out["reason"] or "at least 1" in out["reason"])
    out = mcp_server.start_checkout("TX", "x", items=[{"item_id": "sg-014", "quantity": 3},
                                                              {"item_id": "sg-014", "quantity": -2}])
    assert out["ok"] is False and "at least 1" in out["reason"]
    assert sent == [] and shop.orders() == []


# ---- the shop chat: a zero, negative or fractional quantity is answered in code (judge panel 09.11, seat 04 F-12:
# "I want -2 green fastbacks" was handed to the model, which called the tool with 2 and priced it) ----
from opencounter import shopper   # noqa: E402
from tests.test_lessons import NoModel   # noqa: E402


@pytest.mark.parametrize("said,typed", [
    ("I want -2 green fastbacks and 3 yellow ones shipped to Denver", "-2"),
    ("minus 3 cars to Austin please", "minus 3"),
    ("0 cars, the green one", "0"),
    ("1.5 fastbacks to Chicago", "1.5"),
    ("хочу −2 зелёных в Денвер", "−2")])
def test_the_chat_refuses_a_quantity_below_one_in_code_and_never_calls_the_model(monkeypatch, said, typed):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())   # any model call fails the test
    r = shopper.run([{"role": "user", "content": said}], "v-qty")
    assert r["model"] == "rule" and r["checkout"] is None and r["usd"] == 0.0
    assert typed in r["reply"] and ("at 1" in r["reply"] or "от 1" in r["reply"])
    assert "$" not in r["reply"]   # nothing priced


@pytest.mark.parametrize("said", ["2 green and 3 yellow to Chicago", "2-3 cars to Texas", "I need 40 green fastbacks",
                                  "call 512-555-0142 about 2 green ones", "20% off 2 red ones?", "a 1967 fastback, 1 car",
                                  "ZIP 78701, 1 green"])
def test_ordinary_quantities_phones_ranges_and_years_are_not_mistaken_for_a_bad_quantity(said):
    assert shopper.bad_qty(said) == ""
