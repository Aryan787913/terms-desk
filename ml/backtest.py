"""Terms Desk backtest: does a per-client on-time model beat the client-history baseline?

Data: "Payment Date Dataset" (Kaggle rajattomar132/payment-date-dataset, CC0, 50,000 rows).
B2B large-retail buyers, mostly 15-day terms. NOT freelancer data.

Leakage rule: every history feature for an invoice uses ONLY that customer's invoices
that had already CLEARED before the invoice's posting date.
Split: train = posted before 2020-01-01, test = posted 2020-01-01 or later (time split).

Usage: python ml/backtest.py path/to/dataset.csv  -> prints metrics, writes ml/results.json
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.calibration import calibration_curve
from xgboost import XGBClassifier

SPLIT = pd.Timestamp("2020-01-01")
PRIOR_N = 5  # pseudo-count shrinking a thin client history toward the global rate


def load(path):
    d = pd.read_csv(path, dtype={"cust_number": str})
    raw = len(d)
    d = d[(d.isOpen == 0) & (d.invoice_currency == "USD")].copy()
    d["posting"] = pd.to_datetime(d.posting_date)
    d["clear"] = pd.to_datetime(d.clear_date)
    d["due"] = pd.to_datetime(d.due_in_date.astype("Int64").astype(str), format="%Y%m%d")
    d["base"] = pd.to_datetime(d.baseline_create_date.astype("Int64").astype(str), format="%Y%m%d")
    d = d.drop_duplicates(subset=["cust_number", "posting", "total_open_amount", "due", "clear"])
    d["term_days"] = (d.due - d.base).dt.days
    d["days_late"] = (d.clear - d.due).dt.days
    d["on_time"] = (d.days_late <= 0).astype(int)
    d = d.sort_values("posting").reset_index(drop=True)
    return d, raw


def add_history(d):
    """Per invoice: stats over the same customer's invoices cleared strictly before posting."""
    n_prev = np.zeros(len(d)); ot_prev = np.zeros(len(d)); late_sum = np.zeros(len(d))
    for _, g in d.groupby("cust_number"):
        h = g.sort_values("clear")
        cl = h.clear.values
        c_ot = np.concatenate([[0], np.cumsum(h.on_time.values)])
        c_late = np.concatenate([[0], np.cumsum(np.clip(h.days_late.values, 0, None))])
        k = np.searchsorted(cl, g.posting.values, side="left")  # cleared strictly before posting
        n_prev[g.index] = k; ot_prev[g.index] = c_ot[k]; late_sum[g.index] = c_late[k]
    d["hist_n"] = n_prev
    d["hist_ontime_raw"] = np.where(n_prev > 0, ot_prev / np.maximum(n_prev, 1), np.nan)
    d["hist_mean_late"] = np.where(n_prev > 0, late_sum / np.maximum(n_prev, 1), np.nan)
    return d


def main(path):
    d, raw = load(path)
    d = add_history(d)
    train, test = d[d.posting < SPLIT].copy(), d[d.posting >= SPLIT].copy()
    g = train.on_time.mean()  # global prior from TRAIN only
    for df in (train, test):
        # Baseline: client's past on-time rate, shrunk toward the global train rate.
        df["baseline_p"] = (df.hist_ontime_raw.fillna(0) * df.hist_n + g * PRIOR_N) / (df.hist_n + PRIOR_N)
        df["log_amt"] = np.log1p(df.total_open_amount)
        df["dow"] = df.posting.dt.day_of_week
    feats = ["baseline_p", "hist_n", "hist_mean_late", "log_amt", "term_days", "dow"]
    model = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, eval_metric="logloss", random_state=42)
    model.fit(train[feats], train.on_time)
    test["model_p"] = model.predict_proba(test[feats])[:, 1]
    # Ablation: drop posting weekday (strong here, likely an artefact of the retail AP batch
    # schedule, not something to promise a freelancer).
    feats_nodow = [f for f in feats if f != "dow"]
    m2 = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                       colsample_bytree=0.8, eval_metric="logloss", random_state=42)
    m2.fit(train[feats_nodow], train.on_time)
    test["model_nodow_p"] = m2.predict_proba(test[feats_nodow])[:, 1]

    y = test.on_time
    seen = test.hist_n > 0
    res = {
        "rows_raw": int(raw), "rows_closed_usd_dedup": int(len(d)),
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "test_rows_with_history": int(seen.sum()),
        "train_ontime_rate": round(float(g), 4), "test_ontime_rate": round(float(y.mean()), 4),
        "share_15_day_terms": round(float((d.term_days == 15).mean()), 4),
        "auc_baseline": round(float(roc_auc_score(y, test.baseline_p)), 4),
        "auc_model": round(float(roc_auc_score(y, test.model_p)), 4),
        "auc_model_no_weekday": round(float(roc_auc_score(y, test.model_nodow_p)), 4),
        "brier_model_no_weekday": round(float(brier_score_loss(y, test.model_nodow_p)), 4),
        "brier_baseline": round(float(brier_score_loss(y, test.baseline_p)), 4),
        "brier_model": round(float(brier_score_loss(y, test.model_p)), 4),
        "auc_baseline_seen_clients": round(float(roc_auc_score(y[seen], test.baseline_p[seen])), 4),
        "auc_model_seen_clients": round(float(roc_auc_score(y[seen], test.model_p[seen])), 4),
        "feature_importance": {f: round(float(v), 4) for f, v in zip(feats, model.feature_importances_)},
    }
    # history buckets (test period), the README's headline table
    b = pd.cut(test.loc[seen, "hist_ontime_raw"], [0, 0.5, 0.9, 1.0001], right=False,
               labels=["<50%", "50-90%", ">=90%"])
    res["test_ontime_by_history_bucket"] = {
        str(k): {"n": int(v.size), "ontime_rate": round(float(v.mean()), 4)}
        for k, v in y[seen].groupby(b, observed=True)}
    for name in ("baseline_p", "model_p"):
        pt, pp = calibration_curve(y, test[name], n_bins=10, strategy="quantile")
        res[f"calibration_{name}"] = [[round(float(a), 3), round(float(c), 3)] for a, c in zip(pp, pt)]
    res["k3_model_beats_baseline_auc"] = res["auc_model"] > res["auc_baseline"]
    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
        for name, lab in (("baseline_p", "client-history baseline"), ("model_p", "XGBoost")):
            c = np.array(res[f"calibration_{name}"]); ax.plot(c[:, 0], c[:, 1], "o-", label=lab)
        ax.set_xlabel("predicted P(on time)"); ax.set_ylabel("observed on-time rate")
        ax.set_title("Calibration, 2020 test invoices"); ax.legend()
        fig.tight_layout(); fig.savefig(Path(__file__).with_name("calibration.png"), dpi=120)
    except Exception as e:  # chart is optional
        print("chart skipped:", e)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/ds.csv")
