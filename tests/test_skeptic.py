import math, pytest
from skeptic.engine import (annualized_discount_cost, expected_value, break_even_p_shift,
                            decide, break_even_table)


def test_2_10_net_30_is_37_2_percent():
    assert round(annualized_discount_cost(0.02, 10, 30), 3) == 0.372


def test_annualized_rejects_bad_terms():
    with pytest.raises(ValueError):
        annualized_discount_cost(0.02, 30, 30)


def test_zero_shift_is_pure_giveaway():
    ev, cost, benefit = expected_value(2000, 0.02, 7, 0.24, 0.86, 40, 0.0)
    assert benefit == 0 and math.isclose(cost, 0.02 * 2000 * 0.86)
    assert ev < 0


def test_reliable_client_blocked():
    # 86% pay in window anyway; slow payers only ~10 days later. Time value can't cover 2%.
    dec = decide(2000, 0.02, 7, 0.24, 0.86, 17, p_shift_assumed=0.5)
    assert not dec.approve and dec.break_even_p_shift is None and "Blocked" in dec.reason


def test_chronic_late_client_approved():
    # 10% pay in window; the rest take ~60 days from issue. 53 days at 24% = 3.5% > 2%.
    dec = decide(2000, 0.02, 7, 0.24, 0.10, 60, p_shift_assumed=0.5)
    assert dec.approve and dec.ev > 0
    assert 0 < dec.break_even_p_shift < 0.5


def test_break_even_is_where_ev_crosses_zero():
    args = dict(d=0.02, window_days=7, r=0.24, p0=0.3, days_late_pay=60)
    s = break_even_p_shift(**args)
    ev, _, _ = expected_value(2000, args["d"], 7, 0.24, 0.3, 60, s)
    assert abs(ev) < 1e-9


def test_break_even_none_when_capital_cheap():
    assert break_even_p_shift(0.02, 7, 0.05, 0.3, 60) is None


def test_table_monotone_when_shift_profitable():
    t = break_even_table(2000, 0.02, 7, 0.24, 0.1, 60)
    evs = [row["ev"] for row in t]
    assert len(t) == 11 and evs == sorted(evs)


@pytest.mark.parametrize("bad", [dict(A=0), dict(d=0), dict(d=1), dict(p0=1.2), dict(p_shift=-0.1), dict(r=-1)])
def test_input_validation(bad):
    kw = dict(A=2000, d=0.02, window_days=7, r=0.24, p0=0.5, days_late_pay=40, p_shift=0.5)
    kw.update(bad)
    with pytest.raises(ValueError):
        expected_value(**kw)
