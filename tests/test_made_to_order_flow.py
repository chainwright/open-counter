"""The judges' step 1, in code (live check 08.11 P1-1): the year of the real car is asked BEFORE any quote or
contact details, every time; the quote and the invoice follow as soon as their facts are typed; the reply over the
invoice card describes the build; no raw tool text. PayPal and the model are fakes: nothing is paid for."""
from datetime import datetime, timezone

import pytest

from opencounter import paypal, sample, shop, shopper
from tests.test_lessons import FakeModel, NoModel

SPEC = "A grey fastback with two black stripes, brown inside, two of them."
JUDGE = "Judge Test, 512-555-0142, judge.test@example.com, 100 Congress Ave, Austin, TX 78701"
SUNDAY = datetime(2026, 11, 8, 16, 46, tzinfo=timezone.utc)      # the live check's day: Sunday 8 Nov, 11:46 in Ohio


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shop, "_clock", lambda: SUNDAY)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(paypal, "configured", lambda: True)
    monkeypatch.setattr(paypal, "create_deposit_invoice", lambda **kw: {
        "id": "INV2-TEST", "payer_url": "https://paypal.test/invoice/p/#INV2-TEST",
        "deposit_usd": round(kw["total_usd"] / 2, 2)})
    shop.seed(force=True)
    sample.build()


def chat(*said, model=None, monkeypatch=None):
    """Runs the turns in order (like the browser: each reply and its memo go back with the next message)."""
    h, outs = [], []
    for text in said:
        h.append({"role": "user", "content": text})
        r = shopper.run(h, "v-judge")
        h.append({"role": "assistant", "content": r["reply"], "memo": r["memo"]})
        outs.append(r)
    return outs


def no_tool_text(r):
    return not any(w in r["reply"] for w in ("us_state", "item_id", "Before quoting", "I missed asking", "Let's create"))


