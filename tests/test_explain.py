"""Offline tests for the Otari AI layer guardrails (no network; Otari calls are mocked)."""
from skeptic.engine import decide
from terms_desk import explain as ex
from terms_desk import otari
from terms_desk.otari import OtariError, Reply


def _f(p0=0.857):
    dec = decide(2000, 0.02, 10, 0.36, p0, 90, 0.5)
    return ex.facts("Northwind Design Co.", 2000, 0.02, 10, 0.36, p0, 90, 0.5, dec), dec


def _explain(dec, p0=0.857):
    return ex.explain("Northwind Design Co.", 2000, 0.02, 10, 0.36, p0, 90, 0.5, dec)


def test_grounded_accepts_only_given_numbers():
    f, _ = _f()
    assert ex.grounded(f"Northwind pays within 10 days {f['chance_pays_in_window_anyway']} of the time.", f)[0]
    bad, why = ex.grounded("Northwind would cost you $123 a month.", f)
    assert not bad and "123" in why


def test_grounded_rejects_flipped_verdict():
    f, dec = _f()
    assert f["verdict"] == "BLOCKED" and not dec.approve
    ok, why = ex.grounded("The discount is approved for Northwind.", f)
    assert not ok and "BLOCKED" in why


def test_falls_back_to_template_without_key(monkeypatch):
    for v in ("OTARI_API_KEY", "OTARI_MODEL", "OTARI_EXPLAIN_MODELS"):
        monkeypatch.delenv(v, raising=False)
    _, dec = _f()
    out = _explain(dec)
    assert out.source == "template" and "OTARI_API_KEY" in out.note


def test_bad_llm_reply_is_replaced(monkeypatch):
    monkeypatch.setattr(ex, "call_otari", lambda f, timeout=60: ("Approved! Saves $9,999.", "m", ""))
    _, dec = _f()
    out = _explain(dec)
    assert out.source == "template" and "rejected" in out.note


def test_good_llm_reply_is_kept(monkeypatch):
    f, dec = _f()
    reply = f"Northwind already pays inside 10 days {f['chance_pays_in_window_anyway']} of the time, so the discount is blocked."
    monkeypatch.setattr(ex, "call_otari", lambda f, timeout=60: (reply, "m", ""))
    out = _explain(dec)
    assert out.source == "otari:m" and out.text == reply


def test_chat_falls_back_to_next_model(monkeypatch):
    calls = []

    def fake_post(body, timeout):
        calls.append(body["model"])
        if body["model"] == "a":
            raise OtariError(503, "upstream down")
        return {"choices": [{"message": {"content": "hi"}}], "model": "b"}, {}
    monkeypatch.setattr(otari, "_post", fake_post)
    rep = otari.chat(["a", "b"], [], user="client-x")
    assert calls == ["a", "b"] and rep.model == "b" and rep.tried[0][0] == "a"


def test_budget_exhaustion_stops_chain(monkeypatch):
    def fake_post(body, timeout):
        raise OtariError(402, "Insufficient funds", "insufficient_funds")
    monkeypatch.setattr(otari, "_post", fake_post)
    try:
        otari.chat(["a", "b"], [])
        assert False
    except OtariError as e:
        assert e.is_budget


def test_client_note_blocked_by_guard_uses_template(monkeypatch):
    def fake_chat(models, messages, user=None, timeout=60, **kw):
        if "Policy" in messages[0]["content"]:
            return Reply('{"violation": 1, "reason": "pressure"}', "guard")
        return Reply("2% off if paid by 2026-11-18, else $2,000.00. Pay now or else.", "writer")
    monkeypatch.setattr(ex, "chat", fake_chat)
    out = ex.client_note("Northwind", "2", "2026-11-18", "$2,000.00")
    assert out.source == "template" and "guard" in out.note


def test_client_note_passes_guard(monkeypatch):
    text = "A 2% early-payment discount applies if paid by 2026-11-18. After that the total is $2,000.00."
    def fake_chat(models, messages, user=None, timeout=60, **kw):
        if "Policy" in messages[0]["content"]:
            return Reply('{"violation": 0, "reason": "ok"}', "guard")
        return Reply(text, "writer")
    monkeypatch.setattr(ex, "chat", fake_chat)
    out = ex.client_note("Northwind", "2", "2026-11-18", "$2,000.00")
    assert out.text == text and "guard" in out.source
