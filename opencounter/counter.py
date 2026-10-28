"""What any shopper's agent can do at the counter. The same five functions back the public MCP server and
the built-in demo shopper, so the demo shows exactly what a real outside agent gets.

None of these can take money. start_checkout only creates a PayPal order; a human approves it in PayPal."""
from __future__ import annotations

import os

from . import paypal, shop

PUBLIC_URL = os.environ.get("OPENCOUNTER_PUBLIC_URL", "http://127.0.0.1:8800").rstrip("/")
FIELDS = ("id", "title", "price_usd", "stock", "scale", "length_mm", "materials", "paint", "build_hours",
          "edition", "notes")


def _media_url(name: str) -> str:
    """Media URL stamped with the file's size and time: a phone that cached an older 3D model or photo
    (they're cached for a day) fetches the new one as soon as it changes."""
    p = shop.MEDIA_DIR / name
    v = f"?v={p.stat().st_size:x}{int(p.stat().st_mtime):x}" if p.exists() else ""
    return f"{PUBLIC_URL}/media/{name}{v}"


def receipt(o: dict) -> dict:
    """The order as a receipt: one row per car (qty × unit = sum), then discount, shipping and total (Roma 14551)."""
    rows = []
    if o.get("kind") == "commission":
        q = o["quote"]
        for c in q["cars"]:
            rows.append({"name": f"Made to order: {c['model']} ({c['year']}), {c['body_colour']} body, "
                                 f"{c['interior_colour']} interior", "qty": c["quantity"], "unit": q["unit_usd"],
                         "sum": round(c["quantity"] * q["unit_usd"], 2)})
        extra = [{"name": f"Volume discount {q['volume_discount_percent']}%", "sum": -q["discount_usd"]}] if q["discount_usd"] else []
    else:
        rows = [{"name": ln["title"], "qty": ln["qty"], "unit": ln["unit_usd"], "sum": round(ln["qty"] * ln["unit_usd"], 2)}
                for ln in (o.get("lines") or [{"title": o["title"], "qty": o["qty"], "unit_usd": o["unit_usd"]}])]
        extra = []
    extra.append({"name": "Shipping" if o["shipping_usd"] else "Shipping (free)", "sum": o["shipping_usd"]})
    out = {"rows": rows, "extra": extra, "total": o["total_usd"]}
    if o.get("deposit_usd"):
        out["deposit"] = o["deposit_usd"]
    return out


def _ship_to(o: dict) -> str:
    c = o.get("customer") or {}
    if not c:
        return ""
    return (f"{c['full_name']}, {c['address_line_1']}" + (f" {c['address_line_2']}" if c.get("address_line_2") else "")
            + f", {c['city']}, {c['state']} {c['postal_code']} · {c['phone']} · {c['email']}")


def _public(item: dict) -> dict:
    d = {k: item[k] for k in FIELDS}
    d["photo_url"] = _media_url(item["photo"])
    if item.get("model"):
        d["model_url"] = _media_url(item["model"])   # a 3D model of the replica (glTF binary)
    d["page_url"] = f"{PUBLIC_URL}/c/{shop.shop()['slug']}#{item['id']}"
    r = shop.shop()["rules"]
    d["availability"] = (f"{item['stock']} in stock" if item["stock"] > 0 else "sold out") + (
        "; any car can also be made to order (use quote_commission)" if r["commissions"] else "")
    return d


def about_counter() -> dict:
    s = shop.shop()
    r = s["rules"]
    tiers = "; ".join(f"up to {t['up_to']} cars: {t['weeks']} week{'s' if t['weeks'] > 1 else ''}" for t in r["commission_lead_tiers"])
    return {"shop": s["name"], "maker": s["maker"], "city": s["city"], "about": s["about"],
            "ships_to": r["ships_to"], "shipping_usd": r["shipping_usd"],
            "buying_from_stock": "any quantity up to the stock shown on the listing",
            "shipping_policy": shop.shipping_policy(),
            "made_to_order": (f"${r['commission_usd']} per car; build time {tiers}; then about 1 more week per "
                              f"{r['commission_extra_week_per']} cars; "
                              + "; ".join(f"{t['percent']}% off from {t['min_cars']} cars" for t in r["commission_volume_discounts"])
                              + f"; free shipping from {r['commission_free_shipping_from']} cars. Ask for the car, the "
                              "year of the real car, body colour, interior colour and quantity, then quote_commission, "
                              "then start_commission_checkout (paid through PayPal like any order).")
            if r["commissions"] else "not taken",
            "talk_to_lena": "Lena doesn't give out a number; use leave_contact with the person's phone and she calls them.",
            "payment": "PayPal; the buyer approves every order in PayPal"}


