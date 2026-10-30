"""Test traffic leaves Lena's back office on start; real records and the sample history stay, and the sample
never brings test data back (judge 29.10, N6)."""
import json

import pytest

from opencounter import sample, shop

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
