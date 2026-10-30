"""The eval checks themselves: independent of the day they run on, and a non-answer never passes (judge N10,
TO_NINE #3). Uses the saved transcripts only: no model call."""
import importlib.util
from datetime import datetime, timezone

import pytest

from opencounter import shop

spec = importlib.util.spec_from_file_location("run_evals", shop.ROOT / "evals" / "run_evals.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

CHECKOUT = {"tool": "start_checkout", "result": "3 × Yellow German Rear-Engine Coupé, 1973 at $59.00 = $177.00; "
            "shipping $6.50; total $183.50 · ships Monday Nov 2, arrives Wednesday Nov 4–Friday Nov 6 · to TX · needs: email"}


def check(reply, steps):
    return ev.ship_date_from_tool()(reply, [], steps)


def test_the_ship_date_check_follows_the_tool_not_the_calendar():
    assert check("We ship it Monday, Nov 2, right after payment.", [CHECKOUT])
    assert check("It goes out on November 2nd.", [CHECKOUT])
    assert not check("We ship it Thursday, October 29.", [CHECKOUT])     # the old hard-coded day is now wrong
    assert check("Ships Tuesday.", [{"tool": "delivery_estimate", "result": "ships Tue · arrives Thu–Mon"}])
    assert not check("Ships soon.", [])                                    # no date from a tool, no pass


@pytest.mark.parametrize("today", [datetime(2026, 10, 29, 15, tzinfo=timezone.utc),
                                   datetime(2026, 12, 4, 23, tzinfo=timezone.utc)])
def test_the_saved_ship_date_case_passes_on_any_day(monkeypatch, today):
    monkeypatch.setattr(shop, "_clock", lambda: today)
    out, _ = ev.rescore()
    case = next(r for r in out if r["case"] == "ship date question")
    assert dict(case["checks"])["ship date from tool"] is True


def test_a_non_answer_never_passes():
    sorry = "Sorry, I didn't catch that in time. Could you send it once more?"
    on_time = next(c for c in ev.CASES if c[0] == "deadline: on time")[2][0][1]
    assert not on_time(sorry, [], [])                                      # 'in time' alone no longer counts
    assert on_time("Good news: it arrives in time for next Friday.", [], [])
    log = [{"user": "Do you ship to Hawaii?", "reply": "Yes, Lena ships to Hawaii. " + sorry, "steps": []}]
    assert dict(ev.always_checks(log, 2.0))["no 'send it again' non-answer"] is False


def test_the_offline_rescore_reports_changed_cases_apart():
    out, changed = ev.rescore()
    assert "stock: several cars, one order" in changed and all(r["case"] not in changed for r in out)
    assert len(out) + len(changed) == len(ev.CASES)
