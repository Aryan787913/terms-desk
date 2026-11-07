"""Terms Desk agent (CLI). Sandbox only. Nothing is sent without a human 'y'.

  python -m terms_desk.agent seed              # create fictional demo DRAFT invoices in your sandbox
  python -m terms_desk.agent run               # score drafts, run the Skeptic, ask you, then act
  python -m terms_desk.agent enforce           # remove expired early-pay discounts from unpaid invoices
  python -m terms_desk.agent ledger            # every decision and what it was worth
  python -m terms_desk.agent explain           # offline: Skeptic + Otari explanation for each demo client

Flow for an approved discount (PayPal's native conditional-rules endpoint is not used; see README):
  1. update the draft with invoice_discount percent + a note with the deadline
  2. send the invoice
  3. `enforce` (run daily, e.g. cron) puts unpaid invoices back to full price after the window
"""
from __future__ import annotations
import argparse, copy, datetime as dt, json, os, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from skeptic.engine import decide
from terms_desk.explain import client_note, explain, guard, verify_ev
from terms_desk.model import HistoryModel
from terms_desk.paypal import PayPal, PayPalError

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ledger.jsonl"
TAG = "terms-desk"
READ_ONLY = {"id", "status", "links", "payments", "refunds", "due_amount", "gratuity", "invoicer_view_url"}


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def settings():
    return dict(d=float(os.environ.get("DISCOUNT", 0.02)), w=int(os.environ.get("WINDOW_DAYS", 10)),
                r=float(os.environ.get("COST_OF_CAPITAL", 0.36)), shift=float(os.environ.get("P_SHIFT", 0.5)))


def money(x):
    return str(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def log(entry):
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), **entry}
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def item_total(inv):
    return float(sum(Decimal(i["unit_amount"]["value"]) * Decimal(i.get("quantity", "1")) for i in inv["items"]))


def recipient(inv):
    try:
        return inv["primary_recipients"][0]["billing_info"]["email_address"]
    except (KeyError, IndexError):
        return None


def editable(inv):
    body = {k: copy.deepcopy(v) for k, v in inv.items() if k not in READ_ONLY}
    body.get("detail", {}).pop("metadata", None)
    for it in body.get("items", []):
        it.pop("id", None)
    return body


def with_amount(body, percent=None):
    """Let PayPal recompute amount and breakdown from the items, so we never send a stale total.

    With a percent: only the invoice_discount percent is sent. Without: the amount block is
    dropped, which clears the discount and returns the invoice to the item total.
    """
    body.pop("amount", None)
    if percent:
        body["amount"] = {"currency_code": body["detail"]["currency_code"],
                          "breakdown": {"discount": {"invoice_discount": {"percent": str(percent)}}}}
    return body


def ask(prompt, auto=None):
    if auto is not None:
        print(f"{prompt} {'y' if auto else 'n'} (from --approve/--reject)")
        return auto
    if not sys.stdin.isatty():
        print(f"{prompt} n (no terminal: nothing sent)")
        return False
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


# ---------------- commands ----------------
def cmd_seed(pp, a):
    data = json.loads((ROOT / "data" / "demo_history.json").read_text())
    today = dt.date.today()
    for c in data["clients"]:
        body = {"detail": {"invoice_number": pp.next_number(), "currency_code": "USD", "invoice_date": today.isoformat(),
                           "payment_term": {"term_type": "NET_30"}, "memo": f"{TAG}:draft",
                           "note": "Thank you for your business. (PayPal sandbox demo, fictional client)"},
                "primary_recipients": [{"billing_info": {"email_address": c["email"],
                                                          "name": {"full_name": c["name"]}}}],
                "items": [{"name": c["item"], "quantity": "1",
                           "unit_amount": {"currency_code": "USD", "value": money(c["amount"])}}]}
        inv = pp.create(body)
        inv_id = inv.get("id") or inv.get("href", "").rsplit("/", 1)[-1]
        print(f"draft {inv_id}  {c['name']:<22} ${c['amount']:,.2f}")


