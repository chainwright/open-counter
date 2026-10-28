"""Replays Roma's real conversation from 27.10 against the live model (needs NEBIUS_API_KEY), turn by turn,
the way the browser does it (the reply plus a note of what the tools returned). Prints every turn so a person
can read it. Not part of pytest: it calls a paid model.

    .venv/bin/python tests/roma_dialog.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from opencounter import shop, shopper

shop.DATA = __import__("pathlib").Path(tempfile.mkdtemp())
shop.seed(force=True)

TURNS = [
    "Hi, I like Porsche",
    "But I see you have small car similar with Porsche",
    "When will this car be available?",
    "How I can ask Lena? Give me her phone number",
    "I would like to buy 50 blue cars, do you have?",
    "If I make an order for 50 cars, when will it be ready?",
    "OK then 25: 15 of the yellow ones, number 73, 5 of the same in light blue, and 5 in red. To California.",
    "Yes, go ahead.",
    "Sam Rivera, sam.rivera@example.com, 415-555-0134, 1200 Market St, San Francisco, CA 94102",
    "Yes, send it.",
]

history = []
for t in TURNS:
    history.append({"role": "user", "content": t})
    r = shopper.run(history)
    print(f"\nUSER: {t}")
    for s in r["steps"]:
        print(f"   · {s['label']} · {s['result']}")
    print(f"AGENT: {r['reply']}")
    history.append({"role": "assistant", "content": r["reply"], "memo": r["memo"]})
print(f"\nrequests stored: {[(q['id'], q['quote']['total_cars'], q['quote']['total_usd']) for q in shop.requests_()]}")
print(f"orders created: {len(shop.orders())}")
