"""The maker's shop: listings, stock, rules, orders. Plain JSON on disk; the demo shop is re-seeded on boot.

Everything an agent is told comes from here. If a fact is not in the listing or the rules, the answer is
"ask the maker", never a guess."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("OPENCOUNTER_DATA", ROOT / "data"))
SEED = ROOT / "demo" / "shop.json"
_lock = threading.RLock()

# The public demo is a fictional shop with 1-2 of each car, so one judge's purchase would empty it for everyone after.
# In demo mode a car that sold out comes back after a while ("Lena finished another one"); the sold-out state is
# still visible in between. Items seeded at 0 stay at 0: they show the commission path.
DEMO = os.environ.get("OPENCOUNTER_DEMO", "1") != "0"
RESTOCK_AFTER_S = float(os.environ.get("OPENCOUNTER_DEMO_RESTOCK_MIN", "10")) * 60
MAX_ORDERS = 300

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
           "note": "Estimate from the carrier's published ranges, not a guarantee."}
    nb = _need_by_date(need_by, today)
    if nb:  # decided in code, so the agent never does date arithmetic
        out["need_by"] = day(nb)
        out["need_by_verdict"] = ("on time" if late <= nb else "possible, not certain" if early <= nb
                                  else "too late")
    return out


# ---- orders ----
def orders() -> list[dict]:
    seed()
    return json.loads(_path("orders.json").read_text())


def _save_orders(o: list[dict]):
    _path("orders.json").write_text(json.dumps(o[-MAX_ORDERS:], indent=2, ensure_ascii=False))


def new_order(lid: str, qty: int, state: str, asked_for: str, channel: str) -> dict:
    """Checks the maker's rules before any money moves. Raises ValueError with a sentence an agent can relay."""
    s = shop()
    item = listing(lid)
    if not item:
        raise ValueError(f"No listing '{lid}' at {s['name']}.")
    if qty < 1 or qty > s["rules"]["max_per_order"]:
        raise ValueError(f"{s['maker']} sells at most {s['rules']['max_per_order']} per order.")
    if item["stock"] < qty:
        raise ValueError(f"Only {item['stock']} of '{item['title']}' in stock."
                         + (" It can be commissioned instead." if s["rules"]["commissions"] else ""))
    est = delivery_estimate(state)
    if not est["ok"]:
        raise ValueError(est["reason"])
    o = {"id": "OC-" + uuid.uuid4().hex[:8].upper(), "listing_id": lid, "title": item["title"], "qty": qty,
         "unit_usd": item["price_usd"], "shipping_usd": s["rules"]["shipping_usd"],
         "total_usd": round(item["price_usd"] * qty + s["rules"]["shipping_usd"], 2),
         "ship_state": state.upper(), "estimate": est, "asked_for": asked_for[:400], "channel": channel,
         "status": "awaiting_approval", "created": time.time(), "events": [["created", time.time()]]}
    with _lock:
        all_ = orders()
        all_.append(o)
        _save_orders(all_)
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
