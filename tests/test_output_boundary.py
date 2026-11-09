"""Words written for the agent never reach the shopper (live check 08.11 P0-2): the step line "preparing PayPal
checkout · Before quoting, ask for the year…" and a reply with "us_state TX" were shown in the chat."""
import json
from types import SimpleNamespace

import pytest

from opencounter import sample, shop, shopper


def tool_call(name, args, i=1):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=f"call-{i}", function=fn,
                           model_dump=lambda: {"id": f"call-{i}", "type": "function",
                                               "function": {"name": name, "arguments": json.dumps(args)}})


class ScriptedModel:
    """Each reply is text or a list of tool calls, in order."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = self.completions = self

    def with_options(self, **_):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0) if self.replies else "Happy to help."
        msg = (SimpleNamespace(content="", tool_calls=r) if isinstance(r, list)
               else SimpleNamespace(content=r, tool_calls=None))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(shopper.counter.paypal, "configured", lambda: True)
    shop.seed(force=True)
    sample.build()


def test_a_tools_instruction_to_the_agent_is_rewritten_in_the_step_list_and_cut_from_the_reply(monkeypatch):
    no_year = {"cars": [{"model": "fastback", "year": "", "body_colour": "grey", "interior_colour": "brown",
                         "quantity": 2}], "us_state": "TX", "name": "Judge Test", "phone": "512-555-0142",
               "customer": {"full_name": "Judge Test", "phone": "512-555-0142", "email": "judge.test@example.com",
                            "address_line_1": "100 Congress Ave", "city": "Austin", "state": "TX", "postal_code": "78701"}}
    model = ScriptedModel([tool_call("start_commission_checkout", no_year)],
                          "Before quoting, ask for the year of the real car it's modelled on. Which year is the real car?")
    monkeypatch.setattr(shopper, "_client_", lambda: model)
    r = shopper.run([{"role": "user", "content": "Grey, brown inside, two. Judge Test, 512-555-0142, "
                                                 "judge.test@example.com, 100 Congress Ave, Austin, TX 78701"}], "v-notes")
    shown = " ".join(s["label"] + " · " + s["result"] for s in r["steps"])
    assert "Before quoting" not in shown and "still needed: the year of the real car" in shown, shown
    assert "Before quoting" not in r["reply"] and "Which year is the real car?" in r["reply"], r["reply"]
    assert "Before quoting, ask for the year" in r["memo"]        # the agent's own memo keeps the tool's words


def test_raw_field_names_and_notes_to_itself_are_cut():
    said = ("Made to order, 2 cars: $184.50 with shipping. I have all details: cars (2×1967 Grey Fastback), us_state TX, "
            "name Judge Test. Let's create the commission checkout.")
    assert shopper._for_shopper(said) == "Made to order, 2 cars: $184.50 with shipping."
    assert shopper._for_shopper("I missed asking—what year should it be?") == ""
    assert shopper._for_shopper("Write to judge_test@example.com? Sure.") == "Write to judge_test@example.com? Sure."
    assert shopper._note_for_shopper("ZIP 94105 is in CA, not CO. Ask the person which address is right; don't change "
                                     "it yourself.") == "ZIP 94105 is in CA, not CO. Which address is right?"


def test_a_reply_made_only_of_notes_is_replaced_by_a_real_answer(monkeypatch):
    model = ScriptedModel(*["I have all details: us_state TX, item_id sg-014."] * 12)
    monkeypatch.setattr(shopper, "_client_", lambda: model)
    r = shopper.run([{"role": "user", "content": "what do you have?"}], "v-notes")
    assert r["reply"] and "us_state" not in r["reply"] and "item_id" not in r["reply"]
    assert "On the shelf right now" in r["reply"]


def test_a_build_stopped_for_the_year_asks_the_year_not_the_contacts(monkeypatch):
    # live eval 08.11 ("stock: over the stock goes to made to order"): the model priced 40 green fastbacks as a build
    # without a year, the shop said "still needed: the year", and the model asked for the interior and the contacts
    no_year = {"cars": [{"model": "fastback", "year": "", "body_colour": "green", "interior_colour": "", "quantity": 40}],
               "us_state": "TX"}
    model = ScriptedModel([tool_call("quote_commission", no_year)],
                          "Please provide interior color, full name, phone, email, street address, city, and ZIP code "
                          "in one message.")
    monkeypatch.setattr(shopper, "_client_", lambda: model)
    r = shopper.run([{"role": "user", "content": "I need 40 green fastbacks to Texas"}], "v-forty")
    assert "Which year is the real car" in r["reply"] and "build that to order: 40 × fastback, green body" in r["reply"]
    assert "phone" not in r["reply"] and not r["checkout"] and not [o for o in shop.orders() if not o.get("sample")]


def test_when_the_model_runs_out_the_code_answer_still_asks_the_year_first(monkeypatch):
    no_year = {"cars": [{"model": "fastback", "year": "", "body_colour": "green", "interior_colour": "", "quantity": 40}],
               "us_state": "TX"}
    model = ScriptedModel(*[[tool_call("quote_commission", no_year, i)] for i in range(1, 9)])   # never answers
    monkeypatch.setattr(shopper, "_client_", lambda: model)
    r = shopper.run([{"role": "user", "content": "I need 40 green fastbacks to Texas"}], "v-forty2")
    assert "Which year is the real car" in r["reply"] and "phone" not in r["reply"]
