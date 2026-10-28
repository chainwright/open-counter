"""The built-in demo shopper: a stranger's AI agent shopping Lena's counter with the same tools any outside agent
gets over MCP. NVIDIA Nemotron on Nebius Token Factory with native tool calls, a step budget, a daily spend cap.

It can find, compare and prepare a checkout. It cannot pay: start_checkout returns a PayPal link for the human."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime

from openai import OpenAI

from . import counter, shop

MODEL = os.environ.get("SHOPPER_MODEL", "nvidia/nemotron-3-super-120b-a12b")
PRICE_IN, PRICE_OUT = 0.30, 0.90  # USD per 1M tokens, Token Factory catalog
DAILY_CAP_USD = float(os.environ.get("SHOPPER_DAILY_CAP_USD", "1.00"))
MAX_STEPS = 8
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
LINK_CLAIM = re.compile(r"paypal (link|button|checkout)|link below|approve (the |your )?(payment|order)|approval link|"
                        r"updated (the|your) (order|shipment)|order (is )?ready|order approved|sandbox\.paypal|checkoutnow|link:|orders? ready|"
                        r"approve (it )?(via|in|with|here)|we.?ll update|i.?ve updated|updated order",
                        re.I)
PHONE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")
MEMO_TAG = re.compile(r"\n?\[(what the tools returned|tool results)[^\]]*\]", re.I)
REFUSAL = re.compile(r"^\s*(i.?m sorry,?\s*)?(but\s*)?i (can.?t|cannot) (help|assist) with (that|this)", re.I)
ITEM_ID = re.compile(r"\s*\(?\bsg[-‑–]\d+\b\)?", re.I)
PROMISE = re.compile(r"\b(let me|let's|lets|i'll|i will|we'll|we will|i am going to|i'm going to|we need to)\b.{0,40}"
                     r"\b(search|check|look|find|see|quote|place|send|submit|call|get|calculate|price|prepare|create|confirm|pull|fetch|verify|retry|work out)\b|\bsearching\b|"
                     r"\b(now |i.?m )(creating|placing|setting up|generating|preparing|quoting|checking|calculating|pricing)\b|"
                     r"\bproceeding with\b|\busing (the )?provided details\b", re.I)

SYSTEM = """You are the sales agent of Small Garage: Lena builds 1:43 replica cars by hand in Columbus, Ohio. You talk to
one shopper, in the language of their last message, warmly and briefly (2-4 sentences).

How to answer
1. FIRST answer exactly what they asked, in the first sentence: yes/no, the price, the date, the policy. Then move
   the order forward. Never answer a question with only a request for their details.
2. Facts only from the tools (prices, stock, totals, discounts, dates, build times). Never compute or invent one.
   Never say you will check something: call the tool in the same turn. Never mention tool names or notes to yourself.
3. Prices are fixed. Discounts exist only for made-to-order builds (10% from 10 cars, 15% from 25); say so kindly
   if asked, and never agree to another price.
4. Shipping: every US state including Hawaii and Alaska (check with delivery_estimate; a city is enough to know the
   state). Outside the US: not yet. If they gave a date, pass it as need_by and say the verdict plainly. There is one
   shipping method (USPS Ground Advantage): never offer faster or express shipping, gift wrap or anything not in the
   tools; if they need it sooner, say so honestly and offer what exists.
5. No real car makers or models: Lena makes unbranded replicas named by colour, body style and year; offer the
   closest listed car. Never refuse over a brand name.

Selling from stock
- Any quantity up to the stock shown. If they want more than the stock, say how many are in stock and offer both: buy
  those now, or have all of them made to order (with the volume discount). Several different cars go into ONE start_checkout call (items).
- As soon as cars, quantity and state are clear, call start_checkout: until the person's details are there it creates
  nothing and returns the total, dates and what to ask for. Give the total and dates, and ask in ONE message for
  what's missing: first and last name, phone, email, and street, city and ZIP. Details given earlier count; never ask
  twice. When everything is there, call start_checkout with customer right away (no "shall I?").
- If they change the cart, call start_checkout again with the new cars; the new button replaces the old one.

Made to order (not on the shelf, another colour, or more than the stock)
- Collect only what's missing, taking what they already said: which car, the year of the real car, body colour,
  interior colour, how many; anything extra (stripes, wheels, a plate) goes into details. Then quote_commission (no
  state needed) and give total, discount, build time and ready date. Then ask in one message for name, phone, email
  and full address, and call start_commission_checkout with them. PayPal emails an invoice: half now, the rest
  before it ships.

Always
- A stock order and a made-to-order build are separate checkouts. Never type a payment link or say an order is
  paid or approved: the PayPal button appears under your message. When an order is created, keep the message short;
  the receipt card lists every line.
- Never write personal details the person didn't type, and don't repeat their address back.
- Talking to Lena: take their phone number and what it's about, call leave_contact; she calls them. Never give a number.
- The shop asks about news emails itself after the first order; if they bring it up, call marketing_consent.
- Never ask for the make or brand of a real car: Lena works from body style, year and colours.
- Never show item ids like sg-014. Lines starting with "Tool results from your last turn" are notes for you only."""

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
                "interior_colour": {"type": "string"}, "quantity": {"type": "integer"},
                "details": {"type": "string", "description": "Anything else they asked for, in their words: stripes, wheels, a plate"}},
                "required": ["model", "year", "body_colour", "interior_colour", "quantity"]}}, "us_state": {"type": "string"}},
                       "required": ["cars"]}}},
    {"type": "function", "function": {"name": "start_commission_checkout",
        "description": "After the person agreed to the quote: create the made-to-order order and its PayPal approval link.",
        "parameters": {"type": "object", "properties": {"cars": {"type": "array", "items": {"type": "object", "properties": {
                "model": {"type": "string"}, "year": {"type": "string"}, "body_colour": {"type": "string"},
                "interior_colour": {"type": "string"}, "quantity": {"type": "integer"},
                "details": {"type": "string", "description": "Anything else they asked for, in their words: stripes, wheels, a plate"}},
                "required": ["model", "year", "body_colour", "interior_colour", "quantity"]}}, "us_state": {"type": "string"},
                       "name": {"type": "string"}, "phone": {"type": "string"}, "customer": {"type": "object", "description": "Exactly as the person typed it.", "properties": {
                "full_name": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
                "address_line_1": {"type": "string"}, "address_line_2": {"type": "string"}, "city": {"type": "string"},
                "state": {"type": "string"}, "postal_code": {"type": "string"}},
                "required": ["full_name", "phone", "email", "address_line_1", "city", "state", "postal_code"]},},
                       "required": ["cars", "us_state", "name", "phone", "customer"]}}},
    {"type": "function", "function": {"name": "marketing_consent",
        "description": "Record the person's own yes or no to emails from Lena about new models and offers.",
        "parameters": {"type": "object", "properties": {"email": {"type": "string"}, "agrees": {"type": "boolean"}},
                       "required": ["email", "agrees"]}}},
    {"type": "function", "function": {"name": "leave_contact",
        "description": "Pass the person's phone number and question to Lena; she calls them back.",
        "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "name": {"type": "string"},
                       "message": {"type": "string"}}, "required": ["phone"]}}},
    {"type": "function", "function": {"name": "start_checkout",
        "description": ("Create ONE order that waits for the person's approval in PayPal; returns the approval link. "
                        "Several different cars: pass them all in items, in a single call."),
        "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "quantity": {"type": "integer"},
                                                        "items": {"type": "array", "items": {"type": "object", "properties": {
                                                            "item_id": {"type": "string"}, "quantity": {"type": "integer"}},
                                                            "required": ["item_id", "quantity"]}},
                                                        "us_state": {"type": "string"}, "customer": {"type": "object", "description": "Exactly as the person typed it.", "properties": {
                "full_name": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
                "address_line_1": {"type": "string"}, "address_line_2": {"type": "string"}, "city": {"type": "string"},
                "state": {"type": "string"}, "postal_code": {"type": "string"}},
                "required": ["full_name", "phone", "email", "address_line_1", "city", "state", "postal_code"]},
                                                        "what_the_shopper_asked": {"type": "string"}},
                       "required": ["us_state", "what_the_shopper_asked", "customer"]}}},
]
LABELS = {"about_counter": "reading the counter", "search_counter": "searching the counter",
          "item_details": "reading the listing", "delivery_estimate": "checking delivery",
          "start_checkout": "preparing PayPal checkout", "quote_commission": "pricing a made-to-order build",
          "start_commission_checkout": "preparing PayPal checkout", "leave_contact": "passing your number to Lena",
          "marketing_consent": "noting your email preference"}


class OverBudget(RuntimeError):
    pass


def _client_() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=os.environ["NEBIUS_API_KEY"],
                         timeout=20, max_retries=1)
    return _client


def spent_today() -> float:
    if not _spent:   # first call after a restart: the cap survives deploys, it's kept on the data disk
        _spent.update(shop._json("spend.json", {}))
    return _spent.get(date.today().isoformat(), 0.0)


def add_spend(usd: float):
    """Model spend for the daily cap, written to disk so a restart or a deploy doesn't reset it."""
    with _lock:
        spent_today()
        d = date.today().isoformat()
        _spent[d] = round(_spent.get(d, 0.0) + usd, 6)
        for k in [k for k in _spent if k < d][:-30]:   # keep a month of days
            _spent.pop(k)
        shop._save_json("spend.json", _spent)


