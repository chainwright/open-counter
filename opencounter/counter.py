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
    if item.get("model"):
        d["model_url"] = f"{PUBLIC_URL}/media/{item['model']}"   # a 3D model of the replica (glTF binary)
    d["page_url"] = f"{PUBLIC_URL}/c/{shop.shop()['slug']}#{item['id']}"
    r = shop.shop()["rules"]
    if item["stock"] > 0:
        d["availability"] = "in stock"
    else:
        nb = item.get("next_batch")
        d["availability"] = "sold out" + (f"; next small batch ready about {nb}" if nb else "; no batch planned yet") + (
            f"; can be commissioned at ${r['commission_usd']} per car (not the shelf price), {r['commission_lead_weeks']} weeks "
            "for 1-2 cars; use quote_commission for more cars or exact dates" if r["commissions"] else "")
        d["next_batch"] = nb
    return d


def about_counter() -> dict:
    s = shop.shop()
    r = s["rules"]
    return {"shop": s["name"], "maker": s["maker"], "city": s["city"], "about": s["about"],
            "ships_to": r["ships_to"], "max_per_order": r["max_per_order"], "shipping_usd": r["shipping_usd"],
            "commissions": (f"${r['commission_usd']} per car in any colour; {r['commission_lead_weeks']} weeks for 1-2 cars, "
                            f"about {r['commission_cars_per_week']} more cars a week after that; "
                            + "; ".join(f"{t['percent']}% off from {t['min_cars']} cars" for t in r["commission_volume_discounts"])
                            + f"; free shipping from {r['commission_free_shipping_from']} cars. "
                            "Use quote_commission for exact numbers, request_commission to send Lena a request.")
            if r["commissions"] else "not taken",
            "buying_more_than_max": f"Orders above {r['max_per_order']} cars, and any sold-out car, go through a commission request.",
            "payment": "PayPal; the buyer approves every order in PayPal"}


def quote_commission(cars: list[dict], us_state: str = "") -> dict:
    """Exact price, volume discount, shipping, build time and delivery window for made-to-order cars.
    cars: [{"item_id" (or "body"), "colour", "quantity"}]."""
    try:
        return shop.commission_quote(cars, us_state)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}


def request_commission(name: str, email: str, phone: str, address: str, us_state: str, cars: list[dict],
                       notes: str = "", what_the_shopper_asked: str = "", channel: str = "mcp") -> dict:
    """Sends Lena a made-to-order request. Nothing is charged: she confirms by email, then sends a PayPal invoice."""
    try:
        rq = shop.new_commission_request({"name": name, "email": email, "phone": phone, "address": address},
                                         cars, us_state, notes, what_the_shopper_asked, channel)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    q = rq["quote"]
    return {"ok": True, "request_id": rq["id"], "status": "sent to Lena, waiting for her reply",
            "summary": "; ".join(f"{c['quantity']} × {c['car']} in {c['colour']}" for c in q["cars"]),
            "total_usd": q["total_usd"], "ready_to_ship_by": q["ready_to_ship_by"],
            "next_step": q["how_it_works"]}


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
