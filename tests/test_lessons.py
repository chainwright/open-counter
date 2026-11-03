"""Lena's lessons change the next answer, checked in code: no model call is paid for (the model is a fake)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from opencounter import sample, shop, shopper, web


class FakeModel:
    """Stands in for the Nemotron client: returns the given replies (or raises), records what it was sent."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = self.completions = self

    def with_options(self, **_):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0) if self.replies else "Happy to help."
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r, tool_calls=None))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


class NoModel:
    def __getattr__(self, _):
        raise AssertionError("this answer must be written by code, without a model call")


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    shop.seed(force=True)
    sample.build()          # the shop's own sample lessons L-S1 (outside the US) and L-S2 (returns, packaging)


def ask(text, visitor="v1", history=()):
    return shopper.run(list(history) + [{"role": "user", "content": text}], visitor)


def test_the_sample_lessons_are_read_as_situation_and_instruction():
    when, do = shop.split_lesson(next(n["note"] for n in shop.coaching() if n["id"] == "L-S1"))
    assert "outside the US" in when and do.startswith("say Lena ships")
    when2, _ = shop.split_lesson(next(n["note"] for n in shop.coaching() if n["id"] == "L-S2"))
    assert shop.topics(when2) == {"returns", "packaging"}


def test_lena_lesson_changes_the_canada_answer_and_pausing_it_changes_it_back(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask("Do you ship to Canada?")
    assert "US only" in r["reply"] and "Alaska and Hawaii" in r["reply"]
    assert "leave your email" in r["reply"] and r["lessons"] == ["L-S1"] and r["usd"] == 0
    assert any(s["tool"] == "lesson" and "outside the US" in s["result"] for s in r["steps"])   # visible in the chat
    assert shop.set_coaching("L-S1", False, admin=True)          # Lena pauses her lesson
    r2 = ask("Do you ship to Canada?")
    assert "US only" in r2["reply"] and "email" not in r2["reply"] and r2["lessons"] == []


def test_russian_outside_us_question_is_answered_in_russian(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    r = ask("А в Канаду доставляете?")
    assert "только по США" in r["reply"] and "почту" in r["reply"]


def test_a_us_place_is_not_mistaken_for_abroad():
    assert not shopper._outside_us("Do you ship to Texas?")
    assert not shopper._outside_us("Can you send the yellow German coupe to Austin?")
    assert shopper._outside_us("do you deliver internationally? I'm in Toronto, Canada")


def test_the_email_left_after_the_offer_reaches_lena(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())
    first = ask("Do you ship to Canada?")
    h = [{"role": "user", "content": "Do you ship to Canada?"}, {"role": "assistant", "content": first["reply"]}]
    r = ask("sure, jane.doe@example.com", history=h)
    assert "Lena has your email" in r["reply"]
    kept = [x for x in shop.requests_() if x["kind"] == "notify"]
    assert kept and kept[0]["contact"]["email"] == "jane.doe@example.com" and "Canada" in kept[0]["about"]
    shown = TestClient(web.app).get("/api/maker/requests").json()
    assert "jane.doe@" not in str(shown) and any(x["kind"] == "notify" for x in shown)   # masked on the public page


def test_a_lesson_holds_when_the_model_ignores_it(monkeypatch):
    fake = FakeModel("Our cars are 1:43 resin replicas with brass trim.")
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    r = ask("Do you take returns?")
    assert "Lena will answer that personally" in r["reply"] and "phone" in r["reply"] and r["lessons"] == ["L-S2"]
    assert "Lena wrote a lesson for exactly this kind of question" in fake.calls[0]["messages"][-1]["content"]


def test_a_lesson_answers_even_when_the_model_runs_out_of_time(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel(TimeoutError("slow host")))
    r = ask("Do you take returns?")
    assert "didn't catch that" not in r["reply"] and "Lena will answer that personally" in r["reply"]


def test_a_lesson_that_does_not_apply_leaves_the_answer_alone(monkeypatch):
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel("They're all 1:43, about 10 to 11 cm long."))
    r = ask("What scale are your cars?")
    assert r["reply"].startswith("They're all 1:43") and r["lessons"] == []


def test_a_visitors_own_lesson_applies_to_that_visitor_only_and_old_lessons_still_count(monkeypatch):
    shop.add_coaching("", "When someone asks about the dust cover, say every car comes with a fitted acrylic dust "
                          "cover.", visitor="aaa")
    assert [n["visitor"] for n in shop.lessons_matching("Does it come with a dust cover?", "aaa")] == ["aaa"]
    assert shop.lessons_matching("Does it come with a dust cover?", "bbb") == []
    for i in range(15):   # more of Lena's lessons than fit in the prompt: the old sample one is still checked
        shop.add_coaching("", f"Always mention plinth number {i}.")
    assert [n["id"] for n in shop.lessons_matching("Do you ship to Canada?", "bbb")] == ["L-S1"]
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel("Yes, it ships on a black wood plinth."))
    r = ask("Does it come with a dust cover?", visitor="aaa")
    assert "Every car comes with a fitted acrylic dust cover." in r["reply"]