def quote_commission(cars: list[dict], us_state: str = "") -> dict:
    """Exact price, volume discount, shipping, build time and delivery window for made-to-order cars.
    cars: [{"model", "year", "body_colour", "interior_colour", "quantity"}]."""
    try:
        return shop.commission_quote(cars, us_state)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}


def start_commission_checkout(cars: list[dict], us_state: str, name: str, phone: str, what_the_shopper_asked: str,
                              channel: str = "mcp", customer: dict | None = None) -> dict:
    """Creates the made-to-order order and a PayPal approval link for the quoted total. Nothing is charged until the
    person approves in PayPal; Lena starts building once it's paid."""
    if not paypal.configured():
        return {"ok": False, "reason": "Checkout is offline right now; nothing was created or charged."}
    try:
        o = shop.new_commission_order(cars, us_state, name, phone, what_the_shopper_asked, channel, customer=customer)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    s = shop.shop()
    # one invoice line per car spec (qty × unit), the volume discount shown separately (Roma 14551)
    q = o["quote"]
    lines = [({"id": f"MTO-{i + 1}", "price_usd": q["unit_usd"],
               "title": f"Made to order: {c['model']} ({c['year']}), {c['body_colour']}/{c['interior_colour']}"}, c["quantity"])
             for i, c in enumerate(q["cars"])]
    deposit = None
    if o.get("customer"):
        # Lena's way of working: half up front, the rest before it ships. A PayPal invoice takes the deposit now and
        # the balance later, with the buyer's details already on it.
        try:
            inv = paypal.create_deposit_invoice(order_id=o["id"], shop=s, rows=receipt(o)["rows"],
                                                discount_usd=q["discount_usd"], shipping_usd=o["shipping_usd"],
                                                customer=o["customer"], total_usd=o["total_usd"])
            deposit = inv["deposit_usd"]
            shop.update_order(o["id"], invoice_id=inv["id"], approve_url=inv["payer_url"], deposit_usd=deposit,
                              paid_usd=0.0, payment="invoice")
            link = inv["payer_url"]
        except paypal.PayPalError:
            deposit = None   # fall back to a one-time PayPal checkout for the full amount
    if deposit is not None:
        return {"ok": True, "order_id": o["id"], "approve_url": link, "you_asked_for": what_the_shopper_asked,
                "you_are_approving": f"{o['title']} = ${o['total_usd']:.2f}; deposit now ${deposit:.2f}, "
                                     f"the balance before it ships",
                "delivery": f"built in {q['build_weeks']} week(s), ships {q['delivery']['ships_on']}, arrives "
                            f"{q['delivery']['arrives_earliest']} to {q['delivery']['arrives_latest']} (estimate)",
                "ship_to": _ship_to(o), "receipt": receipt(shop.order(o["id"])),
                "deposit_usd": deposit, "payment": "invoice",
                "next_step": f"A PayPal invoice was sent to the buyer's email. They pay the ${deposit:.2f} deposit now "
                             "(or the full amount) on PayPal; Lena starts building once the deposit is in."}
    try:
        pp = paypal.create_order(order_id=o["id"], shop=s, listing=lines[0][0], qty=lines[0][1], lines=lines,
                                 shipping_usd=o["shipping_usd"], discount_usd=q["discount_usd"],
                                 customer=o.get("customer"),
                                 return_url=f"{PUBLIC_URL}/paypal/return?oc={o['id']}",
                                 cancel_url=f"{PUBLIC_URL}/paypal/cancel?oc={o['id']}")
    except paypal.PayPalError:
        shop.update_order(o["id"], status="error")
        return {"ok": False, "reason": "PayPal could not create the order; nothing was charged."}
    link = paypal.approve_link(pp)
    shop.update_order(o["id"], paypal_order_id=pp["id"], approve_url=link)
    q = o["quote"]
    return {"ok": True, "order_id": o["id"], "approve_url": link, "you_asked_for": what_the_shopper_asked,
            "you_are_approving": f"{o['title']}: {q['total_cars']} × ${q['unit_usd']}"
                                 + (f" − {q['volume_discount_percent']}% (${q['discount_usd']:.2f})" if q["discount_usd"] else "")
                                 + f" + ${q['shipping_usd']:.2f} shipping = ${o['total_usd']:.2f}",
            "delivery": f"built in {q['build_weeks']} week(s), ships {q['delivery']['ships_on']}, arrives "
                        f"{q['delivery']['arrives_earliest']} to {q['delivery']['arrives_latest']} (estimate)",
            "ship_to": _ship_to(o), "receipt": receipt(o),
            "next_step": "Show both lines, then open approve_url. Nothing is charged until they approve in PayPal."}


