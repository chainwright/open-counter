"""Open your counter (Roma 14565, item 4): any maker turns one photo and a sentence into a counter that AI agents
can read and buy from.

The vision model (NVIDIA Nemotron VL) only writes the words of the listing from the photo. Price, quantity and where
it ships from are typed by the maker and stored as they typed them; the AI never sets them. On publish the product
is also registered in PayPal's Catalog Products API, and the counter gets the same agent-readable JSON card as Lena's.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid

from PIL import Image

from . import paypal, shop, shopper

VISION = "nvidia/Nemotron-3.5-Super-VL"
LISTING_SYSTEM = """You write shop listings that AI shopping agents read before they buy. From the photo and the
maker's note, return JSON only, with these keys: title (max 60 chars), category, materials (list), size,
colour, made_by_hand (true/false/null), short_description (two plain sentences a buyer would like), keywords (5-8).
Describe only what you can see or were told. Use null for anything else. Never name a brand, a company or a car maker.
Never mention a price, stock or delivery time."""
MAX_COUNTERS = 60
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[a-z]{2,}$", re.I)
SAMPLE_PAYEE_ENV = "OPEN_COUNTER_SAMPLE_PAYEE"   # a second sandbox business account that the sample counters pay


def _counters() -> dict:
    return shop._json("counters.json", {})


def draft(image_b64: str, note: str, who=()) -> dict:
    """Listing words from a photo. Returns the fields for the maker to check, plus how long it took."""
    raw = base64.b64decode(image_b64.split(",", 1)[-1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    shopper.check_budget(who)
    t0 = time.time()
    r = shopper._client_().chat.completions.create(
        model=VISION, max_tokens=700, temperature=0.2, extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[{"role": "system", "content": LISTING_SYSTEM},
                  {"role": "user", "content": [{"type": "text", "text": "Maker's note: " + (note or "")[:300]},
                                               {"type": "image_url", "image_url": {
                                                   "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}])
    u = r.usage
    shopper.add_spend((u.prompt_tokens * shopper.PRICE_IN + u.completion_tokens * shopper.PRICE_OUT) / 1e6, who)
    text = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        listing = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        listing = {}
    clean = lambda v: shopper.BRANDS.sub("", v).strip() if isinstance(v, str) else v
    listing = {k: ([clean(x) for x in v] if isinstance(v, list) else clean(v)) for k, v in listing.items()}
    return {"listing": listing, "seconds": round(time.time() - t0, 1), "model": VISION}


def publish(listing: dict, price_usd: float, stock: int, ships_from: str, maker: str, shop_name: str,
            image_b64: str, visitor: str = "", paypal_email: str = "") -> dict:
    """Open the counter: save it, register the product with PayPal, and return the agent-readable URLs.
    paypal_email (optional): the maker's own PayPal account; buyers' payments go there (PayPal's 'payee')."""
    title = str(listing.get("title") or "").strip()[:80]
    if not title:
        raise ValueError("The listing needs a title.")
    if not (0 < float(price_usd) <= 10000) or not (0 < int(stock) <= 1000):
        raise ValueError("Set a price and how many you have.")
    payee = (paypal_email or "").strip()[:120]
    if payee and not EMAIL.match(payee):
        raise ValueError("Your PayPal email doesn't look like an email address.")
    st = (ships_from or "").strip().upper()[:2]
    if st not in shop.US_STATES:
        raise ValueError("Ships from: a US state code, like OH.")
    slug = re.sub(r"[^a-z0-9]+", "-", (shop_name or maker or "maker").lower()).strip("-")[:30] + "-" + uuid.uuid4().hex[:4]
    raw = base64.b64decode(image_b64.split(",", 1)[-1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1200, 1200))
    pdir = shop._path("counters")
    pdir.mkdir(exist_ok=True)
    im.save(pdir / f"{slug}.jpg", "JPEG", quality=86)
    product_id = None
    if paypal.configured():
        try:
            p = paypal._call("POST", "/v1/catalogs/products",
                             {"name": title, "description": str(listing.get("short_description") or "")[:250],
                              "type": "PHYSICAL"}, request_id=f"catalog-{slug}")
            product_id = p.get("id")
        except paypal.PayPalError:
            product_id = None
    c = {"slug": slug, "created": time.time(), "visitor": visitor, "maker": (maker or "").strip()[:60] or "A maker",
         "name": (shop_name or "").strip()[:60] or "My counter", "ships_from": st, "payee_email": payee,
         "listing": {**{k: listing.get(k) for k in ("title", "category", "materials", "size", "colour",
                                                     "made_by_hand", "short_description", "keywords")},
                     "id": slug + "-1", "title": title, "price_usd": round(float(price_usd), 2), "stock": int(stock),
                     "paypal_catalog_product": product_id}}
    with shop._lock:
        all_ = _counters()
        all_[slug] = c
        if len(all_) > MAX_COUNTERS:   # a public demo: keep the newest
            for k in sorted(all_, key=lambda k: all_[k]["created"])[:len(all_) - MAX_COUNTERS]:
                del all_[k]
        shop._save_json("counters.json", all_)
    return c


def payee(c: dict) -> str:
    """Whose PayPal account a counter's payments go to: the email the maker gave when she opened it; for the sample
    counters, the second sandbox merchant set in OPEN_COUNTER_SAMPLE_PAYEE; otherwise '' (the platform's merchant)."""
    from . import paypal
    to = c.get("payee_email") or (os.environ.get(SAMPLE_PAYEE_ENV, "").strip() if c.get("sample") else "")
    return to if paypal.can_pay(to) else ""


def screened(c: dict) -> bool:
    """She gave an email, but it isn't a PayPal sandbox account, so the demo pays the test merchant instead."""
    return bool(c.get("payee_email")) and not payee(c)


def paid_to(c: dict) -> str:
    if payee(c):
        return f"{c['maker']}'s own PayPal account"
    return ("the Open Counter demo merchant (sandbox: the email given isn't a PayPal sandbox account)" if screened(c)
            else "the Open Counter demo merchant (sandbox)")


def counter(slug: str) -> dict | None:
    return _counters().get(slug)


def latest(n: int = 12, visitor: str = "") -> list[dict]:
    """The sample counters plus the ones this browser opened (visitors' uploads aren't shown to other people)."""
    cs = [c for c in _counters().values() if c.get("sample") or (visitor and c.get("visitor") == visitor)]
    return sorted(cs, key=lambda c: -c["created"])[:n]


def take(slug: str, qty: int) -> bool:
    """Stock for a counter's listing, taken at capture (all or nothing)."""
    with shop._lock:
        all_ = _counters()
        c = all_.get(slug)
        if not c or c["listing"]["stock"] < qty:
            return False
        c["listing"]["stock"] -= qty
        shop._save_json("counters.json", all_)
        return True


def checkout(slug: str, qty: int, state: str, visitor: str = "") -> dict:
    """A buyer orders from a maker's counter: same rules as Lena's (stock, US state, PayPal approval by a person).
    The money goes to the maker's own PayPal account (the order's payee) when she gave one. If PayPal refuses that
    account in the sandbox (a made-up email on the public demo), the order is paid to the Open Counter demo merchant
    instead and says so; outside the sandbox it is refused, never redirected."""
    from . import paypal
    c = counter(slug)
    if not c:
        raise ValueError("No such counter.")
    l = c["listing"]
    qty, st = int(qty), (state or "").strip().upper()
    if not 1 <= qty <= l["stock"]:
        raise ValueError(f"Choose 1 to {l['stock']}.")
    est = shop.delivery_estimate(st)
    if not est.get("ok"):
        raise ValueError(est.get("reason", "Ships inside the US only."))
    ship = float(c.get("shipping_usd", 6.5))
    o = {"id": "OC-" + uuid.uuid4().hex[:8].upper(), "kind": "counter", "counter": slug, "listing_id": "",
         "title": l["title"], "qty": qty, "unit_usd": l["price_usd"], "shipping_usd": ship,
         "lines": [{"listing_id": l["id"], "title": l["title"], "qty": qty, "unit_usd": l["price_usd"]}],
         "total_usd": round(l["price_usd"] * qty + ship, 2), "ship_state": st, "estimate": est,
         "asked_for": f"{qty} × {l['title']} from {c['name']}", "channel": "counter-page", "visitor": visitor,
         "status": "awaiting_approval", "created": time.time(), "events": [["created", time.time()]]}
    with shop._lock:
        all_ = shop.orders()
        all_.append(o)
        shop._save_orders(all_)
    s = {"name": c["name"]}
    to = payee(c)
    args = dict(order_id=o["id"], shop=s, listing={"id": l["id"], "title": l["title"], "price_usd": l["price_usd"]},
                qty=qty, shipping_usd=ship, return_url=f"{_public_url()}/paypal/return?oc={o['id']}",
                cancel_url=f"{_public_url()}/paypal/cancel?oc={o['id']}")
    note = ""
    try:
        pp = paypal.create_order(**args, payee_email=to or None)
    except paypal.PayPalError as e:
        if not (to and paypal.payee_refused(e) and paypal.sandbox()):
            raise
        pp, to = paypal.create_order(**args), ""
        note = "PayPal didn't accept the maker's PayPal email, so this sandbox payment goes to the Open Counter demo merchant."
    link = paypal.approve_link(pp)
    paid_to_ = (f"{c['maker']}'s own PayPal account" if to else
                "the Open Counter demo merchant (sandbox)" if note else paid_to(c))
    shop.update_order(o["id"], paypal_order_id=pp["id"], approve_url=link, payee_email=to, paid_to=paid_to_,
                      **({"payee_note": note} if note else {}))
    return {"order_id": o["id"], "approve_url": link, "total_usd": o["total_usd"], "paid_to": paid_to_,
            **({"note": note} if note else {})}


def _public_url() -> str:
    from . import counter as _c
    return _c.PUBLIC_URL
