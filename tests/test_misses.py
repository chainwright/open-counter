from opencounter import misses, shop

NOTE = "If someone asks about shipping outside the US, say we ship to the US only and offer to email them when that changes."
STEP = "following Lena's lesson · " + NOTE[:160]


def chat(cid, turns, orders=()):
    return {"id": cid, "no": int(cid[-1]), "turns": turns, "orders": list(orders), "updated": max(t["at"] for t in turns)}


def turn(at, user, reply, steps=()):
    return {"at": at, "user": user, "reply": reply, "steps": list(steps)}


def data():
    convs = [
        chat("c1", [turn(100, "Do you ship to Toronto?", "Yes, 5-7 days.")]),                          # source of the lesson
        chat("c2", [turn(300, "Can you send one to Canada?", "We ship to the US only...", [STEP])], ["OC-A"]),
        chat("c3", [turn(400, "Ship to Mexico City?", "Sure, 2 weeks.")], ["OC-B"]),                   # lesson not applied
        chat("c4", [turn(500, "Is the red one a real Ferrari?", "Sorry, I can't help with that.")]),   # stuck, no lesson
        chat("c5", [turn(600, "Do you ship to Ohio?", "Yes, Thursday.")], ["OC-C"]),                    # not about the lesson
    ]
    lessons = [{"id": "L-1", "at": 200, "chat": "c1", "note": NOTE, "active": True}]
    orders = [{"id": "OC-A", "status": "paid", "total_usd": 65.5}, {"id": "OC-B", "status": "awaiting_approval",
                                                                        "total_usd": 70.0},
              {"id": "OC-C", "status": "paid", "total_usd": 120.0}]
    return convs, lessons, orders


def test_lesson_row_has_the_corrected_answer_and_each_later_test():
    out = misses.agent_misses(*data(), since=0, matches=shop.lesson_matches)
    [row] = out["taught"]
    assert row["asked"] == "Do you ship to Toronto?" and row["said"] == "Yes, 5-7 days."
    assert [(x["chat"], x["followed"]) for x in row["later"]] == [("c2", True), ("c3", False)]
    assert (row["followed"], row["missed"]) == (1, 1)


def test_money_counts_only_paid_orders_from_chats_the_lesson_touched():
    out = misses.agent_misses(*data(), since=0, matches=shop.lesson_matches)
    assert out["taught"][0]["orders_usd"] == 65.5        # OC-B unpaid, OC-C from a chat the lesson never touched
    assert out["orders_usd"] == 65.5


def test_stuck_reply_without_a_lesson_is_an_open_row():
    out = misses.agent_misses(*data(), since=0, matches=shop.lesson_matches)
    assert [r["chat"] for r in out["open"]] == ["c4"]


def test_chat_a_lesson_came_from_is_not_open_and_earlier_turns_dont_count():
    convs, lessons, orders = data()
    lessons[0]["at"] = 350          # lesson written after c2's turn: c2 can't be a test of it
    out = misses.agent_misses(convs, lessons, orders, since=0, matches=shop.lesson_matches)
    assert [x["chat"] for x in out["taught"][0]["later"]] == ["c3"]


def test_two_lessons_touching_one_chat_count_its_money_once():
    convs, lessons, orders = data()
    lessons.append({"id": "L-2", "at": 210, "chat": "c1", "active": True,
                    "note": "If someone asks about Canada, say we don't ship there yet."})
    out = misses.agent_misses(convs, lessons, orders, since=0, matches=shop.lesson_matches)
    assert out["orders_usd"] == 65.5


def test_a_mistake_an_active_lesson_already_covers_is_not_open():
    convs, lessons, orders = data()
    convs.append(chat("c6", [turn(700, "Do you ship to Canada?", "I couldn't finish that in a few steps.")]))
    out = misses.agent_misses(convs, lessons, orders, since=0, matches=shop.lesson_matches)
    assert [r["chat"] for r in out["open"]] == ["c4"]


# ---- final judges 08.11: the safety answer is not a miss; a viewer sees only sample chats and their own ----
SAFE_STEP = "reading the listing · safety and age: quoted from the listings only"


def test_the_deliberate_safety_answer_is_never_an_open_row():
    from opencounter import shopper
    convs, lessons, orders = data()
    reply = shopper._safety_answer("Is the paint toxic for a kid?", False)
    assert misses.STUCK.search(reply)                       # it says "I don't know" for what the listing doesn't say…
    convs.append(chat("c7", [turn(800, "Is the paint toxic for a kid?", reply, [SAFE_STEP])]))
    out = misses.agent_misses(convs, lessons, orders, since=0, matches=shop.lesson_matches)
    assert [r["chat"] for r in out["open"]] == ["c4"]       # …but that's the right answer, not a place it got stuck


