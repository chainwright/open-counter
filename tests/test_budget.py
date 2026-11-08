"""Each browser and each network gets its own share of the day's AI budget, so one burst can't lock every judge
out; the shop's own daily cap is unchanged (judge 29.10, N9). The model is a fake: nothing is paid for."""
import pytest
from fastapi.testclient import TestClient

from opencounter import sample, shop, shopper, web
from test_lessons import FakeModel


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shopper, "_spent", {})
    monkeypatch.setattr(shopper, "_spent_by", {})
    shop.seed(force=True)


def test_the_shops_daily_cap_is_not_raised():
    assert shopper.DAILY_CAP_USD == 1.0 and shopper.VISITOR_CAP_USD < shopper.IP_CAP_USD < shopper.DAILY_CAP_USD


def test_one_visitors_share_runs_out_without_touching_anyone_else():
    shopper.add_spend(shopper.VISITOR_CAP_USD, ["v:burst", "ip:1.2.3.4"])
    with pytest.raises(shopper.OverBudget) as e:
        shopper.check_budget(["v:burst", "ip:1.2.3.4"])
    assert e.value.mine and "this browser's share" in str(e.value)
    shopper.check_budget(["v:judge", "ip:5.6.7.8"])          # another judge is untouched
    assert shopper.spent_today() < shopper.DAILY_CAP_USD


def test_a_bot_switching_browser_ids_still_hits_its_networks_share():
    for i in range(int(shopper.IP_CAP_USD / 0.05) + 1):
        shopper.add_spend(0.05, [f"v:bot{i}", "ip:9.9.9.9"])
    with pytest.raises(shopper.OverBudget):
        shopper.check_budget(["v:fresh-id", "ip:9.9.9.9"])


def test_the_whole_day_spent_says_so_kindly():
    shopper.add_spend(shopper.DAILY_CAP_USD)
    with pytest.raises(shopper.OverBudget) as e:
        shopper.check_budget(["v:anyone"])
    assert not e.value.mine and "Everything else still works" in str(e.value)


def test_shares_survive_a_restart():
    shopper.add_spend(0.2, ["v:x"])
    shopper._spent_by.clear()
    assert abs(shopper.spent_by("v:x") - 0.2) < 1e-9


def test_the_chat_endpoint_answers_429_with_a_friendly_line_and_no_model_call(monkeypatch):
    sample.build()       # chats for the assistant to review
    c = TestClient(web.app)
    shopper.add_spend(shopper.VISITOR_CAP_USD, ["v:spent"])
    monkeypatch.setattr(shopper, "_client_", lambda: (_ for _ in ()).throw(AssertionError("no model call")))
    ask = {"messages": [{"role": "user", "content": "What scale are your cars?"}]}
    r = c.post("/api/shopper", json=ask, headers={"x-visitor": "spent"})
    assert r.status_code == 429 and r.json()["budget"] == "visitor" and "until midnight in Ohio" in r.json()["error"]
    for path, body in (("/api/maker/assistant/ask", {"question": "How much did I make?"}),
                       ("/api/maker/assistant/review", {"days": 14})):
        assert c.post(path, json=body, headers={"x-visitor": "spent"}).status_code == 429
    fake = FakeModel("They're all 1:43, about 10 to 11 cm long.")
    monkeypatch.setattr(shopper, "_client_", lambda: fake)
    ok = c.post("/api/shopper", json=ask, headers={"x-visitor": "another-judge"})
    assert ok.status_code == 200 and ok.json()["reply"].startswith("They're all 1:43")
    assert shopper.spent_by("v:another-judge") > 0 and shopper.spent_by("ip:testclient") > 0   # its share is counted


# ---- final judges 08.11 P1-2: a share a client can't dodge, code-written answers need no budget, a studio pool ----
def test_behind_renders_proxy_the_network_is_the_last_forwarded_hop(monkeypatch):
    c = TestClient(web.app)
    seen = []
    monkeypatch.setattr(shopper, "check_budget", lambda who=(): seen.append(list(who)) or (_ for _ in ()).throw(
        shopper.OverBudget(shopper.BUSY_YOU, mine=True)))
    ask = {"messages": [{"role": "user", "content": "What scale are your cars?"}]}
    monkeypatch.setenv("RENDER", "true")
    for spoof in ("1.1.1.1", "2.2.2.2, 3.3.3.3"):
        c.post("/api/shopper", json=ask, headers={"x-visitor": "bot", "x-forwarded-for": f"{spoof}, 203.0.113.7"})
    assert [w[-1] for w in seen] == ["ip:203.0.113.7", "ip:203.0.113.7"]     # the client's own hops are ignored
    monkeypatch.delenv("RENDER")
    seen.clear()
    c.post("/api/shopper", json=ask, headers={"x-visitor": "bot", "x-forwarded-for": "9.9.9.9"})
    assert seen[-1][-1] == "ip:testclient"                                    # no proxy: the header means nothing


def test_with_the_day_spent_the_made_to_order_steps_written_in_code_still_answer(monkeypatch):
    shopper.add_spend(shopper.DAILY_CAP_USD)
    monkeypatch.setattr(shopper, "_client_", lambda: (_ for _ in ()).throw(AssertionError("no model call")))
    c = TestClient(web.app)
    first = "A grey fastback with two black stripes, brown inside, two of them."
    r = c.post("/api/shopper", json={"messages": [{"role": "user", "content": first}]}, headers={"x-visitor": "judge1"})
    assert r.status_code == 200 and "Which year" in r.json()["reply"]
    msgs = [{"role": "user", "content": first}, {"role": "assistant", "content": r.json()["reply"]},
            {"role": "user", "content": "It is a 1967."}]
    r = c.post("/api/shopper", json={"messages": msgs, "conv_id": r.json().get("conv_id", "")}, headers={"x-visitor": "judge1"})
    assert r.status_code == 200 and "$184.50" in r.json()["reply"]
    # a question only the model can answer still gets the friendly "budget used up" line
    r = c.post("/api/shopper", json={"messages": [{"role": "user", "content": "Tell me a story about your workshop."}]},
               headers={"x-visitor": "judge1"})
    assert r.status_code == 429 and r.json()["budget"] == "day"


def test_the_studio_has_its_own_pool_so_it_cannot_switch_off_the_shop_chat(monkeypatch):
    shopper.add_spend(shopper.STUDIO_CAP_USD, ["pool:studio"])
    assert shopper.STUDIO_CAP_USD < shopper.DAILY_CAP_USD
    c = TestClient(web.app)
    monkeypatch.setattr(shopper, "_client_", lambda: (_ for _ in ()).throw(AssertionError("no model call")))
    r = c.post("/api/studio/llm", json={"input": [], "tools": []}, headers={"x-visitor": "judge2"})
    assert r.status_code == 429 and "studio" in r.json()["error"]
    shopper.check_budget(["v:judge2", "ip:testclient"])        # the shop's chat still has its budget