def cmd_run(pp, a):
    s = settings()
    model = HistoryModel(ROOT / "data" / "demo_history.json", s["w"], k=float(os.environ.get("SHRINK_K", 0)))
    drafts = [i for i in pp.list_invoices() if i.get("status") == "DRAFT"]
    print(f"Pulled {len(drafts)} draft invoice(s) from PayPal sandbox. "
          f"Offer: {s['d']:.0%} off if paid in {s['w']} days. Cost of capital {s['r']:.0%}, assumed response {s['shift']:.0%}.\n")
    approve_ids, reject_ids = set(a.approve or []), set(a.reject or [])
    for stub in drafts:
        inv = pp.get(stub["id"])
        email = recipient(inv)
        sc = model.score(email)
        A = item_total(inv)
        if not sc:
            print(f"- {inv['id']}  {email or 'no recipient'}: no payment history, skipped.\n")
            continue
        dec = decide(A, s["d"], s["w"], s["r"], sc.p0, sc.days_late_pay, s["shift"])
        print(f"- {inv['id']}  {sc.name}  ${A:,.2f}")
        print(f"  Model: {sc.p0:.0%} chance of paying inside {s['w']} days ({sc.history_text}).")
        print(f"  Skeptic: {dec.reason}")
        ex = explain(sc.name, A, s["d"], s["w"], s["r"], sc.p0, sc.days_late_pay, s["shift"], dec)
        print(f"  In plain English ({ex.source}): {ex.text}")
        auto = True if inv["id"] in approve_ids else False if inv["id"] in reject_ids else None
        if dec.approve:
            if ask(f"  Send with {s['d']:.0%} off for {s['w']} days?", auto):
                until = dt.date.today() + dt.timedelta(days=s["w"])
                body = editable(inv)
                pct = money(s["d"] * 100).rstrip("0").rstrip(".")
                body["detail"]["memo"] = f"{TAG}:discount:{pct}:until:{until.isoformat()}"
                cn = client_note(sc.name, pct, until.isoformat(), f"${A:,.2f}")
                print(f"  Invoice note ({cn.source}): {cn.text}")
                body["detail"]["note"] = cn.text + " (PayPal sandbox demo)"
                with_amount(body, pct)
                pp.update(inv["id"], body)
                pp.send(inv["id"])
                after = pp.get(inv["id"])
                print(f"  Sent. PayPal status {after['status']}, amount ${after['amount']['value']}, valid until {until}.\n")
                log({"invoice": inv["id"], "client": sc.name, "amount": A, "action": "discount sent",
                     "by": "you", "ev": dec.ev, "until": until.isoformat()})
            else:
                print("  Not sent.\n")
                log({"invoice": inv["id"], "client": sc.name, "amount": A, "action": "rejected", "by": "you", "ev": 0})
        else:
            saved = round(s["d"] * A * sc.p0, 2)
            if ask("  Send at full price (no discount)?", auto):
                pp.send(inv["id"])
                print(f"  Sent at full price. About ${saved:,.0f} not given away.\n")
                log({"invoice": inv["id"], "client": sc.name, "amount": A, "action": "discount blocked, sent full price",
                     "by": "skeptic + you", "protected": saved})
            else:
                print("  Not sent.\n")
                log({"invoice": inv["id"], "client": sc.name, "amount": A, "action": "discount blocked, held",
                     "by": "skeptic", "protected": saved})


def cmd_enforce(pp, a):
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    n = 0
    for stub in pp.list_invoices():
        if stub.get("status") not in ("SENT", "UNPAID", "PARTIALLY_PAID"):
            continue
        memo = stub.get("detail", {}).get("memo", "") or ""
        inv = None
        if not memo:
            inv = pp.get(stub["id"]); memo = inv["detail"].get("memo", "") or ""
        if not memo.startswith(f"{TAG}:discount:"):
            continue
        until = dt.date.fromisoformat(memo.split(":until:")[1])
        if today <= until:
            print(f"- {stub['id']}: discount still valid until {until}.")
            continue
        inv = inv or pp.get(stub["id"])
        A = item_total(inv)
        body = editable(inv)
        body["detail"]["memo"] = f"{TAG}:expired:{until.isoformat()}"
        body["detail"]["note"] = f"Early-payment discount expired on {until.isoformat()}. Amount due ${A:,.2f}. (PayPal sandbox demo)"
        with_amount(body, None)
        pp.update(inv["id"], body)
        after = pp.get(inv["id"])
        print(f"- {inv['id']}: window ended {until}, unpaid. Restored to ${after['amount']['value']} (status {after['status']}).")
        name = (inv.get("primary_recipients") or [{}])[0].get("billing_info", {}).get("name", {}).get("full_name")
        log({"invoice": inv["id"], "client": name or recipient(inv), "amount": A,
             "action": "discount expired, full price restored", "by": "terms desk"})
        n += 1
    print(f"Done. {n} invoice(s) restored to full price.")