def _mine(c, visitor=None, sample=False):
    return {**c, "visitor": visitor or "", "sample": sample}


def test_a_visitor_sees_open_rows_only_from_sample_chats_and_their_own():
    convs = [_mine(chat("c1", [turn(100, "Ferrari?", "Sorry, I can't help with that.")]), sample=True),
             _mine(chat("c2", [turn(200, "Credit card?", "I'm not sure.")]), visitor="judgeA"),
             _mine(chat("c3", [turn(300, "Gift wrap?", "I don't know.")]), visitor="judgeB")]
    see = lambda viewer: [r["chat"] for r in misses.agent_misses(convs, [], [], since=0, matches=shop.lesson_matches,
                                                                 viewer=viewer)["open"]]
    assert see("judgeA") == ["c2", "c1"] and see("judgeB") == ["c3", "c1"] and see("") == ["c1"]
    assert see(None) == ["c3", "c2", "c1"]                  # Lena sees every chat


def test_crosses_come_only_from_chats_the_lesson_could_apply_to():
    convs, lessons, orders = data()
    convs = [_mine(c, sample=True) for c in convs]
    convs.append(_mine(chat("c8", [turn(900, "Ship to Mexico?", "Sure, 2 weeks.")]), visitor="judgeB"))
    # Lena's lesson: a judge sees the sample chats and their own, not another judge's chat
    later = lambda viewer, ls: [x["chat"] for x in misses.agent_misses(convs, ls, orders, since=0,
                                                                         matches=shop.lesson_matches, viewer=viewer)["taught"][0]["later"]]
    assert later("judgeA", lessons) == ["c2", "c3"] and later("judgeB", lessons) == ["c2", "c3", "c8"]
    # a visitor's own lesson only ever applies to that visitor's chats, so only those can tick or cross it
    own = [{**lessons[0], "visitor": "judgeA", "chat": "c1"}]
    convs.append(_mine(chat("c9", [turn(950, "Send it to Canada?", "We ship to the US only.", [STEP])]), visitor="judgeA"))
    assert later("judgeA", own) == ["c9"] and later(None, own) == ["c9"]


def test_the_studio_endpoint_scopes_open_rows_to_the_viewer(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from opencounter import web
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)
    shop.log_turn("chat-b1", "Do you do gift wrap?", "I'm not sure about that.", [], None, visitor="judgeB")
    c = TestClient(web.app)
    rows = lambda v: [r["chat"] for r in c.get("/api/maker/agent_misses", headers={"x-visitor": v}).json()["open"]]
    assert "chat-b1" in rows("judgeB") and "chat-b1" not in rows("judgeA")


# ---- round-2 judges 08.11 N3: one open row per question, not per chat ----
def test_the_same_question_in_two_chats_is_one_open_row_the_newest_with_a_count():
    convs = [chat("c1", [turn(100, "Can I pay with a credit card instead of PayPal?", "I'm not sure about that.")]),
             chat("c2", [turn(300, "Can I pay with a credit card?", "I'm not sure, sorry.")]),
             chat("c3", [turn(200, "Do you do gift wrap?", "I don't know.")]),
             chat("c4", [turn(250, "Is the red one a real Ferrari?", "Sorry, I can't help with that.")]),   # no topic
             chat("c5", [turn(260, "Is the blue one a real Porsche?", "Sorry, I can't help with that.")])]  # no topic
    out = misses.agent_misses(convs, [], [], since=0, matches=shop.lesson_matches, topics=shop.topics)
    rows = [(r["chat"], r["also"]) for r in out["open"]]
    assert rows == [("c2", 1), ("c5", 0), ("c4", 0), ("c3", 0)]       # credit card once (newest), each untopiced row kept
    # without the topic reader every chat keeps its row, as before
    assert len(misses.agent_misses(convs, [], [], since=0, matches=shop.lesson_matches)["open"]) == 5


def test_the_studio_shows_the_samples_credit_card_question_once(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from opencounter import sample, web
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)
    sample.build()
    out = TestClient(web.app).get("/api/maker/agent_misses", headers={"x-visitor": "judgeA"}).json()
    card = [r for r in out["open"] if "credit card" in r["asked"].lower()]
    assert len(card) == 1 and card[0]["also"] >= 1
