"""How to pay is a shop fact, answered in code; a stock checkout is made only for a car the chat named.

Second opinion 10.11: "Can I pay with a credit card instead of PayPal?" (step 4 of the judge walkthrough) went to the
model, and 3 of 3 fresh chats invented a car nobody mentioned ("Red American Convertible, 1965"), one called
start_checkout with an empty customer, one reply was cut mid-sentence. No model call is paid for here: the model is
a fake."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opencounter import misses, sample, shop, shopper, web
from tests.test_lessons import FakeModel, NoModel

JUDGE_Q = "Can I pay with a credit card instead of PayPal?"   # word for word from DEVPOST.md, walkthrough step 4
TITLES = ("Green American Fastback", "Highland Blue Fastback", "Orange Muscle Coupe", "Yellow German", "Red American")


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(shopper, "_spent_by", {})
    shop.seed(force=True)
    sample.build()


def ask(text, history=(), visitor="qa-pay"):
    return shopper.run(list(history) + [{"role": "user", "content": text}], visitor)


class ToolModel:
    """A fake model that first calls one tool (as the live model did), then says the given words."""

    def __init__(self, name, args, then="Happy to help."):
        self.turns, self.calls = [(name, args), then], []
        self.chat = self.completions = self

    def with_options(self, **_):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        nxt = self.turns.pop(0) if self.turns else "Happy to help."
        if isinstance(nxt, tuple):
            fn = SimpleNamespace(name=nxt[0], arguments=json.dumps(nxt[1]))
            tc = SimpleNamespace(id="call-1", function=fn, model_dump=lambda: {
                "id": "call-1", "type": "function", "function": {"name": fn.name, "arguments": fn.arguments}})
            msg = SimpleNamespace(content="", tool_calls=[tc])
        else:
            msg = SimpleNamespace(content=nxt, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


# ---- the payment answer, by code ----

def test_the_judge_walkthrough_question_is_answered_by_code_with_no_car_and_no_checkout(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())          # any model call fails the test
    before = len(shop.orders())
    r = ask(JUDGE_Q)
    assert r["reply"].startswith("Yes, a card works.")
    assert "paid through PayPal" in r["reply"] and "credit or debit card" in r["reply"]
    assert "guest checkout" in r["reply"] and "without a PayPal account" in r["reply"]
    assert "which car, how many" in r["reply"]                              # offers to continue
    assert not any(t in r["reply"] for t in TITLES), r["reply"]            # no invented car
    assert r["checkout"] is None and len(shop.orders()) == before and r["usd"] == 0
    assert not misses.STUCK.search(r["reply"])                              # not a new "got stuck" row
    assert all(s["tool"] != "start_checkout" for s in r["steps"])


@pytest.mark.parametrize("q, lead", [
    ("Can I pay by card?", "Yes, a card works."),
    ("Do you accept debit cards?", "Yes, a card works."),
    ("Visa or Mastercard?", "Yes, a card works."),
    ("I don't have PayPal, can I still buy one?", "Yes, a card works."),
    ("Do you take Apple Pay?", "We don't take Apple Pay here."),
    ("Can I pay cash?", "We don't take cash here."),
    ("Can I pay by bank transfer?", "We don't take bank transfers here."),
    ("Can I pay with Venmo?", "We don't take Venmo here."),
    ("Can I pay with bitcoin?", "We don't take crypto here."),
    ("Apple Pay or cash?", "We don't take Apple Pay or cash here."),
    ("How do I pay?", "Every order is paid through PayPal"),
    ("What payment methods do you accept?", "Every order is paid through PayPal"),
])
def test_close_variants_get_the_same_answer_from_code(monkeypatch, q, lead):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask(q)
    assert r["reply"].startswith(lead), r["reply"]
    assert "paid through PayPal" in r["reply"] and "guest checkout" in r["reply"]
    assert r["checkout"] is None and r["usd"] == 0


def test_the_payment_answer_in_russian(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask("Можно оплатить картой?")
    assert r["reply"].startswith("Да, картой можно.") and "через PayPal" in r["reply"] and r["checkout"] is None


def test_questions_that_are_not_about_paying_still_go_their_own_way():
    for q in ("Do you ship to Canada?", "Can you rush it?", "2 green and 3 yellow to Chicago", "Do you take returns?",
              "Can you include a birthday card?", "How much do I pay for shipping?", "Is the paint safe?",
              "A grey fastback with two black stripes, brown inside, two of them.", "1967"):
        assert shopper.pay_question(q) is None, q


def test_after_a_cart_is_priced_the_payment_answer_asks_for_the_details_not_the_car(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    first = ask("2 red convertibles to Chicago")                      # priced in code, details still missing
    assert first["checkout"] is None and "needs:" in first["memo"]
    hist = [{"role": "user", "content": "2 red convertibles to Chicago"},
            {"role": "assistant", "content": first["reply"], "memo": first["memo"]}]
    r = ask(JUDGE_Q, hist)
    assert "guest checkout" in r["reply"] and "send your first and last name" in r["reply"]
    assert "which car" not in r["reply"]


def test_inside_an_order_the_model_never_is_the_source_of_the_payment_fact():
    out = shopper._must_say("Sorry, we don't accept cards. It ships Monday.", "1 green to Austin, can I pay by card?", [])
    assert out.startswith("Yes, a card works.") and "guest checkout" in out
    assert "don't accept cards" not in out and "It ships Monday." in out


def test_lenas_lesson_on_payment_is_logged_as_followed_so_the_studio_row_ticks(monkeypatch):
    # the walkthrough's step 4 end to end: the open row → a lesson → the question again → the row's tick
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    c, h = TestClient(web.app), {"x-visitor": "qa-judge"}
    rows = c.get("/api/maker/agent_misses", headers=h).json()
    row = next(r for r in rows["open"] if "credit card instead of PayPal" in r["asked"])
    note = ("If someone asks about paying by credit card, say every order is paid through PayPal and a card works "
            "in PayPal's window.")
    lesson = c.post("/api/maker/coach", json={"chat_id": row["chat"], "note": note}, headers=h).json()
    r = c.post("/api/shopper", json={"messages": [{"role": "user", "content": JUDGE_Q}], "conv_id": "qa-judge-1"},
               headers=h).json()
    assert r["lessons"] == [lesson["id"]] and r["checkout"] is None and "guest checkout" in r["reply"]
    taught = next(t for t in c.get("/api/maker/agent_misses", headers=h).json()["taught"] if t["lesson"] == lesson["id"])
    assert taught["followed"] == 1 and taught["missed"] == 0


# ---- no checkout for a car nobody named ----

def test_a_checkout_for_a_car_nobody_named_is_never_made(monkeypatch):
    invented = {"item_id": "sg-012", "quantity": 1, "us_state": "", "what_the_shopper_asked": "x",
                "customer": {"full_name": "", "phone": "", "email": "", "address_line_1": "", "city": "", "state": "",
                             "postal_code": ""}}
    fake = ToolModel("start_checkout", invented, then="Your Red American Convertible, 1965 is ready.")
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    before = len(shop.orders())
    r = ask("Hi! What would you recommend?")
    assert r["checkout"] is None and len(shop.orders()) == before
    assert "Red American Convertible, 1965 is ready" not in r["reply"]
    assert "Tell me which car, how many" in r["reply"]                     # asks what they want instead
    assert any(s["label"] == "checking the cart" for s in r["steps"]) and len(fake.calls) == 1


def test_a_payment_question_inside_an_order_with_an_invented_car_still_gets_the_payment_answer(monkeypatch):
    fake = ToolModel("start_checkout", {"items": [{"item_id": "Red American Convertible", "quantity": 1}],
                                        "us_state": "TX", "what_the_shopper_asked": "x", "customer": {}})
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    r = ask("Can I pay by card? Sam Rivera, 415-555-0134, sam@example.com")
    assert r["checkout"] is None and r["reply"].startswith("Yes, a card works.") and "which car" in r["reply"]


def test_a_named_car_still_goes_to_checkout(monkeypatch):
    fake = ToolModel("start_checkout", {"items": [{"item_id": "sg-012", "quantity": 2}], "us_state": "IL",
                                        "what_the_shopper_asked": "x", "customer": {}},
                     then="Two red convertibles come to $124.50 with shipping. Send your name, phone, email and address.")
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    r = ask("Could I get two of the convertibles?")
    assert any(s["tool"] == "start_checkout" and "total $" in s["result"] for s in r["steps"]), r["steps"]
    assert not any(s["label"] == "checking the cart" for s in r["steps"])


@pytest.mark.parametrize("typed, said, item, ok", [
    (JUDGE_Q, "", "sg-012", False),
    ("Hi", "", "sg-014", False),
    ("Hi", "", "", False),                                       # no car in the call and none in the chat
    ("2 red convertibles to Chicago", "", "sg-012", True),
    ("the red '65", "", "sg-012", True),
    ("Model 65, California", "", "sg-012", True),
    ("Две зелёные машинки в Чикаго", "", "sg-014", True),
    ("I like Porsche", "", "sg-009", True),                    # a brand: the agent offers the closest replica
    ("yes, that one please", "The Orange Muscle Coupe, 1970 is $59.", "sg-011", True),   # the shop named it
    ("yes please", "That's $65.50 with shipping.", "sg-012", False),   # the 65 of $65.50 is not a year
    ("1 green to Austin", "", "", True),                          # no item in the call, but the chat named one
])
def test_which_carts_count_as_named(typed, said, item, ok):
    args = {"items": [{"item_id": item, "quantity": 1}]} if item else {}
    assert shopper.cart_named(args, typed, said) is ok
