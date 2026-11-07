# Terms Desk

**Discounts are expensive money.** Terms Desk decides, per PayPal invoice, whether an early-payment
discount earns you cash or just hands margin to clients who'd pay on time anyway. It acts through
the PayPal Invoicing v2 API only after you approve.

**Live demo:** https://aryanrsinghsengar.github.io/terms-desk/ · **Video (1:43):** https://youtu.be/jD69cO7EcMU

> Status: hackathon build in progress (PayPal AI Hackathon, 2026). Sections marked TODO are not done yet.

## How it works
1. **Predict**: per-client probability of paying on time, from history a PayPal merchant already has.
2. **Skeptic** (deterministic, not AI): expected value of a discount. Blocks any discount that loses money.
3. **Approve**: proposals land in an approval queue; nothing is sent until you click approve.
4. **Act**: create the invoice with an `invoice_discount` -> `send_invoice`. Terms Desk enforces the
   discount window itself: if the invoice is still unpaid when the window closes, it updates the invoice
   back to full price (recomputing `amount` and `breakdown`). PayPal's native conditional-rules endpoint
   returned `401 client_auth_mech_not_allowed` for our sandbox app (its write calls also list the
   `invoicing/internal` scope). Setting `detail.payment_term.conditional_rules.early_payment_discount`
   directly on create or update was accepted but silently dropped (tested 2026-10-31), so we do not rely on it.
5. **Ledger**: every blocked discount is logged with the money it saved.

## The Skeptic formula
For an invoice of amount A, discount d inside a window of w days, annual cost of capital r:

- p0 = P(client pays inside the window anyway)
- p_shift = share of slower payers who move into the window because of the discount (swept 0-100%, never assumed as fact)
- cost = d · A · (p0 + (1 − p0) · p_shift)
- benefit = (1 − p0) · p_shift · A · r · (days_to_pay_if_slow − w) / 365
- **Approve only if benefit − cost ≥ 0.** If r · (days gained)/365 ≤ d, no p_shift can make it pay.

Reference: 2/10 net 30 costs the merchant d/(1−d) · 365/20 = **37.2% annualized**.
Code: `skeptic/engine.py`; tests: `tests/test_skeptic.py` (`pytest -q`).

## Backtest (measured)
`python ml/backtest.py data/ds.csv` reproduces `ml/results.json` and `ml/calibration.png`.

Data: "Payment Date Dataset", CC0, 50,000 rows (Kaggle `rajattomar132/payment-date-dataset`).
**This is B2B large-retail data on mostly 15-day terms, not freelancer data.** Closed USD invoices after de-duplication: 41,555.
Time split: train on invoices posted in 2019 (36,246), test on 2020 (5,309). History features use only
invoices that had cleared before each invoice's posting date (no leakage).

| Model (2020 test set) | ROC AUC | Brier |
|---|---|---|
| Client-history baseline (past on-time rate, shrunk to global) | 0.749 | 0.188 |
| XGBoost (history + amount + terms + weekday) | 0.826 | 0.157 |
| XGBoost without posting weekday | 0.783 | 0.180 |

Posting weekday is a strong feature here, likely an artefact of the retailers' AP batch schedule; we
report the model without it as the portable number.

On-time rate in 2020 by the client's earlier history: <50% on time before → 28.9% (n=1,464);
50–90% → 73.7% (n=3,614); ≥90% → 84.2% (n=183).

*Numbers above were produced from a GitHub mirror with the identical schema; TODO re-run on the Kaggle original file.*

## Verified PayPal sandbox flow
One real end-to-end run in the PayPal **sandbox** (no real money):

| Step | Result |
|---|---|
| Invoice | `INV2-JCP3-K2T3-VLW6-2ZE5`, $2,000.00 |
| Discount | 2% ($40.00) inside a 10-day window |
| Paid | $1,960.00 with a sandbox Visa, status `PAID` |
| Transaction | `9K007555N0827933D`, `SUCCESS` |

Clients shown in the UI (Northwind, Lumen Labs, ...) are fictional demo data.

## Run it (judges: about 5 minutes)
The agent itself uses only the Python standard library, and talks to the **PayPal sandbox only**
(it refuses `PAYPAL_ENV=live`).

```bash
git clone https://github.com/aryanrsinghsengar/terms-desk && cd terms-desk
cp .env.example .env          # paste a PayPal *sandbox* REST app Client ID + Secret
python -m terms_desk.agent seed      # creates 5 fictional demo DRAFT invoices in your sandbox
python -m terms_desk.agent run       # scores each client, runs the Skeptic, asks you y/N, then acts
python -m terms_desk.agent enforce --today 2099-01-01   # demo: discount window over, unpaid -> full price
python -m terms_desk.agent ledger    # every decision and what it was worth
```

