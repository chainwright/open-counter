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


def get_product(product_id: str) -> dict:
    return _call("GET", f"/v1/catalogs/products/{product_id}")


def create_product(product_id: str, name: str, description: str = "", category: str | None = None) -> dict:
    """A product in the merchant's PayPal catalog, under an id we choose (6-50 characters), so creating it again
    after a restart finds the same product instead of making a second one."""
    body = {"id": product_id, "name": name[:127], "type": "PHYSICAL", "description": (description or name)[:256]}
    if category:
        body["category"] = category
    return _call("POST", "/v1/catalogs/products", body, request_id=f"product-{product_id}")


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


# ---- Invoicing (made-to-order builds: 50% deposit now, the balance before it ships) ----

def create_deposit_invoice(*, order_id: str, shop: dict, rows: list[dict], discount_usd: float, shipping_usd: float,
                           customer: dict, total_usd: float, deposit_share: float = 0.5) -> dict:
    """A PayPal invoice for a made-to-order build: one line per car spec, the volume discount, shipping, and a
    minimum first payment (the deposit). Sent to the buyer; returns {id, payer_url, deposit_usd}."""
    first, _, last = customer["full_name"].partition(" ")
    deposit = Decimal(money(total_usd * deposit_share))
    who = {"name": {"given_name": first, "surname": last or first}}
    addr = {"address_line_1": customer["address_line_1"], "admin_area_2": customer["city"],
            "admin_area_1": customer["state"], "postal_code": customer["postal_code"], "country_code": "US"}
    body = {
        "detail": {"invoice_number": order_id, "currency_code": "USD", "payment_term": {"term_type": "NET_10"},
                   "note": f"Hand-built to order by {shop['maker']}. Pay at least {money(deposit)} USD now; "
                           "the balance is due before your cars ship.",
                   "reference": order_id},
        "invoicer": {"name": {"given_name": shop["maker"].split()[0], "surname": shop["maker"].split()[-1]},
                     "business_name": shop["name"]},
        "primary_recipients": [{"billing_info": {**who, "email_address": customer["email"]},
                                "shipping_info": {**who, "address": addr}}],
        "items": [{"name": r["name"][:200], "quantity": str(r["qty"]), "unit_of_measure": "QUANTITY",
                   "unit_amount": {"currency_code": "USD", "value": money(r["unit"])}} for r in rows],
        "configuration": {"allow_tip": False, "partial_payment": {
            "allow_partial_payment": True, "minimum_amount_due": {"currency_code": "USD", "value": money(deposit)}}},
        "amount": {"breakdown": {"shipping": {"amount": {"currency_code": "USD", "value": money(shipping_usd)}},
                                 **({"discount": {"invoice_discount": {"amount": {"currency_code": "USD",
                                                                                  "value": money(discount_usd)}}}}
                                    if discount_usd else {})}},
    }
    inv = _call("POST", "/v2/invoicing/invoices", body, request_id=f"invoice-{order_id}")
    iid = inv.get("id") or inv["href"].rsplit("/", 1)[-1]
    sent = _call("POST", f"/v2/invoicing/invoices/{iid}/send", {"send_to_invoicer": False, "send_to_recipient": True},
                 request_id=f"invoice-send-{order_id}")
    return {"id": iid, "payer_url": sent.get("href") or f"https://www.sandbox.paypal.com/invoice/p/#{iid}",
            "deposit_usd": float(deposit)}


def get_invoice(iid: str) -> dict:
    return _call("GET", f"/v2/invoicing/invoices/{iid}")


def remind_invoice(iid: str, note: str) -> dict:
    return _call("POST", f"/v2/invoicing/invoices/{iid}/remind",
                 {"subject": "Your cars are ready", "note": note[:400], "send_to_invoicer": False})
