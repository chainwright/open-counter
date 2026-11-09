"""/api/studio/llm takes only Studio's own turns (judge panel 09.11, seat 04 F-01: it passed any visitor's prompt and
tools to the model). Refused before any model call or budget: no visitor header, a foreign tool, an oversized turn,
too many turns a minute from one network. The model is a fake that fails the test if it is ever called."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencounter import shop, shopper, studio_llm, web

ROOT = Path(__file__).resolve().parent.parent
TURN = {"instructions": "You are the lead agent.",
        "input": [{"type": "message", "role": "user", "content": [{"type": "text", "text": "Where did my agent get stuck?"}]}],
        "tools": [{"name": "view_page", "description": "View the page", "parameters": {"type": "object", "properties": {}}},
                  {"name": "delegate_to", "description": "Delegate", "parameters": {"type": "object", "properties": {}}}]}
H = {"x-visitor": "qa-guard"}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(shopper, "_spent_by", {})
    monkeypatch.setattr(web, "_studio_hits", {})
    shop.seed(force=True)


@pytest.fixture
def no_model(monkeypatch):
    calls = []
    monkeypatch.setattr(shopper, "_client_", lambda: calls.append(1) or (_ for _ in ()).throw(AssertionError("model called")))
    return calls


@pytest.fixture
def stub_turn(monkeypatch):
    seen = []
    monkeypatch.setattr(studio_llm, "turn", lambda req, who=(): seen.append(req) or {"text": "ok", "tool_calls": [], "model": "stub"})
    return seen


def post(c, body, headers=H):
    return c.post("/api/studio/llm", content=json.dumps(body), headers={"content-type": "application/json", **headers})


def test_a_studio_turn_with_its_own_tools_gets_through(stub_turn):
    r = post(TestClient(web.app), TURN)
    assert r.status_code == 200 and len(stub_turn) == 1


@pytest.mark.parametrize("bad", [
    {"tools": TURN["tools"] + [{"name": "write_my_essay", "parameters": {}}]},
    {"toolChoice": {"name": "send_email"}},
    {"input": TURN["input"] + [{"type": "function_call", "callId": "x", "name": "shell", "arguments": "{}"}]}])
def test_a_foreign_tool_is_refused_before_the_model(no_model, bad):
    r = post(TestClient(web.app), {**TURN, **bad})
    assert r.status_code == 403 and "studio's own tools" in r.json()["error"] and not no_model
    with pytest.raises(studio_llm.Refused):
        studio_llm.turn({**TURN, **bad})   # the same rule when the function is called directly
    assert not no_model


def test_studio_provided_tools_are_not_forwarded_and_not_refused():
    req = {**TURN, "tools": TURN["tools"] + [{"name": "web_search", "kind": "provided"}]}
    studio_llm.check(req)
    assert [t["function"]["name"] for t in studio_llm.to_tools(req)] == ["view_page", "delegate_to"]


def test_an_oversized_prompt_is_refused(no_model):
    big = {**TURN, "instructions": "x" * (studio_llm.MAX_REQUEST_BYTES + 10)}
    r = post(TestClient(web.app), big)
    assert r.status_code == 413 and not no_model
    with pytest.raises(studio_llm.Refused):
        studio_llm.check({**TURN, "input": [{"type": "message", "role": "user",
                                             "content": [{"type": "text", "text": "y" * studio_llm.MAX_REQUEST_BYTES}]}]})


@pytest.mark.parametrize("headers", [{}, {"x-visitor": ""}, {"x-visitor": "!!!"}])
def test_no_visitor_header_is_refused(no_model, headers):
    r = post(TestClient(web.app), TURN, headers=headers)
    assert r.status_code == 400 and not no_model


def test_not_json_or_not_an_object_is_refused(no_model):
    c = TestClient(web.app)
    assert c.post("/api/studio/llm", content=b"{nope", headers=H).status_code == 400
    assert post(c, ["a", "list"]).status_code == 400 and not no_model


def test_the_rate_limit_hits_per_network_per_minute(stub_turn, monkeypatch):
    monkeypatch.setattr(web, "STUDIO_TURNS_PER_MIN", 3)
    c = TestClient(web.app)
    codes = [post(c, TURN, {"x-visitor": f"v{i}"}).status_code for i in range(5)]   # new browser ids don't help
    assert codes == [200, 200, 200, 429, 429] and len(stub_turn) == 3
    assert web._studio_rate_ok("203.0.113.9")   # another network has its own minute
    assert web._studio_rate_ok("testclient", now=__import__("time").time() + 61)   # and the minute passes


def test_the_daily_cap_still_applies_after_the_guard(no_model):
    shopper.add_spend(shopper.STUDIO_CAP_USD, ["pool:studio"])
    r = post(TestClient(web.app), TURN)
    assert r.status_code == 429 and "studio" in r.json()["error"] and not no_model


def test_the_allowlist_covers_every_tool_ag_studio_and_our_harness_define():
    """Guards against an AG Studio upgrade (or a new analyst tool) the allowlist doesn't know about."""
    harness = (ROOT / "studio/src/harness.ts").read_text()
    ours = set(re.findall(r"name: '([a-z_]+)'", harness))
    assert ours and ours <= studio_llm.STUDIO_TOOLS
    bundle = ROOT / "studio/node_modules/ag-studio/dist/package/main.esm.mjs"
    if not bundle.exists():
        pytest.skip("studio dependencies not installed (cd studio && npm ci)")
    src = bundle.read_text()
    names = set(re.findall(r'(?:defineAiTool|defineDirectTool)\(\{\s*name: "([a-z_]+)"', src))
    names |= set(re.findall(r'var [A-Z_0-9]+_TOOL\d* = "([a-z_]+)"', src))
    assert len(names) >= 20 and names <= studio_llm.STUDIO_TOOLS, names - studio_llm.STUDIO_TOOLS
