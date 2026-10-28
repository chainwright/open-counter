"""The built-in demo shopper: a stranger's AI agent shopping Lena's counter with the same tools any outside agent
gets over MCP. NVIDIA Nemotron on Nebius Token Factory with native tool calls, a step budget, a daily spend cap.

It can find, compare and prepare a checkout. It cannot pay: start_checkout returns a PayPal link for the human."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date

from openai import OpenAI

from . import counter

MODEL = os.environ.get("SHOPPER_MODEL", "nvidia/nemotron-3-super-120b-a12b")
PRICE_IN, PRICE_OUT = 0.30, 0.90  # USD per 1M tokens, Token Factory catalog
DAILY_CAP_USD = float(os.environ.get("SHOPPER_DAILY_CAP_USD", "1.00"))
MAX_STEPS = 6
_spent: dict[str, float] = {}
_lock = threading.Lock()
_client: OpenAI | None = None

# Car makers and models must never appear: the shop sells generic replicas, and the contest bans third-party marks.
BRANDS = re.compile(r"\b(ford|mustang|shelby|eleanor|porsche|911|chevrolet|chevy|camaro|chevelle|impala|dodge|"
                    r"charger|challenger|plymouth|cuda|pontiac|gto|firebird|cadillac|lincoln|mercury|cougar|amc|"
                    r"buick|oldsmobile|ferrari|mercedes|bmw|volkswagen|vw|jaguar|aston martin|corvette|stingray|"
                    r"thunderbird|beetle|bel air|mach 1|boss 302|gt ?350|gt ?500)\b", re.I)
# "Shall I proceed?" after everything is known: the sales agent should place the order, not ask (Roma 14457).
PERMISSION = re.compile(r"\b(shall i|should i|would you like me to|do you want me to|want me to|ready to proceed|"
                        r"shall we|proceed with (the )?(checkout|order))\b", re.I)
PHONE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")
MEMO_TAG = re.compile(r"\n?\[(what the tools returned|tool results)[^\]]*\]", re.I)
REFUSAL = re.compile(r"^\s*(i.?m sorry,?\s*)?(but\s*)?i (can.?t|cannot) (help|assist) with (that|this)", re.I)
ITEM_ID = re.compile(r"\s*\(?\bsg[-‑–]\d+\b\)?", re.I)
PROMISE = re.compile(r"\b(let me|let's|lets|i'll|i will|we'll|we will|i am going to|i'm going to|we need to)\b.{0,40}"
                     r"\b(search|check|look|find|see|quote|place|send|submit|call|get|calculate|price|prepare|create)\b|\bsearching\b", re.I)

SYSTEM = """You are the sales agent at Small Garage, a one-person maker of
hand-built 1:43 replica cars, serving a customer through the shop's public tools. Rules:
- Use only facts returned by the tools. Never invent a price, a date, a discount, a lead time or a stock number.
  Every number you say must come from a tool result in this conversation.
- Never name real car makers or models. If the person names one, say Lena makes unbranded replicas named by
  colour, body style and year, then search and offer the closest listed car first (with its stock and price).
  Never refuse the conversation over a brand name.
- Buying a listed car: the person can buy any quantity up to the stock on the listing. Check delivery to their US
  state (a state name is enough: California → CA; work out the state from a city; pass a deadline as need_by only if the person
  gave one and repeat the tool's verdict; never ask for a deadline), then call
  start_checkout in the same turn as soon as you know the car, the quantity and the state. PayPal collects their
  name and address.
- Made to order (a car or colour not in stock, or more than the stock): ask, one short question at a time and only
  for what's still missing: which car (body style or one of the listings), the year of the real car, the body
  colour, the interior colour, and how many. Then call quote_commission and give the total, discount, shipping,
  build time and ready date exactly as returned, and in the same reply ask for their name and phone number. As
  soon as you have them, call start_commission_checkout right away (no extra "shall I?" question: the person
  confirms by approving in PayPal). Show 'you_are_approving' and say Lena starts building once it's paid.
- Asked when it ships or arrives: answer from delivery_estimate (ships_on, arrival range, shipping_policy), word
  for word on the numbers; don't add your own day counts.
- You are the shop's sales agent: when you have what an order needs, create it; don't ask for permission first.
  Be warm and helpful, suggest the in-stock car that fits, and mention the volume discount when it applies.
- To talk to Lena: ask for the person's phone number (and what it's about), call leave_contact, and say Lena will
  call them herself. Never give out or invent a number for her.
