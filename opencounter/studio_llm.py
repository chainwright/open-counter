"""The model behind Lena's sales studio (AG Studio's Agent Framework), called from our server so the key never reaches
the page. AG Studio sends one turn as an AgLlmRequest (Responses-style items); Nemotron on Nebius speaks chat
completions, so this file translates both ways. It decides nothing itself: Studio runs the loop and the tools, and
every number a widget shows comes from a query on the shop's data, not from the model. The day's AI budget is shared
with the shop's chat (the same per-browser and per-network shares)."""
from __future__ import annotations

import json
import os
import re

from . import shopper

MAX_TOKENS = 2000


def to_messages(req: dict) -> list[dict]:
    """AG Studio's conversation items as chat messages. Consecutive tool calls go into one assistant message, as the
    chat format expects; reasoning items are not sent back."""
    out: list[dict] = []
    if req.get("instructions"):
        out.append({"role": "system", "content": req["instructions"]})
    for it in req.get("input") or []:
        kind = it.get("type")
        if kind == "message":
            text = "".join(c.get("text") or c.get("refusal") or "" for c in it.get("content") or [])
            out.append({"role": it.get("role") or "user", "content": text})
        elif kind == "function_call":
            call = {"id": it["callId"], "type": "function", "function": {"name": it["name"], "arguments": it.get("arguments") or "{}"}}
            if out and out[-1]["role"] == "assistant" and "tool_calls" in out[-1]:
                out[-1]["tool_calls"].append(call)
            else:
                out.append({"role": "assistant", "content": None, "tool_calls": [call]})
        elif kind == "function_call_output":
            out.append({"role": "tool", "tool_call_id": it["callId"], "content": it.get("output") or ""})
    return out


def to_tools(req: dict) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description") or "",
                                               "parameters": t.get("parameters") or {"type": "object", "properties": {}}}}
            for t in req.get("tools") or [] if t.get("kind", "client") != "provided"]


def to_tool_choice(req: dict):
    c = req.get("toolChoice")
    if isinstance(c, dict) and c.get("name"):
        return {"type": "function", "function": {"name": c["name"]}}
    return c if c in ("auto", "none", "required") else None


# A turn that announces a tool call and then stops ("Now I'll place the widget:") ends Studio's run half-way, since
# Studio sees no tool call and no question. Seen in 2 of 3 widget requests by the final AG judge, 08.11 (P1-1).
HALF_DONE = re.compile(r":\s*$|\b(now |next,? )?(i'?ll|i will|let me|i'?m going to)\s+(now\s+)?(place|add|configure|check|create|"
                       r"update|call|delegate|hand|ask|put|look|fetch|view|set|build|make|move|resize)\b", re.I)
CONTINUE = "Continue: make the tool call now."


def half_done(text: str, calls: list, tools: list) -> bool:
    """The model said what it would do next but made no tool call, although tools were offered."""
    return bool(tools) and not calls and bool(text) and bool(HALF_DONE.search(text[-240:]))


def _ask(kw: dict, who) -> tuple[str, list, object, str]:
    r = shopper._client_().with_options(timeout=60, max_retries=1).chat.completions.create(**kw)
    u = r.usage
    usd = (u.prompt_tokens * shopper.PRICE_IN + u.completion_tokens * shopper.PRICE_OUT) / 1e6 if u else 0.0
    shopper.add_spend(usd, who)
    m = r.choices[0].message
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"} for c in (m.tool_calls or [])]
    text = (m.content or "").rsplit("</think>", 1)[-1].strip()
    return text, calls, u, r.choices[0].finish_reason


def turn(req: dict, who=()) -> dict:
    """One turn: {text, tool_calls: [{id, name, arguments}], usage, model}. Raises shopper.OverBudget when the share is
    spent. A turn that only announces its next step is asked once more, with a tool call required."""
    shopper.check_budget(who)
    kw = {"model": shopper.MODEL, "messages": to_messages(req), "max_tokens": MAX_TOKENS, "temperature": 0.2,
          "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    tools = to_tools(req)
    if tools:
        kw["tools"] = tools
        choice = to_tool_choice(req)
        if choice:
            kw["tool_choice"] = choice
    if (req.get("responseFormat") or {}).get("type") == "json":
        rf = req["responseFormat"]
        kw["response_format"] = {"type": "json_schema", "json_schema": {"name": rf.get("name") or "out", "schema": rf.get("schema") or {}}}
    text, calls, u, finish = _ask(kw, who)
    retried = False
    if half_done(text, calls, tools) and kw.get("tool_choice") != "none":
        # one retry, with what it said kept and a tool call required; the first text stays in front of the calls
        retry = {**kw, "messages": kw["messages"] + [{"role": "assistant", "content": text},
                                                    {"role": "user", "content": CONTINUE}],
                 "tool_choice": "required"}
        try:
            shopper.check_budget(who)
            t2, c2, u2, finish = _ask(retry, who)
        except Exception:   # the retry is a bonus: on any error keep the first answer
            t2, c2, u2 = "", [], None
        if c2:
            calls, retried = c2, True
            text = (text + ("\n\n" + t2 if t2 else "")).strip()
            if u and u2:
                u = type("U", (), {"prompt_tokens": u.prompt_tokens + u2.prompt_tokens,
                                   "completion_tokens": u.completion_tokens + u2.completion_tokens})()
    if os.environ.get("STUDIO_LLM_DEBUG"):   # local debugging only: what went in and what came out
        with open(os.environ["STUDIO_LLM_DEBUG"], "a") as fh:
            fh.write(json.dumps({"tools": [t["function"]["name"] for t in tools], "choice": kw.get("tool_choice"),
                                 "last": kw["messages"][-1], "text": text, "calls": calls,
                                 "finish": finish, "retried": retried}) + "\n")
    return {"text": text, "tool_calls": calls, "model": shopper.MODEL,
            "usage": {"inputTokens": u.prompt_tokens, "outputTokens": u.completion_tokens} if u else None}