def _call_tool(name: str, args: dict, asked: str = "", typed: str = "") -> dict:
    if name == "about_counter":
        return counter.about_counter()
    if name == "search_counter":
        # A brand name never matches an unbranded listing; search the plain words, or show everything.
        q = " ".join(BRANDS.sub(" ", args.get("query", "")).split())
        return counter.search_counter(q, args.get("max_price_usd"))
    if name == "item_details":
        return counter.item_details(args.get("item_id", ""))
    if name == "delivery_estimate":
        # the shopper's own deadline ("by next Friday") is always checked, even if the model forgot to pass it
        return counter.delivery_estimate(args.get("us_state", ""), args.get("need_by", "") or shop.deadline_in(typed))
    if name == "quote_commission":
        return counter.quote_commission(args.get("cars") or [], args.get("us_state", ""))
    if name in ("start_checkout", "start_commission_checkout"):
        # The model must not make up who it ships to: phone, email and ZIP have to be ones the person actually typed.
        c = args.get("customer") or {}
        if name == "start_commission_checkout":
            c = {"full_name": args.get("name", ""), "phone": args.get("phone", ""), **c}
        # "same name, phone and email": take what this person already gave for an order in this chat
        prev = next((o.get("customer") for o in reversed(shop.orders())
                     if o.get("customer") and o.get("asked_for", "")[:60] == asked[:60]), None)
        if prev:
            c = {k: v for k, v in c.items() if v}
            for k in ("full_name", "phone", "email"):
                c.setdefault(k, prev[k])
            if not c.get("address_line_1"):
                for k in ("address_line_1", "address_line_2", "city", "state", "postal_code"):
                    c.setdefault(k, prev.get(k))
            args["customer"] = {**(args.get("customer") or {}), **c}
            if name == "start_commission_checkout":
                args["name"], args["phone"] = args.get("name") or c["full_name"], args.get("phone") or c["phone"]
        digits = re.sub(r"\D", "", str(c.get("phone", "")))
        zip_ = re.sub(r"\D", "", str(c.get("postal_code", "")))
        email = str(c.get("email", "")).strip().lower()
        typed_digits = re.sub(r"\D", "", typed)
        need = [lbl for lbl, ok in (
            # the name may come back transliterated (Иван Петров → Ivan Petrov); phone, email and ZIP must be typed
            ("first and last name", len(str(c.get("full_name", "")).split()) >= 2),
            ("phone number", len(digits) >= 7 and digits[-7:] in typed_digits),
            ("email (for the receipt and tracking)", bool(email) and email in typed.lower()),
            ("street address", bool(c.get("address_line_1")) and str(c.get("address_line_1", "")).split()[0] in typed),
            ("city", bool(c.get("city")) and str(c.get("city", "")).lower() in typed.lower()),
            ("ZIP code", len(zip_) == 5 and zip_ in typed)) if not ok]
        if need:
            # Not ready to create the order yet: hand back the price and dates plus exactly what to ask for, so the
            # reply quotes the order and asks for every missing detail in one go.
            out = {"ok": False, "not_created_yet": True, "ask_the_person_for": need,
                   "us_state": str(args.get("us_state", "")).upper()[:2],
                   "how": "Say the total and delivery dates below, then ask for all of these in ONE short message. "
                          "Use only what they type; never fill anything in. Don't name tools."}
            try:
                if name == "start_checkout":
                    lines = shop.order_lines(args.get("item_id", ""), int(args.get("quantity") or 0), args.get("items") or None)
                    est = shop.delivery_estimate(args.get("us_state", ""))
                    total = sum(ln["unit_usd"] * ln["qty"] for ln in lines) + shop.shop()["rules"]["shipping_usd"]
                    out["order_would_be"] = (" + ".join(f"{ln['qty']} × {ln['title']} at ${ln['unit_usd']:.2f} = "
                                                        f"${ln['qty'] * ln['unit_usd']:.2f}" for ln in lines)
                                             + f"; shipping ${shop.shop()['rules']['shipping_usd']:.2f}; total ${total:.2f}")
                    if est.get("ok"):
                        out["delivery"] = f"ships {est['ships_on']}, arrives {est['arrives_earliest']} to {est['arrives_latest']}"
                    dl = shop.deadline_in(typed)
                    if dl and est.get("ok"):
                        v = shop.delivery_estimate(args.get("us_state", ""), need_by=dl).get("need_by_verdict")
                        out["deadline_verdict"] = f"by {dl}: {v}"
            except (ValueError, KeyError, TypeError) as e:
                out["problem"] = str(e)
            return out
        if name == "start_checkout":
            # Same cars and same person as an order already waiting in this chat: hand that one back, don't duplicate.
            try:
                lines = shop.order_lines(args.get("item_id", ""), int(args.get("quantity") or 0), args.get("items") or None)
            except (ValueError, TypeError):
                lines = None
            for o in shop.orders():
                if (lines and o.get("status") == "awaiting_approval" and o.get("kind") != "commission"
                        and o.get("asked_for", "")[:60] == asked[:60] and o.get("approve_url")
                        and [(x["listing_id"], x["qty"]) for x in o.get("lines") or []] == [(x["listing_id"], x["qty"]) for x in lines]
                        and (o.get("customer") or {}).get("postal_code") == zip_):
                    return {"ok": True, "order_id": o["id"], "approve_url": o["approve_url"], "you_asked_for": o["asked_for"],
                            "you_are_approving": " + ".join(f"{x['qty']} × {x['title']} at ${x['unit_usd']:.2f}" for x in o["lines"])
                                                 + f" + ${o['shipping_usd']:.2f} shipping = ${o['total_usd']:.2f}",
                            "delivery": f"ships {o['estimate']['ships_on'].split(' ')[-1]}, estimated arrival "
                                        f"{o['estimate']['arrives_earliest'].split(' ')[-1]} to {o['estimate']['arrives_latest'].split(' ')[-1]}",
                            "ship_to": counter._ship_to(o), "receipt": counter.receipt(o),
                            "next_step": "This order already exists; show it again. Nothing is charged until they approve."}
    if name == "start_commission_checkout":
        said = next((p for p in (parse_made_to_order(u) for u in reversed(typed.split(" / "))) if p), None)
        if said and said.get("details"):
            for car in args.get("cars") or []:   # extras the person asked for (stripes…) must reach the invoice
                if isinstance(car, dict) and not car.get("details"):
                    car["details"] = said["details"]
        cars = sum(int((x or {}).get("quantity") or 0) for x in (args.get("cars") or []))
        for o in shop.orders():   # the same build for the same person in this chat already waits: show it again
            if (o.get("kind") == "commission" and o.get("status") == "awaiting_approval" and o.get("approve_url")
                    and o.get("asked_for", "")[:60] == asked[:60] and o.get("qty") == cars
                    and (o.get("customer") or {}).get("postal_code") == zip_):
                q = o["quote"]
                return {"ok": True, "order_id": o["id"], "approve_url": o["approve_url"], "you_asked_for": o["asked_for"],
                        "you_are_approving": f"{o['title']}: {q['total_cars']} × ${q['unit_usd']} = ${o['total_usd']:.2f}",
                        "delivery": f"built in {q['build_weeks']} week(s), ships {q['delivery']['ships_on']}",
                        "ship_to": counter._ship_to(o), "receipt": counter.receipt(o),
                        "next_step": "This order already exists; show it again."}
        return counter.start_commission_checkout(args.get("cars") or [], args.get("us_state", ""), args.get("name", ""),
                                                 args.get("phone", ""), asked, channel="demo-shopper",
                                                 customer=args.get("customer"))
    if name == "marketing_consent":
        email = str(args.get("email", "")).strip().lower()
        last = typed.rsplit(" / ", 1)[-1]
        # only the person's own answer counts: their email typed earlier, a clear yes/no in their last message
        if not email or email not in typed.lower() or not re.search(
                r"\b(yes|yeah|yep|sure|ok|okay|please|no|nope|not now|don.?t|no thanks)\b", last, re.I):
            return {"ok": False, "reason": "Ask them first and wait for their own yes or no."}
        return counter.marketing_consent(email, bool(args.get("agrees")), last)
    if name == "leave_contact":
        return counter.leave_contact(args.get("phone", ""), args.get("name", ""), args.get("message", ""), asked,
                                     channel="demo-shopper")
    if name == "start_checkout":
        return counter.start_checkout(args.get("item_id", ""), int(args.get("quantity", 1) or 1),
                                      args.get("us_state", ""), asked or args.get("what_the_shopper_asked", ""),
                                      channel="demo-shopper", items=args.get("items") or None,
                                      customer=args.get("customer"))
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
        if out.get("need_by"):
            d = datetime.strptime(out["need_by"].split()[-1], "%Y-%m-%d")
            s += f" · by {d.strftime('%A %b')} {d.day}: {out['need_by_verdict']}"
        return s
    if name in ("start_checkout", "start_commission_checkout") and out.get("not_created_yet"):
        dl = out.get("delivery", "")
        m = re.search(r"ships (\w+) (\d{4}-\d{2}-\d{2}), arrives (\w+) (\d{4}-\d{2}-\d{2}) to (\w+) (\d{4}-\d{2}-\d{2})", dl)
        fmt = lambda wd, iso: f"{wd} {datetime.strptime(iso, '%Y-%m-%d').strftime('%b')} {int(iso[-2:])}"
        dates = (f"ships {fmt(m.group(1), m.group(2))}, arrives {fmt(m.group(3), m.group(4))}–{fmt(m.group(5), m.group(6))} · "
                 if m else "")
        return (((out.get("order_would_be", "") + " · ") if out.get("order_would_be") else "") + dates
                + ((out["deadline_verdict"] + " · ") if out.get("deadline_verdict") else "")
                + (f"to {out['us_state']} · " if out.get("us_state") else "")
                + "needs: " + ", ".join(out["ask_the_person_for"]))
    if name == "start_checkout":
        return "waiting for your approval in PayPal" if out.get("ok") else out.get("reason", out.get("problem", ""))
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
    if name == "marketing_consent":
        return ("subscribed to news" if out.get("subscribed") else "no emails") if out.get("ok") else out.get("reason", "")
    return "done"


