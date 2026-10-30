"""The demo maker's catalogue in PayPal Catalog Products (judge 29.10, N4): Lena's five listings and the sample
counters at /open are registered on start, so their PayPal product ids are on every card without anyone having to
open a counter first. A maker who opens a counter at /open is registered when she publishes (onboard.publish).

Each product gets an id we choose ("OC-SG-014"), so a restart or a redeploy looks it up instead of creating a
duplicate. Nothing here moves money; when PayPal is unreachable the cards simply show no id yet."""
from __future__ import annotations

import re

from . import onboard, paypal, shop


def product_id(key: str) -> str:
    """'sg-014' -> 'OC-SG-014' (PayPal wants 6 to 50 characters)."""
    return ("OC-" + re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-")).upper()[:50]


def ensure_product(pid: str, name: str, description: str, category: str | None = None) -> str | None:
    """The product's id in PayPal: found if it's already there, created if not, None if PayPal can't be reached."""
    try:
        return paypal.get_product(pid).get("id") or pid
    except paypal.PayPalError as e:
        if e.status != 404:
            return None
    try:
        return paypal.create_product(pid, name, description, category).get("id") or pid
    except paypal.PayPalError:
        return None


def sync() -> dict:
    """Register what isn't registered yet; returns {listing or counter: product id} for what changed."""
    if not paypal.configured():
        return {}
    s = shop.shop()
    found = {}
    for l in s["listings"]:
        if not l.get("paypal_catalog_product"):
            pid = ensure_product(product_id(l["id"]), l["title"],
                                 f"{l['scale']} replica hand-built by {s['maker']}, {s['name']} ({s['city']})")
            if pid:
                found[l["id"]] = pid
    if found:
        with shop._lock:   # read again under the lock: stock may have moved while PayPal answered
            s = shop.shop()
            for l in s["listings"]:
                if l["id"] in found:
                    l["paypal_catalog_product"] = found[l["id"]]
            shop.save_shop(s)
    counters = {}
    for slug, c in onboard._counters().items():
        if c.get("sample") and not c["listing"].get("paypal_catalog_product"):
            pid = ensure_product(product_id(slug), c["listing"]["title"], c["listing"].get("short_description") or "")
            if pid:
                counters[slug] = pid
    if counters:
        with shop._lock:
            cs = onboard._counters()
            for slug, pid in counters.items():
                if slug in cs:
                    cs[slug]["listing"]["paypal_catalog_product"] = pid
            shop._save_json("counters.json", cs)
    return found | counters
