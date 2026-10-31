"""Sample history for the public demo (Roma 14540): two weeks of chats and orders so Lena's back office isn't empty.

Everything here is marked "sample": True and shown with a SAMPLE tag; live chats and orders are added on top.
The free host wipes its disk on every deploy, so this is re-created on start whenever the data folder is empty.
Totals over the 14 days: green 4, blue 3, orange 5, yellow 10, red 9 cars from stock, plus 12 made-to-order builds;
about 40 chats, 5 of them today. Names, emails and phones are invented (example.com, 555 numbers).
"""
from __future__ import annotations

import json
import random
import re
import time

from . import shop

PEOPLE = [
    ("Alex Scala", "Austin", "TX", "78701"), ("Maya Chen", "Seattle", "WA", "98101"), ("Jordan Reyes", "Denver", "CO", "80202"),
    ("Priya Nair", "Chicago", "IL", "60601"), ("Sam Okafor", "Atlanta", "GA", "30303"), ("Emma Larsen", "Portland", "OR", "97205"),
    ("Luis Ortega", "Phoenix", "AZ", "85004"), ("Grace Kim", "Boston", "MA", "02108"), ("Noah Fischer", "Columbus", "OH", "43215"),
    ("Olivia Brooks", "Nashville", "TN", "37203"), ("Ethan Walsh", "Miami", "FL", "33130"), ("Hannah Cole", "Minneapolis", "MN", "55401"),
    ("Mateo Silva", "San Diego", "CA", "92101"), ("Chloe Martin", "Raleigh", "NC", "27601"), ("Ben Adler", "Pittsburgh", "PA", "15222"),
    ("Zoe Turner", "Salt Lake City", "UT", "84101"), ("Ryan Patel", "Dallas", "TX", "75201"), ("Lily Novak", "Madison", "WI", "53703"),
    ("Owen Grant", "Kansas City", "MO", "64105"), ("Ava Morales", "Albuquerque", "NM", "87102"),
]
STREETS = ["Main St", "Oak Ave", "Maple Dr", "Elm St", "Park Ave", "Lake Rd", "Cedar Ln", "Pine St", "River Rd", "Hill St"]
TITLE = {"sg-014": "green fastback", "sg-015": "blue fastback", "sg-011": "orange muscle coupe",
         "sg-009": "yellow rear-engine coupe", "sg-012": "red convertible"}
# cars from stock over 14 days, one order per entry (lid, qty)
STOCK_ORDERS = ([("sg-014", 1), ("sg-014", 1), ("sg-014", 2)] + [("sg-015", 1), ("sg-015", 2)]
                + [("sg-011", 2), ("sg-011", 1), ("sg-011", 2)]
                + [("sg-009", 3), ("sg-009", 1), ("sg-009", 2), ("sg-009", 1), ("sg-009", 3)]
                + [("sg-012", 2), ("sg-012", 1), ("sg-012", 3), ("sg-012", 1), ("sg-012", 2)])
CUSTOM = [  # made-to-order builds, 12 in total
    ("the green fastback", "1968", "grey", "black", 2, "with two black stripes, like the movie car"),
    ("the red convertible", "1965", "white", "red", 3, ""), ("the yellow rear-engine coupe", "1973", "silver", "brown", 2, ""),
    ("the orange muscle coupe", "1970", "plum purple", "black", 1, ""), ("the blue fastback", "1967", "black", "tan", 4, ""),
]
QUESTIONS = [  # chats that didn't end in an order
    ("What scale are your cars?", "They're all 1:43, about 10–11 cm long. Each one is hand-built by Lena."),
    ("Do you ship to Canada?", "I couldn't finish that in a few steps. Could you tell me a bit more?"),
    ("Can I get it gift-wrapped?", "Lena packs every car in two layers with a handwritten note. There's no separate gift wrap yet."),
    ("How long does a custom one take?", "1–2 cars take about a week, 10 about two weeks, 20 about three. Want a quote?"),
    ("Do you have a black one?", "Not in stock, but Lena can build any listed car in black to order: $89 per car. Which body style?"),
    ("Is the red one a real metal model?", "It's a resin body with photo-etched brass trim and turned wheels, painted by hand."),
    ("Can I call Lena?", "She doesn't give out a number, but if you leave yours she'll call you back."),
    ("Do you take returns?", "I'm not sure about returns; Lena would need to answer that. Want me to pass your number to her?"),
    ("price for 50 cars?", "For 50 made-to-order cars it's $89 each with 15% off, free shipping. Which car and colours?"),
    ("hi", "Hi! Are you looking for a gift, or something for your own shelf?"),
    ("Can I pay with a credit card?", "I'm not sure, maybe? You could try."),
    ("Do you ship to Hawaii?", "Sorry, we only ship to the US."),
]