EMAIL_IN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ZIP_IN = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def _scrub_invented(reply: str, typed: str) -> str:
    """Personal details in the reply must be ones the person typed. A line with an email, phone or ZIP they never
    wrote is dropped (Roma 14526: the confirmation showed made-up details)."""
    t, td = typed.lower(), re.sub(r"\D", "", typed)
    out = []
    for line in reply.split("\n"):
        bad = any(e.lower() not in t for e in EMAIL_IN.findall(line))
        bad |= any(z[:5] not in td for z in ZIP_IN.findall(line) if not re.search(r"20\d\d-" + re.escape(z[:2]), line))
        bad |= any(len(re.sub(r"\D", "", p)) >= 7 and re.sub(r"\D", "", p)[-7:] not in td
                   for p in PHONE.findall(line) if not re.search(r"\d{4}-\d{2}-\d{2}", p))
        if not bad:
            out.append(line)
    return "\n".join(out).strip()


MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


def _known_amounts(convo: list[dict], messages: list[dict]) -> set[float]:
    """Every dollar amount the tools produced in this chat (this turn's tool results and earlier turns' notes),
    plus the shop's own price list. Anything else in a reply was made up by the model."""
    text = " ".join(str(c.get("content") or "") for c in convo if c.get("role") in ("tool", "system"))
    text += " " + " ".join(str(m.get("memo") or "") for m in messages)
    vals = {float(x.replace(",", "")) for x in MONEY.findall(text)}
    vals |= {float(x) for x in re.findall(r'"(?:price_usd|unit_usd|unit|sum|total|total_usd|shipping_usd|subtotal_usd|'
                                          r'discount_usd|deposit_usd|commission_usd)": (-?\d+(?:\.\d+)?)', text)}
    s = shop.shop()
    vals |= {float(l["price_usd"]) for l in s["listings"]} | {float(s["rules"]["shipping_usd"]), float(s["rules"]["commission_usd"])}
    return {round(abs(v), 2) for v in vals}


NEWS_Q = "One more thing: would you like Lena to email you when new models or offers come out? (yes / no)"
YES = re.compile(r"^\W*(yes|yeah|yep|sure|ok|okay|please|absolutely|of course|why not|да|конечно|хочу|давайте|ага)", re.I)
NO = re.compile(r"^\W*(no|nope|nah|not now|no thanks|don.?t|not really|нет|не надо|не нужно|не хочу)", re.I)
NEWS_Q_RU = "И ещё: хотите, чтобы Лена писала вам на почту, когда появятся новые модели или акции? (да / нет)"
OPT_IN = re.compile(r"\b(e-?mail me|send me|sign me up|subscribe|keep me (posted|updated)|add me)\b.{0,60}"
                    r"\b(new|news|model|offer|update|deal|release)", re.I)
