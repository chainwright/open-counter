"""The public MCP endpoint: any agent (Claude Desktop, an Agents SDK app, …) can shop Lena's counter here.
Read-only tools plus start_checkout, which can only create an order a human must approve in PayPal."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from . import counter


# Typed arguments, so tools/list gives an outside agent every field name and which ones are required (final judge
# 08.11 P1-4: they were bare objects and an agent had to guess full_name / postal_code). The rules themselves stay in
# counter/shop, which also check every value again.
class Customer(BaseModel):
    """Who the order ships to, exactly as the person typed it."""
    full_name: str = Field(description="First and last name.")
    phone: str = Field(description="Phone number, as typed.")
    email: str = Field(description="Email for the PayPal receipt or invoice and tracking.")
    address_line_1: str = Field(description="Street address with the house number.")
    address_line_2: str | None = Field(None, description="Apartment, suite (optional).")
    city: str
    state: str = Field(description="Two-letter US state code, e.g. TX. Must match the ZIP.")
    postal_code: str = Field(description="5-digit US ZIP code.")


class Item(BaseModel):
    """One shelf car in a multi-car order."""
    item_id: str = Field(description="A listing id from search_counter, e.g. sg-014.")
    quantity: int = Field(ge=1, description="How many, a whole number of at least 1 (up to the stock).")


class Car(BaseModel):
    """One made-to-order build."""
    model: str = Field(description="Body style or a listing it's based on: fastback, coupe, convertible…")
    year: str = Field(description="The year of the real car it's modelled on, as the person said it (e.g. 1967).")
    body_colour: str
    interior_colour: str
    quantity: int = Field(ge=1, description="How many of this build, a whole number of at least 1.")
    details: str | None = Field(None, description="Anything extra: stripes, wheels, a plate (optional).")


def _d(x):
    """A typed argument as the plain dict the counter takes (tests may pass dicts directly)."""
    if isinstance(x, list):
        return [_d(v) for v in x]
    return x.model_dump(exclude_none=True) if isinstance(x, BaseModel) else x

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


@mcp.tool(description=("Create an order awaiting the person's approval and get a PayPal approval link. One car: "
                       "item_id + quantity (a whole number ≥ 1). Several different cars: items = [{item_id, quantity}] "
                       "(then item_id/quantity are ignored). customer (optional) = {full_name, phone, email, "
                       "address_line_1, address_line_2?, city, state, postal_code}; without it PayPal uses the address "
                       "on the buyer's PayPal account. Pass the person's request in their own words as "
                       "what_the_shopper_asked."))
def start_checkout(us_state: str, what_the_shopper_asked: str, item_id: str = "", quantity: int = 1,
                   items: list[Item] | None = None, customer: Customer | None = None) -> dict:
    return counter.start_checkout(item_id, quantity, us_state, what_the_shopper_asked, channel="mcp", items=_d(items),
                                  customer=_d(customer))


@mcp.tool(description=("Exact price, volume discount, shipping, build time and delivery for made-to-order cars. "
                       "cars = [{model, year (of the real car), body_colour, interior_colour, quantity (whole number "
                       "≥ 1), details?}]."))
def quote_commission(cars: list[Car], us_state: str = "") -> dict:
    return counter.quote_commission(_d(cars), us_state)


@mcp.tool(description=("Create the made-to-order order after the person agreed to the quote. cars as in "
                       "quote_commission. With customer = {full_name, phone, email, address_line_1, address_line_2?, "
                       "city, state, postal_code} it becomes a PayPal invoice sent to their email: 50% deposit now, the "
                       "balance before shipping. Without it, a one-time PayPal approval link for the full amount."))
def start_commission_checkout(cars: list[Car], us_state: str, name: str, phone: str,
                              what_the_shopper_asked: str, customer: Customer | None = None) -> dict:
    return counter.start_commission_checkout(_d(cars), us_state, name, phone, what_the_shopper_asked, channel="mcp",
                                             customer=_d(customer))


@mcp.tool(description="Pass the person's phone number and question to the maker; she calls them back.")
def leave_contact(phone: str, name: str = "", message: str = "", what_the_shopper_asked: str = "") -> dict:
    return counter.leave_contact(phone, name, message, what_the_shopper_asked, channel="mcp")


@mcp.tool(description="Status of an order: awaiting_approval, paid, shipped (with tracking), cancelled.")
def order_status(order_id: str) -> dict:
    return counter.order_status(order_id)
