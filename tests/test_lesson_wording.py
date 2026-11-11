"""A model-drafted lesson reaches the shopper only as words meant for the shopper.

Live takes of the judge's "Try it" step 1 (10.11, PRESUBMIT_LOG): the drafted lesson's wording was put in front of the
code-written payment answer, so the reply opened with "Lena accepts payments … and you cannot process direct credit
card payments outside of PayPal" (a remark to the agent that reads like a refusal), and another draft named a tool
("offer to have Lena contact them via leave_contact"). The studio row must still tick: the lesson is applied."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from opencounter import assistant, sample, shop, shopper, web
from tests.test_lessons import NoModel

Q = "Can I pay with a credit card?"            # word for word from the Devpost "Try it" step 1
REFUSAL = ("If someone asks about paying with a credit card instead of PayPal, say Lena accepts payments only through "
           "PayPal checkout, and you cannot process direct credit card payments outside of PayPal.")
TOOL_OFFER = ("If someone asks about paying with a credit card, say Lena takes cards inside PayPal's window, and offer "
              "to have Lena contact them via leave_contact.")
TOOL_SAY = ("If someone asks about paying with a credit card, say Lena takes cards inside PayPal's window and that Lena "
            "can call them back via leave_contact.")
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(shopper, "_spent_by", {})
    monkeypatch.setattr(shopper, "_client_", lambda: NoModel())   # the payment answer never calls a model
    shop.seed(force=True)
    sample.build()


def _teach_and_ask(note, visitor):
    """Step 1 through the web API: the open row → accept the lesson → ask the question → the row's numbers."""
    c, h = TestClient(web.app), {"x-visitor": visitor}
    row = next(r for r in c.get("/api/maker/agent_misses", headers=h).json()["open"]
               if "credit card instead of PayPal" in r["asked"])
    lesson = c.post("/api/maker/coach", json={"chat_id": row["chat"], "note": note}, headers=h).json()
    r = c.post("/api/shopper", json={"messages": [{"role": "user", "content": Q}], "conv_id": visitor + "-1"},
               headers=h).json()
    taught = next(t for t in c.get("/api/maker/agent_misses", headers=h).json()["taught"] if t["lesson"] == lesson["id"])
    return r, lesson, taught


def test_live_take_the_agent_remark_never_leads_or_reaches_the_shopper():
    r, lesson, taught = _teach_and_ask(REFUSAL, "qa-wording-1")
    reply = r["reply"]
    assert reply.startswith("Yes, a card works. Every order is paid through PayPal"), reply   # the shop's answer leads
    assert "cannot process" not in reply and "you cannot" not in reply.lower(), reply
    # what the lesson says for the shopper is carried, as its own sentence after the shop's answer, before the next step
    assert "without a PayPal account. Lena accepts payments only through PayPal checkout. Tell me which car" in reply
    assert r["lessons"] == [lesson["id"]] and r["checkout"] is None
    assert taught["followed"] == 1 and taught["missed"] == 0                                  # the tick still draws


@pytest.mark.parametrize("note", [TOOL_OFFER, TOOL_SAY])
def test_live_take_a_tool_name_in_the_lesson_never_reaches_the_shopper(note):
    r, lesson, taught = _teach_and_ask(note, "qa-wording-2")
    reply = r["reply"]
    assert not SNAKE.search(reply) and "leave_contact" not in reply and " via" not in reply, reply
    assert reply.startswith("Yes, a card works."), reply
    assert reply.endswith("I'll get the PayPal checkout ready."), reply
    assert r["lessons"] == [lesson["id"]]
    assert taught["followed"] == 1 and taught["missed"] == 0


def test_the_call_back_clause_reads_as_a_sentence_to_the_shopper():
    r, _, _ = _teach_and_ask(TOOL_SAY, "qa-wording-3")
    assert "Lena can call you back." in r["reply"] and "That Lena" not in r["reply"], r["reply"]


@pytest.mark.parametrize("say, want", [
    ("Lena accepts payments only through PayPal checkout, and you cannot process direct credit card payments outside of "
     "PayPal", ["Lena accepts payments only through PayPal checkout"]),
    ("Lena can call them back via leave_contact", ["Lena can call them back"]),
    ("Lena takes cards and that Lena can call them back using the leave_contact tool",
     ["Lena takes cards", "Lena can call them back"]),
    ("call leave_contact with their phone", []),
    ("we accept cards through PayPal checkout, and the buyer approves the order in PayPal",
     ["we accept cards through PayPal checkout", "the buyer approves the order in PayPal"]),
    ("you can pay by card in PayPal's window", ["you can pay by card in PayPal's window"]),   # a first clause stays
    ("Lena ships inside the US only for now", ["Lena ships inside the US only for now"]),
])
def test_lesson_says_keeps_only_the_shopper_facing_clauses(say, want):
    assert shopper.lesson_says(say) == want


def test_a_model_written_reply_keeps_its_old_order_but_drops_the_agent_remark():
    # the model path (not a code answer): what the lesson says still leads when the reply skipped it
    out = shopper._apply_lessons("It ships Monday.", [{"id": "L-1", "note": REFUSAL}], False)
    assert out == "Lena accepts payments only through PayPal checkout. It ships Monday."


def test_the_sample_lessons_still_apply_as_before():
    l1 = next(n for n in shop.coaching() if n["id"] == "L-S1")
    out = shopper._apply_lessons("", [l1], False)
    assert out.startswith("Lena ships inside the US only for now.") and shopper.EMAIL_OFFER in out


def test_a_drafted_lesson_loses_its_tool_names_before_lena_sees_it():
    assert assistant.tidy_lesson(TOOL_OFFER) == ("If someone asks about paying with a credit card, say Lena takes cards "
                                                 "inside PayPal's window, and offer to have Lena contact them.")
    assert assistant.tidy_lesson('"If someone asks about X, say Y."') == "If someone asks about X, say Y."
    assert assistant.tidy_lesson(REFUSAL) == REFUSAL                 # nothing to cut: left as the model wrote it
    assert "tool or function names" in assistant.LESSON_SYSTEM and "no \"you\"" in assistant.LESSON_SYSTEM


def test_the_streamed_draft_finishes_without_the_tool_name(monkeypatch):
    chat = shop.conversations()[0]["id"]
    monkeypatch.setattr(assistant, "draft_stream", lambda cid, who=(): iter([TOOL_OFFER[:60], TOOL_OFFER[60:]]))
    body = TestClient(web.app).post("/api/maker/agent_misses/draft_stream", json={"chat": chat},
                                    headers={"x-visitor": "qa-wording-4"}).text
    done = next(json.loads(x[6:]) for x in body.split("\n\n") if '"RUN_FINISHED"' in x)
    assert "leave_contact" not in done["lesson"] and done["usable"] is True
