# Terms Desk

**Discounts are expensive money.** Terms Desk decides, per PayPal invoice, whether an early-payment
discount earns you cash or just hands margin to clients who'd pay on time anyway. It acts through
PayPal (Invoicing v2 conditional rules) only after you approve.

> Status: hackathon build in progress (PayPal AI Hackathon, 2026). Sections marked TODO are not done yet.

## How it works
1. **Predict**: per-client probability of paying on time, from history a PayPal merchant already has.
2. **Skeptic** (deterministic, not AI): expected value of a discount. Blocks any discount that loses money.
3. **Approve**: proposals land in an approval queue; nothing is sent until you click approve.
4. **Act**: `create_invoice` -> `create_conditional_rules_for_invoice` (EARLY_PAYMENT_DISCOUNT) -> `send_invoice`.
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

## Run it
```bash
cp .env.example .env    # add sandbox REST app creds
pip install -r requirements.txt
pytest -q
python spike/paypal_spike.py token
```

## How this differs
TODO: collections bots (tidewater, owed, chaser, ...) chase late invoices. Terms Desk decides the
*terms* before the invoice goes out, and is the only entry we found using PayPal conditional rules.

## Built with
PayPal Invoicing v2, PayPal Agent Toolkit (Python 1.11.0), XGBoost, scikit-learn, AG Grid (TODO), Gemini (TODO).

## License
MIT
