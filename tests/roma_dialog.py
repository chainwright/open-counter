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
    "How many of the yellow ones do you have?",
    "How I can ask Lena? Give me her phone number",
    "415-555-0134, I want to ask about a custom paint",
    "I'd like a custom one: the yellow rear-engine coupe, 25 of them",
    "1973, interior black",
    "To California. Yes, go ahead.",
    "Sam Rivera, 415-555-0134",
    "Yes",
]

history = []
for t in TURNS:
    history.append({"role": "user", "content": t})
    t0 = __import__("time").time(); r = shopper.run(history); dt = __import__("time").time() - t0
    print(f"\nUSER: {t}   [{dt:.1f}s]")
    for s in r["steps"]:
        print(f"   · {s['label']} · {s['result']}")
    print(f"AGENT: {r['reply']}")
    history.append({"role": "assistant", "content": r["reply"], "memo": r["memo"]})
print(f"\ncallbacks: {[(q['id'], q['contact']['phone']) for q in shop.requests_()]}")
print(f"orders: {[(o['id'], o.get('kind'), o['qty'], o['total_usd']) for o in shop.orders()]}")
