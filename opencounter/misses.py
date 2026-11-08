"""Where the shop's AI agent got stuck, and whether Lena's lessons fixed it.

Feeds the hero widget of Lena's studio (AG Studio). Everything here is computed in code from the shop's own records:
a lesson's source chat gives what the shopper asked and what the agent said; every later message the lesson is about
(shop.lesson_matches) is a test of it; the reply passed if that turn's steps show the lesson was applied. No model
call happens here; drafting a new lesson is a separate, explicit request (assistant.review on one chat).
"""
from __future__ import annotations

import re

PAID = {"paid", "shipped", "deposit_paid"}

STUCK = re.compile(r"couldn.?t finish|can.?t help|cannot help|unable to|don.?t know|not sure|couldn.?t reach|"
                   r"try again later|checkout (is|system is) (currently )?offline", re.I)


# The shop's deliberate answer to a safety, age or material question ("…only what the listing says…, so I don't know
# that") is the right answer, not a place the agent got stuck (final judges 08.11: it showed up as a red row).
SAFETY_STEP = "safety and age"


def _deliberate(turn: dict) -> bool:
    return any(SAFETY_STEP in s for s in turn.get("steps", []))


def _counts_for(chat: dict, lesson: dict | None, viewer: str | None) -> bool:
    """Whose chats a row may use. viewer None is Lena (everything). A visitor's lesson applies to that visitor's
    chats only, so only those test it; on the public demo a viewer sees the sample history and their own chats,
    never other visitors' (so one judge's chats don't put rows or crosses in front of the next)."""
    if lesson and lesson.get("visitor"):
        return chat.get("visitor") == lesson["visitor"]
    if viewer is None:
        return True
    return bool(chat.get("sample")) or (bool(viewer) and chat.get("visitor") == viewer)


def _followed(turn: dict, note: str) -> bool:
    """The lesson was applied to this reply: the shop logs each applied lesson as a step 'Lena's lesson · <note>'."""
    head = note[:60].lower()
    return any(head in s.lower() for s in turn.get("steps", []))


def _source_turn(chat: dict, note: str, matches) -> dict | None:
    """The answer Lena corrected: the first turn of the lesson's chat that the lesson is about, else the last turn."""
    turns = chat.get("turns") or []
    return next((t for t in turns if matches(note, t.get("user", ""))), turns[-1] if turns else None)


def agent_misses(conversations: list[dict], lessons: list[dict], orders: list[dict], since: float, matches,
                 viewer: str | None = None) -> dict:
    """Rows for the widget.

    taught rows: one per lesson — asked, said (the corrected answer), the lesson, and every later matching message
      with followed True/False, plus the paid value of orders from those chats.
    open rows: replies since `since` where the agent got stuck, in chats no lesson came from — a 'Draft a lesson' row.
    `matches(note, text)` is shop.lesson_matches (passed in so this stays a pure function for tests).
    viewer: None for Lena (every chat); a visitor id on the public demo (sample chats and that visitor's own)."""
    chats = {c["id"]: c for c in conversations}
    by_order = {o["id"]: o for o in orders}
    taught_chats = {n.get("chat") for n in lessons}
    taught, all_touched = [], set()
    for n in sorted(lessons, key=lambda n: n.get("at", 0)):
        src = chats.get(n.get("chat") or "")
        st = _source_turn(src, n["note"], matches) if src else None
        later, touched = [], set()
        for c in conversations:
            if c["id"] == n.get("chat") or not _counts_for(c, n, viewer):
                continue
            for t in c.get("turns", []):
                if t.get("at", 0) > n.get("at", 0) and matches(n["note"], t.get("user", "")):
                    later.append({"chat": c["id"], "no": c.get("no"), "at": t["at"], "followed": _followed(t, n["note"])})
                    touched.add(c["id"])
        later.sort(key=lambda x: x["at"])
        all_touched |= touched
        usd = sum(by_order[oid].get("total_usd", 0) for cid in touched for oid in chats[cid].get("orders", [])
                  if oid in by_order and by_order[oid].get("status") in PAID)
        taught.append({"lesson": n["id"], "note": n["note"], "active": n.get("active", True), "at": n.get("at", 0),
                       "chat": n.get("chat"), "asked": (st or {}).get("user", "")[:200],
                       "said": (st or {}).get("reply", "")[:240], "later": later[-12:],
                       "followed": sum(x["followed"] for x in later), "missed": sum(not x["followed"] for x in later),
                       "orders_usd": round(usd, 2)})
    open_ = []
    for c in conversations:
        if c["id"] in taught_chats or not _counts_for(c, None, viewer):
            continue
        for t in c.get("turns", []):
            covered = any(matches(n["note"], t.get("user", "")) for n in lessons if n.get("active", True))
            if (t.get("at", 0) >= since and STUCK.search(t.get("reply", "")) and not covered
                    and not _deliberate(t)):
                open_.append({"chat": c["id"], "no": c.get("no"), "at": t["at"], "asked": t.get("user", "")[:200],
                              "said": t.get("reply", "")[:240]})
                break   # one row per chat: the first place it got stuck
    open_.sort(key=lambda x: -x["at"])
    return {"taught": taught, "open": open_[:12],
            "orders_usd": round(sum(by_order[oid].get("total_usd", 0) for cid in all_touched
                                    for oid in chats[cid].get("orders", [])
                                    if oid in by_order and by_order[oid].get("status") in PAID), 2),
            "followed": sum(r["followed"] for r in taught), "missed": sum(r["missed"] for r in taught)}