def build(now: float | None = None):
    rnd = random.Random(1028)
    now = now or time.time()
    day0 = now - 13 * 86400
    with shop._lock:
        orders, convs, custs = [], {}, {}
        n = 0

        def when(d: int) -> float:   # evenings are busiest, some lunch-time chats
            hour = rnd.choice([9, 11, 12, 12, 13, 17, 18, 19, 19, 20, 20, 21, 21, 22])
            t = shop.local(day0 + d * 86400).replace(hour=hour, minute=rnd.randint(0, 59), second=0, microsecond=0).timestamp()
            return t if t < now - 600 else now - rnd.randint(15, 300) * 60   # never in the future

        def person(i: int) -> dict:
            name, city, st, zip_ = PEOPLE[i % len(PEOPLE)]
            first = name.split()[0].lower()
            return {"full_name": name, "phone": f"{rnd.choice(['312', '415', '512', '617', '303'])}-555-01{i % 100:02d}",
                    "email": f"{first}.{name.split()[1].lower()}@example.com",
                    "address_line_1": f"{rnd.randint(10, 2400)} {rnd.choice(STREETS)}", "address_line_2": "",
                    "city": city, "state": st, "postal_code": zip_}

        def chat(t: float, turns: list[tuple[str, str, list[str]]], name: str = "", order_id: str | None = None):
            nonlocal n
            n += 1
            cid = f"sample-{n:03d}"
            convs[cid] = {"id": cid, "no": n, "started": t, "updated": t + 60 * len(turns), "channel": "demo-shopper",
                          "name": name, "orders": [order_id] if order_id else [], "sample": True,
                          "turns": [{"at": t + 50 * k, "user": u, "reply": r, "steps": s} for k, (u, r, s) in enumerate(turns)]}

        def order(o: dict, cust: dict | None, t: float, status: str):
            o.update({"created": t, "status": status, "sample": True, "customer": cust,
                      "events": [["created", t]] + ([["paid", t + 900]] if status in ("paid", "shipped") else [])})
            if status in ("paid", "shipped"):
                o["paid_at"] = t + 900
            if status == "shipped":
                o["tracking"] = {"number": f"9400 1000 0000 {rnd.randint(1000, 9999)} {rnd.randint(1000, 9999)} 00", "carrier": "USPS"}
            orders.append(o)
            if cust:
                c = custs.setdefault(cust["email"], {"email": cust["email"], "first_seen": t, "orders": [], "marketing": None})
                c.update({k: cust[k] for k in ("full_name", "phone", "address_line_1", "address_line_2", "city", "state", "postal_code")})
                c["last_seen"] = max(c.get("last_seen", 0), t)
                c["orders"].append(o["id"])
                if rnd.random() < 0.55:
                    c.update({"marketing": True, "consent_at": t + 120, "consent_said": rnd.choice(["yes", "yes please", "sure", "ok"])})
                elif rnd.random() < 0.3:
                    c.update({"marketing": False, "consent_at": t + 120, "consent_said": "no thanks"})

        rules = shop.shop()["rules"]
        listings = {l["id"]: l for l in shop.shop()["listings"]}
        # days for the 40 chats: 5 today, the rest spread over the 13 days before
        days = sorted([13] * 5 + [rnd.randint(0, 12) for _ in range(35)])
        stock = list(STOCK_ORDERS)
        rnd.shuffle(stock)
        kinds = ["stock"] * len(stock) + ["custom"] * len(CUSTOM) + ["question"] * (40 - len(stock) - len(CUSTOM))
        rnd.shuffle(kinds)
        si = ci = qi = 0
        for i, (d, kind) in enumerate(zip(days, kinds)):
            t = when(d)
            status = "awaiting_approval" if d == 13 and rnd.random() < 0.5 else rnd.choice(["paid", "paid", "shipped", "shipped"])
            if kind == "stock":
                lid, q = stock[si]; si += 1
                cust = person(i)
                item = listings[lid]
                est = shop.delivery_estimate(cust["state"])
                total = round(item["price_usd"] * q + rules["shipping_usd"], 2)
                oid = f"OC-S{i:03d}{lid[-2:]}"
                order({"id": oid, "listing_id": lid, "title": item["title"], "qty": q,
                       "lines": [{"listing_id": lid, "title": item["title"], "qty": q, "unit_usd": item["price_usd"]}],
                       "unit_usd": item["price_usd"], "shipping_usd": rules["shipping_usd"], "total_usd": total,
                       "ship_state": cust["state"], "estimate": est, "channel": "demo-shopper",
                       "ship_to": {"name": cust["full_name"], "city": cust["city"], "state": cust["state"]},
                       "asked_for": f"{q} {TITLE[lid]}{'s' if q > 1 else ''} to {cust['city']}"}, cust, t, status)
                chat(t, [(f"{q} {TITLE[lid]}{'s' if q > 1 else ''} to {cust['city']} please",
                          f"{q} × {item['title']} comes to ${total:.2f} with shipping. It ships "
                          f"{est['ships_on'].split(' ')[0]}. What name, phone, email and street address should Lena ship to?",
                          ["searching the counter · 1 found", f"checking delivery · ships {est['ships_on'][:3]}"]),
                         (f"{cust['full_name']}, {cust['phone']}, {cust['email']}, {cust['address_line_1']}, {cust['city']} "
                          f"{cust['state']} {cust['postal_code']}",
                          "Your order is ready, the PayPal button is below.\n\nOne more thing: would you like Lena to email "
                          "you when new models or offers come out? (yes / no)",
                          ["preparing PayPal checkout · waiting for your approval in PayPal"])],
                     name=cust["full_name"], order_id=oid)
            elif kind == "custom":
                car, year, body, inside, q, extra = CUSTOM[ci]; ci += 1
                cust = person(i + 7)
                quote = shop.commission_quote([{"model": car, "year": year, "body_colour": body, "interior_colour": inside,
                                                 "quantity": q}], cust["state"])
                oid = f"OC-M{i:03d}"
                order({"id": oid, "kind": "commission", "listing_id": "", "title": shop.commission_title(quote),
                       "qty": q, "unit_usd": quote["unit_usd"], "discount_usd": quote["discount_usd"],
                       "shipping_usd": quote["shipping_usd"], "total_usd": quote["total_usd"], "quote": quote,
                       "contact": {"name": cust["full_name"], "phone": cust["phone"]}, "ship_state": cust["state"],
                       "estimate": {"ok": True, **{k: quote["delivery"][k] for k in ("ships_on", "arrives_earliest", "arrives_latest", "carrier")}},
                       "channel": "demo-shopper", "asked_for": f"custom {car}, {body}/{inside}, {q}"}, cust, t, status)
                chat(t, [(f"Can Lena make {car} in {body} {extra}".strip() + "?",
                          f"Yes, to order. What interior colour, and how many?", []),
                         (f"{inside} inside, {q} of them", f"{q} × {car}, {body} with {inside} interior: ${quote['total_usd']:.2f}, "
                          f"built in about {quote['build_weeks']} week(s). What name, phone, email and address should it go to?",
                          [f"pricing a made-to-order build · {q} cars · ${quote['total_usd']:,.2f}"]),
                         (f"{cust['full_name']}, {cust['phone']}, {cust['email']}, {cust['address_line_1']}, {cust['city']} "
                          f"{cust['state']} {cust['postal_code']}", "Done, the PayPal button is below. Lena starts building once it's paid.",
                          ["preparing PayPal checkout · waiting for your approval in PayPal"])],
                     name=cust["full_name"], order_id=oid)
            else:
                qn, ans = QUESTIONS[qi % len(QUESTIONS)]; qi += 1
                steps = (["checking delivery · Lena ships inside the US only; 'ON' is not a US state code."]
                         if "Canada" in qn else [])
                chat(t, [(qn, ans, steps)])
        canada = next((k for k, c in convs.items() if "Canada" in c["turns"][0]["user"]), "")
        returns = next((k for k, c in convs.items() if "returns" in c["turns"][0]["user"]), "")
        lessons = [{"id": "L-S1", "at": now - 3 * 86400, "chat": canada, "active": True, "sample": True,
                    "note": "If someone asks about shipping outside the US, say Lena ships inside the US only for now, "
                            "and offer to take their email so she can tell them when that changes."},
                   {"id": "L-S2", "at": now - 86400, "chat": returns, "active": True, "sample": True,
                    "note": "If someone asks something you can't answer from the shop's facts (returns, custom "
                            "packaging), say Lena will answer it personally and offer to take their phone for a call back."}]
        shop._save_json("coaching.json", lessons)
        # three counters other makers opened at /open (sample), so the page shows what it makes
        import shutil
        cdir = shop._path("counters"); cdir.mkdir(exist_ok=True)
        counters = {}
        for k, (slug, name, maker, st, title, desc, mats, price, stock, photo) in enumerate([
                ("clay-kiln-s1", "Clay & Kiln", "Rosa Diaz", "TX", "Handmade Stoneware Mug",
                 "A wheel-thrown stoneware mug with a speckled sea-green glaze. Holds 12 oz.", ["stoneware", "glaze"], 32, 6, "mug.jpg"),
                ("slow-flame-s2", "Slow Flame", "Ben Okoro", "OR", "Hand-Poured Soy Candle",
                 "Soy wax poured by hand into an amber glass jar, with a cotton wick. About 50 hours of burn.", ["soy wax", "glass"], 24, 20, "candle.jpg"),
                ("saddle-thread-s3", "Saddle & Thread", "Ana Petrov", "OH", "Hand-Stitched Leather Wallet",
                 "A brown full-grain leather bifold, saddle-stitched by hand.", ["leather", "waxed thread"], 68, 4, "wallet.jpg")]):
            src = shop.ROOT / "web" / "static" / "open" / photo
            if src.exists():
                shutil.copy(src, cdir / f"{slug}.jpg")
            counters[slug] = {"slug": slug, "created": now - (k + 1) * 3 * 86400, "sample": True, "visitor": "", "maker": maker,
                              "name": name, "ships_from": st,
                              "listing": {"id": slug + "-1", "title": title, "short_description": desc, "materials": mats,
                                          "made_by_hand": True, "price_usd": float(price), "stock": stock,
                                          "keywords": [], "paypal_catalog_product": None}}
        shop._save_json("counters.json", counters)
        shop._save_orders(orders)
        shop._save_json("conversations.json", convs)
        shop._save_json("customers.json", custs)
        return len(orders), len(convs)


