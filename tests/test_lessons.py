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
