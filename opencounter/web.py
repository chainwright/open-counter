"""Open Counter web app: the public counter (for people and agents), the MCP endpoint, PayPal return and
webhooks, and the maker's live order feed."""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from . import misses, assistant, catalog, counter, onboard, paypal, shop, shopper, sample, studio_llm
from .mcp_server import mcp

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "demo" / "media"
WEB = ROOT / "web"

# The counter is public on purpose: any agent may call it. Keep DNS-rebinding protection, but allow our own host.
_host = urlparse(counter.PUBLIC_URL).netloc
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/", stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_host, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[counter.PUBLIC_URL, "http://127.0.0.1:*", "http://localhost:*"]))
_listeners: set[asyncio.Queue] = set()


@contextlib.asynccontextmanager
async def lifespan(_app):
    shop.seed()
    sample.ensure()   # two weeks of sample history on a fresh (wiped) disk, so the back office isn't empty
    # Lena's listings and the sample counters in PayPal Catalog Products, in the background (a slow PayPal never
    # holds up the start); already registered products are looked up, never created twice
    threading.Thread(target=catalog.sync, daemon=True).start()
    async with contextlib.AsyncExitStack() as stack:
        lc = getattr(mcp_app.router, "lifespan_context", None)
        if lc:
            await stack.enter_async_context(lc(mcp_app))
        yield


app = FastAPI(title="Open Counter", lifespan=lifespan)
app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


def _who(req: Request) -> tuple[str, bool]:
    """(visitor, is_lena). The demo back office is public: each browser has its own visitor id, and what it changes
    (lessons, shipping its own orders) stays with it. Lena's key (MAKER_KEY) can do everything."""
    v = re.sub(r"[^A-Za-z0-9_-]", "", req.headers.get("x-visitor", ""))[:40]
    key = os.environ.get("MAKER_KEY", "")
    return v, bool(key) and req.headers.get("x-maker-key", "") == key


def _initials(name: str | None) -> str:
    """'Ana Diaz' -> 'A. D.': what a public page shows of a buyer's name (judge 29.10, N8)."""
    return " ".join(w[0].upper() + "." for w in re.findall(r"[^\W\d_][\w'’-]*", name or ""))


def _budget_keys(req: Request) -> list[str]:
    """Whose share of the day's AI budget a request uses: this browser's and this network's."""
    v = _who(req)[0]
    ip = req.client.host if req.client else ""
    return ([f"v:{v}"] if v else []) + ([f"ip:{ip}"] if ip else [])


def _busy(e: Exception) -> JSONResponse:
    return JSONResponse({"error": str(e), "budget": "visitor" if getattr(e, "mine", False) else "day"}, 429)


def _mask(c: dict | None) -> dict | None:
    """The maker screen is a public demo page, so personal details are shown masked there:
    initials, city/state, email and phone partly hidden. The full record stays on the server (and with Lena's key)."""
    if not c:
        return c
    em = c.get("email") or ""
    ph = re.sub(r"\D", "", c.get("phone") or "")
    return {**{k: v for k, v in c.items() if k not in ("full_name", "name", "email", "phone", "address_line_1",
                                                      "address_line_2", "postal_code", "consent_said")},
            "name": _initials(c.get("full_name") or c.get("name")),
            "email": (em[0] + "•••" + em[em.find("@"):]) if "@" in em else "",
            "phone": ("•••-" + ph[-4:]) if ph else "",
            "where": ", ".join(x for x in (c.get("city"), c.get("state")) if x)}


_STREET = re.compile(r"\b\d{1,6}\s+(?:[A-Za-z0-9][\w.]*\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|"
                     r"Ct|Court|Pl|Place|Pkwy|Hwy)\b\.?", re.I)   # "1120 SW 5th Ave" too


def _names_in(texts: list[str], known: tuple = ()) -> list[str]:
    """Buyers' names to hide in free text: the ones on the order or chat, plus a name typed with contact details
    ("Sam Rivera, 415-555-0134, ..."), found the same way the agent reads it."""
    found = [n for n in known if n]
    # only lines that carry contact details: a bare "Thank You" must not be taken for a name
    lines = [x for t in texts for x in (t or "").split(" / ") if shopper.PHONE.search(x) or "@" in x or re.search(r"\b\d{5}\b", x)]
    typed = shopper.gather_customer(lines).get("full_name")
    return found + ([typed] if typed else [])


def _hide_contact(t: str, names: list[str] | tuple = ()) -> str:
    """Text on public pages: street, email, phone and ZIP replaced with dots, buyers' names with initials."""
    t = _STREET.sub("••• (street)", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "•••@•••", t)
    t = re.sub(r"(?<![\d-])\+?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b", "•••", t)
    t = re.sub(r"(?<![\w-])\+?1?\d{10}\b", "•••", t)   # a phone typed as one run of digits (+12796657833)
    t = re.sub(r"(?<![\d-])\b\d{5}(?:-\d{4})?\b(?!-)", "•••••", t)
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        t = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", _initials(name), t, flags=re.I)
        for w in name.split():   # "Thanks, Sam" or a surname on its own
            if len(w) >= 3:
                t = re.sub(r"(?<!\w)" + re.escape(w) + r"(?!\w)", w[0].upper() + ".", t, flags=re.I)
    return t


def _order_names(o: dict) -> list[str]:
    return _names_in([o.get("asked_for") or ""], ((o.get("customer") or {}).get("full_name"),
                                                  (o.get("contact") or {}).get("name"), (o.get("ship_to") or {}).get("name")))


_PRIVATE = ("approve_url", "paypal_order_id", "invoice_id", "capture_id", "visitor", "payer", "error", "payee_email")


def _mask_order(o: dict | None, visitor: str = "", full: bool = False) -> dict | None:
    """An order for a public page; with Lena's key (full) her own records as they are, minus PayPal secrets."""
    if not o:
        return o
    if full:
        return {**{k: v for k, v in o.items() if k not in _PRIVATE}, "has_invoice": bool(o.get("invoice_id")), "mine": True}
    st = o.get("ship_to") or {}
    return {**{k: v for k, v in o.items() if k not in _PRIVATE}, "customer": _mask(o.get("customer")),
            "contact": _mask(o.get("contact")), "asked_for": _hide_contact(o.get("asked_for") or "", _order_names(o)),
            "ship_to": {**st, "name": _initials(st.get("name"))} if st else st,
            "has_invoice": bool(o.get("invoice_id")),
            "mine": bool(visitor) and o.get("visitor") == visitor and not o.get("sample")}


def _announce(kind: str, o: dict):
    msg = {"kind": kind, "order": _mask_order(o), "at": time.time()}
    for q in list(_listeners):
        q.put_nowait(msg)