What `run` does per draft invoice:
1. Pulls it from PayPal Invoicing v2 and matches the recipient to the client's payment history
   (`data/demo_history.json`, fictional).
2. Model: probability the client pays inside the window anyway, plus expected days to pay otherwise.
3. Skeptic: approves the discount only if expected value is positive, and prints why.
4. Asks you. On `y` it updates the draft with a 2% `invoice_discount` and a dated note, then sends it.
   Blocked discounts can still be sent at full price. Nothing is sent without your `y`.

`enforce` is meant to run daily (cron). After the window, any unpaid Terms Desk invoice is updated back
to full price; PayPal recomputes the amount from the items, so no stale total is ever sent.
Verified in sandbox on 2026-10-31: a SENT $1,960.00 invoice was restored to $2,000.00 and stayed `SENT`.

Tests (offline, no PayPal calls): `pip install pytest && pytest -q`.
Settings (optional, in `.env`): `DISCOUNT=0.02`, `WINDOW_DAYS=10`, `COST_OF_CAPITAL=0.36`, `P_SHIFT=0.5`.

The web UI in `web/` is the judge-friendly walkthrough of the same flow (live link above). Its client
data is fictional and its PayPal steps replay the verified sandbox run.

The ML backtest (`ml/backtest.py`) needs `pip install -r requirements.txt` and the Kaggle CSV.

## Otari AI layer (Mozilla Otari hackathon, branch `otari`)
Every AI call in Terms Desk goes through [Otari](https://otari.ai), Mozilla.ai's hosted AI gateway
(OpenAI-compatible, `https://otari.ai/api/v1`). **The LLMs never decide**: the Skeptic has already approved or
blocked each discount. Open-weight models then do separate jobs:

| Role | Model via Otari (open weights) | Job |
|---|---|---|
| Explainer | `groq:openai/gpt-oss-120b` -> fallback `gpt-oss-20b` | two plain sentences for the merchant |
| Writer | `groq:openai/gpt-oss-20b` -> fallback `gpt-oss-120b` | the client-facing invoice note (approved discounts only) |
| Guard | `groq:openai/gpt-oss-safeguard-20b` | safety model screens every client note against a written policy (no threats, invented fees, wrong amounts) before a human sees it; fails closed |
| Verifier (opt-in) | `groq:openai/gpt-oss-120b` + `otari_code_execution` | re-derives the EV in Otari's code sandbox; a mismatch with the Skeptic is flagged |

Otari features used (`terms_desk/otari.py`, `terms_desk/explain.py`):
- **Multiple open-weight models in distinct roles** (table above).
- **Model routing and fallbacks**: each role has an ordered model chain; a model that errors (404, 5xx, rate limit,
  empty reply) is skipped and the skip is printed. A role's model can also be an Otari **routing policy** name
  (Routing -> Policies), e.g. `OTARI_EXPLAIN_MODELS=terms-desk-explainer`.
- **Guardrails**: the guard model, plus code-level grounding (any number not computed by the Skeptic, or a flipped
  verdict, is rejected) and deterministic templates on any failure.
- **Budgets / per-client budgets**: every request is tagged with its end client; with an Otari service key and
  `OTARI_PER_CLIENT_BUDGETS=1` it is sent as `user`, so Otari caps spend per client. Budget exhaustion (402/429)
  stops the chain and falls back to templates instead of crashing.
- **Code execution**: `--verify` (needs Otari balance for the sandbox).

```bash
# .env: OTARI_API_KEY=otk_...   (models above are the defaults; override with OTARI_EXPLAIN_MODELS etc.)
python -m terms_desk.agent explain                 # no PayPal needed: 5 demo clients through the full AI layer
python -m terms_desk.agent explain --guard-demo    # also shows the guard blocking a threatening note
python -m terms_desk.agent explain --verify        # also re-derives each EV with Otari code execution
OTARI_EXPLAIN_MODELS="groq:llama-3.3-70b-versatile,groq:openai/gpt-oss-120b" python -m terms_desk.agent explain  # fallback demo
python -m terms_desk.agent run                     # full PayPal sandbox flow, AI invoice note included
```
Tests: `tests/test_explain.py` (offline, Otari mocked): grounding, verdict flips, fallback chain, budget stop,
guard block/pass.

## How this differs
Collections bots chase invoices after they are late. Terms Desk works earlier: it decides the
*terms* before the invoice goes out, and refuses discounts that would only pay clients who were going
to pay on time anyway. A human approves every invoice it sends.

## Built with
Otari (Mozilla.ai AI gateway, `otari` branch), PayPal Invoicing v2, PayPal Agent Toolkit (Python 1.11.0), XGBoost, scikit-learn, AG Grid Community, Inter, Playwright (demo recording), ElevenLabs (voiceover).

## License
MIT
