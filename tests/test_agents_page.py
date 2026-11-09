"""/agents: the MCP door made visible. The page serves, its console sends only read-only MCP calls, those exact calls
work on the real transport without a session (test_mcp_http), and the recorded run it replays is the logged one (README), labelled as
recorded, not live."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, shop, web

ROOT = shop.ROOT
JS = (ROOT / "web" / "static" / "agents.js").read_text()
RUN = json.loads((ROOT / "web" / "static" / "agents_run.json").read_text())


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(paypal, "configured", lambda: False)
    shop.seed(force=True)
    yield TestClient(web.app, base_url="http://127.0.0.1:8000")   # no lifespan: the MCP transport is tested in test_mcp_http


def test_the_page_serves_the_address_snippets_console_and_replay(c):
    r = c.get("/agents")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    html = r.text
    assert "https://open-counter.onrender.com/mcp/" in html and html.count('class="copy"') >= 4
    assert "claude_desktop_config.json" in html and "@modelcontextprotocol/inspector --cli" in html
    assert re.search(r'/static/agents\.js\?v=\d+"', html)          # stamped, so phones never keep an old copy
    for call in ("initialize", "tools/list", "search_counter"):
        assert f'data-call="{call}"' in html
    assert 'id="replay"' in html and "NOT LIVE" in html


def test_the_console_can_only_send_read_only_calls():
    allowed = re.search(r"READ_ONLY = \{([^}]*)\}", JS).group(1)
    assert sorted(re.findall(r'"([^"]+)"', allowed)) == ["initialize", "search_counter", "tools/list"]
    for tool in ("start_checkout", "start_commission_checkout", "leave_contact", "quote_commission"):
        assert tool not in JS
    assert JS.count('fetch("/mcp/"') == 1


def test_the_replay_is_the_logged_run_and_says_it_is_recorded():
    assert "sandbox" in RUN["label"] and "not live" in RUN["label"] and "Recorded on" in RUN["label"]
    steps = [s["step"] for s in RUN["steps"]]
    assert steps[:4] == ["tools/list", "search_counter", "delivery_estimate", "start_checkout"] and steps[-1] == "order_status"
    co = json.loads(RUN["steps"][3]["response"]["content"][0]["text"])
    res = RUN["result"]
    assert co["order_id"] == res["order_id"] and res["paypal_order_id"] in co["approve_url"]
    paypal_rec = next(s for s in RUN["steps"] if s["kind"] == "paypal")["response"]
    assert paypal_rec["capture_id"] == res["capture_id"] and paypal_rec["capture_status"] == "COMPLETED"
    assert json.loads(RUN["steps"][-1]["response"]["content"][0]["text"])["status"] == "paid"
    readme = (ROOT / "README.md").read_text()
    for k in ("order_id", "paypal_order_id", "capture_id"):
        assert res[k] in readme, k
    blob = json.dumps(RUN).lower()
    assert "password" not in blob and "bearer" not in blob and not re.search(r'"(qa|qa-)[\w-]*"', blob)


def test_the_home_page_footer_links_the_agents_page(c):
    assert 'href="/agents"' in c.get("/").text


CLAUDE_RUN = json.loads((ROOT / "web" / "static" / "agents_run_claude.json").read_text())
RUN_DIR = ROOT / "docs" / "runs" / "2026-11-09-claude-code-mcp-purchase"


def test_the_ai_agent_replay_is_its_transcript_and_says_who_chose_and_who_approved():
    """Every call in the replay is a tool call the model made in the committed transcript, with the same arguments and
    answer; the only tools the agent had were this MCP server's; the labels say a model chose and a script approved."""
    calls, answers = [], {}
    for t in ("turn1", "turn2"):
        for line in (RUN_DIR / f"{t}.jsonl").read_text().splitlines():
            e = json.loads(line)
            if e.get("type") == "system" and e.get("subtype") == "init":
                assert e["tools"] and all(x.startswith("mcp__open-counter__") for x in e["tools"])   # no built-in tools
                assert [m["name"] for m in e["mcp_servers"]] == ["open-counter"]
            if e.get("type") == "assistant":
                calls += [c for c in e["message"]["content"] if c["type"] == "tool_use"]
            if e.get("type") == "user":
                answers.update({c["tool_use_id"]: c["content"][0]["text"] for c in e["message"]["content"]
                                if isinstance(c, dict) and c.get("type") == "tool_result"})
    replay = [s for s in CLAUDE_RUN["steps"] if s["kind"] == "agent_mcp"]
    assert [s["step"] for s in replay] == [c["name"].split("__")[-1] for c in calls]
    assert [s["step"] for s in replay] == ["search_counter", "delivery_estimate", "start_checkout", "order_status"]
    for s, c in zip(replay, calls):
        assert json.dumps(c["input"], ensure_ascii=False) in s["command"] and s["response"]["content"][0]["text"] == answers[c["id"]]
    res = CLAUDE_RUN["result"]
    co = json.loads(replay[2]["response"]["content"][0]["text"])
    assert co["order_id"] == res["order_id"] and res["paypal_order_id"] in co["approve_url"]
    assert json.loads(replay[-1]["response"]["content"][0]["text"])["status"] == "paid"
    rec = json.loads((RUN_DIR / "paypal_order.json").read_text())
    assert rec["capture_id"] == res["capture_id"] and rec["capture_status"] == "COMPLETED" and rec["custom_id"] == res["order_id"]
    assert "chose the calls" in CLAUDE_RUN["honesty"] and "scripted sandbox buyer login" in CLAUDE_RUN["honesty"]
    assert next(s for s in CLAUDE_RUN["steps"] if s["kind"] == "person")["who"].startswith("a scripted login")
    readme = (ROOT / "README.md").read_text()
    for k in ("order_id", "paypal_order_id", "capture_id"):
        assert res[k] in readme, k
    assert "chose the calls; approval was a scripted sandbox buyer login" in readme
    blob = "".join(p.read_text() for p in RUN_DIR.iterdir()).lower() + json.dumps(CLAUDE_RUN).lower()
    assert "/users/" not in blob and "password" not in blob and "bearer" not in blob and "sb-" not in blob
    assert "agents_run_claude.json" in JS and 'data-run="agents_run_claude.json"' in (ROOT / "web" / "agents.html").read_text()