@app.get("/api/health")
def health():
    return {"ok": True, "paypal": paypal.configured()}


@app.get("/media/{name}")
def media(name: str):
    p = (MEDIA / name).resolve()
    if p.parent != MEDIA.resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


# ---- the counter: same facts as a page for people and as JSON for agents ----
@app.get("/c/{slug}.json")
def counter_json(slug: str):
    if slug != shop.shop()["slug"]:
        c = onboard.counter(slug)
        if not c:
            raise HTTPException(404)
        l = c["listing"]
        return {"shop": c["name"], "maker": c["maker"], "ships_from": c["ships_from"], "ships_to": "US",
                "opened_with": "Open Counter (listing words written by NVIDIA Nemotron VL from the maker's photo)",
                "listings": [{**{k: l.get(k) for k in ("id", "title", "price_usd", "stock", "category", "materials", "size",
                                                        "colour", "made_by_hand", "short_description", "keywords")},
                              "photo_url": f"{counter.PUBLIC_URL}/c/{slug}/photo.jpg",
                              "paypal_catalog_product": l.get("paypal_catalog_product")}],
                "checkout": {"how": "POST JSON {quantity, us_state}; returns a PayPal approval link a person must open",
                             "url": f"{counter.PUBLIC_URL}/api/c/{slug}/checkout",
                             "payment_goes_to": onboard.paid_to(c)}}
    return {"$schema": f"{counter.PUBLIC_URL}/static/schema/open-counter-card.v1.json"} | counter.about_counter() | {
        "listings": counter.search_counter()["results"], "mcp": f"{counter.PUBLIC_URL}/mcp/"}


@app.get("/.well-known/open-counter.json")
def well_known():
    s = shop.shop()
    return {"schema": f"{counter.PUBLIC_URL}/static/schema/open-counter-card.v1.json",
            "search_all_counters": f"{counter.PUBLIC_URL}/api/directory?q=",
            "counters": [{"name": s["name"], "json": f"{counter.PUBLIC_URL}/c/{s['slug']}.json",
                          "mcp": f"{counter.PUBLIC_URL}/mcp/"}]
            + [{"name": c["name"], "json": f"{counter.PUBLIC_URL}/c/{c['slug']}.json"} for c in onboard.latest(20)]}


@app.get("/api/directory")
def directory(q: str = "", max_price: float | None = None):
    """One search across every counter on this host: an agent asks once and gets matching items from Lena's shop and
    from every maker who opened a counter, each with the card to read and the way to check out."""
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2]
    hits = []
    s = shop.shop()
    for x in counter.search_counter()["results"]:
        hits.append({"counter": s["name"], "card": f"{counter.PUBLIC_URL}/c/{s['slug']}.json", "id": x["id"],
                     "title": x["title"], "price_usd": x["price_usd"], "stock": x["stock"],
                     "text": " ".join(str(x.get(k, "")) for k in ("title", "paint", "description")).lower(),
                     "paypal_catalog_product": x.get("paypal_catalog_product"),
                     "checkout": f"{counter.PUBLIC_URL}/mcp/ (start_checkout)"})
    for c in onboard.latest(50):
        l = c["listing"]
        hits.append({"counter": c["name"], "card": f"{counter.PUBLIC_URL}/c/{c['slug']}.json", "id": l.get("id"),
                     "title": l.get("title"), "price_usd": l.get("price_usd"), "stock": l.get("stock"),
                     "text": " ".join(str(l.get(k, "")) for k in ("title", "category", "colour", "materials",
                                                                    "short_description", "keywords")).lower(),
                     "paypal_catalog_product": l.get("paypal_catalog_product"),
                     "checkout": f"{counter.PUBLIC_URL}/api/c/{c['slug']}/checkout"})
    out = []
    for h in hits:
        score = sum(w in h["text"] for w in words)
        if (words and not score) or (max_price is not None and (h["price_usd"] or 0) > max_price):
            continue
        out.append(({k: v for k, v in h.items() if k != "text"}, score))
    out.sort(key=lambda t: (-t[1], t[0]["price_usd"] or 0))
    return {"query": q, "counters": 1 + len(onboard.latest(50)), "results": [h for h, _ in out[:30]]}


@app.get("/c/{slug}/photo.jpg")
def counter_photo(slug: str):
    p = (shop._path("counters") / f"{slug}.jpg").resolve()
    if p.parent != shop._path("counters").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/open/draft")
async def open_draft(req: Request):
    b = await req.json()
    img = str(b.get("image") or "")
    if len(img) < 100 or len(img) > 8_000_000:
        raise HTTPException(400, "Add a photo (up to about 6 MB).")
    try:
        return await asyncio.to_thread(onboard.draft, img, str(b.get("note") or ""), _budget_keys(req))
    except shopper.OverBudget as e:
        return _busy(e)


@app.post("/api/open/publish")
async def open_publish(req: Request):
    b = await req.json()
    try:
        c = await asyncio.to_thread(onboard.publish, b.get("listing") or {}, float(b.get("price_usd") or 0),
                                    int(b.get("stock") or 0), str(b.get("ships_from") or ""), str(b.get("maker") or ""),
                                    str(b.get("shop_name") or ""), str(b.get("image") or ""), _who(req)[0],
                                    str(b.get("paypal_email") or ""))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"slug": c["slug"], "page": f"{counter.PUBLIC_URL}/c/{c['slug']}", "json": f"{counter.PUBLIC_URL}/c/{c['slug']}.json",
            "paypal_catalog_product": c["listing"].get("paypal_catalog_product"), "payment_goes_to": onboard.paid_to(c)}


@app.post("/api/c/{slug}/checkout")
async def counter_checkout(slug: str, req: Request):
    b = await req.json()
    if not paypal.configured():
        raise HTTPException(503, "Checkout is offline right now.")
    try:
        out = await asyncio.to_thread(onboard.checkout, slug, int(b.get("quantity") or 1), str(b.get("us_state") or ""),
                                      _who(req)[0])
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    except paypal.PayPalError:
        raise HTTPException(502, "PayPal could not create the order; nothing was charged.")
    _announce("awaiting_approval", shop.order(out["order_id"]))
    return out


@app.get("/api/open/latest")
def open_latest(req: Request):
    return [{"slug": c["slug"], "name": c["name"], "title": c["listing"]["title"], "price_usd": c["listing"]["price_usd"],
             "sample": bool(c.get("sample")), "paypal_catalog_product": c["listing"].get("paypal_catalog_product")}
            for c in onboard.latest(8, _who(req)[0])]


@app.get("/open")
def open_page():
    return _stamped("open.html")


