"""The maker's shop: listings, stock, rules, orders. Plain JSON on disk; the demo shop is re-seeded on boot.

Everything an agent is told comes from here. If a fact is not in the listing or the rules, the answer is
"ask the maker", never a guess."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("OPENCOUNTER_DATA", ROOT / "data"))
SEED = ROOT / "demo" / "shop.json"
MEDIA_DIR = ROOT / "demo" / "media"
_lock = threading.RLock()

# The public demo is a fictional shop with 1-2 of each car, so one judge's purchase would empty it for everyone after.
# In demo mode a car that sold out comes back after a while ("Lena finished another one"); the sold-out state is
# still visible in between. Items seeded at 0 stay at 0: they show the commission path.
DEMO = os.environ.get("OPENCOUNTER_DEMO", "1") != "0"
RESTOCK_AFTER_S = float(os.environ.get("OPENCOUNTER_DEMO_RESTOCK_MIN", "10")) * 60
MAX_ORDERS = 2000

# USPS Ground Advantage from Columbus, OH, in business days after drop-off. A planning estimate, shown as one.
_ZONE_DAYS = {
    "near": (1, 3, {"OH", "IN", "MI", "KY", "WV", "PA", "IL", "NY", "TN", "VA", "MD", "DC", "DE", "NJ", "WI"}),
    "mid": (2, 4, {"NC", "SC", "GA", "AL", "MS", "MO", "IA", "MN", "AR", "LA", "KS", "NE", "OK", "CT", "RI", "MA",
                   "VT", "NH", "ME", "FL", "TX", "SD", "ND"}),
    "far": (3, 5, {"CO", "NM", "WY", "MT", "ID", "UT", "AZ", "NV", "CA", "OR", "WA"}),
    "remote": (4, 8, {"AK", "HI", "PR"}),
}
US_STATES = set().union(*(z[2] for z in _ZONE_DAYS.values()))


def _path(name: str) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA / name


def seed(force: bool = False):
    with _lock:
        p = _path("shop.json")
        if force or not p.exists():
            p.write_text(SEED.read_text())
        o = _path("orders.json")
        if force or not o.exists():
            o.write_text("[]")


def shop() -> dict:
    seed()
    with _lock:
        s = json.loads(_path("shop.json").read_text())
        if DEMO and _demo_restock(s):
            save_shop(s)
        return s


def _demo_restock(s: dict, now: float | None = None) -> bool:
    now = now or time.time()
    seeded = {x["id"]: x["stock"] for x in json.loads(SEED.read_text())["listings"]}
    changed = False
    for item in s["listings"]:
        sold_at = item.get("sold_out_at")
        if sold_at and item["stock"] <= 0 and now - sold_at >= RESTOCK_AFTER_S:
            item["stock"] = seeded.get(item["id"], 1)
            item.pop("sold_out_at")
            changed = True
    return changed


def save_shop(s: dict):
    with _lock:
        _path("shop.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))


def listing(lid: str) -> dict | None:
    return next((x for x in shop()["listings"] if x["id"] == lid), None)


def search(query: str = "", max_price: float | None = None, in_stock_only: bool = False) -> list[dict]:
    """Keyword match over title, paint, keywords. Deliberately simple and explainable: an agent can always
    see why something matched."""
    words = [w for w in query.lower().replace(",", " ").split() if len(w) > 2]
    out = []
    for item in shop()["listings"]:
        hay = " ".join([item["title"], item["paint"], " ".join(item["keywords"])]).lower()
        hits = [w for w in words if w.rstrip("s") in hay]
        if words and not hits:
            continue
        if max_price is not None and item["price_usd"] > max_price:
            continue
        if in_stock_only and item["stock"] <= 0:
            continue
        out.append({**item, "matched": hits})
    out.sort(key=lambda x: (-len(x["matched"]), x["stock"] <= 0))
    return out


def shipping_policy() -> str:
    r = shop()["rules"]
    days = ", ".join(r["ship_days"])
    return (f"Paid orders from stock ship {r['handling_days']} business day after payment, on the next shipping day "
            f"({days}); the tracking number comes by email when it ships. ships_on assumes payment today.")


def next_ship_day(today: date | None = None) -> date:
    s = shop()["rules"]
    d = (today or date.today()) + timedelta(days=s["handling_days"])
    while d.strftime("%a") not in s["ship_days"]:
        d += timedelta(days=1)
    return d


def _add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _need_by_date(need_by: str, today: date) -> date | None:
    """'2026-10-30', 'Friday' or 'fri' -> a date (the next such weekday, today counts)."""
    v = (need_by or "").strip().lower()
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    for i, name in enumerate(WEEKDAYS):
        if name.startswith(v[:3]):
            return today + timedelta(days=(i - today.weekday()) % 7)
    return None


def delivery_estimate(state: str, today: date | None = None, need_by: str = "") -> dict:
    state = (state or "").strip().upper()
    if state not in US_STATES:
        return {"ok": False, "reason": f"Lena ships inside the US only; '{state or '?'}' is not a US state code."}
    lo, hi = next((z[0], z[1]) for z in _ZONE_DAYS.values() if state in z[2])
    today = today or date.today()
    ship = next_ship_day(today)
    early, late = _add_business_days(ship, lo), _add_business_days(ship, hi)
    day = lambda d: f"{d.strftime('%A')} {d.isoformat()}"
    out = {"ok": True, "today": day(today), "ships_on": day(ship), "arrives_earliest": day(early),
           "arrives_latest": day(late), "carrier": "USPS Ground Advantage",
           "note": "Estimate from the carrier's published ranges, not a guarantee.",
           "shipping_policy": shipping_policy()}
    nb = _need_by_date(need_by, today)
    if nb:  # decided in code, so the agent never does date arithmetic
        out["need_by"] = day(nb)
        out["need_by_verdict"] = ("on time" if late <= nb else "possible, not certain" if early <= nb
                                  else "too late")
    return out


# ---- commissions: priced and scheduled in code, so an agent can only repeat the numbers ----
SPEC = {"model": "the car: body style or one of the listings (e.g. fastback, coupe, convertible)",
        "year": "the year of the real car it's modelled on", "body_colour": "the body colour",
        "interior_colour": "the interior colour", "quantity": "how many"}


def commission_weeks(qty: int) -> int:
    r = shop()["rules"]
    for t in r["commission_lead_tiers"]:
        if qty <= t["up_to"]:
            return t["weeks"]
    last = r["commission_lead_tiers"][-1]
    return last["weeks"] + -(-(qty - last["up_to"]) // r["commission_extra_week_per"])


def commission_quote(lines: list[dict], state: str = "", today: date | None = None) -> dict:
    """lines: [{"model", "year", "body_colour", "interior_colour", "quantity"}]. Price, discount, shipping, build
    time and delivery for made-to-order cars, from the maker's rules. Raises ValueError naming what to ask for."""
    s = shop()
    r = s["rules"]
    if not r.get("commissions"):
        raise ValueError(f"{s['maker']} isn't taking commissions right now.")
    clean, qty = [], 0
    for ln in lines or []:
        item = listing(ln.get("item_id", "")) if ln.get("item_id") else None
        spec = {"model": (ln.get("model") or (item["title"].rsplit(",", 1)[0] if item else "")).strip(),
                "year": str(ln.get("year") or "").strip(), "body_colour": (ln.get("body_colour") or ln.get("colour") or "").strip().lower(),
                "interior_colour": (ln.get("interior_colour") or "").strip().lower(), "quantity": int(ln.get("quantity") or 0),
                "details": re.sub(r"\s+", " ", str(ln.get("details") or "")).strip()[:120]}
        missing = [SPEC[k] for k, v in spec.items() if not v and k in SPEC]
        if missing:
            raise ValueError("Before quoting, ask for " + ", ".join(missing) + ".")
        clean.append(spec)
        qty += spec["quantity"]
    if not clean:
        raise ValueError("Ask which car, the year of the real car, the body and interior colours, and how many.")
    if qty > r["commission_max_cars"]:
        raise ValueError(f"{s['maker']} takes at most {r['commission_max_cars']} cars in one order; for more she'll call.")
    unit = r["commission_usd"]
    pct = max([t["percent"] for t in r["commission_volume_discounts"] if qty >= t["min_cars"]] or [0])
    subtotal = unit * qty
    discount = round(subtotal * pct / 100, 2)
    shipping = 0.0 if qty >= r["commission_free_shipping_from"] else r["shipping_usd"]
    weeks = commission_weeks(qty)
    today = today or date.today()
    ready = today + timedelta(weeks=weeks)
    out = {"ok": True, "cars": clean, "total_cars": qty, "unit_usd": unit, "subtotal_usd": subtotal,
           "volume_discount_percent": pct, "discount_usd": discount, "shipping_usd": round(shipping, 2),
           "total_usd": round(subtotal - discount + shipping, 2), "build_weeks": weeks,
           "ready_to_ship_by": f"{ready.strftime('%A')} {ready.isoformat()}",
           "lead_times": "; ".join(f"up to {t['up_to']} cars: {t['weeks']} week{'s' if t['weeks'] > 1 else ''}"
                                   for t in r["commission_lead_tiers"]),
           "discounts": "; ".join(f"{t['percent']}% off from {t['min_cars']} cars" for t in r["commission_volume_discounts"])
                        + f"; free shipping from {r['commission_free_shipping_from']} cars"}
    if state:
        est = delivery_estimate(state, today=ready)
        if not est["ok"]:
            raise ValueError(est["reason"])
        out["delivery"] = {k: est[k] for k in ("ships_on", "arrives_earliest", "arrives_latest", "carrier")}
    return out


