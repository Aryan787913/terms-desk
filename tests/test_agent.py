"""Offline tests for the agent's PayPal request building and window enforcement (no network)."""
import datetime as dt
from types import SimpleNamespace

from terms_desk import agent
from terms_desk.model import HistoryModel

DRAFT = {"id": "INV2-TEST", "status": "SENT", "links": [], "due_amount": {},
         "detail": {"currency_code": "USD", "memo": "terms-desk:discount:2:until:2026-11-10", "metadata": {"x": 1}},
         "primary_recipients": [{"billing_info": {"email_address": "ap@northwind-demo.example.com",
                                                  "name": {"full_name": "Northwind Design Co."}}}],
         "items": [{"id": "ITEM-1", "name": "Retainer", "quantity": "1",
                    "unit_amount": {"currency_code": "USD", "value": "2000.00"}}],
         "amount": {"currency_code": "USD", "value": "1960.00"}}


def test_editable_strips_read_only_fields():
    b = agent.editable(DRAFT)
    assert "id" not in b and "status" not in b and "links" not in b
    assert "metadata" not in b["detail"] and "id" not in b["items"][0]


def test_discount_sends_percent_only_never_a_stale_total():
    b = agent.with_amount(agent.editable(DRAFT), "2")
    assert b["amount"]["breakdown"]["discount"]["invoice_discount"] == {"percent": "2"}
    assert "value" not in b["amount"]


def test_removing_discount_drops_amount_block():
    assert "amount" not in agent.with_amount(agent.editable(DRAFT), None)


def test_item_total():
    assert agent.item_total(DRAFT) == 2000.0


def test_model_matches_demo_history():
    m = HistoryModel(agent.ROOT / "data" / "demo_history.json", 10)
    nw = m.score("AP@northwind-demo.example.com")
    assert (nw.on_time, nw.n, nw.days_late_pay) == (2, 7, 90)
    assert m.score("nobody@example.com") is None


class FakePP:
    def __init__(self): self.updates = []
    def list_invoices(self): return [DRAFT]
    def get(self, i): return {**DRAFT, "amount": {"currency_code": "USD", "value": "2000.00"}}
    def update(self, i, body): self.updates.append(body)


def test_enforce_respects_window(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "LEDGER", tmp_path / "l.jsonl")
    pp = FakePP()
    agent.cmd_enforce(pp, SimpleNamespace(today="2026-11-10"))
    assert pp.updates == []
    agent.cmd_enforce(pp, SimpleNamespace(today="2026-11-11"))
    assert len(pp.updates) == 1 and "amount" not in pp.updates[0]
    assert pp.updates[0]["detail"]["memo"] == "terms-desk:expired:2026-11-10"