OPT_OUT = re.compile(r"\b(no|don.?t|stop|unsubscribe|never)\b.{0,20}\b(e-?mails?|news|newsletter|updates)\b", re.I)


def _news_answer(messages: list[dict]) -> dict | None:
    """The newsletter question is asked by the shop itself, once, after the first order; a plain yes/no to it is
    recorded in code, in the person's own words, without a model call (and without touching the orders)."""
    if len(messages) < 2 or messages[-1]["role"] != "user" or messages[-2]["role"] != "assistant":
        return None
    said = messages[-1]["content"].strip()
    if NEWS_Q in messages[-2]["content"] or NEWS_Q_RU in messages[-2]["content"]:
        agrees = True if YES.search(said) else False if NO.search(said) else None
    else:   # they bring it up themselves later: "email me when new models come out", "no emails please"
        agrees = (False if OPT_OUT.search(said) else True if OPT_IN.search(said) else None)
    if agrees is None:
        return None
    typed = " ".join(m["content"] for m in messages if m["role"] == "user")
    email = next((e for e in EMAIL_IN.findall(typed)[::-1]), "")
    out = counter.marketing_consent(email, agrees, said) if email else {"ok": False}
    if not out.get("ok"):
        return None
    ru = bool(re.search(r"[а-яё]", said, re.I))
    reply = (("Готово, вы в списке Лены. Она пишет, только когда есть что-то новое. Чем ещё помочь?" if ru else
              "Done, you're on Lena's list. She only writes when there's something new. Anything else I can help with?")
             if agrees else ("Хорошо, писем не будет. Чем ещё помочь?" if ru else "No problem, no emails. Anything else I can help with?"))
    step = {"tool": "marketing_consent", "label": LABELS["marketing_consent"], "args": {"agrees": agrees},
            "result": "subscribed to news" if agrees else "no emails", "ms": 0}
    return {"reply": reply, "steps": [step], "checkout": None, "usd": 0.0, "model": "rule", "memo": f"news: {step['result']}"}


TOOL_NAME = re.compile(r"\b(start_checkout|quote_commission|start_commission_checkout|delivery_estimate|leave_contact|"
                       r"search_counter|item_details|about_counter|marketing_consent|order_status)\b")
SELF_TALK = re.compile(r"\b(let'?s (ask|respond|reply|check|see|tell)|we need (car|the|to ask)|the (user|person|shopper) "
                       r"(wants|asked|said|is)|i should (ask|respond|reply)|need to ask (for|them)|start_checkout|"
                       r"quote_commission|start_commission_checkout|delivery_estimate|leave_contact|search_counter|run the tool|call the tool|the tool|"
                       r"checkout calculation|инструмент\w*|данные как есть|передаём его|ask for (all|the) missing|we still lack|"
                       r"in one message\.)\b|\[tool[^\]]*\]", re.I)