def test_when_the_model_host_fails_the_answer_is_the_shelf_never_send_it_again(monkeypatch):
    from evals import run_evals as ev
    monkeypatch.setattr(shopper, "_client_", lambda: FakeModel(TimeoutError("slow host")))
    r = ask("hmm, what would you recommend for my dad?")
    have = [x for x in shop.shop()["listings"] if x["stock"] > 0]
    assert have and have[0]["title"] in r["reply"] and "$6.50" in r["reply"] and "which state" in r["reply"]
    assert not ev.NON_ANSWER.search(r["reply"])
    ru = shopper._fallback_reply([], True, "хм, что посоветуете?")
    assert "в наличии" in ru and not ev.NON_ANSWER.search(ru)


def test_the_last_resort_says_so_when_the_shelf_is_empty():
    for x in shop.shop()["listings"]:
        shop.take_stock(x["id"], x["stock"])
    said = shopper._fallback_reply([], False, "anything nice?")
    assert said.startswith("The shelf is empty right now.") and "to order" in said and "send it" not in said


def test_a_reply_made_only_of_stalling_or_notes_to_itself_is_written_by_code(monkeypatch):
    # live run 31 Oct: "Let me fetch the current checkout details…" and "…so I can call start_checkout." reached the
    # shopper, because when the filter removed every sentence the original came back whole
    for words in ("Let me fetch the current checkout details for 3 Red American Convertibles to CA.",
                  "We need the checkout created to get the exact total and dates. Please provide your full name, phone "
                  "number, email, street address, city, and ZIP code so I can call start_checkout."):
        monkeypatch.setattr(shopper, "_client_", lambda: FakeModel(*[words] * 12))
        out = shopper.run([{"role": "user", "content": "Model 65, California"}])
        assert out["reply"].strip()
        assert not out["reply"].lower().startswith("let me")
        assert "start_checkout" not in out["reply"] and "we need the checkout" not in out["reply"].lower()
        assert "Red American Convertible, 1965" in out["reply"] and "$65.50" in out["reply"]   # the one car "65" means


def test_drafted_lessons_in_the_forms_the_assistant_writes_are_understood():
    # 1.11: a drafted "When asked about payment methods, clearly state ..." was never matched, so a lesson Lena
    # accepted from the studio would silently do nothing. Adverb + state/confirm verbs and plain "payment" now count.
    from opencounter import shop
    for note, hit, miss in [
        ("When asked about payment methods, clearly state that PayPal is accepted.", "Can I pay with a credit card?", "Do you ship to Ohio?"),
        ("If someone asks about returns, confirm unopened cars come back within 14 days.", "Do you take returns?", "How much is the red one?"),
        ("If a shopper asks about gift wrapping, politely say Lena wraps every car in tissue.", "Can you gift wrap it?", "Is it in stock?"),
    ]:
        assert shop.split_lesson(note)[0], note
        assert shop.lesson_matches(note, hit), (note, hit)
        assert not shop.lesson_matches(note, miss), (note, miss)


