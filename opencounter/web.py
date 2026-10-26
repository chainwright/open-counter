"""Open Counter web app: the public counter (for people and agents), the MCP endpoint, PayPal return and
webhooks, and the maker's live order feed."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from . import counter, paypal, shop, shopper
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
    async with contextlib.AsyncExitStack() as stack:
        lc = getattr(mcp_app.router, "lifespan_context", None)
        if lc:
            await stack.enter_async_context(lc(mcp_app))
        yield


app = FastAPI(title="Open Counter", lifespan=lifespan)
app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


def _announce(kind: str, o: dict):
    msg = {"kind": kind, "order": o, "at": time.time()}
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
        raise HTTPException(404)
    return counter.about_counter() | {"listings": counter.search_counter()["results"],
                                       "mcp": f"{counter.PUBLIC_URL}/mcp/"}


@app.get("/.well-known/open-counter.json")
def well_known():
    s = shop.shop()
    return {"counters": [{"name": s["name"], "json": f"{counter.PUBLIC_URL}/c/{s['slug']}.json",
                          "mcp": f"{counter.PUBLIC_URL}/mcp/"}]}


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
    out = counter.start_checkout(b.get("item_id", ""), int(b.get("quantity", 1)), b.get("us_state", ""),
                                 b.get("asked_for", ""), channel=b.get("channel", "web-agent"))
    if out.get("ok"):
        _announce("awaiting_approval", shop.order(out["order_id"]))
    return out


@app.post("/api/shopper")
async def api_shopper(req: Request):
    b = await req.json()
    msgs = [m for m in b.get("messages", []) if isinstance(m.get("content"), str)][-12:]
    for m in msgs:
        m["content"] = m["content"][:1000]
    try:
        out = await asyncio.to_thread(shopper.run, msgs)
    except shopper.OverBudget as e:
        return JSONResponse({"error": f"{e}; the rest of the demo still works."}, 429)
    if out.get("checkout"):
        _announce("awaiting_approval", shop.order(out["checkout"]["order_id"]))
    return out


@app.get("/api/orders/{oid}")
def api_order(oid: str):
    return counter.order_status(oid)


# ---- PayPal: the human approved (or cancelled) ----
@app.get("/paypal/return")
def paypal_return(oc: str, token: str = ""):
    o = shop.order(oc)
    if not o or (token and token != o.get("paypal_order_id")):
        raise HTTPException(404)
    if o["status"] == "paid":
        return RedirectResponse(f"/thanks/{oc}")
    try:
        cap = paypal.capture(o["paypal_order_id"], oc)
    except paypal.PayPalError as e:
        shop.update_order(oc, status="error", error=str(e))
        return HTMLResponse("<p>PayPal could not complete the payment. Nothing was charged.</p>", 502)
    unit = cap["purchase_units"][0]
    c = unit["payments"]["captures"][0]
    if c["status"] != "COMPLETED":
        shop.update_order(oc, status="pending", capture_id=c["id"])
        return RedirectResponse(f"/thanks/{oc}")
    ship = unit.get("shipping", {})
    if not shop.take_stock(o["listing_id"], o["qty"]):
        paypal.refund(c["id"], oc, note="Sorry, the last one sold a moment before your payment. Full refund.")
        o = shop.update_order(oc, status="refunded_out_of_stock", capture_id=c["id"])
        _announce("refunded", o)
        return RedirectResponse(f"/thanks/{oc}")
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
    return RedirectResponse(f"/thanks/{oc}")


@app.get("/paypal/cancel")
def paypal_cancel(oc: str):
    o = shop.order(oc)
    if o and o["status"] == "awaiting_approval":
        _announce("cancelled", shop.update_order(oc, status="cancelled"))
    return HTMLResponse("<p>Cancelled. Nothing was charged.</p>")


@app.get("/thanks/{oc}")
def thanks(oc: str):
    o = shop.order(oc) or {}
    return HTMLResponse(f"<p>Order {oc}: {o.get('status', '?')}. You can close this tab.</p>")


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
    oc = res.get("custom_id") or (res.get("purchase_units") or [{}])[0].get("custom_id")
    if oc and shop.order(oc) and event.get("event_type") == "PAYMENT.CAPTURE.REFUNDED":
        _announce("refunded", shop.update_order(oc, status="refunded"))
    return {"ok": True}


# ---- maker side ----
@app.get("/api/maker/orders")
def maker_orders():
    return sorted(shop.orders(), key=lambda o: -o["created"])


@app.post("/api/maker/orders/{oid}/tracking")
async def maker_tracking(oid: str, req: Request):
    b = await req.json()
    o = shop.order(oid)
    if not o or o["status"] != "paid":
        raise HTTPException(400, "Only paid orders can be shipped.")
    paypal.add_tracking(o["paypal_order_id"], o["capture_id"], b["tracking_number"], b.get("carrier", "USPS"))
    o = shop.update_order(oid, status="shipped", tracking={"number": b["tracking_number"],
                                                            "carrier": b.get("carrier", "USPS")})
    _announce("shipped", o)
    return o


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
        html = html.replace(f"/static/{f.name}", f"/static/{f.name}?v={int(f.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _stamped("index.html")


@app.get("/maker")
def maker():
    return _stamped("maker.html")
