"""On-time probability per client, from the payment history a merchant already has.

This is the client-history model from ml/backtest.py: past on-time rate, shrunk toward the
global rate with weight K (Beta prior). K=0 gives the raw rate. Clients are matched by
recipient email. The demo history in data/demo_history.json is fictional.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClientScore:
    name: str
    p0: float            # P(pays inside the window without a discount)
    days_late_pay: float # expected days from issue to payment when not inside the window
    n: int
    on_time: int

    @property
    def history_text(self):
        return f"paid {self.on_time} of {self.n} past invoices inside the window"


class HistoryModel:
    def __init__(self, path: Path, window_days: int, k: float = 0.0):
        data = json.loads(Path(path).read_text())
        self.window, self.k = window_days, k
        self.clients = {c["email"].lower(): c for c in data["clients"]}
        all_days = [d for c in data["clients"] for d in c["days_to_pay"]]
        self.global_rate = sum(d <= window_days for d in all_days) / max(len(all_days), 1)

    def score(self, email: str) -> ClientScore | None:
        c = self.clients.get((email or "").lower())
        if not c:
            return None
        days = c["days_to_pay"]
        on = sum(d <= self.window for d in days)
        late = [d for d in days if d > self.window] or [self.window]
        p0 = (on + self.k * self.global_rate) / (len(days) + self.k)
        return ClientScore(c["name"], round(p0, 4), round(sum(late) / len(late)), len(days), on)
