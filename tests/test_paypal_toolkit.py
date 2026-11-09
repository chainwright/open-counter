"""The invoice status read and the balance reminder go through PayPal's Agent Toolkit (paypal-agent-toolkit 1.11.0),
with our own REST call as the fallback. PayPal itself is faked here; no network."""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from opencounter import paypal, shop, web

INV = "INV2-VV7G-JLS2-JXCV-3QTR"


class FakeToolkit:
    def __init__(self, answer=None, error=None, delay=0.0):
        self.answer, self.error, self.delay, self.calls = answer, error, delay, []

    def run(self, method, params):
        self.calls.append((method, params))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return json.dumps(self.answer)   # the Toolkit's tools answer with a JSON string


@pytest.fixture
def rest(monkeypatch):
    calls = []

    def fake_call(method, path, json=None, request_id=None, retry=True):
        calls.append((method, path, json))
        return {"status": "PARTIALLY_PAID", "from": "rest"} if method == "GET" else {}
    monkeypatch.setattr(paypal, "_call", fake_call)
    return calls


def use(monkeypatch, tk):
    monkeypatch.setattr(paypal, "_toolkit", lambda: tk)
    return tk


def test_the_invoice_status_is_read_through_the_toolkit(monkeypatch, rest):
    tk = use(monkeypatch, FakeToolkit({"id": INV, "status": "PARTIALLY_PAID",
                                       "payments": {"paid_amount": {"value": "92.25"}}}))
    inv = paypal.get_invoice(INV)
    assert tk.calls == [("get_invoice", {"invoice_id": INV})] and rest == []
    assert inv["status"] == "PARTIALLY_PAID" and inv["_via"] == paypal.VIA_TOOLKIT


def test_the_balance_reminder_is_sent_through_the_toolkit(monkeypatch, rest):
    tk = use(monkeypatch, FakeToolkit({}))
    out = paypal.remind_invoice(INV, "Your cars are finished." + "x" * 500)
    method, params = tk.calls[0]
    assert method == "send_invoice_reminder" and params["invoice_id"] == INV and rest == []
    assert params["subject"] == "Your cars are ready" and len(params["note"]) == 400
    assert out["_via"] == paypal.VIA_TOOLKIT


@pytest.mark.parametrize("error", [RuntimeError("Failed to obtain access token from PayPal"), ValueError("bad"),
                                   ImportError("No module named 'paypal_agent_toolkit'")])
def test_a_failing_toolkit_falls_back_to_the_direct_call(monkeypatch, rest, error):
    use(monkeypatch, FakeToolkit(error=error))
    inv = paypal.get_invoice(INV)
    assert inv["_via"] == paypal.VIA_REST and inv["from"] == "rest"
    assert paypal.remind_invoice(INV, "ready")["_via"] == paypal.VIA_REST
    assert rest[0] == ("GET", f"/v2/invoicing/invoices/{INV}", None)
    assert rest[1] == ("POST", f"/v2/invoicing/invoices/{INV}/remind",
                       {"subject": "Your cars are ready", "note": "ready", "send_to_invoicer": False})


def test_a_toolkit_answer_without_a_status_falls_back(monkeypatch, rest):
    use(monkeypatch, FakeToolkit({"name": "SOMETHING"}))
    assert paypal.get_invoice(INV)["_via"] == paypal.VIA_REST


def test_a_hung_toolkit_call_falls_back_after_the_deadline(monkeypatch, rest):
    monkeypatch.setattr(paypal, "TOOLKIT_TIMEOUT_S", 0.2)
    use(monkeypatch, FakeToolkit({"status": "PAID"}, delay=1.0))
    t = time.time()
    assert paypal.get_invoice(INV)["_via"] == paypal.VIA_REST and time.time() - t < 0.9


def test_the_toolkit_missing_from_the_image_falls_back(monkeypatch, rest):
    monkeypatch.setattr(paypal, "_toolkit_api", None)
    monkeypatch.setitem(sys.modules, "paypal_agent_toolkit.shared.api", None)   # import fails as if not installed
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    assert paypal.get_invoice(INV)["_via"] == paypal.VIA_REST


def test_the_real_toolkit_package_calls_paypal_invoicing(monkeypatch, rest):
    """The pinned package itself (not a stub): its get_invoice and send_invoice_reminder tools hit the sandbox
    invoicing endpoints with our ids. Only its HTTP layer is faked."""
    pc = pytest.importorskip("paypal_agent_toolkit.shared.paypal_client")
    seen = []

    class R:
        def __init__(self, status, body):
            self.status_code, self._body, self.headers = status, body, {}
            self.request = type("Q", (), {"headers": {"Authorization": "Bearer t"}})()

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def post(url, headers=None, json=None, data=None, auth=None):
        seen.append(("POST", url, json))
        return R(200, {"access_token": "t"}) if url.endswith("/oauth2/token") else R(204, {})

    def get(url, headers=None):
        seen.append(("GET", url, None))
        return R(200, {"id": INV, "status": "PAID"})
    monkeypatch.setattr(pc.requests, "post", post)
    monkeypatch.setattr(pc.requests, "get", get)
    monkeypatch.setattr(paypal, "_toolkit_api", None)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    assert paypal.get_invoice(INV) == {"id": INV, "status": "PAID", "_via": paypal.VIA_TOOLKIT}
    assert paypal.remind_invoice(INV, "ready")["_via"] == paypal.VIA_TOOLKIT
    calls = [(m, u) for m, u, _ in seen if not u.endswith("/oauth2/token")]
    assert calls == [("GET", f"https://api-m.sandbox.paypal.com/v2/invoicing/invoices/{INV}"),
                     ("POST", f"https://api-m.sandbox.paypal.com/v2/invoicing/invoices/{INV}/remind")]
    body = [j for m, u, j in seen if u.endswith("/remind")][0]
    assert body["subject"] == "Your cars are ready" and body["note"] == "ready" and rest == []
    monkeypatch.setattr(paypal, "_toolkit_api", None)


def test_the_order_records_which_path_served_it(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    shop.seed(force=True)
    monkeypatch.setattr(paypal, "remind_invoice", lambda iid, note: {"_via": paypal.VIA_TOOLKIT})
    monkeypatch.setattr(paypal, "get_invoice", lambda iid: {"status": "PARTIALLY_PAID", "_via": paypal.VIA_REST,
                                                            "payments": {"paid_amount": {"value": "92.25"}}})
    shop._save_orders(shop.orders() + [{"id": "OC-MTO2", "kind": "commission", "invoice_id": INV, "status": "awaiting_deposit",
                                        "visitor": "v-lena", "created": time.time(), "events": [], "total_usd": 184.5}])
    assert web._sync_invoice("OC-MTO2")["invoice_via"] == paypal.VIA_REST
    r = TestClient(web.app).post("/api/maker/orders/OC-MTO2/balance", headers={"x-visitor": "v-lena"})
    assert r.status_code == 200 and r.json()["balance_via"] == paypal.VIA_TOOLKIT
