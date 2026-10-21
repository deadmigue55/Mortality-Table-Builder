"""Tests for the profit test, reserves and premium solving."""

from __future__ import annotations

import numpy as np
import pytest

from mortality import pricing as pr


def gompertz_q(n=110):
    age = np.arange(n + 1)
    q = np.minimum(0.0004 + 0.00003 * np.exp(0.095 * age), 1.0)
    q[-1] = 1.0
    return q


def bare(**kw):
    """Assumptions with no expenses, commission or lapses and one rate of interest."""
    base = dict(acquisition_pct=0.0, acquisition_fixed=0.0, maintenance=0.0, commission_first=0.0,
                commission_renewal=0.0, claim_expense=0.0, lapse=(0.0,), investment_return=0.04,
                valuation_interest=0.04)  # fmt: skip
    base.update(kw)
    return pr.Assumptions(**base)


def test_net_premium_by_hand():
    q = np.array([0.1, 0.1])
    assert pr.net_premium(q, 0.0, 1.0) == pytest.approx(0.1)  # claims 0.19 over annuity 1.9
    expected = (0.1 / 1.25 + 0.9 * 0.1 / 1.25**2) / (1 + 0.9 / 1.25)
    assert pr.net_premium(q, 0.25, 1.0) == pytest.approx(expected)


def test_reserves_start_and_end_at_zero_and_match_the_prospective_formula():
    q = pr.q_path(gompertz_q(), 40, 20)
    i, s = 0.04, 1_000_000.0
    v = pr.net_premium_reserves(q, i, s)
    assert v[-1] == 0.0 and (v[:-1] > 0).all()
    p = pr.net_premium(q, i, s)
    for t in (1, 5, 12):  # prospective reserve: future claims minus future premiums
        rest = q[t:]
        surv = np.concatenate([[1.0], np.cumprod(1.0 - rest[:-1])])
        k = np.arange(len(rest))
        claims = (s * surv * rest * (1 + i) ** -(k + 1.0)).sum()
        premiums = (p * surv * (1 + i) ** -k.astype(float)).sum()
        assert v[t - 1] == pytest.approx(claims - premiums, rel=1e-9)


def test_with_no_expenses_or_lapses_the_net_premium_earns_exactly_nothing():
    """The central identity of life insurance mathematics: on the valuation basis, at the
    valuation interest, the net premium reserve is exactly what is needed, so profit is zero
    in every year. Any error in the cash-flow mechanics shows up here."""
    a = bare()
    q = pr.q_path(gompertz_q(), 35, 25)
    p = pr.net_premium(q, a.valuation_interest, a.sum_assured)
    test = pr.profit_test(q, p, a)
    assert np.abs(test["profit_per_policy"]).max() < 1e-7
    assert np.abs(test["profit_issued"]).max() < 1e-7


def test_profit_is_positive_when_mortality_is_lighter_than_priced_and_negative_when_heavier():
    a = bare()
    q = pr.q_path(gompertz_q(), 40, 20)
    p = pr.net_premium(q, 0.04, a.sum_assured)
    light = pr.profit_test(q * 0.8, p, a, q_valuation=q)["profit_issued"].sum()
    heavy = pr.profit_test(q * 1.2, p, a, q_valuation=q)["profit_issued"].sum()
    assert light > 0 > heavy


def test_a_pandemic_year_hits_that_years_claims_only():
    a = bare()
    q = pr.q_path(gompertz_q(), 40, 10)
    base = pr.profit_test(q, 1000.0, a)
    shocked = pr.profit_test(q, 1000.0, a, shock={3: 2.0})
    assert shocked["claims"].iloc[2] == pytest.approx(2 * base["claims"].iloc[2])
    assert shocked["claims"].drop(2).to_numpy() == pytest.approx(base["claims"].drop(2).to_numpy())
    assert shocked["profit_issued"].sum() < base["profit_issued"].sum()


def test_in_force_falls_with_deaths_and_lapses():
    a = pr.Assumptions()
    q = pr.q_path(gompertz_q(), 40, 10)
    t = pr.profit_test(q, 3000.0, a)
    assert t["in_force_start"].iloc[0] == 1.0 and (np.diff(t["in_force_start"]) < 0).all()
    assert t["in_force_start"].iloc[1] == pytest.approx((1 - q[0]) * (1 - 0.11))
    more = pr.profit_test(q, 3000.0, a, lapse_scale=2.0)
    assert more["in_force_start"].iloc[5] < t["in_force_start"].iloc[5]