# the same web fonts every other page loads (open.css names Geist; without this the counter page fell back to a system font)
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family='
         'Big+Shoulders+Display:wght@700;800;900&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" '
         'rel="stylesheet">')


@app.get("/c/{slug}")
def counter_page(slug: str):
    if slug == shop.shop()["slug"]:
        return RedirectResponse("/")
    c = onboard.counter(slug)
    if not c:
        raise HTTPException(404)
    e, l = html.escape, c["listing"]
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c['name'])} · Open Counter</title>{FONTS}<link rel="stylesheet" href="/static/open.css"></head><body><main class="cp">
<span class="k">OPEN COUNTER · A MAKER'S SHOP, READABLE BY ANY AI</span><h1>{e(c['name'])}</h1><p class="by">by {e(c['maker'])} · ships from {e(c['ships_from'])}</p>
<article class="item"><img src="/c/{e(slug)}/photo.jpg" alt=""><div><h2>{e(l['title'])}</h2><p>{e(l.get('short_description') or '')}</p>
<p class="meta">${l['price_usd']:.2f} · {l['stock']} available{(' · ' + e(', '.join(l.get('materials') or []))) if l.get('materials') else ''}</p></div></article>
<form class="buy" id="buy"><label>How many<input type="number" id="q" min="1" max="{l['stock']}" value="1"></label>
<label>Ship to (US state)<input id="st" maxlength="2" placeholder="TX" required></label><button>Buy with PayPal</button><span id="m"></span></form>
<p class="fine">PayPal sandbox, no real money. You approve in PayPal; nothing is charged before that. {
 f"The order names {e(c['maker'])}'s own PayPal account as the payee, so the payment goes to her; Open Counter never holds it." if onboard.payee(c) else
 f"{e(c['maker'])} gave an email that isn't a PayPal sandbox account, so in this demo the payment goes to the Open Counter test merchant. On live PayPal it would go to her own account." if onboard.screened(c) else
 "This maker hasn't connected a PayPal account, so in this demo the payment goes to the Open Counter test merchant."}</p>
<script>
document.getElementById("buy").addEventListener("submit", async (ev) => {{ ev.preventDefault(); const m = document.getElementById("m"); m.textContent = "Opening PayPal…";
  const r = await fetch("/api/c/{e(slug)}/checkout", {{ method: "POST", headers: {{ "content-type": "application/json" }}, body: JSON.stringify({{ quantity: document.getElementById("q").value, us_state: document.getElementById("st").value }}) }});
  const j = await r.json(); if (r.ok && j.approve_url) location.href = j.approve_url; else m.textContent = j.detail || "Couldn't start checkout."; }});
</script>
<p class="agents">For AI agents: <a href="/c/{e(slug)}.json">/c/{e(slug)}.json</a>{(' · PayPal catalog product ' + e(l['paypal_catalog_product'])) if l.get('paypal_catalog_product') else ''}</p>
<a class="back" href="/open">Open your own counter →</a></main></body></html>""")


# ---- agent HTTP API (for agents that don't speak MCP, and for the built-in demo shopper) ----
@app.get("/api/search")
def api_search(q: str = "", max_price: float | None = None):
    return counter.search_counter(q, max_price)


@app.get("/api/delivery/{state}")
def api_delivery(state: str):
    return counter.delivery_estimate(state)


@app.post("/api/checkout")
async def api_checkout(req: Request):
    b = await req.json()
    try:
        qty = int(b.get("quantity", 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "Quantity must be a whole number.")
    out = counter.start_checkout(b.get("item_id", ""), qty, b.get("us_state", ""),
                                 str(b.get("asked_for", ""))[:400], channel=b.get("channel", "web-agent"), items=b.get("items"))
    if out.get("ok"):
        shop.update_order(out["order_id"], visitor=_who(req)[0])
        _announce("awaiting_approval", shop.order(out["order_id"]))
    return out


@app.post("/api/shopper")
async def api_shopper(req: Request):
    b = await req.json()
    # The whole conversation (up to 40 turns), so the agent remembers quantities, colours and quotes already given.
    msgs = [{"role": m.get("role"), "content": m["content"][:1000]}
            for m in b.get("messages", []) if isinstance(m.get("content"), str) and m.get("role") in ("user", "assistant")][-40:]
    if not msgs or msgs[-1]["role"] != "user" or not msgs[-1]["content"].strip():
        raise HTTPException(400, "Say something to the agent first.")
    # tool notes come from the server's own record of this chat, never from the browser (they steer the model)
    memos = shop.server_memos(str(b.get("conv_id") or ""), _who(req)[0])
    k = len(memos) - sum(1 for m in msgs if m["role"] == "assistant")
    for m in msgs:
        if m["role"] == "assistant":
            m["memo"] = memos[k] if 0 <= k < len(memos) else ""
            k += 1
    try:
        visitor, _ = _who(req)
        out = await asyncio.to_thread(shopper.run, msgs, visitor, _budget_keys(req))
    except shopper.OverBudget as e:
        return _busy(e)
    if out.get("checkout"):
        _announce("awaiting_approval", shop.order(out["checkout"]["order_id"]))
    # Lena can read every chat later (and see which order came out of it)
    last_user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    oid = (out.get("checkout") or {}).get("order_id")
    if oid:
        shop.update_order(oid, visitor=visitor)
    o = shop.order(oid) if oid else None
    who = ((o or {}).get("customer") or {}).get("full_name") or ((o or {}).get("contact") or {}).get("name") or ""
    out["conv_id"] = shop.log_turn(str(b.get("conv_id") or ""), last_user, out.get("reply", ""), out.get("steps", []),
                                   oid, name=who, memo=out.get("memo", ""), visitor=visitor)
    return out


@app.get("/api/orders/{oid}")
def api_order(oid: str):
    return counter.order_status(oid)


@app.get("/api/orders/{oid}/ship-to")
def api_order_ship_to(oid: str, req: Request):
    """The buyer's own delivery details, in full, for the browser that placed the order (Roma 14645: let the buyer
    check them). Anyone else holding the order number sees nothing."""
    o = shop.order(oid)
    visitor = _who(req)[0]
    if not o or not visitor or o.get("visitor") != visitor or o.get("sample"):
        raise HTTPException(404)
    return {"ship_to": counter._ship_to(o)}


# ---- PayPal: the human approved (or cancelled) ----
_settling = threading.Lock()


def _settle(oc: str) -> dict:
    """Capture an approved order and hand it to Lena. Called from the buyer's return to the site AND from PayPal's
    CHECKOUT.ORDER.APPROVED webhook, so a buyer who approves and closes the tab still gets their order.
    One at a time, and the capture carries a PayPal-Request-Id, so the two paths can never charge twice."""
    with _settling:
        o = shop.order(oc)
        if o["status"] in ("paid", "shipped", "refunded_out_of_stock", "refund_due", "refunded", "replaced", "cancelled"):
            return o   # already settled, or replaced by a newer order from the same chat: never captured
        cap = paypal.capture(o["paypal_order_id"], oc)
        unit = cap["purchase_units"][0]
        c = unit["payments"]["captures"][0]
        if c["status"] != "COMPLETED":
            return shop.update_order(oc, status="pending", capture_id=c["id"])
        ship = unit.get("shipping", {})
        lines = o.get("lines") or [{"listing_id": o["listing_id"], "qty": o["qty"]}]
        took = (onboard.take(o["counter"], o["qty"]) if o.get("kind") == "counter"
                else True if o.get("kind") == "commission" else shop.take_stock_lines(lines))
        if not took:
            try:
                paypal.refund(c["id"], oc, note="Sorry, the last one sold a moment before your payment. Full refund.")
            except paypal.PayPalError:
                if not o.get("payee_email"):
                    raise
                # the money sits in the maker's own PayPal account, which only she can refund from: tell her, loudly
                o = shop.update_order(oc, status="refund_due", capture_id=c["id"],
                                      note="Sold out before payment: refund this buyer in full from your PayPal account.")
                _announce("refund_due", o)
                return o
            o = shop.update_order(oc, status="refunded_out_of_stock", capture_id=c["id"])
            _announce("refunded", o)
            return o
        real_state = (ship.get("address", {}).get("admin_area_1") or "").upper()
        extra = {}
        if real_state and real_state != o["ship_state"]:
            # The agent guessed one state; PayPal holds the buyer's real address. The estimate follows the address.
            extra = {"estimate": shop.delivery_estimate(real_state), "agent_state": o["ship_state"],
                     "ship_state": real_state}
        o = shop.update_order(oc, status="paid", capture_id=c["id"], paid_at=time.time(),
                              ship_to={"name": ship.get("name", {}).get("full_name"),
                                       "city": ship.get("address", {}).get("admin_area_2"),
                                       "state": real_state},
                              payer=cap.get("payer", {}).get("name", {}).get("given_name"), **extra)
        _announce("paid", o)
        return o


def _sync_invoice(oc: str) -> dict:
    """Read a made-to-order invoice back from PayPal: deposit paid → Lena builds; fully paid → ready to ship."""
    o = shop.order(oc)
    inv = paypal.get_invoice(o["invoice_id"])
    paid = float(((inv.get("payments") or {}).get("paid_amount") or {}).get("value") or 0)
    st = {"PAID": "paid", "MARKED_AS_PAID": "paid", "PARTIALLY_PAID": "deposit_paid",
          "CANCELLED": "cancelled"}.get(inv.get("status"), o["status"])
    fields = {"paid_usd": paid, "invoice_status": inv.get("status"), "invoice_checked": time.time()}
    if st != o["status"]:
        fields["status"] = st
        if st in ("paid", "deposit_paid") and not o.get("paid_at"):
            fields["paid_at"] = time.time()
    o2 = shop.update_order(oc, **fields)
    if st != o["status"] and st in ("paid", "deposit_paid"):
        _announce("paid", o2)
    return o2


@app.get("/api/paypal/config")
def paypal_config():
    """The public client id for PayPal's JS SDK buttons in the chat (the secret never leaves the server)."""
    return {"client_id": os.environ.get("PAYPAL_CLIENT_ID", ""), "env": "sandbox"}


