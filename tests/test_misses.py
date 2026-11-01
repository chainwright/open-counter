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
