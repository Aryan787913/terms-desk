"""Offline tests for the Otari explainer guardrails (no network)."""
from skeptic.engine import decide
from terms_desk import explain as ex


def _f(p0=0.857):
    dec = decide(2000, 0.02, 10, 0.36, p0, 90, 0.5)
    return ex.facts("Northwind Design Co.", 2000, 0.02, 10, 0.36, p0, 90, 0.5, dec), dec


def test_grounded_accepts_only_given_numbers():
    f, _ = _f()
    ok, _ = ex.grounded(f"Northwind pays within 10 days {f['chance_pays_in_window_anyway']} of the time.", f)
    assert ok
    bad, why = ex.grounded("Northwind would cost you $123 a month.", f)
    assert not bad and "123" in why


def test_grounded_rejects_flipped_verdict():
    f, dec = _f(p0=0.857)
    assert f["verdict"] == "BLOCKED" and not dec.approve
    ok, why = ex.grounded("The discount is approved for Northwind.", f)
    assert not ok and "BLOCKED" in why


def test_falls_back_to_template_without_key(monkeypatch):
    monkeypatch.delenv("OTARI_API_KEY", raising=False)
    f, dec = _f()
    out = ex.explain("Northwind Design Co.", 2000, 0.02, 10, 0.36, 0.857, 90, 0.5, dec)
    assert out.source == "template" and "OTARI_API_KEY" in out.note


def test_bad_llm_reply_is_replaced(monkeypatch):
    monkeypatch.setattr(ex, "call_otari", lambda f, timeout=20: ("Approved! Saves $9,999.", "m"))
    f, dec = _f()
    out = ex.explain("Northwind Design Co.", 2000, 0.02, 10, 0.36, 0.857, 90, 0.5, dec)
    assert out.source == "template" and "rejected" in out.note


def test_good_llm_reply_is_kept(monkeypatch):
    f, dec = _f()
    reply = f"Northwind already pays inside 10 days {f['chance_pays_in_window_anyway']} of the time, so the discount is blocked."
    monkeypatch.setattr(ex, "call_otari", lambda f, timeout=20: (reply, "m"))
    out = ex.explain("Northwind Design Co.", 2000, 0.02, 10, 0.36, 0.857, 90, 0.5, dec)
    assert out.source == "otari:m" and out.text == reply