@app.post("/api/paypal/approved")
async def paypal_approved(req: Request):
    """The buyer approved in the PayPal popup without leaving the chat: settle it through the same path as the
    return page and the webhook (capture once, stock re-checked, Lena told)."""
    b = await req.json()
    oc, token = str(b.get("order_id", "")), str(b.get("paypal_order_id", ""))
    o = shop.order(oc)
    if not o or token != o.get("paypal_order_id"):
        raise HTTPException(404, "Unknown order.")
    if o.get("visitor", "").startswith("webhook-only-test"):
        return {"status": o["status"]}
    try:
        o = _settle(oc)
    except paypal.PayPalError as e:
        shop.update_order(oc, status="error", error=str(e))
        return JSONResponse({"error": "PayPal could not complete the payment. Nothing was charged."}, 502)
    return {"status": o["status"], "thanks": f"/thanks/{oc}"}


def _note(title: str, text: str, code: int = 200) -> HTMLResponse:
    """A small page in the shop's look for the PayPal return edge cases."""
    return HTMLResponse(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title} · Open Counter</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;"
        "background:#0d0f12;color:#e8e4dc;font:16px/1.5 system-ui,sans-serif}main{max-width:420px;padding:32px 24px}"
        "small{color:#e0a458;letter-spacing:.12em;font-size:12px}h1{font-size:26px;margin:8px 0 12px}"
        "a{display:inline-block;margin-top:18px;padding:10px 16px;border-radius:8px;background:#e0a458;color:#111;"
        f"text-decoration:none;font-weight:600}}</style><main><small>OPEN COUNTER · SMALL GARAGE</small><h1>{title}</h1>"
        f'<p>{text}</p><a href="/#try">Back to the shop</a></main>', code)


@app.get("/paypal/return")
def paypal_return(oc: str, token: str = ""):
    o = shop.order(oc)
    if not o or (token and token != o.get("paypal_order_id")):
        # an old or unknown checkout link: we never capture it, so the approval lapses and nothing is charged
        return _note("This checkout link is no longer active", "Nothing was charged. Go back to the shop and "
                     "ask the agent for a fresh receipt.", 410)
    if o.get("visitor", "").startswith("webhook-only-test"):
        # test path: the return page stays out of it, as if the buyer had closed the tab; PayPal's webhook settles it
        return _note("Approved in PayPal", f"Order {oc} is finished by PayPal's webhook, not by this page. "
                     "Lena's back office shows it as paid in a few seconds.")
    try:
        _settle(oc)
    except paypal.PayPalError as e:
        shop.update_order(oc, status="error", error=str(e))
        if paypal.payee_refused(e):
            return _note("PayPal couldn't pay this maker", "PayPal refused the maker's account, so the payment "
                         "wasn't taken. Nothing was charged.", 502)
        return _note("PayPal couldn't finish the payment", "Nothing was charged. Go back and try again in a minute.", 502)
    return RedirectResponse(f"/thanks/{oc}")


@app.get("/paypal/cancel")
def paypal_cancel(oc: str):
    o = shop.order(oc)
    if o and o["status"] == "awaiting_approval":
        _announce("cancelled", shop.update_order(oc, status="cancelled"))
    return _note("Cancelled", "Nothing was charged. Your chat is still there if you want to change the order.")


