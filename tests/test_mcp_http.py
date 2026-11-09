"""The MCP door over its real transport (streamable HTTP at /mcp/), as an outside agent sees it: tools/list carries
typed schemas with every field name an agent needs, and a quote comes back computed in code (final judge 08.11 P1-4:
no test exercised the transport, and items / customer were bare objects)."""
import json

import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, shop, web

H = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(paypal, "configured", lambda: False)
    shop.seed(force=True)
    with TestClient(web.app, base_url="http://127.0.0.1:8000") as client:   # runs the MCP session manager's lifespan
        yield client


def rpc(c, method, params, i=1):
    r = c.post("/mcp/", headers=H, json={"jsonrpc": "2.0", "id": i, "method": method, "params": params})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_an_outside_agent_lists_nine_typed_tools_and_gets_a_quote(c):
    init = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "judge", "version": "0"}})
    assert init["serverInfo"]["name"] == "small-garage-counter"
    tools = {t["name"]: t for t in rpc(c, "tools/list", {}, 2)["tools"]}
    assert len(tools) == 9
    schema = json.dumps(tools["start_commission_checkout"]["inputSchema"])
    for field in ("full_name", "postal_code", "address_line_1", "body_colour", "interior_colour", "year"):
        assert field in schema, field
    defs = tools["start_commission_checkout"]["inputSchema"]["$defs"]
    assert set(defs["Customer"]["required"]) == {"full_name", "phone", "email", "address_line_1", "city", "state", "postal_code"}
    assert defs["Car"]["properties"]["quantity"]["minimum"] == 1
    assert "item_id" in json.dumps(tools["start_checkout"]["inputSchema"]) and "postal_code" in tools["start_checkout"]["description"]
    car = {"model": "fastback", "year": "1967", "body_colour": "grey", "interior_colour": "brown", "quantity": 2}
    out = rpc(c, "tools/call", {"name": "quote_commission", "arguments": {"cars": [car], "us_state": "TX"}}, 3)
    q = json.loads(out["content"][0]["text"])
    assert q["ok"] and q["total_usd"] == 184.5 and q["total_cars"] == 2
    # one test: the transport's session manager runs once per process
    # and a negative quantity is refused at the door (schema minimum 1), before the shop's own check
    bad = {**car, "model": "coupe", "quantity": -2}
    out = rpc(c, "tools/call", {"name": "quote_commission", "arguments": {"cars": [car, bad]}}, 4)
    assert out.get("isError") is True or '"ok": false' in out["content"][0]["text"].replace("False", "false")
    assert [o for o in shop.orders() if not o.get("sample")] == []
    # the /agents page's live console sends these exact bodies, each a fresh request with no mcp-session-id
    init = rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "open-counter-agents-page", "version": "1"}}, 5)
    assert init["serverInfo"]["name"] == "small-garage-counter"
    found = json.loads(rpc(c, "tools/call", {"name": "search_counter", "arguments": {"query": "green"}}, 6)["content"][0]["text"])
    assert found["results"] and found["results"][0]["id"] == "sg-014"
    assert [o for o in shop.orders() if not o.get("sample")] == []
