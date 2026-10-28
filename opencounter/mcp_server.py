"""The public MCP endpoint: any agent (Claude Desktop, an Agents SDK app, …) can shop Lena's counter here.
Read-only tools plus start_checkout, which can only create an order a human must approve in PayPal."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import counter

mcp = MCPServer(
    name="small-garage-counter",
    title="Small Garage — Lena's counter",
    instructions=("You are shopping at Small Garage, a one-person maker of hand-built 1:43 replica cars. "
                  "Use only facts returned by these tools. Before checkout, show the person both the "
                  "'you_asked_for' and 'you_are_approving' lines, then give them approve_url. Never claim "
                  "an order is paid until order_status says 'paid'."),
)


@mcp.tool(description="Who the maker is, what she ships where, shipping cost, commissions and how payment works.")
def about_counter() -> dict:
    return counter.about_counter()


@mcp.tool(description="Search the maker's listings by words (colour, year, body style, occasion) and max price.")
def search_counter(query: str = "", max_price_usd: float | None = None) -> dict:
    return counter.search_counter(query, max_price_usd)


@mcp.tool(description="Full listing: scale, size in mm, materials, paint, build hours, stock, photo and page URL.")
def item_details(item_id: str) -> dict:
    return counter.item_details(item_id)


@mcp.tool(description=("Ship date and estimated delivery window to a US state (two-letter code). Pass need_by "
                       "(a date or a weekday like Friday) to get a verdict: on time, possible, or too late."))
def delivery_estimate(us_state: str, need_by: str = "") -> dict:
    return counter.delivery_estimate(us_state, need_by)


@mcp.tool(description=("Create an order awaiting the person's approval and get a PayPal approval link. Pass the "
                       "person's request in their own words as what_the_shopper_asked."))
def start_checkout(item_id: str, quantity: int, us_state: str, what_the_shopper_asked: str) -> dict:
    return counter.start_checkout(item_id, quantity, us_state, what_the_shopper_asked, channel="mcp")


@mcp.tool(description=("Exact price, volume discount, shipping, build time and delivery window for made-to-order "
                       "cars (more than the per-order limit, a sold-out car, or another colour). cars is a list of "
                       "{item_id or body, colour, quantity}."))
def quote_commission(cars: list[dict], us_state: str = "") -> dict:
    return counter.quote_commission(cars, us_state)


@mcp.tool(description=("Send the maker a made-to-order request after the person has seen the quote and agreed. "
                       "Needs their name, email, phone and full shipping address. Nothing is charged: the maker "
                       "confirms by email and sends a PayPal invoice."))
def request_commission(name: str, email: str, phone: str, address: str, us_state: str, cars: list[dict],
                       notes: str = "", what_the_shopper_asked: str = "") -> dict:
    return counter.request_commission(name, email, phone, address, us_state, cars, notes, what_the_shopper_asked,
                                      channel="mcp")


@mcp.tool(description="Status of an order: awaiting_approval, paid, shipped (with tracking), cancelled.")
def order_status(order_id: str) -> dict:
    return counter.order_status(order_id)
