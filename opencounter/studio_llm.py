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

# Only Studio's own agents may use this endpoint (judge panel 09.11, seat 04 F-01: it used to pass any visitor's
# prompt and tools to the model). The tools a turn may offer the model: every tool AG Studio 3.0.0 defines (read from
# its bundle: `defineAiTool`/`defineDirectTool` names, plus delegate_to and complete_task) and our analyst's two.
# tests/test_studio_guard.py re-reads the installed bundle, so an AG Studio upgrade that adds a tool fails a test,
# not the live studio.
STUDIO_TOOLS = frozenset({
    "add_page_filter", "add_widget", "add_widget_filter", "clear_plan", "configure_widget", "create_expression",
    "create_plan", "delete_expression", "execute_query", "position_widget", "remove_page_filter", "remove_widget",
    "remove_widget_filter", "rename_thread", "update_expression", "update_plan", "view_page", "view_plan",
    "view_report", "view_schema", "view_widget", "delegate_to", "complete_task",
    "agent_misses", "agent_sales"})   # studio/src/harness.ts: Lena's shop analyst
# A whole turn as Studio sends it (instructions + history + tool schemas), as JSON. Measured 09.11 on the local
# studio: the Lead's first turn is 19 KB, the analyst's 5–6 KB; a long thread with page and query results stays well
# under this. About 40k tokens at most, so one turn costs at most ~$0.012 of input.
MAX_REQUEST_BYTES = 160_000


class Refused(ValueError):
    """A request that isn't one of Studio's own turns: answered with `status`, and the model is never called."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check(req) -> None:
    """Raises Refused unless `req` looks like one of Studio's own turns: a JSON object within the size cap whose tools,
    tool choice and earlier tool calls all name Studio's own tools. Tools Studio runs itself ("provided") are never
    sent to the model, so they aren't checked."""
    if not isinstance(req, dict):
        raise Refused("A studio turn is a JSON object.")
    if len(json.dumps(req)) > MAX_REQUEST_BYTES:
        raise Refused(f"This studio turn is too long (over {MAX_REQUEST_BYTES // 1000} KB).", 413)
    tools = req.get("tools") or []
    items = req.get("input") or []
    if not isinstance(tools, list) or not isinstance(items, list):
        raise Refused("A studio turn's tools and input are lists.")
    names = [t.get("name") if isinstance(t, dict) else None for t in tools
             if not (isinstance(t, dict) and t.get("kind") == "provided")]
    names += [it.get("name") for it in items if isinstance(it, dict) and it.get("type") == "function_call"]
    choice = req.get("toolChoice")
    if isinstance(choice, dict):
        names.append(choice.get("name"))
    foreign = [str(n) for n in names if n not in STUDIO_TOOLS]
    if foreign:
        raise Refused("Only the studio's own tools can be used here (not: " + ", ".join(sorted(set(foreign)))[:200] + ").", 403)


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
            for t in req.get("tools") or [] if t.get("kind", "client") != "provided" and t.get("name") in STUDIO_TOOLS]


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
    spent, Refused when the request isn't one of Studio's own turns. A turn that only announces its next step is asked
    once more, with a tool call required."""
    check(req)
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

