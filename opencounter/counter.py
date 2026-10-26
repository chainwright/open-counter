"""What any shopper's agent can do at the counter. The same five functions back the public MCP server and
the built-in demo shopper, so the demo shows exactly what a real outside agent gets.

None of these can take money. start_checkout only creates a PayPal order; a human approves it in PayPal."""
from __future__ import annotations

import os

from . import paypal, shop

PUBLIC_URL = os.environ.get("OPENCOUNTER_PUBLIC_URL", "http://127.0.0.1:8800").rstrip("/")
FIELDS = ("id", "title", "price_usd", "stock", "scale", "length_mm", "materials", "paint", "build_hours",
          "edition", "notes")


def _public(item: dict) -> dict:
    d = {k: item[k] for k in FIELDS}
    d["photo_url"] = f"{PUBLIC_URL}/media/{item['photo']}"
    d["page_url"] = f"{PUBLIC_URL}/c/{shop.shop()['slug']}#{item['id']}"
    d["availability"] = "in stock" if item["stock"] > 0 else "sold out (can be commissioned)"
    return d


def about_counter() -> dict:
    s = shop.shop()
    r = s["rules"]
    return {"shop": s["name"], "maker": s["maker"], "city": s["city"], "about": s["about"],
            "ships_to": r["ships_to"], "max_per_order": r["max_per_order"], "shipping_usd": r["shipping_usd"],
            "commissions": f"from ${r['commission_from_usd']}, about {r['commission_lead_weeks']} weeks"
            if r["commissions"] else "not taken", "payment": "PayPal; the buyer approves every order in PayPal"}


def search_counter(query: str = "", max_price_usd: float | None = None) -> dict:
    hits = shop.search(query, max_price_usd)
    return {"shop": shop.shop()["name"], "results": [_public(h) | {"matched": h["matched"]} for h in hits[:6]],
            "note": "Only items listed here exist. Anything not in a listing is unknown: ask the maker."}


def item_details(item_id: str) -> dict:
    item = shop.listing(item_id)
    return _public(item) if item else {"error": f"No item '{item_id}'."}


def delivery_estimate(us_state: str, need_by: str = "") -> dict:
    return shop.delivery_estimate(us_state, need_by=need_by)


def start_checkout(item_id: str, quantity: int, us_state: str, what_the_shopper_asked: str,
                   channel: str = "mcp") -> dict:
    """Creates an order that waits for the human. Returns the PayPal approval link and a side-by-side
    'you asked for / you are approving' summary the agent must show before sending the person to PayPal."""
    if not paypal.configured():
        return {"ok": False, "reason": "Checkout is offline right now; nothing was created or charged."}
    try:
        o = shop.new_order(item_id, int(quantity), us_state, what_the_shopper_asked, channel)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    s = shop.shop()
    item = shop.listing(item_id)
    try:
        pp = paypal.create_order(order_id=o["id"], shop=s, listing=item, qty=o["qty"],
                                 shipping_usd=o["shipping_usd"],
                                 return_url=f"{PUBLIC_URL}/paypal/return?oc={o['id']}",
                                 cancel_url=f"{PUBLIC_URL}/paypal/cancel?oc={o['id']}")
    except paypal.PayPalError as e:
        shop.update_order(o["id"], status="error", error=str(e))
        return {"ok": False, "reason": "PayPal could not create the order; nothing was charged."}
    link = paypal.approve_link(pp)
    shop.update_order(o["id"], paypal_order_id=pp["id"], approve_url=link)
    est = o["estimate"]
    est = {k: (v.split(" ")[-1] if isinstance(v, str) and k.startswith(("ships", "arrives")) else v) for k, v in est.items()}
    return {"ok": True, "order_id": o["id"], "approve_url": link,
            "you_asked_for": what_the_shopper_asked,
            "you_are_approving": f"{o['qty']} × {o['title']} at ${o['unit_usd']:.2f} + ${o['shipping_usd']:.2f} "
                                 f"shipping = ${o['total_usd']:.2f}, from {s['name']} ({s['maker']}, {s['city']})",
            "delivery": f"ships {est['ships_on']}, estimated arrival {est['arrives_earliest']} to "
                        f"{est['arrives_latest']} ({est['carrier']}; estimate, not a guarantee)",
            "next_step": "Show both lines to the person, then open approve_url. Nothing is charged until they "
                         "approve in PayPal."}


def order_status(order_id: str) -> dict:
    o = shop.order(order_id)
    if not o:
        return {"error": f"No order '{order_id}'."}
    out = {k: o.get(k) for k in ("id", "title", "qty", "total_usd", "status", "tracking")}
    out["estimate"] = o["estimate"]
    return out