def test_acquisition_costs_make_year_one_a_loss():
    a = pr.Assumptions()
    q = pr.q_path(gompertz_q(), 40, 20)
    p = pr.solve_premium(q, a)
    t = pr.profit_test(q, p, a)
    assert t["profit_issued"].iloc[0] < 0 < t["profit_issued"].iloc[1:].sum()
    s = pr.summarise(t, a.hurdle)
    assert s["payback_year"] > 2 and s["year_1_profit"] < 0


def test_irr_of_known_cash_flows():
    assert pr.irr(np.array([-100.0, 60.0, 60.0])) == pytest.approx(0.1307, abs=1e-4)
    assert np.isnan(pr.irr(np.array([10.0, 20.0])))  # never negative: no rate
    assert np.isnan(pr.irr(np.array([-10.0, -20.0])))


def test_the_solved_premium_earns_the_target_return():
    a = pr.Assumptions()
    q = pr.q_path(gompertz_q(), 40, 20)
    for target in (0.08, 0.10, 0.15):
        p = pr.solve_premium(q, a, target_irr=target)
        s = pr.summarise(pr.profit_test(q, p, a), target)
        assert s["npv"] == pytest.approx(0.0, abs=1.0)
        assert s["irr"] == pytest.approx(target, abs=2e-4)


def test_the_premium_rises_with_age_mortality_and_the_required_return():
    a = pr.Assumptions()
    table = gompertz_q()
    p30 = pr.solve_premium(pr.q_path(table, 30, 20), a)
    p50 = pr.solve_premium(pr.q_path(table, 50, 20), a)
    assert p50 > 2 * p30
    heavy = pr.solve_premium(pr.q_path(table, 40, 20) * 1.3, a)
    assert heavy > pr.solve_premium(pr.q_path(table, 40, 20), a)
    assert pr.solve_premium(pr.q_path(table, 40, 20), a, target_irr=0.15) > pr.solve_premium(
        pr.q_path(table, 40, 20), a, target_irr=0.08
    )


def test_the_scenario_grid_moves_the_margin_the_right_way():
    a = pr.Assumptions()
    q = pr.q_path(gompertz_q(), 40, 20)
    p = pr.solve_premium(q, a)
    g = pr.scenario_grid(q, a, p).set_index("scenario")
    assert g.loc["base case", "irr"] == pytest.approx(a.hurdle, abs=2e-4)
    assert g.loc["base case", "irr_change"] == 0 and abs(g.loc["base case", "margin"]) < 1e-6
    m = g["margin"]
    assert m["mortality +20%"] < m["mortality +10%"] < 0 < m["mortality -10%"] < m["mortality -20%"]
    assert m["investment return -1 pt"] < 0 < m["investment return +1 pt"]
    assert m["expenses +10%"] < 0 < m["expenses -10%"]
    assert m["pandemic: year 2 mortality x2"] < m["pandemic: year 2 mortality x1.5"] < 0
    # the IRR is undefined when no year ever makes a profit: heavy mortality is that case
    assert np.isnan(g.loc["mortality +20%", "irr"]) or g.loc["mortality +20%", "irr"] < a.hurdle
    assert g.loc["mortality -20%", "irr"] > a.hurdle


def test_this_term_product_is_supported_by_lapses():
    """Lapsing policies release their reserve (there is no surrender value), so fewer lapses
    mean less profit: a property of the product design, shown by the grid."""
    a = pr.Assumptions()
    q = pr.q_path(gompertz_q(), 40, 20)
    p = pr.solve_premium(q, a)
    g = pr.scenario_grid(q, a, p).set_index("scenario")
    assert g.loc["lapse -25%", "npv"] < 0 < g.loc["lapse +25%", "npv"]


def test_q_path_applies_age_and_multiplier():
    table = gompertz_q()
    path = pr.q_path(table, 40, 3, multiplier=np.array([0.5, 1.0, 2.0]))
    assert path == pytest.approx([table[40] * 0.5, table[41], table[42] * 2.0])
    assert pr.q_path(table, 108, 5)[-1] <= 1.0  # ages past the table are clipped, not an error
    assert pr.with_assumptions(pr.Assumptions(), hurdle=0.12).hurdle == 0.12