def commission_title(q: dict) -> str:
    return "Made to order: " + "; ".join(f"{c['quantity']} × {c['model']} ({c['year']}), {c['body_colour']} body, "
                                         f"{c['interior_colour']} interior" + (f", {c['details']}" if c.get("details") else "")
                                         for c in q["cars"])


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def clean_customer(c: dict | None, state: str) -> dict:
    """Who the order ships to, checked before any money moves (Roma 14497: name, phone, email, exact address).
    Raises ValueError naming everything still missing, so the agent asks once."""
    c = {k: str(v or "").strip() for k, v in (c or {}).items()}
    zip_ = re.sub(r"\D", "", c.get("postal_code", ""))
    missing = [label for label, ok in (
        ("first and last name", len(c.get("full_name", "").split()) >= 2),
        ("phone number", len(re.sub(r"\D", "", c.get("phone", ""))) >= 7),
        ("email (for the receipt and tracking)", bool(EMAIL.match(c.get("email", "")))),
        ("street address", bool(re.search(r"\d", c.get("address_line_1", ""))) and len(c.get("address_line_1", "")) >= 5),
        ("city", len(c.get("city", "")) >= 2),
        ("ZIP code", len(zip_) == 5)) if not ok]
    if missing:
        raise ValueError("Still needed for the delivery: " + ", ".join(missing) + ".")
    st = (c.get("state") or state or "").strip().upper()
    real = zip_state(zip_)
    if real and st != real:
        # the ZIP decides: a model must not "fix" a mismatch by changing the state (28.10 audit: SF ZIP sent to CO)
        raise ValueError(f"ZIP {zip_} is in {real}, not {st}. Ask the person which address is right; don't change it yourself.")
    if state and st != state.strip().upper():
        raise ValueError(f"The address is in {st} but the order ships to {state.upper()}; ask the person which is right.")
    return {"full_name": c["full_name"][:120], "phone": c["phone"][:40], "email": c["email"][:120],
            "address_line_1": c["address_line_1"][:200], "address_line_2": c.get("address_line_2", "")[:200],
            "city": c["city"][:80], "state": st, "postal_code": zip_}


