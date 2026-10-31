"""Day-1 feasibility spike (kill switch K2): does an EARLY_PAYMENT_DISCOUNT conditional rule
work in the PayPal sandbox, and is the discount applied when the buyer pays inside the window?

Steps (each prints the raw JSON response; nothing is faked):
  python spike/paypal_spike.py token
  python spike/paypal_spike.py create  --buyer sb-buyer@personal.example.com --amount 2000
  python spike/paypal_spike.py rule    INV2-XXXX-XXXX-XXXX-XXXX --percent 2 --window SEVEN_DAYS_AFTER_ISSUE_DATE
  python spike/paypal_spike.py send    INV2-...
  (pay the invoice as the sandbox personal buyer from the emailed/recipient link)
  python spike/paypal_spike.py status  INV2-...      # invoice + conditional rules, check is_applied / amounts
  python spike/paypal_spike.py remind  INV2-...

Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET / PAYPAL_ENV from the environment or .env.
Standard library only, so it runs before any dependency install.
"""
import argparse, base64, datetime as dt, json, os, sys, urllib.request, urllib.error, uuid
from pathlib import Path

WINDOW_DAYS = {"THREE_DAYS_AFTER_ISSUE_DATE": 3, "SEVEN_DAYS_AFTER_ISSUE_DATE": 7,
               "FIFTEEN_DAYS_AFTER_ISSUE_DATE": 15, "THIRTY_DAYS_AFTER_ISSUE_DATE": 30}


def load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


def base_url():
    return "https://api-m.paypal.com" if os.environ.get("PAYPAL_ENV") == "live" else "https://api-m.sandbox.paypal.com"


def call(method, path, body=None, token=None, form=None):
    headers = {"Content-Type": "application/json", "PayPal-Request-Id": str(uuid.uuid4())}
    data = None
    if form is not None:
        cid, sec = os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]
        headers = {"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
                   "Content-Type": "application/x-www-form-urlencoded"}
        data = form.encode()
    else:
        headers["Authorization"] = f"Bearer {token}"
        headers["Prefer"] = "return=representation"
        data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode(); status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(); status = e.code
    out = json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw}
    print(f"HTTP {status} {method} {path}")
    return status, out


def token():
    s, out = call("POST", "/v1/oauth2/token", form="grant_type=client_credentials")
    if s != 200:
        sys.exit(json.dumps(out, indent=2))
    return out["access_token"]


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["token", "create", "rule", "send", "status", "remind"])
    ap.add_argument("invoice_id", nargs="?")
    ap.add_argument("--buyer"); ap.add_argument("--amount", default="2000.00")
    ap.add_argument("--percent", default="2")
    ap.add_argument("--window", default="SEVEN_DAYS_AFTER_ISSUE_DATE", choices=list(WINDOW_DAYS))
    ap.add_argument("--net-days", type=int, default=30)
    a = ap.parse_args()
    t = token()
    if a.cmd == "token":
        print("token OK (not printed)"); return
    if a.cmd == "create":
        today = dt.date.today()
        s, num = call("POST", "/v2/invoicing/generate-next-invoice-number", {}, t)
        body = {
            "detail": {"invoice_number": num.get("invoice_number"), "currency_code": "USD",
                       "invoice_date": today.isoformat(),
                       "payment_term": {"due_date": (today + dt.timedelta(days=a.net_days)).isoformat()},
                       "note": "Terms Desk spike invoice (sandbox)"},
            "primary_recipients": [{"billing_info": {"email_address": a.buyer}}] if a.buyer else [],
            "items": [{"name": "Design retainer (sandbox test)", "quantity": "1",
                       "unit_amount": {"currency_code": "USD", "value": str(a.amount)}}],
        }
        s, out = call("POST", "/v2/invoicing/invoices", body, t)
    elif a.cmd == "rule":
        end = dt.date.today() + dt.timedelta(days=WINDOW_DAYS[a.window])
        body = {"rules": [{"conditional_rule_type": "EARLY_PAYMENT_DISCOUNT",
                           "conditional_rule_value_type": "PERCENT", "conditional_rule_value": str(a.percent),
                           "rule_expiry_terms": {"rule_expiry_condition": a.window,
                                                 "condition_rule_end_date": end.isoformat()}}]}
        s, out = call("POST", f"/v2/invoicing/invoices/{a.invoice_id}/conditional-rules", body, t)
    elif a.cmd == "send":
        s, out = call("POST", f"/v2/invoicing/invoices/{a.invoice_id}/send", {"send_to_recipient": True}, t)
    elif a.cmd == "remind":
        s, out = call("POST", f"/v2/invoicing/invoices/{a.invoice_id}/remind", {}, t)
    elif a.cmd == "status":
        s, out = call("GET", f"/v2/invoicing/invoices/{a.invoice_id}", None, t)
        print(json.dumps({k: out.get(k) for k in ("status", "amount", "due_amount", "payments")}, indent=2))
        s, out = call("GET", f"/v2/invoicing/invoices/{a.invoice_id}/conditional-rules", None, t)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
