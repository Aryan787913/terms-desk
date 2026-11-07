"""Tiny Otari (otari.ai) client: OpenAI-compatible chat completions, standard library only.

Otari features this client uses:
  * Model routing + fallbacks: `model` may be a routing policy name created in the Otari dashboard
    (Routing -> Policies). Otari reports the model that actually served it in the `Otari-Model` /
    `Otari-Fallback` response headers, which we surface. On top of that, the app keeps its own ordered
    fallback list, so a model that errors (rate limit, 5xx, not offered) is skipped.
  * Per-user attribution / budgets: every request is tagged with the end client. With a service key and
    OTARI_PER_CLIENT_BUDGETS=1 it is sent as `user=<client id>`, so Otari meters and caps spend per client
    (end_user_budget_id); otherwise as request metadata. Budget or balance exhaustion (402/429) is
    reported, never crashes the agent.
  * Server-side code execution: `tools=[{"type": "otari_code_execution"}]`, Otari runs the model's Python
    in its sandbox.
"""
from __future__ import annotations
import json, os, urllib.error, urllib.request
from dataclasses import dataclass, field

DEFAULT_BASE = "https://otari.ai/api/v1"


class OtariError(RuntimeError):
    def __init__(self, status, detail, code=""):
        self.status, self.detail, self.code = status, detail, code
        super().__init__(f"Otari HTTP {status} {code}: {detail}")

    @property
    def is_budget(self):
        return self.status in (402, 429) or "budget" in (self.code + self.detail).lower() \
            or "insufficient_funds" in self.code


@dataclass
class Reply:
    text: str
    model: str                       # model that served the reply
    tried: list = field(default_factory=list)   # (model, error) for every model skipped before it
    raw: dict = field(default_factory=dict)


def _post(body, timeout):
    key = os.environ.get("OTARI_API_KEY", "").strip()
    if not key:
        raise OtariError(0, "OTARI_API_KEY not set", "no_key")
    base = os.environ.get("OTARI_API_BASE", DEFAULT_BASE).rstrip("/")
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Otari-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            j = json.loads(raw); detail, code = str(j.get("detail", raw)), str(j.get("code", ""))
        except ValueError:
            detail, code = raw[:200], ""
        raise OtariError(e.code, detail[:200], code) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise OtariError(0, str(e)[:200], "network") from None


def models_from_env(var, default):
    """'a,b,c' -> ['a','b','c']: primary first, then fallbacks."""
    return [m.strip() for m in os.environ.get(var, default).split(",") if m.strip()]


def chat(models, messages, user=None, timeout=60, **extra) -> Reply:
    """Try each model in order; return the first non-empty reply. Budget exhaustion stops the chain."""
    tried = []
    for m in models:
        body = {"model": m, "messages": messages, **extra}
        if user:
            # Per-client budgets need an Otari *service key* (is_service_key + end_user_budget_id); a normal
            # workspace key rejects `user`, so then we only tag the request with metadata for usage reports.
            if os.environ.get("OTARI_PER_CLIENT_BUDGETS") == "1":
                body["user"] = user
            else:
                body["metadata"] = {"terms_desk_client": user}
        try:
            out, headers = _post(body, timeout)
        except OtariError as e:
            tried.append((m, f"{e.status} {e.code or e.detail}"))
            if e.is_budget or e.code == "no_key":
                raise
            continue
        msg = out["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        h = {k.lower(): v for k, v in headers.items()}
        served = h.get("otari-model") or out.get("model") or m
        if served != m and "/" not in m:            # m was an Otari routing policy name
            served = f"policy {m} -> {served}"
        if h.get("otari-fallback") == "true":
            tried.append((m, "Otari routing policy fell back inside the gateway"))
        if not text:
            tried.append((m, "empty reply"))
            continue
        return Reply(text, served, tried, out)
    raise OtariError(0, "; ".join(f"{m}: {e}" for m, e in tried) or "no models configured", "all_failed")
