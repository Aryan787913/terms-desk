"""The Skeptic: a deterministic expected-value rule for early-payment discounts.

Not AI, on purpose. Every number here is either a user input or a model estimate
the user can see. No discount-response uplift is assumed: p_shift is swept as a
sensitivity, never claimed.

Definitions (one invoice, amount A):
  d        discount fraction offered for paying within `window_days` of issue (e.g. 0.02)
  r        merchant's annual cost of capital (user input, e.g. 0.24)
  p0       P(client pays inside the window anyway, no discount)
  days_late_pay  expected days-from-issue to payment for clients who would NOT pay in window
  p_shift  share of those slower payers who move into the window because of the discount

  P(pay in window | discount) = p0 + (1 - p0) * p_shift
  cost    = d * A * P(pay in window | discount)            # every window payer takes the discount
  benefit = (1 - p0) * p_shift * A * r * (days_late_pay - window_days) / 365
  EV      = benefit - cost
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


def annualized_discount_cost(d: float, window_days: int, net_days: int) -> float:
    """Classic implied annual rate of 'd/window net net_days': d/(1-d) * 365/(net-window)."""
    if not 0 < d < 1:
        raise ValueError("d must be in (0, 1)")
    if net_days <= window_days:
        raise ValueError("net_days must exceed window_days")
    return d / (1 - d) * 365 / (net_days - window_days)


@dataclass(frozen=True)
class Decision:
    approve: bool
    ev: float
    cost: float
    benefit: float
    break_even_p_shift: float | None   # None = no p_shift in [0,1] makes it pay
    reason: str

    def to_dict(self):
        return asdict(self)


def expected_value(A, d, window_days, r, p0, days_late_pay, p_shift):
    _check(A, d, r, p0, p_shift)
    days_gained = max(days_late_pay - window_days, 0)
    p_win = p0 + (1 - p0) * p_shift
    cost = d * A * p_win
    benefit = (1 - p0) * p_shift * A * r * days_gained / 365
    return benefit - cost, cost, benefit


def break_even_p_shift(d, window_days, r, p0, days_late_pay):
    """Smallest p_shift with EV >= 0, or None if no value in [0, 1] works.

    EV(s) = (1-p0) s [r g/365 - d] - d p0, with g = days gained.
    """
    g = max(days_late_pay - window_days, 0)
    per_shift = (1 - p0) * (r * g / 365 - d)
    if per_shift <= 0:
        return 0.0 if p0 == 0 and per_shift == 0 else None
    s = d * p0 / per_shift
    return s if s <= 1 else None


def decide(A, d, window_days, r, p0, days_late_pay, p_shift_assumed) -> Decision:
    """Approve only when EV >= 0 at the merchant's stated p_shift assumption."""
    ev, cost, benefit = expected_value(A, d, window_days, r, p0, days_late_pay, p_shift_assumed)
    be = break_even_p_shift(d, window_days, r, p0, days_late_pay)
    g = max(days_late_pay - window_days, 0)
    if be is None and r * g / 365 <= d:
        reason = (f"Blocked: {d:.0%} for {g} days sooner costs more than your {r:.0%} cost of capital, "
                  f"whoever pays early. Expected giveaway to on-time payers ${d*A*p0:,.0f}.")
    elif be is None:
        reason = (f"Blocked: even if every slow payer sped up, the early cash would not cover the "
                  f"${d*A*p0:,.0f} you'd give to clients who pay on time anyway.")
    elif ev >= 0:
        reason = (f"Approved: EV +${ev:,.0f}. Pays off if at least {be:.0%} of slow payers move "
                  f"into the {window_days}-day window (you assumed {p_shift_assumed:.0%}).")
    else:
        reason = (f"Blocked: EV -${-ev:,.0f}. Needs {be:.0%} of slow payers to shift; you assumed "
                  f"{p_shift_assumed:.0%}. Expected giveaway to on-time payers ${d*A*p0:,.0f}.")
    return Decision(ev >= 0 and be is not None, round(ev, 2), round(cost, 2), round(benefit, 2), be, reason)


def break_even_table(A, d, window_days, r, p0, days_late_pay, steps=11):
    """EV across p_shift = 0..100% for the README / UI sensitivity table."""
    rows = []
    for i in range(steps):
        s = i / (steps - 1)
        ev, cost, benefit = expected_value(A, d, window_days, r, p0, days_late_pay, s)
        rows.append({"p_shift": round(s, 2), "ev": round(ev, 2), "cost": round(cost, 2), "benefit": round(benefit, 2)})
    return rows


def _check(A, d, r, p0, p_shift):
    if A <= 0: raise ValueError("A must be positive")
    if not 0 < d < 1: raise ValueError("d must be in (0, 1)")
    if r < 0: raise ValueError("r must be >= 0")
    for name, v in (("p0", p0), ("p_shift", p_shift)):
        if not 0 <= v <= 1: raise ValueError(f"{name} must be in [0, 1]")