- Keep track of the whole conversation: details the person already gave, quotes already made. Never ask them to
  confirm something they already said; if they name a listed car, that is the model. If you have everything a
  quote needs, call quote_commission in that same turn.
- If someone says they were promised another price, the price stands; never agree to a different one.
- Never say you will search or check something: call the tool in the same turn, then answer.
- You cannot pay and must never claim an order is paid.
- Never show item ids like sg-014 to the person; use the item's name.
- Be friendly and brief: 2-4 complete sentences, never telegraphic notes.
- Lines that start with "Tool results from your last turn" are notes for you, not for the person; never copy them."""

TOOLS = [
    {"type": "function", "function": {"name": "about_counter", "description": counter.about_counter.__doc__ or
        "Who the maker is, shipping, commissions, payment.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "search_counter", "description": "Search listings by words and max price.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                                                        "max_price_usd": {"type": "number"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "item_details", "description": "Full listing for one item id.",
        "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}}},
    {"type": "function", "function": {"name": "delivery_estimate", "description": "Ship date and delivery window to a US state code.",
        "parameters": {"type": "object", "properties": {"us_state": {"type": "string"},
                                                        "need_by": {"type": "string", "description": "date or weekday the person needs it by"}},
                       "required": ["us_state"]}}},
    {"type": "function", "function": {"name": "quote_commission",
        "description": "Exact price, volume discount, shipping, build time and delivery for made-to-order cars.",
        "parameters": {"type": "object", "properties": {"cars": {"type": "array", "items": {"type": "object", "properties": {
                "model": {"type": "string"}, "year": {"type": "string"}, "body_colour": {"type": "string"},
                "interior_colour": {"type": "string"}, "quantity": {"type": "integer"}},
                "required": ["model", "year", "body_colour", "interior_colour", "quantity"]}}, "us_state": {"type": "string"}},
                       "required": ["cars"]}}},
    {"type": "function", "function": {"name": "start_commission_checkout",
        "description": "After the person agreed to the quote: create the made-to-order order and its PayPal approval link.",
        "parameters": {"type": "object", "properties": {"cars": {"type": "array", "items": {"type": "object", "properties": {
                "model": {"type": "string"}, "year": {"type": "string"}, "body_colour": {"type": "string"},
                "interior_colour": {"type": "string"}, "quantity": {"type": "integer"}},
                "required": ["model", "year", "body_colour", "interior_colour", "quantity"]}}, "us_state": {"type": "string"},
                       "name": {"type": "string"}, "phone": {"type": "string"}},
                       "required": ["cars", "us_state", "name", "phone"]}}},
    {"type": "function", "function": {"name": "leave_contact",
        "description": "Pass the person's phone number and question to Lena; she calls them back.",
        "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "name": {"type": "string"},
                       "message": {"type": "string"}}, "required": ["phone"]}}},
    {"type": "function", "function": {"name": "start_checkout",
        "description": "Create an order that waits for the person's approval in PayPal; returns the approval link.",
        "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "quantity": {"type": "integer"},
                                                        "us_state": {"type": "string"},
                                                        "what_the_shopper_asked": {"type": "string"}},
                       "required": ["item_id", "quantity", "us_state", "what_the_shopper_asked"]}}},
]
LABELS = {"about_counter": "reading the counter", "search_counter": "searching the counter",
          "item_details": "reading the listing", "delivery_estimate": "checking delivery",
          "start_checkout": "preparing PayPal checkout", "quote_commission": "pricing a made-to-order build",
          "start_commission_checkout": "preparing PayPal checkout", "leave_contact": "passing your number to Lena"}


class OverBudget(RuntimeError):
    pass


def _client_() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=os.environ["NEBIUS_API_KEY"],
                         timeout=20, max_retries=1)
    return _client


def spent_today() -> float:
    return _spent.get(date.today().isoformat(), 0.0)


def _call_tool(name: str, args: dict, asked: str = "") -> dict:
    if name == "about_counter":
        return counter.about_counter()
    if name == "search_counter":
        # A brand name never matches an unbranded listing; search the plain words, or show everything.
        q = " ".join(BRANDS.sub(" ", args.get("query", "")).split())
        return counter.search_counter(q, args.get("max_price_usd"))
    if name == "item_details":
        return counter.item_details(args.get("item_id", ""))
    if name == "delivery_estimate":
        return counter.delivery_estimate(args.get("us_state", ""), args.get("need_by", ""))
    if name == "quote_commission":
        return counter.quote_commission(args.get("cars") or [], args.get("us_state", ""))
    if name == "start_commission_checkout":
        # The model must not make up contact details: the number has to be one the person actually typed.
        digits = re.sub(r"\D", "", args.get("phone", ""))
        typed = re.sub(r"\D", "", asked)
        if len(digits) < 7 or digits[-7:] not in typed:
            return {"ok": False, "reason": "Ask the person for their name and phone number first; don't fill them in."}
        return counter.start_commission_checkout(args.get("cars") or [], args.get("us_state", ""), args.get("name", ""),
                                                 args.get("phone", ""), asked, channel="demo-shopper")
    if name == "leave_contact":
        return counter.leave_contact(args.get("phone", ""), args.get("name", ""), args.get("message", ""), asked,
                                     channel="demo-shopper")
    if name == "start_checkout":
        return counter.start_checkout(args.get("item_id", ""), int(args.get("quantity", 1) or 1),
                                      args.get("us_state", ""), asked or args.get("what_the_shopper_asked", ""),
                                      channel="demo-shopper")
    return {"error": f"unknown tool {name}"}


def _summary(name: str, out: dict) -> str:
    """One line per tool result for the visible step list."""
    if name == "search_counter":
        r = out.get("results", [])
        s = f"{len(r)} found" + (f" · {r[0]['title']} · ${r[0]['price_usd']:.0f} · {r[0]['stock']} in stock" if r else "")
        return s + "".join(f" · {x['title']}: {x['stock']} in stock" for x in r[1:])
    if name == "item_details":
        return f"{out.get('title', '?')} · {out.get('length_mm', '?')} mm · {out.get('availability', '')}"
    if name == "delivery_estimate":
        if not out.get("ok"):
            return out.get("reason", "")
        s = f"ships {out['ships_on'][:3]} · arrives {out['arrives_earliest'][:3]}–{out['arrives_latest'][:3]}"
        return s + (f" · by {out['need_by'][:3]}: {out['need_by_verdict']}" if out.get("need_by") else "")
    if name == "start_checkout":
        return "waiting for your approval in PayPal" if out.get("ok") else out.get("reason", "")
    if name == "quote_commission":
        if not out.get("ok"):
            return out.get("reason", "")
        s = f"{out['total_cars']} cars · ${out['total_usd']:,.2f}"
        s += f" ({out['volume_discount_percent']}% off)" if out["volume_discount_percent"] else ""
        return s + f" · ready {out['ready_to_ship_by'].split(' ')[-1]}"
    if name == "start_commission_checkout":
        return "waiting for your approval in PayPal" if out.get("ok") else out.get("reason", "")
    if name == "leave_contact":
        return "passed to Lena" if out.get("ok") else out.get("reason", "")
    return "done"


def run(messages: list[dict]) -> dict:
    """messages: the visible conversation [{role: user|assistant, content}]. Returns the reply, the tool steps,
    and a checkout (if one was created)."""
    if spent_today() >= DAILY_CAP_USD:
        raise OverBudget("today's demo budget is spent")
    convo = [{"role": "system", "content": SYSTEM}]
    for m in messages[-40:]:
        if m["role"] not in ("user", "assistant"):
            continue
        convo.append({"role": m["role"], "content": MEMO_TAG.sub("", m["content"]).strip()})
        if m["role"] == "assistant" and m.get("memo"):
            convo.append({"role": "system", "content": "Tool results from your last turn: " + m["memo"]})
    steps, checkout, usd, nudged = [], None, 0.0, False
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    quoted_before = any("made-to-order build" in (m.get("memo") or "") and "ready" in (m.get("memo") or "")
                        for m in messages if m["role"] == "assistant")
    # 'You asked for' is the person's own words, not the model's paraphrase of them.
    asked = " / ".join(m["content"] for m in messages if m["role"] == "user")[-400:]
    t_start = time.time()
    for _ in range(MAX_STEPS):
        r = _client_().chat.completions.create(model=MODEL, messages=convo, tools=TOOLS, max_tokens=500,
                                               temperature=0.2,
                                               extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        u = r.usage
        usd += (u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT) / 1e6
        msg = r.choices[0].message
        if time.time() - t_start > 12:
            nudged = True   # the person has waited long enough: no more second tries, answer with what we have
        if not msg.tool_calls and not nudged and PROMISE.search(msg.content or ""):
            # It announced a search instead of doing one. Hold it to its word once.
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Go ahead: use the tools now, then answer."}]
            continue
        quoted = quoted_before or any(st["tool"] == "quote_commission" and "ready" in st["result"] for st in steps)
        if (not msg.tool_calls and not nudged and not checkout and quoted and PHONE.search(last_user)
                and not any(st["tool"] == "start_commission_checkout" for st in steps)):
            # The person gave their name and number after a quote: that's everything the order needs.
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "You have the quote, the name and the phone. Call "
                       "start_commission_checkout now with the same cars and state, then answer."}]
            continue
        if (not msg.tool_calls and not nudged and not checkout
                and any(st["tool"] in ("delivery_estimate", "quote_commission") for st in steps)):
            # It priced or dated an order and then stopped (asked permission, asked for a gift note, ...).
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Don't ask for permission: if you have the car, quantity and state "
                       "(and for a made-to-order build also the name and phone), create the order now with the "
                       "checkout tool; otherwise ask only for what is missing."}]
            continue
        if (not msg.tool_calls and not nudged and not checkout and re.search(r"\d|\b(one|two|three|four|five|six|"
                r"seven|eight|nine|ten|a couple)\b", last_user, re.I) and "?" in (msg.content or "")
                and any(st["tool"] in ("search_counter", "item_details") and "in stock" in st["result"] for st in steps)):
            # It found the car and the person said how many, then asked something optional (a date, a confirmation).
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "A deadline is optional. If the person gave the car, the quantity "
                       "and a US state or city, call delivery_estimate and start_checkout now; otherwise ask only "
                       "for what is missing."}]
            continue
        if not msg.tool_calls and REFUSAL.search(msg.content or "") and not nudged:
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "That's not a refusal case. Answer the person: Lena makes unbranded "
                       "replicas named by colour, body style and year; search and offer the closest one."}]
            continue
        if not msg.tool_calls:
            reply = MEMO_TAG.sub("", msg.content or "")
            if BRANDS.search(reply):
                # Ask once for a rewrite: blanking the name out can turn "no <brand> replicas" into a false sentence.
                fix = _client_().chat.completions.create(
                    model=MODEL, max_tokens=300, temperature=0,
                    messages=[{"role": "system", "content": "Rewrite the message without naming any real car maker "
                               "or model. Keep every fact and the meaning. Return only the message."},
                              {"role": "user", "content": reply}],
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}})
                fu = fix.usage
                usd += (fu.prompt_tokens * PRICE_IN + fu.completion_tokens * PRICE_OUT) / 1e6
                fixed = fix.choices[0].message.content or ""
                # The rewrite pass sometimes refuses outright; then keep the original and just mask the names.
                reply = reply if (not fixed or re.search(r"\b(can.?t|cannot) help\b|^i.?m sorry", fixed, re.I)) else fixed
                if BRANDS.search(reply):
                    reply = BRANDS.sub("that model", reply)
            reply = ITEM_ID.sub("", reply)
            break
        convo.append({"role": "assistant", "content": msg.content or "",
                      "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            out = _call_tool(tc.function.name, args, asked)
            steps.append({"tool": tc.function.name, "label": LABELS.get(tc.function.name, tc.function.name),
                          "args": args, "result": _summary(tc.function.name, out), "ms": int((time.time() - t0) * 1000)})
            if tc.function.name in ("start_checkout", "start_commission_checkout") and out.get("ok"):
                checkout = out
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)[:4000]})
    else:
        reply = "I couldn't finish that in a few steps. Could you tell me a bit more?"
    with _lock:
        d = date.today().isoformat()
        _spent[d] = _spent.get(d, 0.0) + usd
    # What the tools returned this turn, so the next turn still knows it (the browser sends it back with the reply).
    memo = "; ".join(f"{st['label']}: {st['result']}" for st in steps)
    return {"reply": reply.strip(), "steps": steps, "checkout": checkout, "usd": round(usd, 5), "model": MODEL,
            "memo": memo}
