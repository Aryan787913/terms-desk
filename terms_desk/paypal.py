"""Minimal PayPal Invoicing v2 client (standard library only).

Credentials come from PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET (sandbox by default).
The token is never printed.
"""
from __future__ import annotations
import base64, json, os, time, urllib.error, urllib.request, uuid


class PayPalError(RuntimeError):
    def __init__(self, status, method, path, body):
        self.status, self.body = status, body
        msg = body.get("name") or body.get("error") or body
        super().__init__(f"PayPal {method} {path} -> HTTP {status}: {msg}")


class PayPal:
    def __init__(self):
        live = os.environ.get("PAYPAL_ENV") == "live"
        if live:
            raise SystemExit("Terms Desk is a sandbox demo. Refusing PAYPAL_ENV=live.")
        self.base = "https://api-m.sandbox.paypal.com"
        self._token, self._exp = None, 0.0

    # ---- low level ----
    def _req(self, method, path, body=None, form=None, auth=True):
        headers = {"Content-Type": "application/json", "PayPal-Request-Id": str(uuid.uuid4())}
        data = None
        if form is not None:
            cid, sec = os.environ.get("PAYPAL_CLIENT_ID", ""), os.environ.get("PAYPAL_CLIENT_SECRET", "")
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if cid and sec:
                headers["Authorization"] = "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()
            data = form.encode()
        else:
            if auth:
                headers["Authorization"] = f"Bearer {self.token()}"
            headers["Prefer"] = "return=representation"
            data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw, status = r.read().decode(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode(), e.code
        out = json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw}
        if status >= 300:
            raise PayPalError(status, method, path, out)
        return out

    def token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        out = self._req("POST", "/v1/oauth2/token", form="grant_type=client_credentials")
        self._token, self._exp = out["access_token"], time.time() + int(out.get("expires_in", 3000))
        return self._token

    # ---- invoicing ----
    def list_invoices(self, page_size=100):
        items, page = [], 1
        while True:
            out = self._req("GET", f"/v2/invoicing/invoices?page={page}&page_size={page_size}&total_required=true")
            items += out.get("items", [])
            if page >= int(out.get("total_pages", 1) or 1):
                return items
            page += 1

    def get(self, inv_id):
        return self._req("GET", f"/v2/invoicing/invoices/{inv_id}")

    def next_number(self):
        return self._req("POST", "/v2/invoicing/generate-next-invoice-number", {}).get("invoice_number")

    def create(self, body):
        return self._req("POST", "/v2/invoicing/invoices", body)

    def update(self, inv_id, body):
        return self._req("PUT", f"/v2/invoicing/invoices/{inv_id}?send_to_recipient=false", body)

    def send(self, inv_id):
        return self._req("POST", f"/v2/invoicing/invoices/{inv_id}/send", {"send_to_recipient": True})

    def delete(self, inv_id):
        return self._req("DELETE", f"/v2/invoicing/invoices/{inv_id}")