def cmd_explain(pp, a):
    """No PayPal needed: model + Skeptic on the demo clients, then the Otari AI layer for each decision."""
    s = settings()
    llm = not a.no_llm
    model = HistoryModel(ROOT / "data" / "demo_history.json", s["w"], k=float(os.environ.get("SHRINK_K", 0)))
    until = (dt.date.today() + dt.timedelta(days=s["w"])).isoformat()
    pct = money(s["d"] * 100).rstrip("0").rstrip(".")
    for c in json.loads((ROOT / "data" / "demo_history.json").read_text())["clients"]:
        sc = model.score(c["email"])
        A = c["amount"]
        dec = decide(A, s["d"], s["w"], s["r"], sc.p0, sc.days_late_pay, s["shift"])
        print(f"- {sc.name}  ${A:,.2f}")
        print(f"  Skeptic: {dec.reason}")
        ex = explain(sc.name, A, s["d"], s["w"], s["r"], sc.p0, sc.days_late_pay, s["shift"], dec, use_llm=llm)
        print(f"  Explainer ({ex.source}): {ex.text}")
        if ex.note:
            print(f"    ({ex.note})")
        if dec.approve:
            cn = client_note(sc.name, pct, until, f"${A:,.2f}", use_llm=llm)
            print(f"  Invoice note ({cn.source}): {cn.text}")
            if cn.note:
                print(f"    ({cn.note})")
        if a.verify and llm:
            try:
                agrees, ev, vm = verify_ev(A, s["d"], s["w"], s["r"], sc.p0, sc.days_late_pay, s["shift"], dec)
                print(f"  Verifier ({vm}, Otari code execution): EV {ev:+.2f} vs Skeptic {dec.ev:+.2f} -> "
                      f"{'agrees' if agrees else 'MISMATCH, flag for review'}")
            except Exception as e:
                print(f"  Verifier skipped: {str(e)[:160]}")
        print()
    if a.guard_demo and llm:
        bad = ("FINAL NOTICE: pay within 24 hours or a 15% late fee and legal action will follow. "
               "Discount 2% only if you pay today.")
        try:
            safe, reason, gm = guard(bad)
            print(f"Guard demo ({gm}) on a pushy note: {'ALLOWED' if safe else 'BLOCKED'} - {reason}")
        except Exception as e:
            print(f"Guard demo skipped: {str(e)[:160]}")


def cmd_ledger(pp, a):
    if not LEDGER.exists():
        print("Ledger is empty."); return
    for line in LEDGER.read_text().splitlines():
        e = json.loads(line)
        val = f"+${e['protected']:,.0f} protected" if "protected" in e else (f"EV {e['ev']:+,.0f}" if "ev" in e else "")
        print(f"{e['at'][:16]}  {e.get('client', e['invoice']):<22} ${e['amount']:>9,.2f}  {e['action']:<36} {e['by']:<14} {val}")


def main():
    load_env()
    ap = argparse.ArgumentParser(prog="terms_desk.agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    r = sub.add_parser("run")
    r.add_argument("--approve", nargs="*", help="invoice IDs to approve without prompting")
    r.add_argument("--reject", nargs="*", help="invoice IDs to reject without prompting")
    e = sub.add_parser("enforce")
    e.add_argument("--today", help="pretend today is YYYY-MM-DD (to demo an expired window)")
    sub.add_parser("ledger")
    x = sub.add_parser("explain")
    x.add_argument("--no-llm", action="store_true", help="skip Otari, use the deterministic templates")
    x.add_argument("--verify", action="store_true", help="re-derive each EV with Otari code execution")
    x.add_argument("--guard-demo", action="store_true", help="show the guard model blocking a pushy note")
    a = ap.parse_args()
    pp = None if a.cmd == "explain" else PayPal()
    try:
        {"seed": cmd_seed, "run": cmd_run, "enforce": cmd_enforce, "ledger": cmd_ledger,
         "explain": cmd_explain}[a.cmd](pp, a)
    except PayPalError as err:
        sys.exit(f"{err}\n{json.dumps(err.body, indent=2)[:1500]}")


if __name__ == "__main__":
    main()