def _polish(reply: str, last_user: str) -> tuple[str, float]:
    """Last pass on the words only: a reply must speak to the shopper (no notes to itself) and in their language.
    One cheap rewrite when needed; the facts and numbers are kept exactly."""
    cyr = bool(re.search(r"[а-яё]", last_user, re.I))
    wrong_lang = cyr and not re.search(r"[а-яё]", reply, re.I)
    if not (SELF_TALK.search(reply) or wrong_lang):
        return reply, 0.0
    task = ("Below is a message the SHOP ASSISTANT wrote TO a shopper. Rewrite it as that same assistant's direct, "
            "friendly message to the shopper; never write as the shopper, never add names, numbers or details. "
            "Remove any notes the assistant "
            "wrote to itself. Keep every fact, number, date and question exactly. "
            + ("Write it in Russian. " if cyr else "Keep its language. ")
            + "Return only the reply.")
    r = _client_().chat.completions.create(
        model=MODEL, max_tokens=500, temperature=0,
        messages=[{"role": "system", "content": task + " Do not quote or repeat the shopper's message."},
                  {"role": "user", "content": reply}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    u = r.usage
    out = (r.choices[0].message.content or "").rsplit("</think>", 1)[-1].strip() or reply
    # last resort: drop any sentence that still names a tool
    out = " ".join(x for x in re.split(r"(?<=[.!?])\s+", out) if not TOOL_NAME.search(x)) or out
    return out, (u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT) / 1e6


_COLOURS = {"grey": "grey", "gray": "grey", "сер": "grey", "black": "black", "чёрн": "black", "черн": "black",
            "white": "white", "бел": "white", "red": "red", "красн": "red", "blue": "blue", "син": "blue", "голуб": "light blue",
            "green": "green", "зелён": "green", "зелен": "green", "yellow": "yellow", "жёлт": "yellow", "желт": "yellow",
            "orange": "orange", "оранж": "orange", "brown": "brown", "коричн": "brown", "tan": "tan", "beige": "beige",
            "беж": "beige", "silver": "silver", "серебр": "silver", "cream": "cream", "кремов": "cream", "purple": "purple",
            "фиолет": "purple", "burgundy": "burgundy", "бордов": "burgundy"}
_STYLES = {"rear-engine": "rear-engine coupe", "rear engine": "rear-engine coupe", "muscle": "muscle coupe",
           "fastback": "fastback", "фастб": "fastback", "convertible": "convertible", "кабриол": "convertible",
           "coupe": "coupe", "coupé": "coupe", "купе": "coupe"}
_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "одн": 1, "две": 2, "два": 2, "три": 3, "четыр": 4, "пять": 5, "шесть": 6, "семь": 7, "восем": 8, "девять": 9,
         "десять": 10, "дюжин": 12}


def parse_made_to_order(text: str) -> dict | None:
    """A made-to-order spec written in plain words (English or Russian), read in code so a quote never depends on the
    model noticing it: body style, year, body colour, interior colour, quantity, extras. None if anything is missing."""
    t = text.lower()
    style = next((v for k, v in _STYLES.items() if k in t), None)
    year = re.search(r"\b(19[2-9]\d|20[0-2]\d)\b", t)
    inner = re.search(r"(\w+)\s+(?:interior|inside|салон\w*)|(?:interior|inside|салон\w*)\s*(?:is\s*|-\s*)?(\w+)", t)
    in_col = None
    if inner:
        w = inner.group(1) or inner.group(2) or ""
        in_col = next((v for k, v in _COLOURS.items() if w.startswith(k)), None)
    body = None
    bm = re.search(r"(\w+)\s+(?:body|кузов\w*)|(?:body|кузов\w*)\s+(\w+)", t)
    if bm:
        w = bm.group(1) or bm.group(2) or ""
        body = next((v for k, v in _COLOURS.items() if w.startswith(k)), None)
    for m in ([] if body else re.finditer(r"[a-zа-яё]+", t)):
        w = m.group(0)
        if inner and inner.start() <= m.start() <= inner.end():
            continue
        body = next((v for k, v in _COLOURS.items() if w.startswith(k)), None)
        if body:
            break
    qty = re.search(r"\b(\d{1,3})\s*(?:x\b|×|pcs|pieces|cars|of them|штук|шт|машин)", t)
    q = int(qty.group(1)) if qty else next((n for k, n in _NUMS.items() if re.search(r"\b" + k + r"\w*\s+(штук|шт|машин|of them|cars)", t)
                                             or re.search(r"(of them|штук)\W+" + k, t)), None)
    if q is None:
        q = next((n for k, n in _NUMS.items() if re.search(r"\b" + k + r"\w*\b", t) and k in ("две", "два", "two", "три", "three")), None)
    extras = re.search(r"((?:two|2|две|с двумя)\s+\w+\s+(?:stripes|полос\w*)|(?:racing )?stripes|полос\w+)", t)
    if not (style and year and body and in_col and q):
        return None
    return {"model": style, "year": year.group(1), "body_colour": body, "interior_colour": in_col, "quantity": q,
            "details": extras.group(0) if extras else ""}


US_STATE_NAMES = {n.lower() for n in (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois "
    "Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana "
    "Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming").split()} | {
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "rhode island",
    "south carolina", "south dakota", "west virginia", "puerto rico"} - {"puerto rico"}


def _must_say(reply: str, last_user: str, steps: list[dict], checkout: dict | None = None, lang_text: str = "") -> str:
    """Two answers a shopper must never miss, added in code if the model left them out: the deadline verdict, and
    the answer to 'can I get a discount?'."""
    ru = bool(re.search(r"[а-яё]", lang_text or last_user, re.I))
    ok = next((m for m in (re.search(r"by ([\w ]+): on time", st["result"]) for st in steps) if m), None)
    if ok and not re.search(r"on time|in time|arrive[sd]? (by|before)|успе", reply, re.I):
        reply = (f"Хорошая новость: успеет к сроку ({ok.group(1).strip()}). " if ru else
                 f"Good news: it arrives in time for {ok.group(1).strip()}. ") + reply
    v = next((m for m in (re.search(r"by ([\w ]+): (too late|possible, not certain)", st["result"]) for st in steps) if m), None)
    if v and not re.search(r"too late|\blate\b|won.?t (arrive|make|reach|get)|not (arrive|make|reach)|past your|miss(es)? (your|the)|"
                           r"may not|not certain|не успе|опозда", reply, re.I):
        day = v.group(1).strip()
        day = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday", "sat": "Saturday",
               "sun": "Sunday"}.get(day.lower()[:3], day) if len(day) <= 4 else day
        reply = (("По расчёту доставки к этому сроку не успеем. " if v.group(2) == "too late" else "К этому сроку успеть можно, но без гарантии. ")
                 if ru else (f"Heads-up: it won't arrive by {day}. " if v.group(2) == "too late"
                             else f"It may arrive by {day}, but that isn't certain. ")) + reply
    # the total the shopper pays, written by code from the tool, if the reply skipped it or gave a price without shipping
    pv = next((st for st in steps if st["tool"] == "start_checkout" and "total $" in st["result"]), None)
    if pv:
        tot = re.search(r"total \$([\d,.]+)", pv["result"]).group(1)
        if f"${tot}" not in reply.replace(" ", "") and f"{tot}$" not in reply.replace(" ", ""):
            reply = (f"Итого с доставкой: ${tot}. " if ru else f"Total with shipping: ${tot}. ") + reply
    st_q = re.search(r"(?:ship|deliver)\w*\s+(?:to|in)\s+([A-Za-z ]{4,20}?)\s*\?", last_user, re.I)
    if st_q and st_q.group(1).strip().lower() in US_STATE_NAMES and not re.search(r"\byes\b|\bда\b|we (do )?ship", reply, re.I):
        reply = (f"Да, Лена отправляет в {st_q.group(1).strip()}. " if ru else f"Yes, Lena ships to {st_q.group(1).strip().title()}. ") + reply
    if (re.search(r"discount|% off|\d+ ?% |cheaper|скидк|дешевл", last_user, re.I)
            and not re.search(r"discount|fixed|скидк|фиксир", reply, re.I)):
        reply = ("Цены фиксированные; скидки есть только на сборку под заказ: 10% от 10 машинок и 15% от 25. " if ru else
                 "Prices are fixed; the only discounts are on made-to-order builds: 10% from 10 cars, 15% from 25. ") + reply
    if checkout and checkout.get("receipt") and not re.search(r"\$\s?\d|\d\s?\$|\d\s?доллар|\d\s?usd", reply, re.I):
        r_ = checkout["receipt"]
        if r_.get("deposit"):
            reply = (f"Заказ готов: всего ${r_['total']:.2f}, сейчас предоплата ${r_['deposit']:.2f} по счёту PayPal ниже, остальное перед отправкой. "
                     if ru else f"Your order is ready: ${r_['total']:.2f} in total, ${r_['deposit']:.2f} deposit now through the PayPal "
                     "invoice below, the rest before it ships. ") + reply
        else:
            reply = (f"Заказ готов: всего ${r_['total']:.2f} с доставкой, кнопка PayPal ниже. " if ru else
                     f"Your order is ready: ${r_['total']:.2f} with shipping. The PayPal button is below. ") + reply
    if re.search(r"\bwhen\b|когда", last_user, re.I) and not re.search(
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.? \d|"
            r"\d{4}-\d{2}-\d{2}|понед|вторн|сред|четв|пятн|суббот|воскр|ноябр|октябр|декабр", reply, re.I):
        d = next((m for m in (re.search(r"ships (\w+ \w+ \d+), arrives (\w+ \w+ \d+)[–-](\w+ \w+ \d+)", st["result"]) for st in steps) if m), None)
        if d:
            reply = (f"Отправка: {d.group(1)}, доставка: {d.group(2)} – {d.group(3)}. " if ru else
                     f"It ships {d.group(1)} and arrives {d.group(2)} to {d.group(3)}. ") + reply
    return reply


STREET_WORDS = r"(st|street|ave|avenue|rd|road|dr|drive|blvd|ln|lane|way|ct|court|pl|place|pkwy|hwy|ул|улица|пр|просп)"
STATE_NAMES = re.compile(r"\b(" + "|".join(["alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming"]) + r")\b", re.I)


