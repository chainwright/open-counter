"""Product safety, age and materials are answered only from the listing text (live check 08.11: "Is the paint
lead-free? It's for my 5 year old" got "Our paints are non-toxic and safe", while the listing says "Not a toy, not
for children under 14"). No model call is paid for: the model is a fake."""
import pytest

from opencounter import sample, shop, shopper
from tests.test_lessons import FakeModel, NoModel


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    shop.seed(force=True)
    sample.build()


def ask(text, history=()):
    return shopper.run(list(history) + [{"role": "user", "content": text}], "v-safety")


@pytest.mark.parametrize("q", ["Is the paint lead-free? It's for my 5 year old.",
                               "Is it safe for kids?", "Is the green fastback non-toxic?",
                               "Can my 3-year-old play with it?", "Is the paint safe?"])
def test_a_safety_question_is_answered_from_the_listing_in_code(monkeypatch, q):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask(q)
    assert "Not a toy, not for children under 14." in r["reply"]          # the age warning, quoted
    assert "don't know" in r["reply"]
    assert not shopper.SAFETY_CLAIM.search(r["reply"]), r["reply"]       # no claim of its own
    assert r["usd"] == 0


def test_the_named_car_is_quoted_with_its_materials_and_paint(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask("Is the paint on the red convertible toxic?")
    assert "candy-apple red" in r["reply"] and "resin body" in r["reply"]
    assert "Not a toy, not for children under 14." in r["reply"]          # the shop's age warning is still said


def test_russian_safety_question_gets_the_listing_words_in_russian(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask("Краска не токсичная? Это для ребёнка 5 лет.")
    assert "Not a toy, not for children under 14." in r["reply"] and "не знаю" in r["reply"]


def test_a_model_safety_claim_never_reaches_the_shopper(monkeypatch):
    # a safety question inside an order goes to the model; its invented claim is cut and the listing leads
    made_up = "Our paints are non‑toxic and safe for display, and fine for kids with supervision. It's $65.50 to Austin."
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel(*[made_up] * 12))
    r = ask("1 green fastback to Austin please, is it safe for my 5 year old?")
    assert "non‑toxic" not in r["reply"] and "fine for kids" not in r["reply"], r["reply"]
    assert "Not a toy, not for children under 14." in r["reply"]
    assert shopper._scrub_safety("It's lead-free and child-safe. It ships Monday.") == "It ships Monday."
    assert shopper._scrub_safety("Lena packs it safely. PayPal keeps your payment safe.") == \
        "Lena packs it safely. PayPal keeps your payment safe."             # not product-safety claims


def test_ordinary_questions_are_not_taken_for_safety():
    for q in ("What scale are your cars?", "2 red convertibles to Chicago", "Do you ship to Hawaii?",
              "How long does a custom one take?", "Is the red one a real metal model?", "A gift for my dad",
              "Is shipping safe for a fragile car?", "Is it safe to pay with PayPal?", "Is the box safe in transit?"):
        assert not shopper._safety_q(q), q