def test_the_year_is_asked_first_then_the_quote_then_the_invoice_all_in_code(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    ask, quote, done = chat(SPEC, "It is a 1967.", JUDGE)
    # 1: the year, before any price or contact details
    assert "Which year is the real car" in ask["reply"] and "$" not in ask["reply"] and "phone" not in ask["reply"]
    assert "2 × fastback" in ask["reply"] and "two black stripes" in ask["reply"]
    assert not ask["checkout"] and not quote["checkout"]            # nothing is made before the contacts are in
    # 2: the quote, with one date (the day it ships), and one request for the contacts
    assert "$184.50" in quote["reply"] and "ships Monday 2026-11-16" in quote["reply"] and "first and last name" in quote["reply"]
    assert "Volume discounts start at 10 cars" in quote["reply"]
    # 3: the invoice, and the words over it describe the build
    assert done["checkout"] and done["checkout"]["payment"] == "invoice" and done["checkout"]["deposit_usd"] == 92.25
    assert "Lena will build 2 × fastback (1967), grey body, brown interior, two black stripes" in done["reply"]
    assert "$92.25 deposit" in done["reply"] and "On the shelf right now" not in done["reply"]
    assert "ships Monday 2026-11-16" in done["reply"] and "ships Monday 2026-11-16" in done["checkout"]["delivery"]
    assert all(no_tool_text(r) for r in (ask, quote, done))
    [o] = [o for o in shop.orders() if o.get("kind") == "commission" and not o.get("sample")]
    assert o["quote"]["ready_to_ship_by"] == o["estimate"]["ships_on"] == "Monday 2026-11-16"


def test_contacts_typed_before_the_year_wait_and_the_year_brings_quote_and_invoice(monkeypatch):
    # the browser run of 08.11: contacts came second, the agent quoted with no year and said "I missed asking"
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    ask, again, done = chat(SPEC, JUDGE, "It is a 1967.")
    assert "Which year" in ask["reply"] and "Which year" in again["reply"] and "Thanks, I have your details." in again["reply"]
    assert not again["checkout"] and "$" not in again["reply"]
    assert done["checkout"] and "Lena will build 2 × fastback (1967)" in done["reply"] and "$184.50" in done["reply"]
    assert no_tool_text(done)


def test_a_year_the_model_made_up_never_prices_a_build(monkeypatch):
    spec = [{"model": "fastback", "year": "1967", "body_colour": "grey", "interior_colour": "brown", "quantity": 2}]
    out = shopper._call_tool("quote_commission", {"cars": [dict(spec[0])]}, SPEC, SPEC)
    assert out["ok"] is False and "year of the real car" in out["reason"]
    ok = shopper._call_tool("quote_commission", {"cars": [dict(spec[0])]}, SPEC, SPEC + " / it's a '67")
    assert ok["ok"] and ok["total_usd"] == 184.5
    assert shopper._year_typed("1967", "a 1967 one") and shopper._year_typed("1967", "the ’67 fastback")
    assert not shopper._year_typed("1968", "two of them, brown inside")


def test_a_shelf_purchase_is_not_taken_for_a_build():
    assert shopper._build_wanted(["2 green fastbacks to Austin"]) is None
    assert shopper._build_wanted(["Do you have a black one?"]) is None
    assert shopper._build_wanted([SPEC])["body_colour"] == "grey"
    assert shopper._build_wanted(["Could Lena build a black convertible?"])["model"] == "convertible"


def test_a_thank_you_after_the_invoice_makes_no_second_one(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    outs = chat(SPEC, "It is a 1967.", JUDGE)
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel("You're welcome! Lena starts once the deposit is in."))
    h = []
    for text, r in zip((SPEC, "It is a 1967.", JUDGE), outs):
        h += [{"role": "user", "content": text}, {"role": "assistant", "content": r["reply"], "memo": r["memo"]}]
    shopper.run(h + [{"role": "user", "content": "no thanks, that's all"}], "v-judge")
    assert len([o for o in shop.orders() if o.get("kind") == "commission" and not o.get("sample")]) == 1


def test_russian_build_goes_the_same_way(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    ask, quote, done = chat("Серый фастбек, салон коричневый, две штуки.", "1967 года.",
                            "Иван Петров, 312-555-0190, ivan@example.com, 233 S Wacker Dr, Chicago IL 60606")
    assert "Какого года" in ask["reply"] and "$" not in ask["reply"]
    assert "Под заказ" in quote["reply"] and "$184.50" in quote["reply"]
    assert done["checkout"] and "Лена соберёт" in done["reply"]


def test_the_words_over_an_invoice_the_model_made_describe_the_build_not_the_shelf(monkeypatch):
    # live check 08.11: the card was right, the text above it was the shelf fallback ("On the shelf right now: …")
    from tests.test_output_boundary import ScriptedModel, tool_call
    cars = [{"model": "fastback", "year": "1967", "body_colour": "grey", "interior_colour": "brown", "quantity": 2,
             "details": "two black stripes"}]
    cust = {"full_name": "Judge Test", "phone": "512-555-0142", "email": "judge.test@example.com",
            "address_line_1": "100 Congress Ave", "city": "Austin", "state": "TX", "postal_code": "78701"}
    shelf = shopper._shelf_answer(False)
    model = ScriptedModel([tool_call("start_commission_checkout", {"cars": cars, "us_state": "TX", "name": "Judge Test",
                                                                   "phone": "512-555-0142", "customer": cust})], shelf)
    monkeypatch.setattr(shopper, "_client_", lambda: model)
    monkeypatch.setattr(shopper, "parse_made_to_order", lambda text: None)   # the model makes this invoice, not code
    h = [{"role": "user", "content": "Yes, please send the invoice. It's a 1967 grey fastback, two black stripes, brown "
                                     "inside, two of them? " + JUDGE}]
    r = shopper.run(h, "v-judge")
    assert r["checkout"] and "On the shelf right now" not in r["reply"], r["reply"]
    assert "Lena will build 2 × fastback (1967)" in r["reply"] and "$92.25 deposit" in r["reply"]


def test_a_build_for_another_state_waits_for_that_address(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    first, = chat(JUDGE)  # contacts from an earlier order in this chat (Austin, TX)
    h = [{"role": "user", "content": JUDGE}, {"role": "assistant", "content": first["reply"], "memo": first["memo"]},
         {"role": "user", "content": "Also a custom one: the yellow rear-engine coupe, 1973, red body, black interior, "
                                     "12 of them, to California"}]
    r = shopper.run(h, "v-judge")
    assert not r["checkout"] and "$961.20" in r["reply"] and "Where in California should it go?" in r["reply"]
