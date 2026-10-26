# Open Counter

**A one-person maker's shop that any AI shopping agent can buy from. Paid through PayPal, approved by a human.**

Lena builds 1:43 replica cars in her spare room,  each. People now ask their AI assistant for gifts, and those
assistants never find her. PayPal's agentic-commerce program exists, but it is invite-only and built for platform stores.
Open Counter makes her shop *legible* to any agent (a page, a JSON card and an MCP server), *payable* through PayPal
Orders v2, and still *hers*: nothing is charged until a person approves in PayPal, and her rules hold in code.

Built for the PayPal AI Hackathon 2026 by Elite Product LLC.

## Try it in two minutes
- Live demo: _(Render URL)_
- Chat with the built-in shopper's AI in section 01, or point your own agent at the MCP endpoint (section 04).
- When it gives you a PayPal link, log in with the **sandbox** test buyer:
  - email: `sb-yi0xc53507798@personal.example.com`
  - password: `2dt_AD6W`
  - This is PayPal's test environment. No real money moves.
- Watch Lena's side at `/maker`: the order appears, then "SOLD TO AN AI AGENT" when you pay.

## What uses PayPal, and where
| PayPal API | What for | Code |
|---|---|---|
| OAuth 2.0 client credentials | server-side token, cached and refreshed on 401 | `opencounter/paypal.py` |
| Orders v2: create (CAPTURE, with item and shipping breakdown) | the agent's checkout, amounts recomputed from the listing | `paypal.create_order` |
| Orders v2: buyer approval link (payer-action) | the human's yes | `paypal.approve_link` |
| Orders v2: capture | after approval; stock re-checked at this moment | `web.paypal_return` |
| Orders v2: shipment tracking | Lena adds a USPS number, the buyer is notified | `paypal.add_tracking` |
| Payments v2: refund | automatic full refund if the last one sold during approval | `paypal.refund` |
| Webhooks: signature verification | refund events | `web.webhook` |
| `PayPal-Request-Id` idempotency | a retried create, capture or refund never doubles money | `paypal._call` |

## What uses AI, and where
- **The shopper's AI** (`opencounter/shopper.py`): NVIDIA Nemotron 3 Super on Nebius Token Factory, with native tool
  calls to the same six tools any MCP agent gets. Daily spend cap; car-maker names are filtered out of replies.
- **What the model is not trusted with:** prices, totals, stock, delivery dates and deadline verdicts are computed in
  code (`opencounter/shop.py`). "You asked for" is the person's own words, not the model's paraphrase.

## For agents
- MCP (streamable HTTP): `/mcp/`: `about_counter`, `search_counter`, `item_details`, `delivery_estimate`,
  `start_checkout`, `order_status`.
- JSON card: `/c/small-garage.json`; discovery: `/.well-known/open-counter.json`.

## Run locally
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
export PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=...   # sandbox app
export NEBIUS_API_KEY=...                              # for the built-in shopper
export OPENCOUNTER_PUBLIC_URL=http://127.0.0.1:8800
.venv/bin/uvicorn opencounter.web:app --port 8800
.venv/bin/python -m pytest -q tests
```

## Tools used while building
Claude Code (code and tests), with PayPal's developer docs. Product photos of the replica models are AI-generated
(Higgsfield: FLUX.2, Flux Kontext, an upscaler); the shop and Lena are fictional. No car brands or logos are used.

## License
MIT. See LICENSE.