def gather_customer(user_msgs: list[str]) -> dict:
    """The person's details, assembled in code from everything they typed in this chat, in any order and over several
    messages (Roma 14629: the address came first, then name and phone, then the email, and the agent went in circles).
    Only text the person typed is used; the latest value of each field wins."""
    c: dict[str, str] = {}
    for msg in user_msgs:
        t = msg.strip()
        em = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t)
        if em:
            c["email"] = em[-1]
        ph = [p for p in PHONE.findall(t) if 10 <= len(re.sub(r"\D", "", p)) <= 12]
        if ph:
            c["phone"] = ph[-1].strip()
        rest = t
        for x in em + ph:
            rest = rest.replace(x, " ")
        zips = [z for z in re.findall(r"(?<![\d-])\d{5}(?![\d-])", rest) if shop.zip_state(z)]
        if zips:
            c["postal_code"] = zips[-1]
        parts = [x.strip(" .") for x in re.split(r"[,\n;]|\.\s+(?=[A-ZА-Я])", rest) if x.strip(" .")]
        for x in parts:   # a street: a house number and a few words ("5526 manzanita", "ship to 500 Howard St")
            sm = re.search(r"(?:^|\bto\s+|\bat\s+)(\d{2,6}[a-z]?\s+[A-Za-zА-Яа-я][\w .'#-]{1,40}?)(?:\s+\d{5})?$", x, re.I)
            if sm and not (zips and sm.group(1).split()[0] == zips[-1]):   # "95608 Carmichael" is a ZIP and a city
                c["address_line_1"] = sm.group(1).strip()
        for x in parts:   # the city sits next to the ZIP or the state
            if zips and zips[-1] in x or re.search(r"\b[A-Z]{2}\b", x) and not re.match(r"^\d", x) and x != c.get("address_line_1"):
                y = re.sub(r"\d{5}", " ", x)
                y = STATE_NAMES.sub(" ", y)
                y = re.sub(r"\b[A-Z]{2}\b", " ", y)
                y = " ".join(w for w in y.split() if not re.search(r"\d", w))
                if 2 <= len(y) <= 40 and not re.search(STREET_WORDS + r"\.?$", y, re.I) and (zips or em or ph):
                    c["city"] = y.strip()
        alone = re.fullmatch(r"\s*[A-ZА-ЯЁ][a-zа-яё'’-]+(\s+[A-ZА-ЯЁ][a-zа-яё'’-]+){1,2}\s*", t)   # a message that is just a name
        if ph or em or zips or c.get("address_line_1") or alone:
            for x in parts:   # a name: two to four words, letters only, written with capitals
                x = re.sub(r"^(my name is|i am|i'm|name:?|меня зовут|я)\s+", "", x, flags=re.I).strip()
                ws = x.split()
                if (2 <= len(ws) <= 4 and all(re.fullmatch(r"[A-Za-zА-Яа-яЁё'’-]+", w) for w in ws)
                        and all(w[0].isupper() for w in ws) and x != c.get("city")
                        and not re.search(r"\b(cars?|red|green|blue|yellow|orange|grey|gray|black|white|coupe|fastback|"
                                          r"convertible|hi|hello|thanks|yes|no|машин\w*)\b", x, re.I)
                        and not STATE_NAMES.search(x) and not re.search(STREET_WORDS + r"$", x, re.I)):
                    c["full_name"] = x
    if c.get("postal_code"):
        c["state"] = shop.zip_state(c["postal_code"]) or ""
    return c


def _cart_waiting(messages: list[dict]) -> tuple[list[dict], str] | None:
    """The cart and state of the last order the agent priced but couldn't create yet (details were missing)."""
    for m in reversed(messages):
        if m["role"] != "assistant":
            continue
        memo = m.get("memo") or ""
        if "waiting for your approval" in memo:
            return None   # an order already exists after it
        pv = re.search(r"preparing PayPal checkout: (.+?); shipping \$[\d.]+; total .*?\bto ([A-Z]{2}) · needs:", memo)
        if pv:
            items = [{"item_id": t.strip(), "quantity": int(q)} for q, t in re.findall(r"(\d+) × (.+?) at \$", pv.group(1))]
            return (items, pv.group(2)) if items else None
    return None


TURN_SECONDS = 7   # the longest a shopper waits for one answer (Roma 14635: "maximum 7")


def _fallback_reply(steps: list[dict], ru: bool) -> str:
    """Out of time: say what the tools already found, written by code, instead of making the person wait."""
    for st in reversed(steps):
        r = st["result"]
        m = re.search(r"^(.+?); shipping \$([\d.]+); total \$([\d.]+) · (ships [^·]+)·.*?needs: (.+)$", r)
        if st["tool"] == "start_checkout" and m:
            return (f"Итого ${m.group(3)} с доставкой ${m.group(2)} ({m.group(1)}); {m.group(4).strip()}. Чтобы оформить "
                    f"заказ в PayPal, пришлите одним сообщением: имя и фамилию, телефон, email, адрес с ZIP." if ru else
                    f"That's ${m.group(3)} with ${m.group(2)} shipping ({m.group(1)}); {m.group(4).strip()}. To create the "
                    f"PayPal order, send in one message: {m.group(5)}.")
        if st["tool"] in ("search_counter", "item_details") and re.search(r"\$\d+|in stock", r):
            return ((f"Вот что есть: {r}. Сколько штук и в какой штат отправить?") if ru else
                    (f"Here's what I found: {r}. How many would you like, and which US state should it go to?"))
    return ("Простите, не успела. Напишите, пожалуйста, ещё раз." if ru else "Sorry, I didn't catch that in time. Could you send it once more?")


def _one_car_meant(text: str) -> str:
    """'blue', 'red 65', "the '68": when a colour or a year fits exactly one listing, name it for the model."""
    low = text.lower()
    colours = [w for w in ("green", "blue", "orange", "yellow", "red", "зелён", "зелен", "син", "оранж", "жёлт", "желт", "красн")
               if w in low]
    years = re.findall(r"(?<![\d-])(?:19)?(6[0-9]|7[0-9])\b(?!-)", low)
    if not colours and not years:
        return ""
    ru = {"зелён": "green", "зелен": "green", "син": "blue", "оранж": "orange", "жёлт": "yellow", "желт": "yellow", "красн": "red"}
    fit = [x for x in shop.shop()["listings"]
           if all(ru.get(c, c) in x["title"].lower() for c in colours) and all(y in x["title"][-2:] for y in years)]
    return f"{fit[0]['title']} (item_id {fit[0]['id']}, ${fit[0]['price_usd']:.0f}, {fit[0]['stock']} in stock)" if len(fit) == 1 else ""


