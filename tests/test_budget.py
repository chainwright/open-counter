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
