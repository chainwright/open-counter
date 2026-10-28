"""Open Counter web app: the public counter (for people and agents), the MCP endpoint, PayPal return and
webhooks, and the maker's live order feed."""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import time
from datetime import datetime
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
    # The whole conversation (up to 40 turns), so the agent remembers quantities, colours and quotes already given.
    msgs = [{"role": m.get("role"), "content": m["content"][:1000], "memo": str(m.get("memo") or "")[:800]}
            for m in b.get("messages", []) if isinstance(m.get("content"), str)][-40:]
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
    if o.get("kind") != "commission" and not shop.take_stock(o["listing_id"], o["qty"]):
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
        "pending": ("Payment is processing.", "PayPal is still confirming it. Nothing else to do.",
                    [("What happens next", "As soon as PayPal confirms, Lena sees the order and ships it.")]),
    }.get(status, ("Order received.", f"Status: {e(status)}.", []))
    if o.get("kind") == "commission" and status == "paid":
        q = o.get("quote") or {}
        head, lead = "It's yours. Congratulations!", f"Paid {total} through PayPal. Lena starts building your order."
        steps = [("Lena builds it", f"{q.get('total_cars')} car(s), about {q.get('build_weeks')} week(s); she may call you about the details."),
                 ("It ships", f"About {_day(est.get('ships_on', ''))}, and PayPal sends you the tracking."),
                 ("It arrives", f"Between {_day(est.get('arrives_earliest', ''))} and {_day(est.get('arrives_latest', ''))}.")]
    photo = f"/media/{e(item['photo'])}" if item.get("photo") else "/media/hero.jpg"
    rows = "".join(f'<li><b>{t}</b><span>{d}</span></li>' for t, d in steps)
    asked = e(o.get("asked_for", ""))
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(head)} · Small Garage</title>
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
.asked small{{display:block;font:500 11px/1 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin-bottom:6px}}
ol{{list-style:none;margin:0;padding:0;display:grid;gap:14px;counter-reset:s}}
li{{display:grid;grid-template-columns:30px 1fr;column-gap:12px;counter-increment:s}}
li:before{{content:counter(s);grid-row:span 2;width:30px;height:30px;border-radius:50%;border:1px solid var(--hair);display:grid;place-items:center;font:500 13px 'Geist Mono',monospace;color:var(--lamp)}}
li b{{font-weight:600}}li span{{color:var(--mute);font-size:15px;line-height:1.4}}
.foot{{margin-top:26px;padding-top:18px;border-top:1px solid var(--hair);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font:400 13px 'Geist Mono',monospace;color:var(--mute)}}
.foot a{{color:var(--cyan);text-decoration:none}}
@media (max-width:760px){{.wrap{{grid-template-columns:1fr}}.pic{{min-height:260px}}.body{{padding:26px 22px}}h1{{font-size:38px}}}}
</style></head><body><main class="wrap">
<div class="pic" style="background-image:url('{photo}')" role="img" aria-label="{e(item.get('title', ''))}"></div>
<div class="body"><div class="k">Small Garage · order {e(oc)}</div><h1>{e(head)}</h1>
<p class="lead">{lead}</p><p class="item">{e(o.get('title', item.get('title', '')))} · qty {o.get('qty', 1)}</p>
{f'<div class="asked"><small>You asked for</small>{asked}</div>' if asked else ''}
<ol>{rows}</ol>
<div class="foot"><span>PayPal sandbox · no real money</span><a href="/">Back to the counter</a></div></div>
</main></body></html>""")


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


@app.get("/api/maker/requests")
def maker_requests():
    """Call-back requests for Lena (newest first)."""
    return list(reversed(shop.requests_()))


@app.post("/api/maker/requests/{rid}")
async def maker_request_status(rid: str, req: Request):
    """Lena marks a call-back as done."""
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
        html = html.replace(f"/static/{f.name}", f"/static/{f.name}?v={int(f.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _stamped("index.html")


@app.get("/maker")
def maker():
    return _stamped("maker.html")