def new_commission_order(lines: list[dict], state: str, name: str, phone: str, asked_for: str, channel: str,
                         customer: dict | None = None) -> dict:
    """A made-to-order order that waits for the buyer's PayPal approval, like a stock order, priced from the quote."""
    if not str(name or "").strip() or not str(phone or "").strip():
        raise ValueError("Ask for the person's name and a phone number, so Lena can call about the details.")
    cust = clean_customer(customer, state) if customer else None
    q = commission_quote(lines, state)
    o = {"id": "OC-" + uuid.uuid4().hex[:8].upper(), "kind": "commission", "listing_id": "", "title": commission_title(q),
         "qty": q["total_cars"], "unit_usd": q["unit_usd"], "discount_usd": q["discount_usd"],
         "shipping_usd": q["shipping_usd"], "total_usd": q["total_usd"], "quote": q,
         "contact": {"name": str(name).strip()[:120], "phone": str(phone).strip()[:40]}, "customer": cust,
         "ship_state": state.upper(), "estimate": {"ok": True, "ships_on": q["delivery"]["ships_on"],
                                                   "arrives_earliest": q["delivery"]["arrives_earliest"],
                                                   "arrives_latest": q["delivery"]["arrives_latest"],
                                                   "carrier": q["delivery"]["carrier"]},
         "asked_for": asked_for[:400], "channel": channel, "status": "awaiting_approval", "created": time.time(),
         "events": [["created", time.time()]]}
    with _lock:
        all_ = orders()
        all_.append(o)
        _save_orders(all_)
    remember_customer(o.get("customer"), o["id"])
    return o


