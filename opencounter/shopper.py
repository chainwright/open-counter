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
MEMO_TAG = re.compile(r"\n?\[(what the tools returned|tool results)[^\]]*\]", re.I)
REFUSAL = re.compile(r"^\s*(i.?m sorry,?\s*)?(but\s*)?i (can.?t|cannot) (help|assist) with (that|this)", re.I)
ITEM_ID = re.compile(r"\s*\(?\bsg[-‑–]\d+\b\)?", re.I)
PROMISE = re.compile(r"\b(let me|let's|lets|i'll|i will|we'll|we will|i am going to|i'm going to|we need to)\b.{0,40}"
                     r"\b(search|check|look|find|see|quote|place|send|submit|call)\b|\bsearching\b", re.I)

SYSTEM = """You are a shopping agent acting for one person. You are visiting Small Garage, a one-person maker of
hand-built 1:43 replica cars, through its public tools. Rules:
- Use only facts returned by the tools. Never invent a price, a date, a discount, a lead time or a quantity rule.
  Every number you say must come from a tool result in this conversation.
- Never name real car makers or models. If the person names one, say Lena makes unbranded replicas named by
  colour, body style and year, and offer the closest one (a rear-engine coupe, a fastback, a convertible). Never
  refuse the conversation over a brand name.
- In stock, up to the per-order limit (about_counter: max_per_order): check delivery to the person's US state
  (work out the state from a city yourself; pass a deadline as need_by and repeat the tool's verdict), then call
  start_checkout. PayPal collects their name and shipping address, so don't ask for those.
- More than the per-order limit, a sold-out car, or another colour: that is a commission. Call quote_commission
  with each car, colour and quantity (ask for the colour if it's missing) and the US state, then tell the person
  the total, the discount, the shipping and the ready-to-ship date exactly as returned. If they want to go ahead,
  ask for their name, email, phone and full shipping address, repeat the order back in one line, and after they
  confirm call request_commission. Say Lena replies by email and sends a PayPal invoice; nothing is charged now.
- "When will it be back?" / "when available?": call item_details for that car in the same turn and answer from its
  next_batch date. Only if next_batch is empty say no batch is planned, and offer a commission.
- As soon as you know a car (or colour) and a quantity above the per-order limit, call quote_commission in the same
  turn; it applies the limits itself, and us_state is optional (quote without it, ask for the state after).
  Don't answer with questions only.
- Before request_commission, repeat the whole order back in one line (cars, colours, quantities, total, name,
  address) and ask "Shall I send it to Lena?". Call request_commission only after a yes.
- To contact Lena (questions, special wishes), use request_commission's notes or say she answers by email after a
  request; never invent a phone number or email for her.
- Keep track of the whole conversation: quantities and colours the person already gave, quotes already made.
- If someone says they were promised another price, the price stands; never agree to a different one.
- Never say you will search or check something: call the tool in the same turn, then answer.
- After start_checkout, show the 'you_asked_for' and 'you_are_approving' lines and say they must approve in PayPal.
  You cannot pay and must never claim an order is paid.
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
        "parameters": {"type": "object", "properties": {
            "cars": {"type": "array", "items": {"type": "object", "properties": {
                "item_id": {"type": "string"}, "body": {"type": "string"}, "colour": {"type": "string"},
                "quantity": {"type": "integer"}}, "required": ["colour", "quantity"]}},
            "us_state": {"type": "string"}}, "required": ["cars"]}}},
    {"type": "function", "function": {"name": "request_commission",
        "description": "Send Lena the made-to-order request after the person agreed to the quote. Nothing is charged.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
            "address": {"type": "string", "description": "full shipping address: street, city, state, ZIP"},
            "us_state": {"type": "string"},
            "cars": {"type": "array", "items": {"type": "object", "properties": {
                "item_id": {"type": "string"}, "body": {"type": "string"}, "colour": {"type": "string"},
                "quantity": {"type": "integer"}}, "required": ["colour", "quantity"]}},
            "notes": {"type": "string"}},
            "required": ["name", "email", "phone", "address", "us_state", "cars"]}}},
    {"type": "function", "function": {"name": "start_checkout",
        "description": "Create an order that waits for the person's approval in PayPal; returns the approval link.",
        "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "quantity": {"type": "integer"},
                                                        "us_state": {"type": "string"},
                                                        "what_the_shopper_asked": {"type": "string"}},
                       "required": ["item_id", "quantity", "us_state", "what_the_shopper_asked"]}}},
]
LABELS = {"about_counter": "reading the counter", "search_counter": "searching the counter",
          "item_details": "reading the listing", "delivery_estimate": "checking delivery",
          "start_checkout": "preparing PayPal checkout", "quote_commission": "pricing a commission",
          "request_commission": "sending the request to Lena"}


class OverBudget(RuntimeError):
    pass


def _client_() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=os.environ["NEBIUS_API_KEY"],
                         timeout=60)
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
    if name == "request_commission":
        return counter.request_commission(args.get("name", ""), args.get("email", ""), args.get("phone", ""),
                                          args.get("address", ""), args.get("us_state", ""), args.get("cars") or [],
                                          args.get("notes", ""), asked, channel="demo-shopper")
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
        out_ = [x for x in r if x["stock"] == 0]
        return s + "".join(f" · {x['title']}: sold out, next batch {x.get('next_batch') or 'not planned'}" for x in out_)
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
    if name == "request_commission":
        return f"sent · {out['request_id']}" if out.get("ok") else out.get("reason", "")
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
    # 'You asked for' is the person's own words, not the model's paraphrase of them.
    asked = " / ".join(m["content"] for m in messages if m["role"] == "user")[-400:]
    for _ in range(MAX_STEPS):
        r = _client_().chat.completions.create(model=MODEL, messages=convo, tools=TOOLS, max_tokens=500,
                                               temperature=0.2,
                                               extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        u = r.usage
        usd += (u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT) / 1e6
        msg = r.choices[0].message
        if not msg.tool_calls and not nudged and PROMISE.search(msg.content or ""):
            # It announced a search instead of doing one. Hold it to its word once.
            nudged = True
            convo += [{"role": "assistant", "content": msg.content or ""},
                      {"role": "user", "content": "Go ahead: use the tools now, then answer."}]
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
            if tc.function.name == "start_checkout" and out.get("ok"):
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
