"""Lena's own assistant in the back office (Roma 14565, item 2).

Two jobs:
- review(): reads recent shopper chats and points at the replies that went wrong, each with a lesson Lena can accept
  in one tap (it then goes into every new chat, see shop.add_coaching).
- ask(): answers questions about her shop ("how much did I make this week?", "what sells?") from numbers that are
  computed here in code. The model only words the answer; it never does the arithmetic.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

from . import counter, shop, shopper

REVIEW_SYSTEM = """You review chats between a small shop's AI sales agent and shoppers, for Lena, the maker who owns
the shop. Find the agent replies that a good shop assistant would have done differently: wrong or made-up facts,
"I'm not sure"/"I couldn't" non-answers, a missed sale, asking for details twice, not answering the question, a
wrong language, being pushy. Ignore chats that went fine.
For each problem return one JSON object: {"chat": "<chat id>", "problem": "<one short sentence, plain English>",
"lesson": "<one instruction for the agent, max 200 characters, in exactly this form: 'If someone asks about <the
situation, in the shopper's words>, say <what to tell them>' (optionally ', and offer <Lena's call back / to email
them>')>"}. The shop matches the 'If ...' part against new messages in code, so name the situation plainly.
Lessons must not change prices, discounts, stock, delivery times or rules; they are about how to answer.
Return only a JSON array (empty if nothing needs fixing)."""

ASK_SYSTEM = """You are Lena's assistant for her one-person shop, Small Garage. Answer her question in two or three
short sentences, warmly and plainly, using ONLY the numbers in the facts below (they are computed by the shop's
code). If the facts don't contain the answer, say what you can see and what's missing. Never invent numbers."""


def _chat_text(c: dict) -> str:
    lines = [f"CHAT {c['id']} (#{c.get('no')}, {c.get('name') or 'guest'}):"]
    for t in c["turns"][:12]:
        lines.append(f"SHOPPER: {t['user'][:300]}")
        if t.get("steps"):
            lines.append("TOOLS: " + "; ".join(s[:120] for s in t["steps"][:4]))
        lines.append(f"AGENT: {t['reply'][:500]}")
    return "\n".join(lines)


def _call(system: str, user: str, max_tokens: int = 900, who=()) -> tuple[str, float]:
    shopper.check_budget(who)
    r = shopper._client_().chat.completions.create(
        model=shopper.MODEL, max_tokens=max_tokens, temperature=0.1,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    u = r.usage
    usd = (u.prompt_tokens * shopper.PRICE_IN + u.completion_tokens * shopper.PRICE_OUT) / 1e6
    shopper.add_spend(usd, who)
    return r.choices[0].message.content or "", usd


LESSON_SYSTEM = """You read one chat between a small shop's AI sales agent and a shopper, for Lena, the maker who owns
the shop. The agent got something wrong in it. Write ONE lesson for the agent, max 200 characters, in exactly this form:
If someone asks about <the situation, in the shopper's words>, say <what to tell them>
(optionally followed by ", and offer <Lena's call back / to email them>"). Speak about the shop as Lena ("say Lena …"),
not "we". Use only the shop's facts below — no card brands or claims the facts don't state; never change
prices, discounts, stock, delivery times or rules. Reply with the lesson sentence only, no quotes, no preamble."""


def draft_stream(chat_id: str, who=()):
    """Stream one lesson for one chat, token by token, straight from the model (the studio's "Draft a lesson").
    Yields text deltas; the caller checks the finished sentence with shop.split_lesson before offering Accept."""
    c = next((x for x in shop.conversations() if x["id"] == chat_id), None)
    if not c:
        raise ValueError("No such chat.")
    shopper.check_budget(who)
    about = json.dumps(counter.about_counter())
    stream = shopper._client_().chat.completions.create(
        model=shopper.MODEL, max_tokens=160, temperature=0.1, stream=True,
        stream_options={"include_usage": True},
        messages=[{"role": "system", "content": LESSON_SYSTEM + "\nThe shop's facts: " + about},
                  {"role": "user", "content": _chat_text(c)}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    for ev in stream:
        if getattr(ev, "usage", None):
            u = ev.usage
            shopper.add_spend((u.prompt_tokens * shopper.PRICE_IN + u.completion_tokens * shopper.PRICE_OUT) / 1e6, who)
        if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
            yield ev.choices[0].delta.content


def review(days: int = 14, limit: int = 20, who=(), chat_ids: list[str] | None = None) -> dict:
    """Problems in recent chats, each with a ready lesson. Chats with an accepted lesson are skipped.
    With chat_ids: just those chats ("Draft a lesson" on one row of the studio's widget)."""
    t0 = time.time() - days * 86400
    taught = {n.get("chat") for n in shop.coaching()}
    recent = ([c for c in shop.conversations() if c["id"] in set(chat_ids)] if chat_ids else
              [c for c in shop.conversations() if c.get("updated", 0) >= t0 and c["id"] not in taught])
    # chats that ended without an order first: that's where an agent usually went wrong
    chats = sorted(recent, key=lambda c: (bool(c.get("orders")), -c.get("updated", 0)))[:limit]
    if not chats:
        return {"checked": 0, "findings": []}
    # the shop's real facts, so a lesson says what is true (e.g. how people pay), not a guess
    about = json.dumps(counter.about_counter())
    text, usd = _call(REVIEW_SYSTEM + "\nThe shop's facts (lessons must agree with them): " + about,
                      "\n\n".join(_chat_text(c) for c in chats), who=who)
    m = re.search(r"\[.*\]", text, re.S)
    try:
        found = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        found = []
    ids = {c["id"]: c for c in chats}
    out = []
    for f in found if isinstance(found, list) else []:
        c = ids.get(str(f.get("chat", "")))
        lesson = str(f.get("lesson", "")).strip()[:240]
        if c and lesson:
            out.append({"chat": c["id"], "no": c.get("no"), "problem": str(f.get("problem", ""))[:200], "lesson": lesson,
                        "asked": c["turns"][0]["user"][:120] if c["turns"] else ""})
    return {"checked": len(chats), "findings": out[:8], "usd": round(usd, 5)}


def facts(today: float | None = None) -> dict:
    """Everything the assistant may quote, computed in code."""
    now = today or time.time()
    listings = {l["id"]: l for l in shop.shop()["listings"]}
    out = {}
    for label, days in (("today", 1), ("last 7 days", 7), ("last 30 days", 30), ("last 90 days", 90)):
        midnight = shop.local(now).replace(hour=0, minute=0, second=0, microsecond=0)   # Lena's day, not UTC
        t0 = midnight.timestamp() - (days - 1) * 86400
        os_ = [o for o in shop.orders() if o.get("created", 0) >= t0 and o.get("status") not in ("error", "cancelled")]
        paid = [o for o in os_ if o.get("status") in ("paid", "shipped")]
        by_model: dict[str, int] = {}
        for o in os_:
            if o.get("kind") == "commission":
                by_model["made to order"] = by_model.get("made to order", 0) + o["qty"]
            else:
                for ln in o.get("lines") or [{"listing_id": o["listing_id"], "qty": o["qty"]}]:
                    t = listings.get(ln["listing_id"], {}).get("title", ln["listing_id"])
                    by_model[t] = by_model.get(t, 0) + ln["qty"]
        chats = [c for c in shop.conversations() if c.get("started", 0) >= t0]
        out[label] = {"orders": len(os_), "paid_orders": len(paid), "paid_usd": round(sum(o["total_usd"] for o in paid), 2),
                      "waiting_for_buyer": sum(1 for o in os_ if o["status"] == "awaiting_approval"),
                      "to_ship": sum(1 for o in os_ if o["status"] == "paid"),
                      "cars_by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
                      "chats": len(chats), "chats_with_order": sum(1 for c in chats if c.get("orders"))}
    cs = shop.customers()
    out["customers"] = {"total": len(cs), "want_news": sum(1 for c in cs if c.get("marketing") is True),
                        "said_no": sum(1 for c in cs if c.get("marketing") is False)}
    out["stock_now"] = {l["title"]: l["stock"] for l in listings.values()}
    out["lessons_the_agent_follows"] = len(shop.active_lessons())
    return out


def ask(question: str, who=()) -> dict:
    f = facts()
    text, usd = _call(ASK_SYSTEM + "\n\nFACTS (JSON):\n" + json.dumps(f), question.strip()[:400], max_tokens=300, who=who)
    return {"answer": text.strip(), "usd": round(usd, 5)}