def _requests_path() -> Path:
    return _path("requests.json")


def requests_() -> list[dict]:
    seed()
    p = _requests_path()
    return json.loads(p.read_text()) if p.exists() else []


def new_callback(phone: str, name: str, message: str, asked_for: str, channel: str) -> dict:
    """The person wants to talk to Lena: their number and question go to her screen; she calls them."""
    if len(re.sub(r"\D", "", phone or "")) < 7:
        raise ValueError("Ask for a phone number Lena can call (with area code).")
    rq = {"id": "CB-" + uuid.uuid4().hex[:8].upper(), "kind": "callback", "status": "to_call", "created": time.time(),
          "contact": {"name": str(name or "").strip()[:120], "phone": phone.strip()[:40]},
          "message": (message or "")[:500], "asked_for": asked_for[:400], "channel": channel}
    with _lock:
        all_ = requests_()
        all_.append(rq)
        _requests_path().write_text(json.dumps(all_[-MAX_ORDERS:], indent=2, ensure_ascii=False))
    return rq


def update_request(rid: str, **fields) -> dict:
    with _lock:
        all_ = requests_()
        r = next(x for x in all_ if x["id"] == rid)
        r.update(fields)
        _requests_path().write_text(json.dumps(all_, indent=2, ensure_ascii=False))
        return r


# ---- orders ----
def orders() -> list[dict]:
    seed()
    return json.loads(_path("orders.json").read_text())


def _save_orders(o: list[dict]):
    # sample history always stays; live orders keep the newest 2000 (a flood of demo checkouts can't push them out)
    keep = [x for x in o if x.get("sample")] + [x for x in o if not x.get("sample")][-MAX_ORDERS:]
    _save_json("orders.json", keep)