def test_a_build_spec_spread_over_two_messages_is_not_turned_into_a_shelf_car(monkeypatch):
    # live check 3 Nov (judge step 1): "A grey fastback … brown inside, two of them." → "what year?" → "It is a 1967.
    # Alex Doe …" got "We have the Highland Blue Fastback, 1967 in stock", because each message alone isn't a full
    # build spec and a bare 1967 matches one shelf car. Read together they are a build.
    fake = FakeModel(*["Two grey fastbacks, made to order."] * 12)
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    history = [{"role": "user", "content": "A grey fastback with two black stripes, brown inside, two of them."},
               {"role": "assistant", "content": "Which year is the real car?"}]
    shopper.run(history + [{"role": "user", "content": "It is a 1967. Alex Doe, 512-555-0100, alex@example.com, "
                                                       "12 Oak St, Austin TX 78701."}])
    sent = " ".join(m.get("content") or "" for c in fake.calls for m in c["messages"] if m["role"] == "system")
    assert "The person means" not in sent and "only car on the shelf" not in sent   # no shelf-car hint


def test_once_the_order_exists_the_reply_stops_asking_for_details_and_says_ready_once():
    checkout = {"receipt": {"total": 184.50, "deposit": 92.25}}
    for model_text in ("Your order is ready! Let me know if you'd like any adjustments!",
                       "It's paid with a PayPal invoice. Send your first and last name, phone, email and address with "
                       "ZIP in one message, and I'll create it."):
        out = shopper._must_say(model_text, "It is a 1967. Alex Doe …", [], checkout, "")
        assert out.count("order is ready") <= 1, out
        assert "Send your" not in out and "I'll create it" not in out, out
        assert "$92.25 deposit" in out, out


def test_an_order_is_shown_again_only_to_the_visitor_it_was_made_for(monkeypatch):
    # live check 3 Nov: two separate chats with the same words and ZIP got the same invoice, and with it the first
    # person's name and address. The "show it again" shortcut must stay inside one visitor's chats.
    theirs = {"id": "OC-1", "kind": "commission", "status": "awaiting_approval", "approve_url": "https://x/inv",
              "asked_for": "two grey fastbacks", "qty": 2, "visitor": "v-first",
              "customer": {"postal_code": "78701", "full_name": "Alex Doe", "phone": "512-555-0100", "email": "a@x.com"},
              "quote": {"total_cars": 2, "unit_usd": 80, "build_weeks": 1, "delivery": {"ships_on": "Wednesday"}},
              "title": "Grey Fastback", "total_usd": 184.5}
    monkeypatch.setattr(shop, "orders", lambda: [theirs])
    monkeypatch.setattr(shopper.counter, "_ship_to", lambda o: "Alex Doe, 12 Oak St")
    monkeypatch.setattr(shopper.counter, "receipt", lambda o: {})
    made = []
    monkeypatch.setattr(shopper.counter, "start_commission_checkout",
                        lambda *a, **k: made.append(k.get("customer") or {}) or {"ok": True, "order_id": "OC-NEW"})
    typed = "two grey fastbacks / Bea Roe, 512-555-0199, b@y.com, 5 Elm St, Austin TX 78701"
    for who, expect in (("v-second", "OC-NEW"), ("v-first", "OC-1")):
        shopper._VISITOR.set(who)
        args = {"cars": [{"model": "fastback", "year": "1967", "body_colour": "grey", "interior_colour": "brown",
                          "quantity": 2}], "us_state": "TX", "name": "Bea Roe", "phone": "512-555-0199",
                "customer": {"postal_code": "78701", "email": "b@y.com", "address_line_1": "5 Elm St", "city": "Austin"}}
        out = shopper._call_tool("start_commission_checkout", args, "two grey fastbacks", typed)
        assert out["order_id"] == expect, (who, out)
    # the second visitor's new order must not be filled with the first person's name, phone or email
    assert made and not any(v in ("Alex Doe", "512-555-0100", "a@x.com") for v in made[0].values()), made