def _day(s: str) -> str:
    """'Wednesday 2026-10-28' -> 'Wed, Oct 28'."""
    try:
        d = datetime.strptime(s.split()[-1], "%Y-%m-%d")
        return d.strftime("%a, %b ") + str(d.day)
    except Exception:
        return s or ""


@app.get("/thanks/{oc}")
def thanks(oc: str):
    """The page a person lands on after approving in PayPal: what they bought, what happens next."""
    o = shop.order(oc)
    if not o:
        raise HTTPException(404)
    e = html.escape
    item = shop.listing(o.get("listing_id", "")) or {}
    est = o.get("estimate") or {}
    status = o.get("status", "")
    total = f"${o.get('total_usd', 0):.2f}"
    head, lead, steps = {
        "paid": ("It's yours. Congratulations!", f"Paid {total} through PayPal. Lena has your order.",
                 [("Lena packs it", f"She ships {_day(est.get('ships_on', ''))} from Columbus, Ohio, with a note in the box."),
                  ("You get the tracking", "When she adds the USPS number, PayPal tells you it's on its way."),
                  ("It arrives", f"Between {_day(est.get('arrives_earliest', ''))} and {_day(est.get('arrives_latest', ''))}.")]),
        "shipped": ("On its way.", f"{total} through PayPal. Lena has shipped it.",
                    [("USPS tracking", e((o.get("tracking") or {}).get("number", ""))),
                     ("It arrives", f"Between {_day(est.get('arrives_earliest', ''))} and {_day(est.get('arrives_latest', ''))}.")]),
        "refunded_out_of_stock": ("Sorry, it sold a moment before you paid.", "You've been refunded in full through PayPal.",
                                  [("Nothing to do", "The refund is already on its way back to your PayPal account."),
                                   ("Want one anyway?", "Lena takes commissions. Ask your agent for the same car in your colour.")]),
        "refund_due": ("Sorry, it sold a moment before you paid.", "The maker refunds you in full from her own PayPal account.",
                       [("Nothing to do", "She has been told; the refund comes back to your PayPal account.")]),
        "pending": ("Payment is processing.", "PayPal is still confirming it. Nothing else to do.",
                    [("What happens next", "As soon as PayPal confirms, Lena sees the order and ships it.")]),
        "replaced": ("This order was replaced.", "You changed the order in the chat, so this one can't be paid.",
                     [("Your current order", f"Pay the newer order from the same chat: {e(o.get('replaced_by', ''))}."),
                      ("Nothing was charged", "No money moved for this one.")]),
        "awaiting_approval": ("Waiting for your OK in PayPal.", f"{total}, nothing charged yet.",
                              [("Approve in PayPal", "Use the PayPal button in the chat. Until then no money moves."),
                               ("Then Lena gets it", "The moment you approve, the order lands on her phone.")]),
        "cancelled": ("Cancelled.", "Nothing was charged.", [("Changed your mind?", "Your chat is still there.")]),
        "deposit_paid": ("Deposit in. Lena starts building.", f"The rest of {total} is due before it ships.",
                         [("The balance", "PayPal sends you the invoice for the rest when the cars are ready.")]),
    }.get(status, ("Order received.", "Lena has it.", []))
    if o.get("kind") == "commission" and status == "paid":
        q = o.get("quote") or {}
        head, lead = "It's yours. Congratulations!", f"Paid {total} through PayPal. Lena starts building your order."
        steps = [("Lena builds it", f"{q.get('total_cars')} car(s), about {q.get('build_weeks')} week(s); she may call you about the details."),
                 ("It ships", f"About {_day(est.get('ships_on', ''))}, and PayPal sends you the tracking."),
                 ("It arrives", f"Between {_day(est.get('arrives_earliest', ''))} and {_day(est.get('arrives_latest', ''))}.")]
    photo = f"/media/{e(item['photo'])}" if item.get("photo") else "/media/hero.jpg"
    brand = "Small Garage"
    if o.get("kind") == "counter":   # an order from another maker's counter: her name, her photo
        cc = onboard.counter(o.get("counter", "")) or {}
        first = (cc.get("maker") or "The maker").split()[0]
        swap = lambda t: t.replace("Lena", first).replace("from Columbus, Ohio", f"from {cc.get('ships_from', 'the US')}").replace(
            " She ", " They ").replace("She ships", "Ships").replace("she adds", "they add").replace("Lena takes commissions. Ask your agent for the same car in your colour.", "")
        lead = swap(lead)
        steps = [(swap(a), swap(b)) for a, b in steps]
        photo = f"/c/{e(o.get('counter', ''))}/photo.jpg"
        brand = cc.get("name", "Open Counter")
    rows = "".join(f'<li><b>{t}</b><span>{d}</span></li>' for t, d in steps)
    asked = e(_hide_contact(o.get("asked_for", ""), _order_names(o)))   # shareable URL: no name, address or phone
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(head)} · {e(brand)}</title>
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--black:#0D0E10;--soot:#17191C;--hair:#2A2D31;--paper:#F2F3F1;--mute:#8C9096;--lamp:#FFE9C7;--cyan:#38F2E5}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:var(--black);color:var(--paper);font-family:Geist,system-ui,sans-serif;display:grid;place-items:center;padding:28px 16px}}
.wrap{{width:min(960px,100%);display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);background:var(--soot);border:1px solid var(--hair);border-radius:22px;overflow:hidden}}
.pic{{position:relative;min-height:420px;background:#000 center/cover no-repeat}}
.pic:after{{content:"";position:absolute;inset:0;background:radial-gradient(60% 55% at 45% 40%,transparent 0,rgba(13,14,16,.55) 70%,var(--black) 100%)}}
.body{{padding:38px 36px 34px}}
.k{{font:500 12px/1 'Geist Mono',monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--cyan)}}
h1{{font:800 46px/1.02 'Big Shoulders Display',sans-serif;letter-spacing:.01em;margin:14px 0 10px;color:var(--lamp)}}
.lead{{color:var(--paper);font-size:18px;margin:0 0 4px}}.item{{color:var(--mute);font-size:15px;margin:0 0 22px}}
.asked{{border-left:3px solid var(--lamp);padding:8px 14px;margin:0 0 22px;color:#d9dcd7;font-size:15px;line-height:1.45}}
.asked[hidden]{{display:none}}.asked small{{display:block;font:500 11px/1 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin-bottom:6px}}
ol{{list-style:none;margin:0;padding:0;display:grid;gap:14px;counter-reset:s}}
li{{display:grid;grid-template-columns:30px 1fr;column-gap:12px;counter-increment:s}}
li:before{{content:counter(s);grid-row:span 2;width:30px;height:30px;border-radius:50%;border:1px solid var(--hair);display:grid;place-items:center;font:500 13px 'Geist Mono',monospace;color:var(--lamp)}}
li b{{font-weight:600}}li span{{color:var(--mute);font-size:15px;line-height:1.4}}
.foot{{margin-top:26px;padding-top:18px;border-top:1px solid var(--hair);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font:400 13px 'Geist Mono',monospace;color:var(--mute)}}
.foot a{{color:var(--cyan);text-decoration:none}}
@media (max-width:760px){{.wrap{{grid-template-columns:1fr}}.pic{{min-height:260px}}.body{{padding:26px 22px}}h1{{font-size:38px}}}}
</style></head><body><main class="wrap">
<div class="pic" style="background-image:url('{photo}')" role="img" aria-label="{e(item.get('title', ''))}"></div>
<div class="body"><div class="k">{e(brand)} · order {e(oc)}</div><h1>{e(head)}</h1>
<p class="lead">{lead}</p><p class="item">{e(o.get('title', item.get('title', '')))} · {f"{o.get('qty')} cars" if len(o.get('lines') or []) > 1 else f"qty {o.get('qty', 1)}"}</p>
{f'<div class="asked"><small>You asked for</small>{asked}</div>' if asked else ''}
<div class="asked mine" id="mine" hidden><small>Ships to · please check · only you see this</small><span id="mine-t"></span></div>
<ol>{rows}</ol>
<div class="foot"><span>PayPal sandbox · no real money</span><a href="/">Back to the counter</a></div></div>
</main><script>
(function () {{  // the buyer's own browser gets the full address back to check it; the shareable page shows dots
  var v = ""; try {{ v = localStorage.getItem("oc_visitor") || ""; }} catch (e) {{}}
  if (!v) return;
  fetch("/api/orders/{e(oc)}/ship-to", {{ headers: {{ "x-visitor": v }} }}).then(function (r) {{ return r.ok ? r.json() : null; }})
    .then(function (j) {{ if (!j || !j.ship_to) return; document.getElementById("mine-t").textContent = j.ship_to; document.getElementById("mine").hidden = false; }})
    .catch(function () {{}});
}})();
</script></body></html>""")


@app.post("/paypal/webhook")
async def webhook(req: Request):
    event = await req.json()
    try:
        ok = paypal.verify_webhook(dict(req.headers), event)
    except paypal.PayPalError:
        ok = False
    if not ok:
        return JSONResponse({"ok": False}, 400)
    res = event.get("resource", {})
    kind = event.get("event_type", "")
    if kind.startswith("INVOICING."):
        inv = res.get("invoice") or res
        oc = (inv.get("detail") or {}).get("invoice_number")
        if oc and shop.order(oc) and shop.order(oc).get("invoice_id"):
            await asyncio.to_thread(_sync_invoice, oc)
        return {"ok": True}
    oc = res.get("custom_id") or (res.get("purchase_units") or [{}])[0].get("custom_id")
    o = shop.order(oc) if oc else None
    if not o:
        return {"ok": True, "ignored": "not our order"}
    shop.update_order(oc, events=o["events"] + [[f"webhook:{kind}", time.time()]])
    if kind == "CHECKOUT.ORDER.APPROVED" and o["status"] == "awaiting_approval":
        # approved in PayPal but the buyer never came back to the site: finish it here
        await asyncio.to_thread(_settle, oc)
    elif kind == "PAYMENT.CAPTURE.COMPLETED" and o["status"] in ("awaiting_approval", "pending"):
        _announce("paid", shop.update_order(oc, status="paid", paid_at=time.time(), capture_id=res.get("id")))
    elif kind in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REVERSED"):
        _announce("refunded", shop.update_order(oc, status="payment_failed" if kind.endswith("DENIED") else "reversed"))
    elif kind == "PAYMENT.CAPTURE.REFUNDED" and o["status"] != "refunded_out_of_stock":
        _announce("refunded", shop.update_order(oc, status="refunded"))
    return {"ok": True}


# ---- maker side ----
@app.post("/api/studio/llm")
async def studio_llm_turn(req: Request):
    """One model turn for Lena's sales studio (AG Studio's agents run in the page and call this, so no key is in it)."""
    try:
        return await asyncio.to_thread(studio_llm.turn, await req.json(), _budget_keys(req))
    except shopper.OverBudget as e:
        return JSONResponse({"error": str(e)}, status_code=429)


@app.get("/api/maker/orders")
def maker_orders(req: Request):
    # made-to-order invoices: if a webhook was missed, look again (at most once a minute per order)
    for o in shop.orders():
        if (o.get("invoice_id") and not o.get("sample") and o["status"] in ("awaiting_approval", "deposit_paid")
                and time.time() - o.get("invoice_checked", 0) > 60):
            try:
                _sync_invoice(o["id"])
            except paypal.PayPalError:
                shop.update_order(o["id"], invoice_checked=time.time())
    visitor, lena = _who(req)
    return [_mask_order(o, visitor, full=lena) for o in sorted(shop.orders(), key=lambda o: -o["created"])]


@app.post("/api/maker/orders/{oid}/tracking")
async def maker_tracking(oid: str, req: Request):
    b = await req.json()
    o = shop.order(oid)
    visitor, lena = _who(req)
    if not o or o["status"] != "paid":
        raise HTTPException(400, "Only orders paid in full can be shipped.")
    if o.get("sample") and not lena:
        raise HTTPException(403, "Sample orders are history; place your own order to try shipping.")
    if not (lena or (visitor and o.get("visitor") == visitor)):
        raise HTTPException(403, "On the demo you can ship the orders you placed yourself.")
    num = str(b.get("tracking_number") or "").strip()[:40]
    if not re.fullmatch(r"[A-Za-z0-9 -]{8,40}", num):
        raise HTTPException(400, "Enter the carrier's tracking number.")
    note = "kept on the order"
    if o.get("paypal_order_id") and o.get("capture_id") and not o.get("sample"):
        paypal.add_tracking(o["paypal_order_id"], o["capture_id"], num, b.get("carrier", "USPS"))
        note = "sent to PayPal; the buyer is told"
    o = shop.update_order(oid, status="shipped", tracking={"number": num, "carrier": b.get("carrier", "USPS"), "note": note})
    _announce("shipped", o)
    return o


def _chat_names(c: dict, orders: dict) -> list[str]:
    """Every buyer name a chat may contain: the chat's name, the people on its orders, a name typed in it."""
    known = [c.get("name")] + [n for oid in c.get("orders", []) for n in _order_names(orders.get(oid) or {})]
    return _names_in([t["user"] for t in c.get("turns", [])], tuple(known))


@app.get("/api/maker/conversations")
def maker_conversations(req: Request):
    """Every shopper chat, newest first, with the orders it produced. Names as initials on the public demo."""
    lena = _who(req)[1]
    orders = {o["id"]: o for o in shop.orders()}
    out = []
    for c in shop.conversations()[:200]:
        asked = any(re.search(r"\bname\b", t["reply"], re.I) for t in c["turns"])
        if lena:
            out.append({**c, "asked_name": asked})
            continue
        names = _chat_names(c, orders)
        out.append({**c, "name": _initials(c.get("name")), "asked_name": asked,
                    "turns": [{**t, "user": _hide_contact(t["user"], names), "reply": _hide_contact(t["reply"], names),
                               "steps": [_hide_contact(s, names) for s in t.get("steps", [])],
                               "memo": _hide_contact(t.get("memo") or "", names)} for t in c["turns"]]})
    return out


_STUCK = re.compile(r"couldn.?t finish|can.?t help|cannot help|unable to|don.?t know|not sure|couldn.?t reach|"
                    r"try again later|checkout (is|system is) (currently )?offline", re.I)
_TOOL_TROUBLE = re.compile(r"^(no listing|only \d+|.*not a us state|checkout is offline|paypal could not|ask the person|"
                           r"still needed|before checkout)", re.I)
_SHOP_TZ = shop.SHOP_TZ   # Columbus, Ohio
_PAINT = {"68-G": "#2FA36B", "67-B": "#3D6FE0", "70-O": "#FF6A2B", "73-Y": "#F5C400", "65-R": "#E3242B"}


@app.get("/api/maker/insights")
def maker_insights(days: int = 30):
    """Lena's numbers for a period: cars by model per day (in the cars' own colours), when the shop's AI is busiest,
    and how well it does (chats that became orders, and the replies where it got stuck)."""
    days = max(1, min(int(days), 366))
    now = shop.now().timestamp()
    t0 = now - days * 86400
    listings = {l["id"]: l for l in shop.shop()["listings"]}
    colour = {lid: _PAINT.get((re.search(r"code (\w+-\w)", l.get("paint", "")) or [None, ""])[1], "#8C9096")
              for lid, l in listings.items()}
    day = lambda t: shop.local(t).strftime("%Y-%m-%d")   # days on Lena's clock, like the heatmap
    labels = [day(now - (days - 1 - i) * 86400) for i in range(days)]
    series = {lid: {"title": l["title"].rsplit(",", 1)[0], "colour": colour[lid], "units": [0] * days, "usd": 0.0}
              for lid, l in listings.items()}
    series["made-to-order"] = {"title": "Made to order", "colour": "#FFE9C7", "units": [0] * days, "usd": 0.0}
    idx = {d: i for i, d in enumerate(labels)}
    paid = {"paid", "shipped"}
    for o in shop.orders():
        if o.get("created", 0) < t0 or o.get("status") in ("error", "cancelled", "refunded_out_of_stock"):
            continue
        i = idx.get(day(o["created"]))
        if i is None:
            continue
        lines = ([{"listing_id": "made-to-order", "qty": o["qty"], "unit_usd": o["total_usd"] / max(o["qty"], 1)}]
                 if o.get("kind") == "commission" else o.get("lines") or
                 [{"listing_id": o["listing_id"], "qty": o["qty"], "unit_usd": o["unit_usd"]}])
        for ln in lines:
            s = series.get(ln["listing_id"])
            if s:
                s["units"][i] += ln["qty"]
                if o.get("status") in paid:
                    s["usd"] += ln["qty"] * ln["unit_usd"]
    chats = [c for c in shop.conversations() if c.get("updated", 0) >= t0]
    heat = [[0] * 24 for _ in range(7)]   # weekday (Mon=0) x hour, messages from shoppers
    stuck = []
    by_id = {o["id"]: o for o in shop.orders()}
    for c in chats:
        names = _chat_names(c, by_id)
        for t in c["turns"]:
            if t["at"] < t0:
                continue
            lt = datetime.fromtimestamp(t["at"], _SHOP_TZ)   # Lena's time (Columbus), not the server's UTC
            heat[lt.weekday()][lt.hour] += 1
            why = ("the AI got stuck" if _STUCK.search(t["reply"]) else
                   next(("a tool said: " + s.split(" · ", 1)[-1][:80] for s in t["steps"]
                         if _TOOL_TROUBLE.search(s.split(" · ", 1)[-1])), None))
            if why:
                stuck.append({"chat": c["id"], "at": t["at"], "asked": _hide_contact(t["user"], names)[:160], "why": why})
    turns = sum(len(c["turns"]) for c in chats)
    with_order = sum(1 for c in chats if c.get("orders"))
    return {"days": days, "labels": labels, "series": [s | {"id": k} for k, s in series.items()],
            "heat": heat, "chats": len(chats), "messages": turns, "chats_with_order": with_order,
            "conversion": round(100 * with_order / len(chats)) if chats else 0,
            "stuck": sorted(stuck, key=lambda x: -x["at"])[:30],
            "answered_pct": round(100 * (1 - len(stuck) / turns)) if turns else 100}


@app.get("/api/maker/agent_misses")
def maker_agent_misses(req: Request, days: int = 7):
    """The studio's hero widget: each lesson with the answer it corrected and every later chat that tested it
    (followed or not), plus replies where the agent got stuck and no lesson exists yet. Computed in code."""
    days = max(1, min(int(days), 366))
    visitor, lena = _who(req)
    convs = shop.conversations()
    orders = shop.orders()
    out = misses.agent_misses(convs, shop.lessons_for(visitor, lena), orders,
                              since=shop.now().timestamp() - days * 86400, matches=shop.lesson_matches)
    if not lena:   # public demo: no names, phones or addresses in what the widget quotes
        chats, by_id = {c["id"]: c for c in convs}, {o["id"]: o for o in orders}
        for r in out["taught"] + out["open"]:
            names = _chat_names(chats.get(r.get("chat") or "", {}), by_id)
            r["asked"], r["said"] = _hide_contact(r["asked"], names), _hide_contact(r["said"], names)
    return out | {"days": days}


@app.post("/api/maker/agent_misses/draft")
async def maker_draft_lesson(req: Request):
    """'Draft a lesson' on one row: Lena's assistant reads that chat and proposes an if-then lesson. Nothing is
    saved: Lena accepts it through /api/maker/coach, like any lesson she writes herself."""
    b = await req.json()
    cid = re.sub(r"[^A-Za-z0-9_-]", "", str(b.get("chat") or ""))[:40]
    if not cid or not any(c["id"] == cid for c in shop.conversations()):
        raise HTTPException(404, "No such chat.")
    try:
        out = await asyncio.to_thread(assistant.review, 14, 1, _budget_keys(req), [cid])
    except shopper.OverBudget as e:
        return _busy(e)
    f = next(iter(out.get("findings") or []), None)
    if not f:
        return {"chat": cid, "lesson": None, "why": "The assistant found nothing to teach from this chat."}
    when, _ = shop.split_lesson(f["lesson"])
    return {"chat": cid, "lesson": f["lesson"], "usable": bool(when), "problem": _hide_contact(f.get("problem", "")) if not _who(req)[1]
            else f.get("problem", ""), "usd": out.get("usd", 0)}


@app.post("/api/maker/assistant/review")
async def assistant_review(req: Request):
    """Lena's assistant reads recent chats and suggests lessons for her shop's AI."""
    b = await req.json() if (await req.body()) else {}
    try:
        out = await asyncio.to_thread(assistant.review, int(b.get("days") or 14), 20, _budget_keys(req))
    except shopper.OverBudget as e:
        return _busy(e)
    if not _who(req)[1]:   # the demo page is public: the chats it quotes show no name, phone or address
        chats = {c["id"]: c for c in shop.conversations()}
        orders = {o["id"]: o for o in shop.orders()}
        for f in out.get("findings", []):
            names = _chat_names(chats.get(f["chat"], {}), orders)
            f["asked"], f["problem"] = _hide_contact(f.get("asked", ""), names), _hide_contact(f.get("problem", ""), names)
    return out


@app.post("/api/maker/assistant/ask")
async def assistant_ask(req: Request):
    b = await req.json()
    q = str(b.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "Ask something about the shop.")
    try:
        return await asyncio.to_thread(assistant.ask, q, _budget_keys(req))
    except shopper.OverBudget as e:
        return _busy(e)


@app.get("/api/maker/coach")
def coach_list(req: Request):
    """Lena's lessons for her shop's AI (newest first): hers, plus the ones this browser wrote on the demo."""
    visitor, lena = _who(req)
    return [n | {"mine": bool(visitor) and n.get("visitor") == visitor} for n in reversed(shop.lessons_for(visitor, lena))]


@app.post("/api/maker/coach")
async def coach_add(req: Request):
    b = await req.json()
    visitor, lena = _who(req)
    if not visitor and not lena:
        raise HTTPException(400, "Open the back office in a browser to teach the agent.")
    try:
        return shop.add_coaching(str(b.get("chat_id") or ""), str(b.get("note") or ""), visitor="" if lena else visitor)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/maker/coach/{lid}")
async def coach_set(lid: str, req: Request):
    b = await req.json()
    visitor, lena = _who(req)
    if not shop.set_coaching(lid, bool(b.get("active")), visitor, lena):
        raise HTTPException(403, "On the demo you can pause the lessons you wrote yourself.")
    return {"ok": True}


@app.get("/api/maker/customers")
def maker_customers(req: Request):
    """Buyers from orders; marketing is true only after their own yes in chat. Full details with Lena's key."""
    lena = _who(req)[1]
    return [({**c, "name": c.get("full_name", ""), "where": ", ".join(x for x in (c.get("city"), c.get("state")) if x)}
             if lena else _mask(c)) for c in shop.customers()]


@app.post("/api/maker/orders/{oid}/balance")
def request_balance(oid: str, req: Request):
    """Lena: the cars are ready, ask the buyer for the rest (PayPal sends the reminder)."""
    o = shop.order(oid)
    if not o or not o.get("invoice_id"):
        raise HTTPException(404)
    visitor, lena = _who(req)
    if not (lena or (visitor and o.get("visitor") == visitor)):
        raise HTTPException(403, "On the demo you can request the balance for orders you placed yourself.")
    if o.get("balance_requested") and time.time() - o["balance_requested"] < 3600:
        raise HTTPException(429, "A reminder already went out in the last hour.")
    paypal.remind_invoice(o["invoice_id"], "Your hand-built cars are finished. Pay the balance and they ship the next day.")
    return _mask_order(shop.update_order(oid, balance_requested=time.time()))


@app.get("/api/maker/requests")
def maker_requests(req: Request):
    """Call-back requests for Lena (newest first; masked on the public demo screen, full with her key)."""
    if _who(req)[1]:
        return list(reversed(shop.requests_()))
    out = []
    for r in reversed(shop.requests_()):
        names = _names_in([r.get("asked_for") or "", r.get("message") or ""], ((r.get("contact") or {}).get("name"),))
        out.append({**r, "contact": _mask(r.get("contact")), "message": _hide_contact(r.get("message") or "", names),
                    "about": _hide_contact(r.get("about") or "", names), "asked_for": _hide_contact(r.get("asked_for") or "", names)})
    return out


@app.get("/api/maker/news-list.csv")
def news_list(key: str = ""):
    """Everyone who said yes to news in chat, full details, for Lena only (MAKER_KEY)."""
    want = os.environ.get("MAKER_KEY", "")
    if not want or key != want:
        raise HTTPException(403, "Lena's key needed")
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "phone", "city", "state", "orders", "said", "when"])
    for c in shop.customers():
        if c.get("marketing") is True:
            w.writerow([c.get("full_name"), c.get("email"), c.get("phone"), c.get("city"), c.get("state"),
                        " ".join(c.get("orders", [])), c.get("consent_said", ""),
                        shop.local(c.get("consent_at", 0)).strftime("%Y-%m-%d %H:%M")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=small-garage-news-list.csv"})


@app.post("/api/maker/requests/{rid}")
async def maker_request_status(rid: str, req: Request):
    """Lena marks a call-back as done. Her key only: on the public demo nobody else can tick off her call list."""
    if not _who(req)[1]:
        raise HTTPException(403, "Only Lena can mark a call-back as done (her key is needed).")
    b = await req.json()
    st = b.get("status")
    if st not in ("called",):
        raise HTTPException(400, "status must be called")
    try:
        return shop.update_request(rid, status=st)
    except StopIteration:
        raise HTTPException(404)


@app.get("/api/maker/feed")
async def maker_feed():
    q: asyncio.Queue = asyncio.Queue()
    _listeners.add(q)

    async def stream():
        try:
            yield ": hi\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), 20)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            _listeners.discard(q)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _stamped(name: str) -> HTMLResponse:
    """The page with each static file stamped by its modification time, so phones never keep an old copy."""
    html = (WEB / name).read_text()
    for f in (WEB / "static").iterdir():
        if f.is_file():   # files only, and only a whole path ending in a quote (a folder name is a prefix of others)
            html = html.replace(f'/static/{f.name}"', f'/static/{f.name}?v={int(f.stat().st_mtime)}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _stamped("index.html")


@app.get("/maker")
def maker():
    return _stamped("maker.html")
