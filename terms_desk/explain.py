"""Plain-English explanations of Skeptic decisions, written by an LLM through Otari (otari.ai).

The LLM never decides. The Skeptic (skeptic/engine.py) has already approved or blocked the
discount; the model only turns its numbers into two sentences a merchant can read at a glance.

Guardrails:
  * The model sees only numbers the Skeptic and the history model computed.
  * Grounding check: every number in the model's reply must be one of those numbers
    (or a plain count like "2 sentences"). A reply that invents a figure, or flips the verdict,
    is thrown away and the deterministic template is used instead.
  * No Otari token, a network error, or a timeout -> the template. The agent never blocks on AI.

Otari is OpenAI-compatible. Settings (in .env):
  OTARI_API_KEY   workspace token from otari.ai -> API Keys (starts with otk_)
  OTARI_MODEL     any model your workspace serves (Models tab), e.g. groq:openai/gpt-oss-120b (open-weight)
  OTARI_API_BASE  default https://otari.ai/api/v1
"""
from __future__ import annotations
import json, os, re, urllib.error, urllib.request
from dataclasses import dataclass

DEFAULT_BASE = "https://otari.ai/api/v1"
SYSTEM = (
    "You explain an invoice-discount decision to a small-business owner. The decision is final and "
    "was made by a deterministic rule; do not change it, question it, or add advice. Write exactly two "
    "short sentences in plain English. Use only the numbers given in FACTS, written exactly as given. "
    "No other numbers, no markdown."
)


@dataclass
class Explanation:
    text: str
    source: str            # "otari:<model>" or "template"
    note: str = ""         # why the template was used, if it was


def facts(client, A, d, w, r, p0, days_late, shift, dec):
    """The only numbers the LLM is allowed to use, already formatted the way it must write them."""
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
    if f["verdict"] == "BLOCKED" and re.search(r"\b(approved|approve it|should offer|go ahead)\b", low):
        return False, "contradicts BLOCKED verdict"
    if f["verdict"] == "APPROVED" and re.search(r"\b(blocked|do not offer|don't offer)\b", low):
        return False, "contradicts APPROVED verdict"
    return True, ""


def call_otari(f, timeout=20):
    key = os.environ.get("OTARI_API_KEY", "").strip()
    model = os.environ.get("OTARI_MODEL", "").strip()
    if not key or not model:
        raise RuntimeError("OTARI_API_KEY / OTARI_MODEL not set")
    base = os.environ.get("OTARI_API_BASE", DEFAULT_BASE).rstrip("/")
    body = {"model": model, "temperature": 0.2, "max_tokens": 1000, "reasoning_effort": "low",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "FACTS:\n" + json.dumps(f, indent=1)}]}
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Otari-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Otari HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None
    return (out["choices"][0]["message"].get("content") or "").strip(), model


def explain(client, A, d, w, r, p0, days_late, shift, dec, use_llm=True) -> Explanation:
    f = facts(client, A, d, w, r, p0, days_late, shift, dec)
    if not use_llm:
        return Explanation(template(f), "template", "LLM off")
    try:
        text, model = call_otari(f)
    except Exception as e:  # network, auth, missing key: never block the agent on AI
        return Explanation(template(f), "template", str(e)[:160])
    if not text:
        return Explanation(template(f), "template", "Otari reply was empty")
    ok, why = grounded(text, f)
    if not ok:
        return Explanation(template(f), "template", f"Otari reply rejected ({why})")
    return Explanation(text, f"otari:{model}")
