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
                    r"buick|oldsmobile|ferrari|mercedes|bmw|volkswagen|vw|jaguar|aston martin)\b", re.I)

SYSTEM = """You are a shopping agent acting for one person. You are visiting Small Garage, a one-person maker of
hand-built 1:43 replica cars, through its public tools. Rules:
- Use only facts returned by the tools. If something is not in a listing, say you don't know and suggest asking Lena.
- Never name real car makers or models. Use the shop's own names, like "Green Fastback, 1968".
- Check stock and delivery to the person's US state before suggesting checkout. If the person gave no state, ask.
  If they named a deadline, pass it as need_by and repeat the tool's need_by_verdict; never compute dates yourself.
- When the person wants to buy, call start_checkout with their request in their own words.
- After start_checkout, show the 'you_asked_for' and 'you_are_approving' lines and say they must approve in PayPal.
  You cannot pay and must never claim the order is paid.
- Never show item ids like sg-014 to the person; use the item's name.
- Be brief: 2-4 short sentences per reply."""

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
    {"type": "function", "function": {"name": "start_checkout",
        "description": "Create an order that waits for the person's approval in PayPal; returns the approval link.",
        "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "quantity": {"type": "integer"},
                                                        "us_state": {"type": "string"},
                                                        "what_the_shopper_asked": {"type": "string"}},
                       "required": ["item_id", "quantity", "us_state", "what_the_shopper_asked"]}}},
]
LABELS = {"about_counter": "reading the counter", "search_counter": "searching the counter",
          "item_details": "reading the listing", "delivery_estimate": "checking delivery",
          "start_checkout": "preparing PayPal checkout"}


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
        return counter.search_counter(args.get("query", ""), args.get("max_price_usd"))
    if name == "item_details":
        return counter.item_details(args.get("item_id", ""))
    if name == "delivery_estimate":
        return counter.delivery_estimate(args.get("us_state", ""), args.get("need_by", ""))
    if name == "start_checkout":
        return counter.start_checkout(args.get("item_id", ""), int(args.get("quantity", 1) or 1),
                                      args.get("us_state", ""), asked or args.get("what_the_shopper_asked", ""),
                                      channel="demo-shopper")
    return {"error": f"unknown tool {name}"}


def _summary(name: str, out: dict) -> str:
    """One line per tool result for the visible step list."""
    if name == "search_counter":
        r = out.get("results", [])
        return f"{len(r)} found" + (f" · {r[0]['title']} · ${r[0]['price_usd']:.0f} · {r[0]['stock']} in stock" if r else "")
    if name == "item_details":
        return f"{out.get('title', '?')} · {out.get('length_mm', '?')} mm · {out.get('availability', '')}"
    if name == "delivery_estimate":
        if not out.get("ok"):
            return out.get("reason", "")
        s = f"ships {out['ships_on'][:3]} · arrives {out['arrives_earliest'][:3]}–{out['arrives_latest'][:3]}"
        return s + (f" · by {out['need_by'][:3]}: {out['need_by_verdict']}" if out.get("need_by") else "")
    if name == "start_checkout":
        return "waiting for your approval in PayPal" if out.get("ok") else out.get("reason", "")
    return "done"


def run(messages: list[dict]) -> dict:
    """messages: the visible conversation [{role: user|assistant, content}]. Returns the reply, the tool steps,
    and a checkout (if one was created)."""
    if spent_today() >= DAILY_CAP_USD:
        raise OverBudget("today's demo budget is spent")
    convo = [{"role": "system", "content": SYSTEM}] + [m for m in messages[-12:] if m["role"] in ("user", "assistant")]
    steps, checkout, usd = [], None, 0.0
    # 'You asked for' is the person's own words, not the model's paraphrase of them.
    asked = " / ".join(m["content"] for m in messages if m["role"] == "user")[-400:]
    for _ in range(MAX_STEPS):
        r = _client_().chat.completions.create(model=MODEL, messages=convo, tools=TOOLS, max_tokens=500,
                                               temperature=0.2,
                                               extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        u = r.usage
        usd += (u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT) / 1e6
        msg = r.choices[0].message
        if not msg.tool_calls:
            reply = msg.content or ""
            if BRANDS.search(reply):
                reply = BRANDS.sub("classic", reply)
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
    return {"reply": reply.strip(), "steps": steps, "checkout": checkout, "usd": round(usd, 5), "model": MODEL}
