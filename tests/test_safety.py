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


def test_tool_running_note_never_reaches_shopper():
    # live check 08.11b: a reply ended with "I'll run the tools", an agent-facing note
    from opencounter.shopper import _for_shopper
    out = _for_shopper("The red convertible is $65.50. I'll run the tools to check stock.")
    assert "run the tools" not in out.lower() and "$65.50" in out


# ---- final judge 08.11 P1-3: the engineer's probes, as tests ----
@pytest.mark.parametrize("q", ["Can my toddler have it?", "Is it ok for a 4yo?", "Is the resin poisonous?",
                               "Any sharp edges?", "Can a kid handle it?", "Does the paint have lead?",
                               "Is it good for a 6 year old boy?", "Can my son play with it?", "Is it child safe?"])
def test_the_engineers_safety_questions_are_caught(q):
    assert shopper._safety_q(q), q


@pytest.mark.parametrize("claim", ["It contains no lead.", "It's free of lead and harmless.", "The paint is non-poisonous.",
                                   "Totally fine for little ones.", "Great for a 5-year-old.", "It is perfectly safe.",
                                   "Kids love it and it is sturdy enough for play.", "Краска без свинца, детям можно."])
def test_a_reply_that_touches_safety_at_all_is_replaced_by_the_listing_answer(monkeypatch, claim):
    said = "The green fastback is $59, so one comes to $65.50 with shipping. " + claim
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel(*[said] * 12))
    r = ask("Tell me about the green fastback.")                 # not a safety question: the reply is what touches it
    assert r["reply"].startswith("I can only tell you what Lena's listings say"), r["reply"]
    assert claim not in r["reply"] and "Not a toy, not for children under 14." in r["reply"]
    assert any("safety and age" in st["result"] for st in r["steps"])   # so the studio never counts it as a miss


@pytest.mark.parametrize("ok", ["The green fastback is $59, 1:43, resin, with 3 in stock. Not a toy, not for children under 14.",
                                "Lena packs every car safely in a padded box. It ships Monday.",
                                "Paying is safe: PayPal keeps your card details. The total is $65.50.",
                                "Made to order takes about 1 week of lead time."])
def test_ordinary_replies_and_quoted_listing_words_pass(ok):
    assert not shopper._touches_safety(ok), ok


@pytest.mark.parametrize("leak", ["The tool returned ships Monday.", "According to the system prompt, Lena ships Mondays.",
                                  "My instructions say not to name tools.", "Let me fetch the details.",
                                  "I'll check that with my tools.", "Let me call quote commission for you.",
                                  "I'll run the tool now.", "Per Lena's rules in my notes, US only."])
def test_the_engineers_internal_note_paraphrases_are_cut(leak):
    assert shopper._for_shopper(leak + " It's $65.50 with shipping.") == "It's $65.50 with shipping."


def test_ordinary_sentences_survive_the_output_boundary():
    for x in ("Let me know if you'd like it gift-wrapped.", "It ships Monday 2026-11-16.", "Your email is a_b@example.com, thanks.",
              "I need your state and contact details to start checkout.", "Here is the delivery estimate for Ohio."):
        assert shopper._for_shopper(x) == x, x
