"""The studio's model adapter on the server (opencounter/studio_llm.py), with the model stubbed: AG Studio's items
become chat messages, and a turn that only announces its next step is asked once more with a tool call required
(final AG judge 08.11 P1-1: "Now I'll place the widget:" and then nothing)."""
from types import SimpleNamespace as NS

import pytest

from opencounter import shop, shopper, studio_llm


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.chat = NS(completions=NS(create=self.create))

    def with_options(self, **_):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        text, calls = self.answers.pop(0)
        tc = [NS(id=f"c{i}", function=NS(name=n, arguments=a)) for i, (n, a) in enumerate(calls)]
        return NS(usage=NS(prompt_tokens=100, completion_tokens=10),
                  choices=[NS(message=NS(content=text, tool_calls=tc or None), finish_reason="tool_calls" if tc else "stop")])


REQ = {"instructions": "You are the page agent.",
       "input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "Add a stuck panel"}]}],
       "tools": [{"name": "add_widget", "description": "Add a widget", "parameters": {"type": "object", "properties": {}}}]}


def use(monkeypatch, answers):
    fc = FakeClient(answers)
    monkeypatch.setattr(shopper, "_client_", lambda: fc)
    return fc


def test_a_turn_that_only_announces_a_tool_call_is_asked_once_more(monkeypatch):
    fc = use(monkeypatch, [("Now I'll place the agent-stuck widget next to the chart:", []),
                           ("", [("add_widget", '{"type": "agent-stuck"}')])])
    out = studio_llm.turn(REQ)
    assert [c["name"] for c in out["tool_calls"]] == ["add_widget"]
    assert len(fc.calls) == 2 and fc.calls[1]["tool_choice"] == "required"
    assert fc.calls[1]["messages"][-1] == {"role": "user", "content": studio_llm.CONTINUE}
    assert fc.calls[1]["messages"][-2]["content"].startswith("Now I'll place")
    assert out["usage"] == {"inputTokens": 200, "outputTokens": 20}


@pytest.mark.parametrize("text", ["The panel is on your page: 3 of 5 chats followed the Canada lesson.",
                                  "Done. Let me know if you want it wider."])
def test_a_finished_answer_is_not_asked_again(monkeypatch, text):
    fc = use(monkeypatch, [(text, [])])
    assert studio_llm.turn(REQ)["text"] == text and len(fc.calls) == 1


def test_no_retry_without_tools_or_when_the_retry_brings_nothing(monkeypatch):
    fc = use(monkeypatch, [("Let me check that:", [])])
    assert studio_llm.turn({**REQ, "tools": []})["tool_calls"] == [] and len(fc.calls) == 1
    fc = use(monkeypatch, [("I'll add it now.", []), ("Sorry.", [])])
    out = studio_llm.turn(REQ)
    assert out["text"] == "I'll add it now." and out["tool_calls"] == [] and len(fc.calls) == 2


def test_studio_items_become_chat_messages_and_provided_tools_are_dropped():
    req = {"instructions": "sys", "toolChoice": {"name": "add_widget"},
           "input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "hi"}]},
                     {"type": "function_call", "callId": "a", "name": "view_page", "arguments": "{}"},
                     {"type": "function_call", "callId": "b", "name": "view_schema", "arguments": "{}"},
                     {"type": "function_call_output", "callId": "a", "output": "page"},
                     {"type": "function_call_output", "callId": "b", "output": "schema"},
                     {"type": "reasoning", "content": "secret thoughts"}],
           "tools": [{"name": "add_widget"}, {"name": "web_search", "kind": "provided"}]}
    m = studio_llm.to_messages(req)
    assert [x["role"] for x in m] == ["system", "user", "assistant", "tool", "tool"]
    assert [c["id"] for c in m[2]["tool_calls"]] == ["a", "b"]        # consecutive calls in one assistant message
    assert [t["function"]["name"] for t in studio_llm.to_tools(req)] == ["add_widget"]
    assert studio_llm.to_tool_choice(req) == {"type": "function", "function": {"name": "add_widget"}}