DATA_VERSION = "7"   # bump to wipe ALL demo data (also real sandbox orders) and lay the sample history down again

# QA and judge runs on the public demo use visitor ids and chat ids starting with "qa" (qa-e0147409, qa5-canada-7409);
# a real browser's ids are random hex ("anon-…", 24 hex digits) and never do. Orders from the judge rounds that were
# placed before the convention are listed by id. They're removed on every start (purge_test_data); real orders,
# chats and customers stay, and the sample history is never touched.
TEST_ID = re.compile(r"^(qa|test|judge)", re.I)
KNOWN_TEST_ORDERS = {"OC-24754B6E",                                                       # judge round 5
                     "OC-D3BC6995", "OC-F64CAFF8", "OC-C4CAB985", "OC-80212819", "OC-FA099F18",   # round 4
                     "OC-A4F2CD96", "OC-C88BA7F6", "OC-831EE13B", "OC-FF085841"}               # round 1


def purge_test_data() -> dict:
    """Take test traffic out of Lena's back office: test chats, the orders they made, those buyers, lessons and
    counters test browsers wrote, and call-backs left from test chats. Returns what was removed, by kind."""
    gone: dict[str, list[str]] = {}
    with shop._lock:
        convs = shop._json("conversations.json", {})
        test_chats = {k for k, c in convs.items()
                      if not c.get("sample") and (TEST_ID.match(k) or TEST_ID.match(c.get("visitor") or ""))}
        test_orders = set(KNOWN_TEST_ORDERS) | {oid for k in test_chats for oid in convs[k].get("orders", [])}
        orders = shop.orders()
        test_orders |= {o["id"] for o in orders if TEST_ID.match(o.get("visitor") or "")}
        test_orders -= {o["id"] for o in orders if o.get("sample")}
        # call-backs carry the chat's own words; only a distinctive opening (not "hi") is used to find them
        said = [t["user"][:60] for k in test_chats for t in convs[k].get("turns", [])[:1] if len(t.get("user", "")) >= 12]
        if test_chats:
            gone["chats"] = sorted(test_chats)
            shop._save_json("conversations.json", {k: c for k, c in convs.items() if k not in test_chats})
        if any(o["id"] in test_orders for o in orders):
            gone["orders"] = sorted(o["id"] for o in orders if o["id"] in test_orders)
            shop._save_orders([o for o in orders if o["id"] not in test_orders])
        custs = shop._json("customers.json", {})
        changed = False
        for key, c in list(custs.items()):
            mine = [x for x in c.get("orders", []) if x in test_orders]
            if mine:
                c["orders"] = [x for x in c["orders"] if x not in test_orders]
                changed = True
                if not c["orders"]:   # this buyer exists only because of test orders
                    gone.setdefault("customers", []).append(key)
                    del custs[key]
        if changed:
            shop._save_json("customers.json", custs)
        lessons = shop.coaching()
        keep = [n for n in lessons if n.get("sample") or not (TEST_ID.match(n.get("visitor") or "") or n.get("chat") in test_chats)]
        if len(keep) != len(lessons):
            gone["lessons"] = [n["id"] for n in lessons if n not in keep]
            shop._save_json("coaching.json", keep)
        counters = shop._json("counters.json", {})
        test_counters = [k for k, c in counters.items() if not c.get("sample") and TEST_ID.match(c.get("visitor") or "")]
        if test_counters:
            gone["counters"] = test_counters
            for k in test_counters:
                del counters[k]
                (shop._path("counters") / f"{k}.jpg").unlink(missing_ok=True)
            shop._save_json("counters.json", counters)
        reqs = shop.requests_()
        keep_r = [r for r in reqs if not any(s and s in (r.get("asked_for") or "") for s in said)]
        if len(keep_r) != len(reqs):
            gone["requests"] = [r["id"] for r in reqs if r not in keep_r]
            shop._requests_path().write_text(json.dumps(keep_r, indent=2, ensure_ascii=False))
    return gone


def ensure():
    """On an empty data folder, or when DATA_VERSION changes, lay down the sample history; on every start, take
    test traffic out (real records stay)."""
    if not shop.DEMO:
        return
    vf = shop._path("data_version")
    if not (vf.exists() and vf.read_text().strip() == DATA_VERSION):
        import shutil
        for f in ("orders.json", "conversations.json", "customers.json", "coaching.json", "counters.json", "requests.json"):
            p = shop._path(f)
            if p.exists():
                p.unlink()
        shutil.rmtree(shop._path("counters"), ignore_errors=True)
        shop.seed(force=True)
        build()
        vf.write_text(DATA_VERSION)
    purge_test_data()
