"""Buyers' names never appear on public pages: initials there, full names only with Lena's key (judge 29.10, N8)."""
import json

import pytest
from fastapi.testclient import TestClient

from opencounter import shop, web

SAM = {"full_name": "Sam Rivera", "phone": "415-555-0134", "email": "sam.rivera@example.com",
       "address_line_1": "1200 Lavaca St", "city": "Austin", "state": "TX", "postal_code": "78701"}
TYPED = "1 green to Austin / Sam Rivera, 415-555-0134, sam.rivera@example.com, 1200 Lavaca St, Austin TX 78701"


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setenv("MAKER_KEY", "lenas-key")
    shop.seed(force=True)


@pytest.fixture
def c():
    return TestClient(web.app)


def order_and_chat():
    o = shop.new_order("sg-014", 1, "TX", TYPED, "demo-shopper", customer=SAM)
    shop.update_order(o["id"], status="paid", ship_to={"name": "Sam Rivera", "city": "Austin", "state": "TX"})
    shop.log_turn("anon-1", "1 green to Austin", "That's $65.50. Your name, phone, email and address?", [], None)
    shop.log_turn("anon-1", TYPED.split(" / ")[1], "Thanks, Sam! It ships to Austin, TX 78701.", [], o["id"],
                  name="Sam Rivera")
    return o


def test_initials():
    assert web._initials("Ana Diaz") == "A. D." and web._initials("Иван Петров") == "И. П." and web._initials("") == ""


def test_the_thanks_page_shows_initials_not_the_name(c):
    o = order_and_chat()
    page = c.get(f"/thanks/{o['id']}").text
    assert "Sam" not in page and "Rivera" not in page and "S. R." in page and "Lavaca" not in page


def test_lenas_public_back_office_shows_initials_everywhere(c):
    o = order_and_chat()
    for path in ("/api/maker/orders", "/api/maker/conversations", "/api/maker/customers", "/api/maker/insights"):
        body = c.get(path, headers={"x-visitor": "someone"}).text
        assert "Rivera" not in body and "Sam" not in body, path
    chats = c.get("/api/maker/conversations").json()
    assert chats[0]["name"] == "S. R." and "Thanks, S.!" in chats[0]["turns"][1]["reply"]
    assert c.get("/api/maker/customers").json()[0]["name"] == "S. R."


def test_a_name_typed_in_a_chat_without_an_order_is_hidden_too(c):
    shop.log_turn("anon-2", "Kim Park, 415-555-0101, kim@example.com, 500 Howard St, San Francisco CA 94105", "Thanks!",
                  [], None)
    shop.new_callback("415-555-0101", "Kim Park", "call me", "Kim Park, 415-555-0101: can Lena call me?", "demo-shopper")
    for path in ("/api/maker/conversations", "/api/maker/requests"):
        body = c.get(path).text
        assert "Kim" not in body and "Park" not in body and "K. P." in body, path


def test_with_lenas_key_her_own_screen_has_full_names(c):
    order_and_chat()
    lena = {"x-maker-key": "lenas-key"}
    assert c.get("/api/maker/customers", headers=lena).json()[0]["name"] == "Sam Rivera"
    assert c.get("/api/maker/orders", headers=lena).json()[0]["customer"]["full_name"] == "Sam Rivera"
    assert c.get("/api/maker/conversations", headers=lena).json()[0]["name"] == "Sam Rivera"
    assert "Rivera" not in c.get("/api/maker/customers", headers={"x-maker-key": "wrong"}).text


def test_ordinary_words_are_not_taken_for_a_name(c):
    shop.log_turn("anon-3", "Thank You", "You're welcome! Anything else you'd like?", [], None)
    assert "You're welcome! Anything else you'd like?" in c.get("/api/maker/conversations").text
