"""Test traffic leaves Lena's back office on start; real records and the sample history stay, and the sample
never brings test data back (judge 29.10, N6)."""
import json
import time

import pytest

from opencounter import misses, sample, shop

SAM = {"full_name": "Sam Rivera", "phone": "415-555-0134", "email": "sam.rivera@example.com",
       "address_line_1": "1200 Lavaca St", "city": "Austin", "state": "TX", "postal_code": "78701"}
ROMA = {"full_name": "Real Buyer", "phone": "312-555-0177", "email": "real.buyer@example.org",
        "address_line_1": "233 S Wacker Dr", "city": "Chicago", "state": "IL", "postal_code": "60606"}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shop, "DEMO", True)
    sample.ensure()     # first start: sample history laid down


def counts():
    return (len(shop.orders()), len(shop.conversations()), len(shop.customers()), len(shop.coaching()))


def test_the_sample_history_has_no_test_records_and_a_restart_changes_nothing():
    before = counts()
    assert sample.purge_test_data() == {}
    sample.ensure()
    assert counts() == before
    assert not any(sample.TEST_ID.match(c["id"]) for c in shop.conversations())
    assert not {o["id"] for o in shop.orders()} & sample.KNOWN_TEST_ORDERS


def test_qa_chats_their_orders_buyers_lessons_and_callbacks_go_and_real_ones_stay():
    sample_before = counts()
    # a judge's QA chat with an order (round 5 style), a QA lesson, a QA call-back
    qa = shop.new_order("sg-015", 1, "WA", "1 blue fastback to Seattle", "demo-shopper", customer={
        **SAM, "full_name": "Ana Diaz", "email": "ana.diaz@example.com", "city": "Seattle", "state": "WA", "postal_code": "98101"})
    shop.update_order(qa["id"], visitor="qa-e0147409")
    shop.log_turn("qa5-blue-7409", "1 blue fastback to Seattle please", "It ships to Seattle.", [], qa["id"],
                  name="Ana Diaz", visitor="qa-e0147409")
    shop.add_coaching("qa5-blue-7409", "Always say hello first.", visitor="qa-e0147409")
    shop.new_callback("415-555-0199", "", "call me", "Can I talk to Lena? My number is 415-555-0199", "demo-shopper")
    shop.log_turn("qa5-lena-7409", "Can I talk to Lena? My number is 415-555-0199", "She'll call.", [], None,
                  visitor="qa-e0147409")
    old = shop.new_order("sg-014", 1, "TX", "x", "t")            # a round-4 order listed by id
    orders = shop.orders()
    next(o for o in orders if o["id"] == old["id"])["id"] = "OC-D3BC6995"
    shop._save_orders(orders)
    # a real buyer in a real browser, with a paid order
    real = shop.new_order("sg-012", 1, "IL", "1 red to Chicago", "demo-shopper", customer=ROMA)
    shop.update_order(real["id"], visitor="9f2c4e1a7b3d5f6e8a0c2b4d", status="paid")
    shop.log_turn("anon-1a2b3c4d", "1 red to Chicago", "It ships to Chicago.", [], real["id"], name="Real Buyer",
                  visitor="9f2c4e1a7b3d5f6e8a0c2b4d")

    sample.ensure()                       # the next start of the app (same path as on Render)
    assert not any(c["id"].startswith("qa") for c in shop.conversations())
    assert not any(n.get("visitor") == "qa-e0147409" for n in shop.coaching())
    assert not any("415-555-0199" in r["asked_for"] for r in shop.requests_())
    ids = {o["id"] for o in shop.orders()}
    assert "OC-D3BC6995" not in ids
    assert real["id"] in ids and qa["id"] not in ids
    assert any(c["id"] == "anon-1a2b3c4d" for c in shop.conversations())
    assert any(c["email"] == "real.buyer@example.org" for c in shop.customers())
    assert not any(c["email"] == "ana.diaz@example.com" for c in shop.customers())
    assert counts() == (sample_before[0] + 1, sample_before[1] + 1, sample_before[2] + 1, sample_before[3])
    sample.ensure()                       # the next start: nothing comes back, nothing else goes
    assert sample.purge_test_data() == {} and real["id"] in {o["id"] for o in shop.orders()}


def test_a_sample_order_is_never_purged_even_if_listed():
    one = next(o for o in shop.orders() if o.get("sample"))
    orders = shop.orders()
    for o in orders:
        if o["id"] == one["id"]:
            o["visitor"] = "qa-x"
    shop._save_orders(orders)
    sample.purge_test_data()
    assert one["id"] in {o["id"] for o in shop.orders()}


def open_rows(now):
    return misses.agent_misses(shop.conversations(), shop.lessons_for(), shop.orders(), since=now - 7 * 86400,
                               matches=shop.lesson_matches)["open"]


