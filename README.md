# Open Counter

**A one-person maker's shop that any AI shopping agent can buy from. Paid through PayPal, approved by a human, and
run by a sales agent the maker teaches herself.**

People increasingly ask an AI assistant for a gift, and those assistants buy from big stores. PayPal's agentic
checkout exists, but it is request-access and built for platform stores. A maker who sells a few things a week is not
on that path. Open Counter is the other half: it makes a small shop *readable* to every agent (a page, a JSON card and
an MCP server), *payable* through PayPal, and still *hers*: nothing is charged until a person approves in PayPal, her
rules hold in code, and she can see and correct what her agent says.

The demo maker is Lena, who builds 1:43 replica cars by hand ($59 each). Any other maker can open a counter at `/open`.

Built for the PayPal AI Hackathon 2026 by Elite Product LLC.

## Why it matters
- Traffic from AI assistants to US retail sites grew **693%** in the 2025 holidays vs 2024 ([Adobe Analytics](https://news.adobe.com/news/2026/01/adobe-holiday-shopping-season)).
- About **70%** of Americans could imagine using AI tools to pick Christmas gifts ([Statista, 2025](https://www.statista.com/chart/35529/ai-tools-adoption-and-applications-for-holiday-shopping)).
- Etsy alone had **5.6 million** active sellers at the end of 2025 ([Inside Retail](https://insideretail.us/etsy-vows-sustained-growth-after-revenue-lift/)): makers like Lena.
- PayPal's agentic checkout (Store Sync, Agent Ready) is request-access and built around platform stores
  ([PayPal docs](https://developer.paypal.com/agentic-commerce-services/about)). Open Counter gives a one-person shop the
  same reach with what any PayPal account already has.

## Does it work? Measured, not claimed
`evals/run_evals.py` runs 30 scripted conversations against the live model (English and Russian, deadlines, discounts,
a changed cart, made to order, a wrong ZIP, brand names, an injected instruction, talking to Lena) on a fresh shop each,
with checks written in code. Latest results and every transcript: [`evals/RESULTS.md`](evals/RESULTS.md),
`evals/transcripts.json`.

The closed-tab case, run on the live sandbox on 28 Oct 2026: order `OC-C7DAD2E3` (PayPal order `9NC75431R2481360K`)
was approved by a person while the return page was told to stay out of it (a `webhook-only-test` visitor). PayPal's
`CHECKOUT.ORDER.APPROVED` webhook arrived, its signature was verified, and the webhook handler captured the payment
(capture `9Y869986895732623`, 20:18 UTC); the order showed as paid on Lena's side without the buyer's browser doing
anything. Same code path as the return page, so the two can never charge twice.

## Try it in two minutes
- **Shop:** https://open-counter.onrender.com · chat with the shop's sales agent in section 01, turn any car in 3D.
- **Lena's back office (open, no login):** https://open-counter.onrender.com/maker
- **Open your own counter:** https://open-counter.onrender.com/open
- When the agent gives you a PayPal button, log in with the **sandbox** test buyer:
  `sb-yi0xc53507798@personal.example.com` / `2dt_AD6W`. This is PayPal's test environment; no real money moves.
- The back office starts with two weeks of sample history (marked SAMPLE) so the charts aren't empty. Your own chat
  and order appear on top, live.

## What it does
**For the shopper (or their agent)**
- Ask in English or Russian (tested; other languages work as the model allows). The agent finds the car, checks stock and delivery, gives the total and dates, asks once for
  name, phone, email and address, and puts a receipt under its message: one line per car, quantity × price, shipping,
  total, and PayPal's own button: the buyer approves in PayPal's window without leaving the chat. Several different cars go into one PayPal order.
- Something not on the shelf? Describe it. The agent asks the year, body and interior colours and the quantity, and
  quotes the build time and volume discount from Lena's rules. It's paid with a **PayPal invoice: 50% deposit now,
  the balance before shipping.**
- Any outside agent gets the same nine tools through the MCP server, with the same rules.

**For the maker**
- **Back office** with one period filter (today … year) over every tab: orders, numbered chats by day with the
  buyer's name (or "Guest, no name"), insights (cars sold per model in the cars' own colours, best sellers, when
  shoppers come, how often a chat becomes an order, where the agent got stuck), customers, stock.
- **She teaches her agent.** Under any chat: "Teach the AI from this chat". Lena's lessons go into every new chat.
  On this public demo a visitor's lesson applies to that visitor's own chats only, so nobody can change the shop's
  agent for other people (Lena's key, `MAKER_KEY`, makes a lesson global).
- **Her assistant** reviews the latest chats, points at the answers that went wrong and writes the lesson for her to
  accept in one tap. It also answers "how much did I make this week?" from numbers computed in code.
- **Customers and consent:** buyers are asked once, after their first order, whether Lena may email them about new
  models. Only a yes in their own words puts them on the list.
- **Open your counter (`/open`):** one photo and one sentence. Shoppers can buy from a new counter at `/c/<slug>` the
  same way (PayPal approval by a person, stock taken at capture); in the demo the sandbox payment goes to the Open Counter
  test merchant, and a live counter connects the maker's own PayPal account. NVIDIA Nemotron VL writes the listing words; the maker
  sets price and stock; the product is registered in PayPal Catalog Products and gets its own agent-readable card.

## How it works
```mermaid
flowchart LR
  subgraph Shoppers
    H[Person in the shop chat] --> SA[Shop's sales agent<br/>NVIDIA Nemotron, tool calls]
    X[Any outside AI agent] --> MCP[MCP server<br/>9 tools]
  end
  SA --> C[Counter rules in code<br/>prices · stock · delivery · discounts · build time]
  MCP --> C
  C --> PP[(PayPal)]
  PP -->|Orders v2: create → buyer approves → capture| C
  PP -->|Invoicing v2: deposit + balance| C
  PP -->|Webhooks, signature-verified| W[Webhook handler]
  W --> C
  C --> D[(Orders · chats · customers · lessons<br/>JSON on a Render persistent disk)]
  D --> BO[Lena's back office]
  BO -->|lessons| SA
  AS[Lena's assistant<br/>reviews chats, answers from facts] --> BO
  BO -->|tracking number| PP
  M[Any maker at /open] -->|photo → Nemotron VL listing| CAT[PayPal Catalog Products]
```

## What uses PayPal, and where
| PayPal API | What for | Code |
|---|---|---|
| OAuth 2.0 client credentials | server-side token, cached and refreshed on 401 | `opencounter/paypal.py` |
| Orders v2: create (CAPTURE) | stock orders: one item per car, shipping, the buyer's address (`SET_PROVIDED_ADDRESS`) | `paypal.create_order` |
| Orders v2: approval link → capture | the human's yes; stock re-checked at capture | `web._settle` |
| Invoicing v2: create, send, partial payment, remind | made-to-order: 50% deposit now, balance before shipping | `paypal.create_deposit_invoice`, `remind_invoice` |
| Orders v2: shipment tracking | Lena adds a USPS number, PayPal tells the buyer | `paypal.add_tracking` |
| Payments v2: refund | automatic full refund if the last one sold during approval | `paypal.refund` |
| Catalog Products v1 | products of makers who open a counter at `/open` | `onboard.publish` |
| Webhooks + signature verification | `CHECKOUT.ORDER.APPROVED` (captured even if the buyer never returns), capture completed/denied/reversed/refunded, invoice paid/updated | `web.webhook` |
| `PayPal-Request-Id` | a retried create, capture, invoice or refund never doubles money | `paypal._call` |

## What uses AI, and where
- **Sales agent** (`opencounter/shopper.py`): NVIDIA Nemotron 3 Super on Nebius, native tool calls, answers in the
  shopper's language, daily spend cap. It reads Lena's lessons in every chat.
- **What the model is not trusted with:** prices, totals, discounts, stock, delivery dates and build times are computed
  in `opencounter/shop.py`. The code refuses an order unless the phone, email and ZIP were typed by the person; lines
  with contact details the person never typed are removed from replies; a promised link without a real order is caught.
- **Lena's assistant** (`opencounter/assistant.py`): reviews chats against the shop's facts and proposes lessons;
  answers questions from a facts object computed in code.
- **Listing writer** (`opencounter/onboard.py`): NVIDIA Nemotron VL turns a photo and a sentence into listing words.

## For agents
- MCP (streamable HTTP) at `/mcp/`: `about_counter`, `search_counter`, `item_details`, `delivery_estimate`,
  `start_checkout` (one or several cars), `quote_commission`, `start_commission_checkout`, `leave_contact`, `order_status`.
- JSON card: `/c/small-garage.json`; every counter: `/c/<slug>.json`; discovery: `/.well-known/open-counter.json`.
- One search across every counter on the host: `/api/directory?q=green&max_price=60` returns matching items from
  Lena's shop and every counter opened at `/open`, each with its card and its checkout.
- The card is a small open format: [JSON Schema](web/static/schema/open-counter-card.v1.json). Any shop can publish one
  at a well-known URL; any agent can read it the same way. The two new ideas, in one line each:
  1. **A shop card any AI agent can read and buy from**, with checkout that only a person can approve in PayPal.
  2. **A sales agent the maker supervises**: she reads its chats, her assistant flags the bad answers, and her
     lessons change its next answer.

## Run locally
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
export PAYPAL_CLIENT_ID=... PAYPAL_CLIENT_SECRET=...   # sandbox app
export NEBIUS_API_KEY=...                              # sales agent, assistant, listing writer
export OPENCOUNTER_PUBLIC_URL=http://127.0.0.1:8800
.venv/bin/uvicorn opencounter.web:app --port 8800
.venv/bin/python -m pytest -q tests
```
Optional: `PAYPAL_WEBHOOK_ID` (webhook verification), `OPENCOUNTER_DATA` (data folder; on Render it points at a
mounted persistent disk, `/var/data`, so data survives deploys), `MAKER_KEY` (Lena's key: global lessons, news-list export).

On the public demo every browser gets its own visitor id: lessons it writes, orders it can ship and counters it opens
stay with that browser. Sample history (marked SAMPLE) is read-only.

## Tools used while building
Claude Code wrote code and tests with us, using PayPal's developer docs. Product photos, the 3D models and the bench
clips are AI-generated (Higgsfield); the shop, Lena and the sample history are fictional. No car brands or logos.

## License
MIT. See LICENSE.
