"""PayPal REST, sandbox. Orders v2 (create → buyer approves → capture), shipment tracking, catalog products,
webhook signature check. Server-side only: the client id and secret never reach the browser or an agent."""
from __future__ import annotations

import os
import threading
import time
from decimal import Decimal

import httpx

BASE = os.environ.get("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
_token: dict = {"value": None, "exp": 0.0}
_lock = threading.Lock()


class PayPalError(Exception):
    def __init__(self, status: int, body: dict | str):
        self.status, self.body = status, body
        name = body.get("name") if isinstance(body, dict) else ""
        detail = ""
        if isinstance(body, dict) and body.get("details"):
            detail = body["details"][0].get("issue", "")
        super().__init__(f"PayPal {status} {name} {detail}".strip())


def configured() -> bool:
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))


def _access_token() -> str:
    """Client-credentials token, cached until a minute before it expires (sandbox tokens live 3–9 h)."""
    with _lock:
        if _token["value"] and time.time() < _token["exp"] - 60:
            return _token["value"]
        r = httpx.post(f"{BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                       auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]), timeout=20)
        if r.status_code != 200:
            raise PayPalError(r.status_code, _json(r))
        j = r.json()
        _token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 3000)))
        return _token["value"]


def _json(r: httpx.Response):
    try:
        return r.json()
    except ValueError:
        return r.text


def _call(method: str, path: str, json: dict | None = None, request_id: str | None = None, retry: bool = True):
    headers = {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if request_id:  # idempotency: a retried create or capture never doubles the money
        headers["PayPal-Request-Id"] = request_id
    r = httpx.request(method, f"{BASE}{path}", json=json, headers=headers, timeout=30)
    if r.status_code == 401 and retry:
        _token["value"] = None
        return _call(method, path, json, request_id, retry=False)
    if r.status_code >= 400:
        raise PayPalError(r.status_code, _json(r))
    return _json(r) if r.content else {}


def money(x) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.01'))}"


def create_order(*, order_id: str, shop: dict, listing: dict, qty: int, shipping_usd: float,
                 return_url: str, cancel_url: str, lines: list[tuple[dict, int]] | None = None,
                 customer: dict | None = None, discount_usd: float = 0.0) -> dict:
    """One purchase unit with the exact item, quantity and shipping. Amounts are recomputed here from the
    listing, never taken from the agent's words. The buyer's address comes from their PayPal account."""
    lines = lines or [(listing, qty)]
    item_total = sum(Decimal(money(li["price_usd"])) * q for li, q in lines)
    total = item_total - Decimal(money(discount_usd)) + Decimal(money(shipping_usd))
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": order_id,
            "custom_id": order_id,
            "invoice_id": order_id,
            "description": f"{shop['name']}: " + " + ".join(f"{q} × {li['title']}" if len(lines) > 1 else li["title"]
                                                            for li, q in lines)[:100],
            "soft_descriptor": "SMALLGARAGE",
            "amount": {"currency_code": "USD", "value": money(total), "breakdown": {
                "item_total": {"currency_code": "USD", "value": money(item_total)},
                "shipping": {"currency_code": "USD", "value": money(shipping_usd)},
                **({"discount": {"currency_code": "USD", "value": money(discount_usd)}} if discount_usd else {})}},
            "items": [{"name": li["title"][:127], "quantity": str(q), "sku": li["id"], "category": "PHYSICAL_GOODS",
                       "unit_amount": {"currency_code": "USD", "value": money(li["price_usd"])}} for li, q in lines],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": shop["name"], "shipping_preference": "GET_FROM_FILE", "user_action": "PAY_NOW",
            "return_url": return_url, "cancel_url": cancel_url}}},
    }
    if customer:   # the address the buyer gave the agent: PayPal shows it and ships there
        body["purchase_units"][0]["shipping"] = {
            "name": {"full_name": customer["full_name"]},
            "address": {"address_line_1": customer["address_line_1"], "address_line_2": customer.get("address_line_2") or None,
                        "admin_area_2": customer["city"], "admin_area_1": customer["state"],
                        "postal_code": customer["postal_code"], "country_code": "US"}}
        if not body["purchase_units"][0]["shipping"]["address"]["address_line_2"]:
            del body["purchase_units"][0]["shipping"]["address"]["address_line_2"]
        body["payment_source"]["paypal"]["experience_context"]["shipping_preference"] = "SET_PROVIDED_ADDRESS"
    return _call("POST", "/v2/checkout/orders", body, request_id=f"create-{order_id}")


def approve_link(pp_order: dict) -> str | None:
    for link in pp_order.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link["href"]
    return None


def get_order(pp_id: str) -> dict:
    return _call("GET", f"/v2/checkout/orders/{pp_id}")


def capture(pp_id: str, order_id: str) -> dict:
    return _call("POST", f"/v2/checkout/orders/{pp_id}/capture", {}, request_id=f"capture-{order_id}")


def add_tracking(pp_id: str, capture_id: str, tracking_number: str, carrier: str = "USPS") -> dict:
    return _call("POST", f"/v2/checkout/orders/{pp_id}/track",
                 {"capture_id": capture_id, "tracking_number": tracking_number, "carrier": carrier,
                  "notify_payer": True})


def create_product(listing: dict, shop: dict) -> dict:
    """Mirror a listing into PayPal's catalog, so the same item exists in the merchant's PayPal account."""
    body = {"id": listing["id"].upper().replace("-", ""), "name": listing["title"][:127], "type": "PHYSICAL",
            "category": "HOBBIES_AND_CRAFTS", "description": f"{listing['scale']} hand-built replica by {shop['maker']}"}
    return _call("POST", "/v1/catalogs/products", body, request_id=f"product-{listing['id']}")


def verify_webhook(headers: dict, event: dict) -> bool:
    wid = os.environ.get("PAYPAL_WEBHOOK_ID")
    if not wid:
        return False
    h = {k.lower(): v for k, v in headers.items()}
    body = {"auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
            "transmission_id": h.get("paypal-transmission-id"), "transmission_sig": h.get("paypal-transmission-sig"),
            "transmission_time": h.get("paypal-transmission-time"), "webhook_id": wid, "webhook_event": event}
    return _call("POST", "/v1/notifications/verify-webhook-signature", body).get("verification_status") == "SUCCESS"


def refund(capture_id: str, order_id: str, amount_usd: float | None = None, note: str = "") -> dict:
    """Full refund unless an amount is given (Payments v2). Used when stock ran out between approval and capture."""
    body: dict = {"note_to_payer": note[:255]} if note else {}
    if amount_usd is not None:
        body["amount"] = {"currency_code": "USD", "value": money(amount_usd)}
    return _call("POST", f"/v2/payments/captures/{capture_id}/refund", body, request_id=f"refund-{order_id}")