def new_order(lid: str, qty: int, state: str, asked_for: str, channel: str,
              items: list[dict] | None = None, customer: dict | None = None) -> dict:
    """Checks the maker's rules before any money moves. Raises ValueError with a sentence an agent can relay.
    items: several cars in one order, [{"item_id", "quantity"}]; otherwise lid/qty is the single line."""
    s = shop()
    lines = order_lines(lid, qty, items)
    est = delivery_estimate(state)
    if not est["ok"]:
        raise ValueError(est["reason"])
    cust = clean_customer(customer, state) if customer else None
    items_usd = sum(ln["unit_usd"] * ln["qty"] for ln in lines)
    return _store_order(s, lines, est, cust, items_usd, state, asked_for, channel)


def order_lines(lid: str, qty: int, items: list[dict] | None = None) -> list[dict]:
    """The checked lines of a stock order (merged by listing, stock respected)."""
    s = shop()
    want: dict[str, int] = {}
    for it in (items or [{"item_id": lid, "quantity": qty}]):
        k = str(it.get("item_id", ""))
        want[k] = want.get(k, 0) + int(it.get("quantity") or 0)
    lines = []
    for k, q in want.items():
        item = listing(k)
        if not item and k:
            hits = search(k)   # an agent passed a name or colour instead of the id: accept one clear match
            item = hits[0] if len(hits) == 1 else None
            k = item["id"] if item else k
        if not item:
            raise ValueError(f"No listing '{k}' at {s['name']}.")
        if q < 1:
            raise ValueError("Quantity must be at least 1.")
        if item["stock"] < q:
            raise ValueError(f"Only {item['stock']} of '{item['title']}' in stock."
                             + (" It can be commissioned instead." if s["rules"]["commissions"] else ""))
        lines.append({"listing_id": k, "title": item["title"], "qty": q, "unit_usd": item["price_usd"]})
    if not lines:
        raise ValueError("Say which car and how many.")
    return lines


def _store_order(s, lines, est, cust, items_usd, state, asked_for, channel) -> dict:
    title = lines[0]["title"] if len(lines) == 1 else " + ".join(f"{ln['qty']} × {ln['title']}" for ln in lines)
    o = {"id": "OC-" + uuid.uuid4().hex[:8].upper(), "listing_id": lines[0]["listing_id"], "title": title,
         "qty": sum(ln["qty"] for ln in lines), "lines": lines, "customer": cust,
         "unit_usd": lines[0]["unit_usd"], "shipping_usd": s["rules"]["shipping_usd"],
         "total_usd": round(items_usd + s["rules"]["shipping_usd"], 2),
         "ship_state": state.upper(), "estimate": est, "asked_for": asked_for[:400], "channel": channel,
         "status": "awaiting_approval", "created": time.time(), "events": [["created", time.time()]]}
    with _lock:
        all_ = orders()
        all_.append(o)
        _save_orders(all_)
    remember_customer(o.get("customer"), o["id"])
    return o


def update_order(oid: str, **fields) -> dict:
    with _lock:
        all_ = orders()
        o = next(x for x in all_ if x["id"] == oid)
        if "status" in fields and fields["status"] != o["status"]:
            o["events"].append([fields["status"], time.time()])
        o.update(fields)
        _save_orders(all_)
        return o


def order(oid: str) -> dict | None:
    return next((x for x in orders() if x["id"] == oid), None)


def take_stock_lines(lines: list[dict]) -> bool:
    """All lines of one order or none: False if any ran out in between (then the payment is refunded)."""
    with _lock:
        s = shop()
        items = {x["id"]: x for x in s["listings"]}
        if any(items[ln["listing_id"]]["stock"] < ln["qty"] for ln in lines):
            return False
        for ln in lines:
            it = items[ln["listing_id"]]
            it["stock"] -= ln["qty"]
            if it["stock"] <= 0:
                it["sold_out_at"] = time.time()
        save_shop(s)
        return True


