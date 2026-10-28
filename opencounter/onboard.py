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


def _counters() -> dict:
    return shop._json("counters.json", {})


def draft(image_b64: str, note: str) -> dict:
    """Listing words from a photo. Returns the fields for the maker to check, plus how long it took."""
    raw = base64.b64decode(image_b64.split(",", 1)[-1])
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    if shopper.spent_today() >= shopper.DAILY_CAP_USD:
        raise shopper.OverBudget("today's AI budget is spent")
    t0 = time.time()
    r = shopper._client_().chat.completions.create(
        model=VISION, max_tokens=700, temperature=0.2, extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        messages=[{"role": "system", "content": LISTING_SYSTEM},
                  {"role": "user", "content": [{"type": "text", "text": "Maker's note: " + (note or "")[:300]},
                                               {"type": "image_url", "image_url": {
                                                   "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}])
    u = r.usage
    with shopper._lock:
        d = time.strftime("%Y-%m-%d")
        shopper._spent[d] = shopper._spent.get(d, 0.0) + (u.prompt_tokens * shopper.PRICE_IN + u.completion_tokens * shopper.PRICE_OUT) / 1e6
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
            image_b64: str, visitor: str = "") -> dict:
    """Open the counter: save it, register the product with PayPal, and return the agent-readable URLs."""
    title = str(listing.get("title") or "").strip()[:80]
    if not title:
        raise ValueError("The listing needs a title.")
    if not (0 < float(price_usd) <= 10000) or not (0 < int(stock) <= 1000):
        raise ValueError("Set a price and how many you have.")
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
         "name": (shop_name or "").strip()[:60] or "My counter", "ships_from": st,
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


def counter(slug: str) -> dict | None:
    return _counters().get(slug)


def latest(n: int = 12, visitor: str = "") -> list[dict]:
    """The sample counters plus the ones this browser opened (visitors' uploads aren't shown to other people)."""
    cs = [c for c in _counters().values() if c.get("sample") or (visitor and c.get("visitor") == visitor)]
    return sorted(cs, key=lambda c: -c["created"])[:n]