def leave_contact(phone: str, name: str = "", message: str = "", what_the_shopper_asked: str = "",
                  channel: str = "mcp") -> dict:
    """Passes the person's phone number and question to Lena; she calls them back."""
    try:
        rq = shop.new_callback(phone, name, message, what_the_shopper_asked, channel)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True, "request_id": rq["id"], "next_step": "Passed to Lena; she'll call this number herself."}


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
                   channel: str = "mcp", items: list[dict] | None = None, customer: dict | None = None) -> dict:
    """Creates an order that waits for the human. Returns the PayPal approval link and a side-by-side
    'you asked for / you are approving' summary the agent must show before sending the person to PayPal."""
    if not paypal.configured():
        return {"ok": False, "reason": "Checkout is offline right now; nothing was created or charged."}
    try:
        o = shop.new_order(item_id, int(quantity or 0), us_state, what_the_shopper_asked, channel, items=items,
                           customer=customer)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    s = shop.shop()
    item = shop.listing(item_id)
    try:
        pp = paypal.create_order(order_id=o["id"], shop=s, listing=item, qty=o["qty"],
                                 shipping_usd=o["shipping_usd"],
                                 lines=[(shop.listing(ln["listing_id"]), ln["qty"]) for ln in o["lines"]],
                                 customer=o.get("customer"),
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
            "you_are_approving": " + ".join(f"{ln['qty']} × {ln['title']} at ${ln['unit_usd']:.2f}" for ln in o["lines"])
                                 + f" + ${o['shipping_usd']:.2f} shipping = ${o['total_usd']:.2f}, from {s['name']} "
                                 f"({s['maker']}, {s['city']})",
            "delivery": f"ships {est['ships_on']}, estimated arrival {est['arrives_earliest']} to "
                        f"{est['arrives_latest']} ({est['carrier']}; estimate, not a guarantee)",
            "ship_to": _ship_to(o), "receipt": receipt(o),
            "next_step": "Show both lines to the person, then open approve_url. Nothing is charged until they "
                         "approve in PayPal."}


def order_status(order_id: str) -> dict:
    o = shop.order(order_id)
    if not o:
        return {"error": f"No order '{order_id}'."}
    out = {k: o.get(k) for k in ("id", "title", "qty", "total_usd", "status", "tracking")}
    out["estimate"] = o["estimate"]
    return out


def marketing_consent(email: str, agrees: bool, what_they_said: str) -> dict:
    """Records the buyer's own yes/no to emails about new models and offers (asked once, after an order)."""
    try:
        c = shop.set_marketing(email, agrees, what_they_said)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True, "subscribed": c["marketing"],
            "next_step": "Thank them briefly; don't ask again." if c["marketing"] else "Fine, no emails. Don't ask again."}