def take_stock(lid: str, qty: int) -> bool:
    """Decrement stock at capture time; False if it ran out in between (then the payment is refunded)."""
    with _lock:
        s = shop()
        item = next(x for x in s["listings"] if x["id"] == lid)
        if item["stock"] < qty:
            return False
        item["stock"] -= qty
        if item["stock"] <= 0:
            item["sold_out_at"] = time.time()
        save_shop(s)
        return True


# ---- conversations and customers (Roma 14526: keep chats, let Lena read them, build a customer list) ----

def _json(name: str, default):
    p = _path(name)
    return json.loads(p.read_text()) if p.exists() else default


def _save_json(name: str, data):
    p = _path(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(p)


def log_turn(cid: str, user_text: str, reply: str, steps: list[dict], order_id: str | None, channel: str = "demo-shopper",
             name: str = "", memo: str = ""):
    """One question and answer of a shopper chat, kept for Lena (newest chats first on her screen)."""
    cid = re.sub(r"[^A-Za-z0-9_-]", "", cid or "")[:40] or "anon-" + uuid.uuid4().hex[:8]
    now = time.time()
    with _lock:
        all_ = _json("conversations.json", {})
        if cid not in all_:   # chats are numbered in the order they start, like tickets
            n = max([x.get("no", 0) for x in all_.values()] + [0]) + 1
            all_[cid] = {"id": cid, "no": n, "started": now, "channel": channel, "turns": [], "orders": [], "name": ""}
        c = all_[cid]
        if name and not c.get("name"):
            c["name"] = name.strip()[:80]
        c["turns"].append({"at": now, "user": user_text[:1000], "reply": reply[:2000],
                           "steps": [s.get("label", "") + " · " + s.get("result", "") for s in steps][:8],
                           "memo": memo[:800]})
        c["turns"] = c["turns"][-80:]
        if order_id and order_id not in c["orders"]:
            c["orders"].append(order_id)
        c["updated"] = now
        if len(all_) > 500:   # keep the newest 500 chats
            for k in sorted(all_, key=lambda k: all_[k].get("updated", 0))[:len(all_) - 500]:
                del all_[k]
        _save_json("conversations.json", all_)
    return cid


def server_memos(cid: str) -> list[str]:
    """What the tools returned in each earlier turn of this chat, as the server recorded it (never the browser's copy)."""
    c = _json("conversations.json", {}).get(re.sub(r"[^A-Za-z0-9_-]", "", cid or "")[:40])
    return [t.get("memo", "") for t in (c or {}).get("turns", [])]


def conversations() -> list[dict]:
    return sorted(_json("conversations.json", {}).values(), key=lambda c: c.get("updated", 0), reverse=True)


def remember_customer(cust: dict | None, order_id: str):
    """The buyer's details from an order, merged by email. Marketing consent stays unknown until they answer."""
    if not cust or not cust.get("email"):
        return
    key = cust["email"].lower()
    with _lock:
        all_ = _json("customers.json", {})
        c = all_.setdefault(key, {"email": cust["email"], "first_seen": time.time(), "orders": [], "marketing": None})
        c.update({k: cust.get(k) for k in ("full_name", "phone", "address_line_1", "address_line_2", "city", "state",
                                             "postal_code")})
        c["last_seen"] = time.time()
        if order_id not in c["orders"]:
            c["orders"].append(order_id)
        _save_json("customers.json", all_)


def set_marketing(email: str, agrees: bool, said: str) -> dict:
    """Only after the person answered in their own words; their answer is kept as the record of consent."""
    key = (email or "").strip().lower()
    with _lock:
        all_ = _json("customers.json", {})
        if key not in all_:
            raise ValueError("No customer with that email yet; this is asked after an order.")
        all_[key].update({"marketing": bool(agrees), "consent_at": time.time(), "consent_said": said[:300]})
        _save_json("customers.json", all_)
        return all_[key]


def customers() -> list[dict]:
    return sorted(_json("customers.json", {}).values(), key=lambda c: c.get("last_seen", 0), reverse=True)


# ---- Lena teaches her shop's AI from a chat (Roma 14551) ----

def coaching() -> list[dict]:
    return _json("coaching.json", [])


def add_coaching(chat_id: str, note: str, sample: bool = False, visitor: str = "") -> dict:
    """A short lesson Lena writes after reading a chat; every new chat's AI reads the active ones."""
    note = re.sub(r"https?://\S+", "", note or "").strip()
    if len(note) < 5:
        raise ValueError("Write what the AI should do next time.")
    with _lock:
        all_ = coaching()
        n = {"id": "L-" + uuid.uuid4().hex[:6].upper(), "at": time.time(), "chat": (chat_id or "")[:40],
             "note": note[:400], "active": True, "sample": sample, "visitor": visitor or ""}
        all_.append(n)
        glob = [x for x in all_ if not x.get("visitor")]
        _save_json("coaching.json", glob[-40:] + [x for x in all_ if x.get("visitor")][-400:])
        return n


def set_coaching(lid: str, active: bool, visitor: str = "", admin: bool = False) -> bool:
    with _lock:
        all_ = coaching()
        for n in all_:
            if n["id"] == lid and (admin or (visitor and n.get("visitor") == visitor)):
                n["active"] = bool(active)
                _save_json("coaching.json", all_)
                return True
        return False


def lessons_for(visitor: str = "", admin: bool = False) -> list[dict]:
    """Lena's own lessons apply to everyone. On the public demo, a lesson written by a visitor applies to that
    visitor's chats only, so nobody can change the shop's agent for other people."""
    return [n for n in coaching() if admin or not n.get("visitor") or n.get("visitor") == visitor]


def active_lessons(limit: int = 12, visitor: str = "") -> list[str]:
    return [n["note"] for n in lessons_for(visitor) if n.get("active")][-limit:]


# ZIP code prefixes (first three digits) by state, from USPS ranges, so a ZIP can't sit in the wrong state.
_ZIP3 = {
    "AL": [(350, 369)], "AK": [(995, 999)], "AZ": [(850, 865)], "AR": [(716, 729)], "CA": [(900, 961)],
    "CO": [(800, 816)], "CT": [(60, 69)], "DE": [(197, 199)], "DC": [(200, 205), (569, 569)], "FL": [(320, 349)],
    "GA": [(300, 319), (398, 399)], "HI": [(967, 968)], "ID": [(832, 838)], "IL": [(600, 629)], "IN": [(460, 479)],
    "IA": [(500, 528)], "KS": [(660, 679)], "KY": [(400, 427)], "LA": [(700, 714)], "ME": [(39, 49)],
    "MD": [(206, 219)], "MA": [(10, 27), (55, 55)], "MI": [(480, 499)], "MN": [(550, 567)], "MS": [(386, 397)],
    "MO": [(630, 658)], "MT": [(590, 599)], "NE": [(680, 693)], "NV": [(889, 898)], "NH": [(30, 38)],
    "NJ": [(70, 89)], "NM": [(870, 884)], "NY": [(5, 5), (63, 63), (100, 149)], "NC": [(270, 289)],
    "ND": [(580, 588)], "OH": [(430, 459)], "OK": [(730, 749)], "OR": [(970, 979)], "PA": [(150, 196)],
    "RI": [(28, 29)], "SC": [(290, 299)], "SD": [(570, 577)], "TN": [(370, 385)], "TX": [(750, 799), (885, 885)],
    "UT": [(840, 847)], "VT": [(50, 59)], "VA": [(201, 201), (220, 246)], "WA": [(980, 994)], "WV": [(247, 268)],
    "WI": [(530, 549)], "WY": [(820, 831)],
}


def zip_state(zip5: str) -> str | None:
    if not re.fullmatch(r"\d{5}", zip5 or ""):
        return None
    z = int(zip5[:3])
    return next((st for st, rs in _ZIP3.items() for a, b in rs if a <= z <= b), None)