def test_the_studio_has_an_open_row_this_week_on_any_day_the_demo_is_opened(monkeypatch):
    # live check 08.11: the sample was laid down 19.10-01.11 and never re-dated, so "this week" had no open row and
    # judge step 4 ("Draft a lesson") had no button
    t0 = time.time()
    assert any("credit card instead of PayPal" in r["asked"] for r in open_rows(t0))
    later = t0 + 10 * 86400                        # ten days on, the app never restarted: the hourly refresh runs
    assert sample.refresh(now=later) is True
    rows = open_rows(later)
    assert rows and all(r["at"] >= later - 7 * 86400 for r in rows)
    assert any("credit card instead of PayPal" in r["asked"] for r in rows)
    assert sample.refresh(now=later + 60) is False  # fresh enough: nothing is rewritten


def test_a_refresh_keeps_every_live_record(monkeypatch):
    real = shop.new_order("sg-012", 1, "IL", "1 red to Chicago", "demo-shopper", customer=ROMA)
    shop.update_order(real["id"], visitor="9f2c4e1a7b3d5f6e8a0c2b4d", status="paid")
    shop.log_turn("anon-1a2b3c4d", "1 red to Chicago", "It ships to Chicago.", [], real["id"], name="Real Buyer",
                  visitor="9f2c4e1a7b3d5f6e8a0c2b4d")
    lesson = shop.add_coaching("anon-1a2b3c4d", "If someone asks about rush, say there's one shipping speed.",
                               visitor="9f2c4e1a7b3d5f6e8a0c2b4d")
    cs = shop._json("counters.json", {})
    cs["clay-kiln-s1"]["listing"]["paypal_catalog_product"] = "OC-CLAY-KILN-S1-1"   # registered by catalog.sync
    shop._save_json("counters.json", cs)
    before = counts()
    sample_dates = sorted(o["created"] for o in shop.orders() if o.get("sample"))
    assert sample.refresh(now=time.time() + 3 * 86400)
    assert counts() == before
    assert real["id"] in {o["id"] for o in shop.orders()} and lesson["id"] in {n["id"] for n in shop.coaching()}
    assert any(c["id"] == "anon-1a2b3c4d" for c in shop.conversations())
    assert next(c for c in shop.customers() if c["email"] == "real.buyer@example.org")["orders"] == [real["id"]]
    assert shop._json("counters.json", {})["clay-kiln-s1"]["listing"]["paypal_catalog_product"] == "OC-CLAY-KILN-S1-1"
    moved = sorted(o["created"] for o in shop.orders() if o.get("sample"))
    assert min(moved) > min(sample_dates) + 2 * 86400   # the sample moved with the clock


def test_the_new_data_version_wipes_the_live_check_and_probe_data_but_not_the_budget(tmp_path):
    # the live disk as it was on 08.11: data version 11, the judge-path check's records, the 02-03.11 probes
    shop._path("data_version").write_text("11")
    orders = shop.orders()
    for oid, extra in (("OC-2C9A66AA", {"kind": "commission", "invoice_id": "INV2-2WXK-33LT-AN9D-FKRN", "visitor": "judgetest20261108a"}),
                       ("OC-AA30F65F", {"channel": "mcp"}), ("OC-DE08FDC7", {"channel": "mcp"})):
        orders.append({"id": oid, "status": "awaiting_approval", "created": time.time(), "total_usd": 65.5, "qty": 1,
                       "title": "x", "events": [], **extra})
    shop._save_orders(orders)
    shop.log_turn("anon-174c5ffe", "A grey fastback…", "Which year?", [], "OC-2C9A66AA", name="Judge Test", visitor="judgetest20261108a")
    shop.log_turn("anon-8bd494f5", "Can you rush it?", "No.", [], None, visitor="5c1e0d2a9b8f7e6d5c4b3a21")
    shop._save_json("coaching.json", shop.coaching() + [{"id": "L-F1A94D", "at": time.time(), "chat": "anon-8bd494f5",
                                                         "note": "If someone asks for faster shipping, say …", "active": True,
                                                         "visitor": "judgetest20261108a"}])
    custs = shop._json("customers.json", {})
    custs["judge.test+20261108@example.com"] = {"email": "judge.test+20261108@example.com", "full_name": "Judge Test",
                                                "orders": ["OC-2C9A66AA"]}
    shop._save_json("customers.json", custs)
    shop._save_json("spend.json", {"2026-11-08": 0.42})
    sample.ensure()                                  # the first start after the deploy
    ids = {o["id"] for o in shop.orders()}
    assert not ids & {"OC-2C9A66AA", "OC-AA30F65F", "OC-DE08FDC7"}
    assert not any(c["id"] in ("anon-174c5ffe", "anon-8bd494f5") for c in shop.conversations())
    assert "L-F1A94D" not in {n["id"] for n in shop.coaching()}
    assert not any("judge" in c["email"] for c in shop.customers()), [c for c in shop.customers() if "judge" in c["email"]]
    assert all(o.get("sample") for o in shop.orders()) and all(c.get("sample") for c in shop.conversations())
    assert shop._json("spend.json", {}) == {"2026-11-08": 0.42}         # the day's AI budget is not demo data
    assert shop._path("data_version").read_text() == sample.DATA_VERSION == "12"
    assert any("credit card instead of PayPal" in r["asked"] for r in open_rows(time.time()))