def run(messages: list[dict], visitor: str = "") -> dict:
    """messages: the visible conversation [{role: user|assistant, content}]. Returns the reply, the tool steps,
    and a checkout (if one was created)."""
    answered = _news_answer(messages)
    if answered:
        return answered
    if spent_today() >= DAILY_CAP_USD:
        raise OverBudget("today's demo budget is spent")
    # The live shelf with ids, every turn: across turns the model otherwise forgets ids and invents one.
    shelf = "; ".join(f"{x['id']} = {x['title']}, ${x['price_usd']:.0f}, {x['stock']} in stock"
                      for x in shop.shop()["listings"])
    lessons = shop.active_lessons(visitor=visitor)
    # Lena's own lessons from reading past chats; the rules above still win if a note ever conflicts with them
    taught = ("\nLena's notes from reading earlier chats (follow them unless they conflict with the rules above):\n- "
              + "\n- ".join(lessons)) if lessons else ""
    convo = [{"role": "system", "content": SYSTEM + taught + "\nThe shelf right now (use these item_id values): " + shelf}]
    for m in messages[-40:]:
        if m["role"] not in ("user", "assistant"):
            continue
        convo.append({"role": m["role"], "content": MEMO_TAG.sub("", m["content"]).strip()})
        if m["role"] == "assistant" and m.get("memo"):
            convo.append({"role": "system", "content": "Tool results from your last turn: " + m["memo"]})
    steps, checkout, usd, nudges = [], None, 0.0, 2
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    quoted_before = any("made-to-order build" in (m.get("memo") or "") and "ready" in (m.get("memo") or "")
                        for m in messages if m["role"] == "assistant")
    # 'You asked for' is the person's own words, not the model's paraphrase of them.
    typed = " / ".join(m["content"] for m in messages if m["role"] == "user")
    asked = typed[-400:]
    # the conversation's language: a message that is only a name and an address doesn't switch it
    lang_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"
                      and len(re.findall(r"[а-яё]", m["content"], re.I)) + len(re.findall(r"[a-z]", m["content"], re.I)) > 0
                      and (re.search(r"[а-яё]{3,}", m["content"], re.I) and not PHONE.search(m["content"])
                           or not PHONE.search(m["content"]))), last_user)
    t_start = time.time()
    # The agent priced a cart earlier and asked for the person's details; once everything has been typed (in any
    # order, over several messages), the order is made here in code, not left to the model to put together.
    by_code = False
    waiting = _cart_waiting(messages)
    if waiting:
        cust = gather_customer([m["content"] for m in messages if m["role"] == "user"])
        items, st = waiting
        # only when the address is in the state that was priced; otherwise the person is asked which one is right
        if all(cust.get(k) for k in ("full_name", "phone", "email", "address_line_1", "city", "postal_code", "state")) \
                and cust["state"] == st:
            args = {"items": items, "us_state": st, "customer": cust, "what_the_shopper_asked": asked}
            t0 = time.time()
            out = _call_tool("start_checkout", args, asked, typed)
            if out.get("ok"):
                steps.append({"tool": "start_checkout", "label": LABELS["start_checkout"], "args": args,
                              "result": _summary("start_checkout", out), "ms": int((time.time() - t0) * 1000)})
                for o in shop.orders():   # only the newest stock order from this chat can be paid
                    if (o["id"] != out["order_id"] and o.get("kind") != "commission" and o["status"] == "awaiting_approval"
                            and o.get("asked_for", "")[:60] == asked[:60]):
                        shop.update_order(o["id"], status="replaced", replaced_by=out["order_id"])
                checkout, by_code = out, True
                ru = re.search(r"[а-яё]", lang_text, re.I)
                reply = _must_say(("Спасибо, всё есть. " if ru else "Thanks, that's everything. ")
                                  + (f"Отправлю на: {out.get('ship_to', '')}." if ru else f"It ships to {out.get('ship_to', '')}."),
                                  last_user, steps, checkout, lang_text)
    # One colour or one year that fits a single car on the shelf ("a blue one", "the red '65"): that's the car.
    hint = _one_car_meant(last_user)
    if hint:
        convo.append({"role": "system", "content": f"The person means {hint}: it is the only car on the shelf that "
                      "fits what they said. Offer it directly with its price and stock; don't ask which model."})
    for _ in range(0 if by_code else MAX_STEPS):
        left = TURN_SECONDS - (time.time() - t_start)
        if left < 1.5:
            # the person has waited long enough: answer with what the tools already found instead of thinking on
            reply = _must_say(_fallback_reply(steps, bool(re.search(r"[а-яё]", lang_text, re.I))),
                              last_user, steps, checkout, lang_text)
            by_code = True
            break
        try:
            r = _client_().with_options(timeout=min(20, left), max_retries=0).chat.completions.create(
                model=MODEL, messages=convo, tools=TOOLS, max_tokens=500, temperature=0.2,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        except Exception:   # the model host was slow or failed: say what we have, never an endless wait
            reply = _must_say(_fallback_reply(steps, bool(re.search(r"[а-яё]", lang_text, re.I))),
                              last_user, steps, checkout, lang_text)
            by_code = True
            break
        u = r.usage
        usd += (u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT) / 1e6
        msg = r.choices[0].message
        if msg.content and "</think>" in msg.content:
            # the model sometimes writes its private reasoning before the answer even with thinking off: drop it
            msg.content = msg.content.rsplit("</think>", 1)[-1].strip()
        if msg.content:
            msg.content = re.sub(r"^\s*<think>.*", "", msg.content, flags=re.S) if msg.content.lstrip().startswith("<think>") else msg.content
        if time.time() - t_start > TURN_SECONDS - 3:
            nudges = 0   # the person has waited long enough: no more second tries, answer with what we have
        if not msg.tool_calls and nudges > 0 and PROMISE.search(msg.content or ""):
            # It announced a search instead of doing one. Hold it to its word once.
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Go ahead: use the tools now, then answer."}]
            continue
        quoted = quoted_before or any(st["tool"] == "quote_commission" and "ready" in st["result"] for st in steps)
        if (not msg.tool_calls and nudges > 0 and not checkout and quoted
                and (PHONE.search(last_user) or re.search(r"\b\d{5}\b|@", last_user))
                and not any(st["tool"] == "start_commission_checkout" for st in steps)):
            # The person gave their name and number after a quote: that's everything the order needs.
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "If the person has now given name, phone, email and the full "
                       "address, call start_commission_checkout now with the same cars and state; otherwise ask only "
                       "for what is missing."}]
            continue
        if (not msg.tool_calls and nudges > 0 and not checkout
                and not re.search(r"e-?mail|address|phone|last name|zip", msg.content or "", re.I)
                and any(st["tool"] in ("delivery_estimate", "quote_commission") for st in steps)):
            # It priced or dated an order and then stopped (asked permission, asked for a gift note, ...).
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Don't ask for permission: if you have the cars, quantity and the "
                       "person's name, phone, email and full address, create the order now with the checkout tool; "
                       "otherwise ask in one message for everything still missing."}]
            continue
        if (not msg.tool_calls and nudges > 0 and not checkout and re.search(r"\d|\b(one|two|three|four|five|six|"
                r"seven|eight|nine|ten|a couple)\b", last_user, re.I) and "?" in (msg.content or "")
                and not re.search(r"e-?mail|address|phone|last name|zip", msg.content or "", re.I)
                and any(st["tool"] in ("search_counter", "item_details") and "in stock" in st["result"] for st in steps)):
            # It found the car and the person said how many, then asked something optional (a date, a confirmation).
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "A deadline is optional, don't ask for it. If you have the cars, "
                       "quantity, name, phone, email and full address, call start_checkout now; otherwise give the "
                       "price and delivery dates and ask in one message for every missing detail."}]
            continue
        if (not msg.tool_calls and not checkout and LINK_CLAIM.search(msg.content or "")
                and not any(st["tool"] in ("start_checkout", "start_commission_checkout") and "waiting" in st["result"]
                            for st in steps) and sum(1 for c in convo if c.get("content", "").startswith("No PayPal button")) < 1):
            # It talks about a payment link or an updated order, but no checkout exists for this turn: the button
            # under the message would be missing. Make the order now (with the final cars and state) or ask.
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "No PayPal button was created in this turn. If you have the final "
                       "cars, name, phone, email and full address, call start_checkout now (all cars in items, with "
                       "customer); otherwise ask in one message for what is missing. Never mention a link that "
                       "doesn't exist."}]
            continue
        if (not msg.tool_calls and nudges > 0 and not checkout
                and re.search(r"e-?mail|address|zip|почт|адрес|телефон", msg.content or "", re.I)
                and not re.search(r"\$\s?\d|\d\s?\$|долл", msg.content or "", re.I)):
            # It asks for the person's details but never said the price: price it first, then ask.
            nudges -= 1
            priced = any(st["tool"] in ("start_checkout", "quote_commission") for st in steps)
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": ("Lead with the total and the dates from the tool result you already have"
                       if priced else "First get the price: for cars from the shelf call start_checkout (it creates nothing "
                       "yet and returns the total and dates); for a made-to-order build call quote_commission")
                       + ". Answer their question first, then ask for the missing details in one message."}]
            continue
        if (not msg.tool_calls and nudges > 0 and re.search(r"discount|% off|\boff\b|cheaper|скидк|дешевл", last_user, re.I)
                and not re.search(r"discount|fixed|скидк|фиксир", msg.content or "", re.I)):
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "They asked about a discount: answer it first (prices are fixed; made-to-order "
                       "builds get 10% from 10 cars and 15% from 25), then continue."}]
            continue
        if (not msg.tool_calls and nudges > 0 and BRANDS.search(last_user)
                and not any(st["tool"] in ("search_counter", "item_details") for st in steps)):
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Search the counter now and offer the closest listed car by name, with its "
                       "price and stock (Lena's replicas are named by colour, body style and year)."}]
            continue
        if (not msg.tool_calls and PHONE.search(last_user) and re.search(r"lena|call|talk|speak|связ|позвон", last_user, re.I)
                and not any(st["tool"] in ("leave_contact", "start_checkout", "start_commission_checkout") for st in steps)
                and not parse_made_to_order(last_user)):
            # they asked to talk to Lena and gave a number: pass it on in code, then let the model confirm
            out = counter.leave_contact(PHONE.search(last_user).group(1), "", last_user[:300], asked, channel="demo-shopper")
            steps.append({"tool": "leave_contact", "label": LABELS["leave_contact"], "args": {}, "result": _summary("leave_contact", out), "ms": 0})
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "system", "content": "Done in code: " + json.dumps(out) + " Tell them Lena will call them back."}]
            continue
        spec = None if msg.tool_calls or checkout else parse_made_to_order(last_user)
        if spec and not any(st["tool"] in ("quote_commission", "start_commission_checkout") for st in steps) \
                and not any("made-to-order build" in (m.get("memo") or "") for m in messages if m["role"] == "assistant"):
            # the person described a made-to-order build in full: quote it in code, then let the model answer
            out = counter.quote_commission([spec], "")
            steps.append({"tool": "quote_commission", "label": LABELS["quote_commission"], "args": {"cars": [spec]},
                          "result": _summary("quote_commission", out), "ms": 0})
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "system", "content": "Quote from the shop (made to order, computed in code): " + json.dumps(out)[:2000]
                       + " Give this total, the build time and ready date now, then ask in one message for name, phone, "
                         "email and full address (street, city, state, ZIP)."}]
            continue
        verdict = next((m for m in (re.search(r"by [\w ]+: (too late|possible, not certain|on time)", st["result"])
                                     for st in steps) if m), None)
        if (not msg.tool_calls and nudges > 0 and verdict and verdict.group(1) != "on time"
                and not re.search(r"late|won.?t|not (arrive|make|reach|be there)|can.?t|might|may not|possible|not certain|no guarantee", msg.content or "", re.I)):
            # the deadline verdict is the most important fact for a gift with a date: say it, don't bury it
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": f"Tell the person plainly first: for their date the delivery verdict is "
                       f"'{verdict.group(1)}'. Then offer what's possible."}]
            continue
        said = {float(x.replace(",", "")) for x in MONEY.findall(msg.content or "")}
        known = _known_amounts(convo, messages)
        if not msg.tool_calls and nudges > 0 and said - known:
            # an amount no tool produced: the model did arithmetic (e.g. a changed cart). Price it with the tools.
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Don't compute amounts yourself. If the cart or the details changed, call "
                       "start_checkout (or quote_commission) again with the new cars to get the real total and a new PayPal "
                       "button; otherwise only repeat amounts the tools returned."}]
            continue
        if (not msg.tool_calls and nudges > 0 and lessons
                and re.search(r"can.?t answer|not sure|don.?t know|unable to answer|no information", msg.content or "", re.I)):
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Check Lena's notes in your instructions: one of them tells you what to do "
                       "here. Follow it and answer again."}]
            continue
        if not msg.tool_calls and REFUSAL.search(msg.content or "") and nudges > 0:
            nudges -= 1
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "That's not a refusal case. Answer the person: Lena makes unbranded "
                       "replicas named by colour, body style and year; search and offer the closest one."}]
            continue
        if not msg.tool_calls:
            reply = MEMO_TAG.sub("", msg.content or "")
            late = TURN_SECONDS - (time.time() - t_start) < 2.5   # no time for another model pass: fix it in code
            if BRANDS.search(reply) and late:
                reply = BRANDS.sub("that model", reply)
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
            reply = _scrub_invented(reply, typed)
            if late:   # drop notes-to-self sentences instead of a rewrite pass
                reply = " ".join(x for x in re.split(r"(?<=[.!?])\s+", reply) if not SELF_TALK.search(x)) or reply
            else:
                fixed, fusd = _polish(reply, lang_text)
                reply, usd = _scrub_invented(fixed, typed), usd + fusd
            # a final answer never says "one moment" or "let me check" (nothing happens after it), nor labels its parts
            reply = re.sub(r"\b(first|second|third|final) (sentence|answer|reply|part)\s*:\s*", "", reply, flags=re.I)
            reply = " ".join(x for x in re.split(r"(?<=[.!?])\s+", reply) if not re.match(
                r"(let me (confirm|check|fetch|retry|get|look|see|pull)|i'?ll (confirm|check|fetch|pull|look) |one moment|please (wait|hold)|"
                r"секунду|минуту|сейчас (проверю|уточню))",
                x.strip(), re.I)) or reply
            reply = _must_say(reply, last_user, steps, checkout, lang_text)
            break
        convo.append({"role": "assistant", "content": msg.content or "",
                      "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            out = _call_tool(tc.function.name, args, asked, typed)
            steps.append({"tool": tc.function.name, "label": LABELS.get(tc.function.name, tc.function.name),
                          "args": args, "result": _summary(tc.function.name, out), "ms": int((time.time() - t0) * 1000)})
            if tc.function.name in ("start_checkout", "start_commission_checkout") and out.get("ok"):
                if checkout is None and tc.function.name == "start_checkout":
                    # a changed cart: the earlier stock order from this chat is replaced, so only one button can pay
                    for o in shop.orders():
                        if (o["id"] != out["order_id"] and o.get("kind") != "commission" and o["status"] == "awaiting_approval"
                                and o.get("asked_for", "")[:60] == asked[:60]):
                            shop.update_order(o["id"], status="replaced", replaced_by=out["order_id"])
                checkout = out
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)[:4000]})
    else:
        if not by_code:
            # out of steps: keep the last real answer the model wrote rather than a canned apology
            last = next((c["content"] for c in reversed(convo) if c.get("role") == "assistant" and c.get("content")), "")
            reply = _scrub_invented(ITEM_ID.sub("", MEMO_TAG.sub("", last)), typed) or \
                "I couldn't finish that in a few steps. Could you tell me a bit more?"
    add_spend(usd)
    # What the tools returned this turn, so the next turn still knows it (the browser sends it back with the reply).
    memo = "; ".join(f"{st['label']}: {st['result']}" for st in steps)
    # after the first order with an email, the shop asks about news once (the model is told not to ask itself)
    asked_before = any(NEWS_Q in m.get("content", "") or NEWS_Q_RU in m.get("content", "") for m in messages
                       if m["role"] == "assistant")
    if asked_before:   # the shop already asked; a model-written repeat of the question is dropped
        reply = " ".join(x for x in re.split(r"(?<=[.!?])\s+", reply)
                         if not re.search(r"(news|email|e-mail|почт|рассыл).{0,40}(\?|new models|offers|новы|акци)", x, re.I)) or reply
    if checkout and checkout.get("ship_to") and not asked_before:
        reply = reply.strip() + "\n\n" + (NEWS_Q_RU if re.search(r"[а-яё]", lang_text, re.I) else NEWS_Q)
    if not reply.strip():
        reply = "Sorry, I lost my thread there. Could you say that again in a few words?"
    return {"reply": reply.strip(), "steps": steps, "checkout": checkout, "usd": round(usd, 5), "model": MODEL,
            "memo": memo}
