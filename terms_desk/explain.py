"""AI layer for Terms Desk, every call routed through Otari (otari.ai). The LLMs never decide.

The Skeptic (skeptic/engine.py) has already approved or blocked each discount. Open-weight models served
through Otari then do three separate jobs, each with its own model and fallback chain:

  1. EXPLAINER  (Otari routing policy terms-desk-explainer: gpt-oss-120b -> gpt-oss-20b) two sentences for the merchant
  2. WRITER     (default groq:openai/gpt-oss-20b  -> gpt-oss-120b)  the client-facing invoice note, approved
                                                                     discounts only
  3. GUARD      (default groq:openai/gpt-oss-safeguard-20b)          safety model that screens the client note
                                                                     against a written policy before a human
                                                                     ever sees it
  4. VERIFIER   (optional, OTARI_CODE_EXEC=1)                        a model re-derives the EV in Otari's code
                                                                     sandbox; a mismatch with the Skeptic is
                                                                     flagged

Guardrails in code, on top of the guard model:
  * Grounding: every number in an LLM reply must be one the Skeptic computed; a flipped verdict is rejected.
  * Any failure (no key, budget exhausted, all models down, rejected reply) -> deterministic template.
    The agent never blocks on AI.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass

from terms_desk.otari import OtariError, chat, models_from_env

SYSTEM_EXPLAIN = (
    "You explain an invoice-discount decision to a small-business owner. The decision is final and "
    "was made by a deterministic rule; do not change it, question it, or add advice. Write exactly two "
    "short sentences in plain English. Use only the numbers given in FACTS, written exactly as given. "
    "No other numbers, no markdown."
)
SYSTEM_WRITE = (
    "You write the short note printed on a PayPal invoice to a client. Friendly, professional, at most "
    "three sentences. Mention the early-payment discount, its percentage, the pay-by date and the full "
    "amount after that date, using only the values in FACTS exactly as written. No pressure, no threats, "
    "no false urgency, no markdown, no greeting line, no signature."
)
GUARD_POLICY = """Policy: client-facing invoice note.
VIOLATION (1) if the note does ANY of: threatens or pressures the client (penalties, legal action, "act now",
"final notice"); invents fees, interest, or terms not given; misstates the discount, date, or amount;
contains personal data beyond the client's business name; is rude or manipulative.
SAFE (0) otherwise.
Answer with JSON only: {"violation": 0 or 1, "reason": "<short>"}"""

EXPLAIN_MODELS = "terms-desk-explainer,groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b"  # Otari routing policy first
WRITER_MODELS = "groq:openai/gpt-oss-20b,groq:openai/gpt-oss-120b"
GUARD_MODELS = "groq:openai/gpt-oss-safeguard-20b"
VERIFY_MODELS = "groq:openai/gpt-oss-120b"


@dataclass
class Explanation:
    text: str
    source: str            # "otari:<model>" or "template"
    note: str = ""         # why the template was used / which models were skipped


def _user_id(client):
    return "client-" + re.sub(r"[^a-z0-9]+", "-", client.lower()).strip("-")


def facts(client, A, d, w, r, p0, days_late, shift, dec):
    """The only numbers the LLMs may use, formatted the way they must write them."""
    f = {
        "verdict": "APPROVED" if dec.approve else "BLOCKED",
        "client": client,
        "invoice_amount": f"${A:,.0f}",
        "discount": f"{d:.0%}",
        "window_days": str(w),
        "chance_pays_in_window_anyway": f"{p0:.0%}",
        "days_to_pay_when_late": str(round(days_late)),
        "assumed_share_of_slow_payers_who_speed_up": f"{shift:.0%}",
        "cost_of_capital": f"{r:.0%}",
        "expected_value": f"{'+' if dec.ev >= 0 else '-'}${abs(dec.ev):,.0f}",
        "giveaway_to_on_time_payers": f"${d * A * p0:,.0f}",
    }
    if dec.break_even_p_shift is not None:
        f["break_even_share_of_slow_payers"] = f"{dec.break_even_p_shift:.0%}"
    return f


def template(f):
    if f["verdict"] == "APPROVED":
        return (f"{f['client']} pays inside {f['window_days']} days only {f['chance_pays_in_window_anyway']} of the time, "
                f"so a {f['discount']} discount mostly buys faster cash. Expected value is {f['expected_value']} "
                f"on this {f['invoice_amount']} invoice.")
    return (f"{f['client']} already pays inside {f['window_days']} days {f['chance_pays_in_window_anyway']} of the time, "
            f"so a {f['discount']} discount would mostly be a gift. Sending at full price keeps about "
            f"{f['giveaway_to_on_time_payers']} that would have gone to on-time payments.")


def note_template(n):
    return (f"{n['discount']} early-payment discount applied if paid by {n['pay_by']}. "
            f"After that the invoice returns to {n['full_amount']}. Thank you for your business.")


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(s):
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(s)}


def grounded(text, f):
    """True if every number in `text` appears in the facts, and the verdict is not contradicted."""
    allowed = set().union(*(_numbers(v) for v in f.values())) | {"1", "2"}
    extra = _numbers(text) - allowed
    if extra:
        return False, f"invented number(s): {', '.join(sorted(extra))}"
    low = text.lower()
    if f.get("verdict") == "BLOCKED" and re.search(r"\b(approved|approve it|should offer|go ahead)\b", low):
        return False, "contradicts BLOCKED verdict"
    if f.get("verdict") == "APPROVED" and re.search(r"\b(blocked|do not offer|don't offer)\b", low):
        return False, "contradicts APPROVED verdict"
    return True, ""


def _skipped(reply):
    return "; ".join(f"fallback: {m} failed ({e})" for m, e in reply.tried)


def call_otari(f, timeout=60):
    """Explainer call. Returns (text, served_model, skipped_note)."""
    rep = chat(_legacy() or models_from_env("OTARI_EXPLAIN_MODELS", EXPLAIN_MODELS),
               [{"role": "system", "content": SYSTEM_EXPLAIN},
                {"role": "user", "content": "FACTS:\n" + json.dumps(f, indent=1)}],
               user=_user_id(f["client"]), timeout=timeout, temperature=0.2, max_tokens=1000,
               reasoning_effort="low")
    return rep.text, rep.model, _skipped(rep)


def _legacy():
    """OTARI_EXPLAIN_MODELS, or the older single OTARI_MODEL, if set."""
    import os
    v = os.environ.get("OTARI_EXPLAIN_MODELS") or os.environ.get("OTARI_MODEL")
    return [m.strip() for m in v.split(",") if m.strip()] if v else None


def explain(client, A, d, w, r, p0, days_late, shift, dec, use_llm=True) -> Explanation:
    f = facts(client, A, d, w, r, p0, days_late, shift, dec)
    if not use_llm:
        return Explanation(template(f), "template", "LLM off")
    try:
        text, model, skipped = call_otari(f)
    except Exception as e:  # network, auth, budget, all models down: never block the agent on AI
        return Explanation(template(f), "template", str(e)[:200])
    if not text:
        return Explanation(template(f), "template", "Otari reply was empty")
    ok, why = grounded(text, f)
    if not ok:
        return Explanation(template(f), "template", f"Otari reply rejected ({why})")
    return Explanation(text, f"otari:{model}", skipped)


# ---------------- writer + guard ----------------
def guard(note, timeout=60):
    """Safety model screens the client note. Returns (safe: bool, reason, model)."""
    rep = chat(models_from_env("OTARI_GUARD_MODELS", GUARD_MODELS),
               [{"role": "system", "content": GUARD_POLICY}, {"role": "user", "content": note}],
               timeout=timeout, temperature=0, max_tokens=800, reasoning_effort="low")
    m = re.search(r"\{.*\}", rep.text, re.S)
    try:
        j = json.loads(m.group(0)) if m else {}
        violation = int(j.get("violation", 1))
        return violation == 0, str(j.get("reason", ""))[:160], rep.model
    except (ValueError, TypeError):
        v = re.search(r"\b([01])\b", rep.text)
        return (v is not None and v.group(1) == "0"), rep.text[:120], rep.model


def client_note(client, pct, pay_by, full_amount, use_llm=True) -> Explanation:
    """Writer drafts the invoice note; grounding check + guard model must both pass, else template."""
    n = {"client": client, "discount": f"{pct}%", "pay_by": pay_by, "full_amount": full_amount}
    if not use_llm:
        return Explanation(note_template(n), "template", "LLM off")
    try:
        rep = chat(models_from_env("OTARI_WRITER_MODELS", WRITER_MODELS),
                   [{"role": "system", "content": SYSTEM_WRITE},
                    {"role": "user", "content": "FACTS:\n" + json.dumps(n, indent=1)}],
                   user=_user_id(client), timeout=60, temperature=0.4, max_tokens=1000, reasoning_effort="low")
    except Exception as e:
        return Explanation(note_template(n), "template", str(e)[:200])
    ok, why = grounded(rep.text, n)
    if not ok:
        return Explanation(note_template(n), "template", f"writer reply rejected ({why})")
    try:
        safe, reason, gm = guard(rep.text)
    except Exception as e:  # guard can't run -> refuse the AI text (fail closed)
        return Explanation(note_template(n), "template", f"guard unavailable, failing closed ({str(e)[:120]})")
    if not safe:
        return Explanation(note_template(n), "template", f"guard {gm} blocked it: {reason}")
    return Explanation(rep.text, f"otari:{rep.model} + guard {gm}", _skipped(rep))


# ---------------- verifier (Otari code execution) ----------------
def verify_ev(A, d, w, r, p0, days_late, shift, dec, timeout=120):
    """Ask a model to recompute EV in Otari's code sandbox. Returns (agrees, model_ev, model) or raises."""
    prompt = (
        "Use the code execution tool to compute this in Python, then reply with JSON only: {\"ev\": <number>}.\n"
        f"A={A}; d={d}; w={w}; r={r}; p0={p0}; days_late={days_late}; p_shift={shift}\n"
        "g=max(days_late-w,0); p_win=p0+(1-p0)*p_shift; cost=d*A*p_win; "
        "benefit=(1-p0)*p_shift*A*r*g/365; ev=benefit-cost"
    )
    rep = chat(models_from_env("OTARI_VERIFY_MODELS", VERIFY_MODELS), [{"role": "user", "content": prompt}],
               timeout=timeout, tools=[{"type": "otari_code_execution"}], max_tokens=1500)
    m = re.search(r"-?\d+(?:\.\d+)?", (re.search(r"\{.*\}", rep.text, re.S) or re.search(r".*", rep.text)).group(0))
    ev = float(m.group(0)) if m else float("nan")
    return abs(ev - dec.ev) <= 1.0, ev, rep.model
