"""Numerical proof of the formulas in docs/handbook/08-pricing.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mortality import experience as ex
from mortality import pricing as pr
from mortality.lifetable import Commutation, build_life_table

ROOT = Path(__file__).resolve().parents[1]
AGES = np.arange(0, 111)
Q_ALL = np.clip(0.0004 * np.exp(0.095 * AGES), 0, 1)
Q_ALL[-1] = 1.0
TABLE = Commutation.from_table(build_life_table(AGES, Q_ALL), 0.04)
BARE = pr.Assumptions(
    acquisition_pct=0.0,
    acquisition_fixed=0.0,
    maintenance=0.0,
    commission_first=0.0,
    commission_renewal=0.0,
    claim_expense=0.0,
    lapse=(0.0,),
    investment_return=0.04,
)  # no expenses, no lapses, earning exactly the valuation interest


# ── 8.1: the net premium and the reserve ─────────────────────────────────────


def test_net_premium_is_the_term_premium_of_chapter_5():
    """(8.1): P = S sum v^(t+1) tp q_t / sum v^t tp, the same number as A1 / a-due."""
    x, n = 40, 20
    q = Q_ALL[x : x + n]
    premium = pr.net_premium(q, 0.04, 1.0)
    assert premium == pytest.approx(TABLE.term_premium(x, n), rel=1e-12)
    assert premium == pytest.approx(ex.term_net_premium(q[None, :], 0.04)[0], rel=1e-12)
    assert pr.net_premium(q, 0.04, 1_000_000) == pytest.approx(1e6 * premium)  # linear in S


def test_the_reserve_recursion_equals_the_prospective_reserve():
    """(8.2), (8.3): V(t) = ((V(t-1) + P)(1 + i) - q S) / (1 - q), and V(t) = S A1 - P a-due."""
    x, n, s, i = 40, 20, 1_000_000.0, 0.04
    q = Q_ALL[x : x + n]
    reserve = pr.net_premium_reserves(q, i, s)
    premium = pr.net_premium(q, i, s)
    for t in (1, 5, 10, 19):
        prospective = s * TABLE.term_insurance(
            x + t, n - t
        ) - premium * TABLE.temporary_annuity_due(x + t, n - t)
        assert reserve[t - 1] == pytest.approx(prospective, rel=1e-9, abs=1e-6)
    assert reserve[-1] == 0.0
    # the recursion itself, run without the final reset, closes at zero: the premium is exact
    raw = 0.0
    for qt in q:
        raw = ((raw + premium) * (1 + i) - qt * s) / (1 - qt)
    assert raw == pytest.approx(0.0, abs=1e-6)
    assert (reserve[:-1] > 0).all()  # level term cover: positive after year 0


# ── 8.2 and 8.3: the profit test and its two identities ──────────────────────


def test_a_bare_policy_priced_at_the_net_premium_earns_exactly_nothing():
    """(8.9): with no expenses or lapses and i at the valuation rate, profit is zero each year."""
    q = Q_ALL[40:60]
    premium = pr.net_premium(q, 0.04, BARE.sum_assured)
    test = pr.profit_test(q, premium, BARE)
    assert test["profit_per_policy"].to_numpy() == pytest.approx(np.zeros(20), abs=1e-6)


def test_the_zero_profit_example_by_hand():
    """Section 8.8: S = 100, q = (0.1, 0.2), no interest: P = 14.737, V = (5.263, 0), profits 0."""
    a = pr.Assumptions(
        sum_assured=100.0, acquisition_pct=0.0, acquisition_fixed=0.0, maintenance=0.0,
        commission_first=0.0, commission_renewal=0.0, claim_expense=0.0, lapse=(0.0,),
        investment_return=0.0, valuation_interest=0.0,
    )  # fmt: skip
    q = np.array([0.1, 0.2])
    premium = pr.net_premium(q, 0.0, 100.0)
    assert premium == pytest.approx(28 / 1.9) and round(premium, 3) == 14.737
    reserve = pr.net_premium_reserves(q, 0.0, 100.0)
    assert reserve.tolist() == pytest.approx([(premium - 10) / 0.9, 0.0])
    assert round(reserve[0], 3) == 5.263
    assert pr.profit_test(q, premium, a)["profit_per_policy"].to_numpy() == pytest.approx(
        [0.0, 0.0], abs=1e-9
    )


def test_the_value_of_the_profits_at_the_earned_rate_is_minus_the_best_estimate_liability():
    """(8.10): the statutory reserve moves profit in time but cannot change its value at i."""
    a = pr.Assumptions()
    q = Q_ALL[40:60]
    premium = pr.solve_premium(q, a)
    for q_val in (q, Q_ALL[40:60] * 1.3, Q_ALL[40:60] * 0.7):  # any valuation basis
        test = pr.profit_test(q, premium, a, q_valuation=q_val)
        t = np.arange(1, 21)
        value = (test["profit_issued"].to_numpy() * (1 + a.investment_return) ** -t).sum()
        assert value == pytest.approx(-pr.best_estimate_liability(q, premium, a)[0], rel=1e-9)


def test_npv_is_affine_in_the_premium_so_the_solved_premium_has_a_closed_form():
    """(8.8): NPV(P) = a + b P; the bisection of solve_premium finds P* = -a / b."""
    a, q = pr.Assumptions(), Q_ALL[40:60]

    def npv(premium: float) -> float:
        return pr.summarise(pr.profit_test(q, premium, a), a.hurdle)["npv"]

    p0, p1, p2 = 1000.0, 2000.0, 5000.0
    slope = (npv(p1) - npv(p0)) / (p1 - p0)
    assert npv(p2) == pytest.approx(npv(p0) + slope * (p2 - p0), rel=1e-9)  # a straight line
    closed_form = p0 - npv(p0) / slope
    solved = pr.solve_premium(q, a)
    assert solved == pytest.approx(closed_form, rel=1e-9)
    summary = pr.summarise(pr.profit_test(q, solved, a), a.hurdle)
    assert summary["npv"] == pytest.approx(0.0, abs=1e-4)
    assert summary["irr"] == pytest.approx(
        a.hurdle, abs=1e-9
    )  # zero NPV at the hurdle is IRR = hurdle


def test_irr_by_hand_including_a_stream_with_two_roots():
    """(8.7): -100 + 60/(1+r) + 60/(1+r)^2 = 0 gives r = 13.07%; two sign changes give two roots."""
    x = (-60 + np.sqrt(60**2 + 4 * 60 * 100)) / (2 * 60)  # 1 / (1 + r) from 60 x^2 + 60 x - 100 = 0
    assert pr.irr(np.array([-100.0, 60.0, 60.0])) == pytest.approx(1 / x - 1)
    assert round(pr.irr(np.array([-100.0, 60.0, 60.0])), 4) == 0.1307
    two = np.array([-100.0, 230.0, -132.0])  # roots at exactly 10% and 20%
    assert pr.irr(two, near=0.10) == pytest.approx(0.10, abs=1e-9)
    assert pr.irr(two, near=0.20) == pytest.approx(0.20, abs=1e-9)
    assert np.isnan(pr.irr(np.array([100.0, 50.0, 20.0])))  # never negative: no rate exists


def test_margin_is_npv_over_the_value_of_the_premiums_paid_at_the_start_of_each_year():
    """(8.6): margin = NPV / sum(premium_issued x (1 + h)^-(t-1))."""
    a, q = pr.Assumptions(), Q_ALL[40:60]
    test = pr.profit_test(q, 2500.0, a)
    s = pr.summarise(test, a.hurdle)
    t = np.arange(1, 21)
    pv_premium = (test["premium_issued"].to_numpy() * (1 + a.hurdle) ** -(t - 1)).sum()
    assert s["pv_premium"] == pytest.approx(pv_premium)
    assert s["margin"] == pytest.approx(s["npv"] / pv_premium)
    in_force = np.concatenate([[1.0], np.cumprod((1 - q) * (1 - a.lapse_path(20)))[:-1]])
    assert test["in_force_start"].to_numpy() == pytest.approx(in_force)  # (8.5)
    assert s["year_1_profit"] == pytest.approx(test["profit_issued"].iloc[0])


# ── 8.4: the best-estimate liability ─────────────────────────────────────────


def test_best_estimate_liability_toy_example_by_hand():
    """(8.11): two years, S = 1000, premium 20, q = (0.01, 0.02), w = (0.1, 0.05), i = 5%."""
    a = pr.Assumptions(
        sum_assured=1000.0,
        acquisition_pct=0.0,
        acquisition_fixed=0.0,
        maintenance=0.0,
        commission_first=0.0,
        commission_renewal=0.0,
        claim_expense=0.0,
        lapse=(0.1, 0.05),
        investment_return=0.05,
    )
    q = np.array([0.01, 0.02])
    bel = pr.best_estimate_liability(q, 20.0, a)
    bel_1 = -20 + 0.02 * 1000 / 1.05  # last year: premium in, claim out
    bel_0 = -20 + (0.01 * 1000 + 0.99 * 0.9 * bel_1) / 1.05
    assert bel.tolist() == pytest.approx([bel_0, bel_1])
    assert (round(bel_0, 4), round(bel_1, 4)) == (-11.2844, -0.9524)


# ── 8.5: the mortality cushion ───────────────────────────────────────────────


def test_the_mortality_cushion_is_the_multiplier_that_zeroes_the_lifetime_profit():
    """(8.12): at the cushion the undiscounted profit is zero; below it the product makes money."""
    a, q = pr.Assumptions(), Q_ALL[40:60]
    premium = pr.solve_premium(q, a)
    cushion = pr.mortality_cushion(q, premium, a, q_valuation=q)
    assert 1.0 < cushion < 1.2
    at = pr.profit_test(np.clip(q * cushion, 0, 0.999999), premium, a, q_valuation=q)
    assert at["profit_issued"].sum() == pytest.approx(0.0, abs=1e-3)
    below = pr.profit_test(q * 0.95 * cushion, premium, a, q_valuation=q)
    above = pr.profit_test(q * 1.05 * cushion, premium, a, q_valuation=q)
    assert below["profit_issued"].sum() > 0 > above["profit_issued"].sum()


# ── 8.6: scenarios ───────────────────────────────────────────────────────────


def test_a_pandemic_shock_touches_one_year_of_claims_and_nothing_else():
    """Section 8.6: shock {2: 1.5} multiplies year 2's mortality only; reserves do not move."""
    a, q = pr.Assumptions(), Q_ALL[40:60]
    premium = pr.solve_premium(q, a)
    base = pr.profit_test(q, premium, a)
    hit = pr.profit_test(q, premium, a, shock={2: 1.5})
    assert hit["claims"].iloc[1] == pytest.approx(1.5 * base["claims"].iloc[1])
    assert hit["claims"].drop(index=1).to_numpy() == pytest.approx(
        base["claims"].drop(index=1).to_numpy()
    )
    assert hit["reserve_end"].to_numpy() == pytest.approx(base["reserve_end"].to_numpy())
    assert hit["profit_issued"].sum() < base["profit_issued"].sum()
    grid = pr.scenario_grid(q, a, premium).set_index("scenario")
    assert grid.loc["base case", "npv"] == pytest.approx(0.0, abs=1e-4)
    npv = grid["npv"]
    assert npv["mortality -20%"] > npv["mortality -10%"] > 0 > npv["mortality +10%"]
    assert npv["mortality +10%"] > npv["mortality +20%"]


def test_mortality_paths_scale_by_a_margin_and_are_clipped_to_probabilities():
    """(8.13): the insured prudent basis is the best estimate times (1 + margin) in every year."""
    best = pr.q_path(Q_ALL, 40, 20)
    prudent = pr.q_path(Q_ALL, 40, 20, np.full(20, 1.15))
    assert prudent == pytest.approx(1.15 * best)
    assert pr.q_path(Q_ALL, 105, 20).max() <= 0.999999
    assert pr.q_path(Q_ALL, 40, 3, np.array([0.5, 1.0, 2.0])) == pytest.approx(
        Q_ALL[40:43] * np.array([0.5, 1.0, 2.0])
    )


# ── The numbers quoted in the chapter come from the shipped database ─────────


@pytest.fixture(scope="module")
def demo():
    path = ROOT / "app" / "data" / "demo.sqlite"
    if not path.exists():
        pytest.skip("demo database not built")
    con = sqlite3.connect(path)
    yield con
    con.close()


def test_chapter_numbers_match_the_database(demo):
    """Section 8.9: premiums, adequacy, sensitivities, reserves, the year-5 split, insured basis."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    prem = q("SELECT * FROM pricing_premiums WHERE term = 20 AND sex = 'M'").set_index("issue_age")
    assert prem.loc[[30, 40, 50, 60], "net_premium_per_1000"].round(2).tolist() == [
        0.97,
        1.74,
        3.72,
        9.44,
    ]
    assert prem.loc[[30, 40, 50, 60], "gross_premium_per_1000"].round(2).tolist() == [
        1.54,
        2.32,
        4.30,
        9.93,
    ]
    assert (prem.loc[[30, 40, 50, 60], "loading_over_net"] * 100).round().tolist() == [
        58,
        33,
        16,
        5,
    ]
    assert prem.loc[[30, 40, 50, 60], "year_1_profit"].round().tolist() == [
        -1463,
        -2009,
        -3412,
        -7460,
    ]
    assert (prem["irr"].round(6) == 0.1).all()  # every premium is solved for the 10% hurdle
    women = q("SELECT * FROM pricing_premiums WHERE term = 20 AND sex = 'F'").set_index("issue_age")
    assert (women["gross_premium_per_1000"] - prem["gross_premium_per_1000"]).abs().max() < 1e-9

    adequacy = q("SELECT * FROM pricing_adequacy")
    margin = adequacy.pivot_table(index="basis", columns=["sex", "issue_age"], values="margin")
    pct = lambda basis, sex: (margin.loc[basis, sex].loc[[30, 40, 50]] * 100).round(1).tolist()  # noqa: E731
    assert pct("experience", "M") == [-2.2, 0.4, 4.4] and pct("experience", "F") == [
        15.0,
        18.8,
        23.1,
    ]
    assert pct("improving", "M") == [3.9, 4.6, 4.3] and pct("cnsf_p995", "M") == [
        -26.2,
        -29.3,
        -31.6,
    ]
    assert pct("population", "F") == [-21.1, -44.4, -65.6]
    assert pct("insured", "M")[1] == 30.0 and pct("insured", "F")[1] == 46.1
    cushion = adequacy[adequacy["basis"] == "cnsf"]["mortality_cushion"]
    assert cushion.min() > 1.07 and cushion.max() < 1.11
    pop = adequacy[(adequacy["basis"] == "population") & (adequacy["issue_age"] == 40)]
    assert pop.set_index("sex")["mortality_cushion"].round(2).to_dict() == {"F": 0.57, "M": 0.28}
    assert pop["irr"].isna().all()  # the policy never recovers its first-year loss

    sens = q("SELECT * FROM pricing_sensitivity WHERE sex = 'M'").set_index("scenario")
    assert (sens["margin"] * 100).round(1).to_dict()["mortality -20%"] == 11.6
    assert sens.loc["mortality -20%", "irr"] == pytest.approx(0.257, abs=0.001)
    assert sens.loc["pandemic: year 2 mortality x2", "irr"] == pytest.approx(0.035, abs=0.001)
    assert (sens.loc["pandemic: year 2 mortality x2", "irr_change"] * 100) == pytest.approx(
        -6.5, abs=0.05
    )
    assert sens.loc[["lapse +25%", "lapse -25%"], "margin"].abs().max() < 0.005
    assert sens.loc[["mortality +20%", "mortality +10%"], "irr"].isna().all()

    res = q("SELECT * FROM pricing_reserves WHERE sex = 'M'").set_index("policy_year")
    assert res.loc[[1, 4, 10, 15, 20], "statutory_reserve_end"].round().tolist() == [
        776,
        2951,
        5957,
        5623,
        0,
    ]
    assert res.loc[[1, 4, 10, 15, 20], "best_estimate_end"].round().tolist() == [
        -2230,
        6,
        4034,
        5015,
        0,
    ]

    test = q("SELECT * FROM pricing_profit_test WHERE sex = 'M'").set_index("policy_year")
    assert test["profit_issued"].cumsum().gt(0).idxmax() == 9  # undiscounted payback in year 9
    year5 = test.loc[5]
    share = lambda column: year5[column] / year5["premium"]  # noqa: E731
    reserve_added = (
        year5["reserve_kept"] - test.loc[4, "reserve_end"] - year5["interest"]
    ) / year5["premium"]
    assert [
        round(100 * share(c)) for c in ("claims", "expenses", "commission", "profit_per_policy")
    ] == [55, 13, 5, 16]
    assert round(100 * reserve_added) == 11

    first = test.loc[1]  # section 8.8: the first year of the man of 40, line by line
    assert round(first["premium"], 2) == 2316.41
    assert first["commission"] == pytest.approx(0.40 * first["premium"])
    assert first["expenses"] == pytest.approx(0.35 * first["premium"] + 600 + 250)
    assert round(first["claims"] / 1_001_500, 6) == 0.001033
    held = first["premium"] - first["commission"] - first["expenses"]
    assert (round(held, 2), round(held * 0.05, 2)) == (-270.90, -13.54)
    assert held * 1.05 - first["claims"] - first["reserve_kept"] == pytest.approx(
        first["profit_per_policy"]
    )
    assert (
        round(first["reserve_kept"], 2) == 689.97
        and round(first["profit_per_policy"], 2) == -2008.97
    )
    assert round(-first["profit_per_policy"] / first["premium"], 2) == 0.87

    insured = q("SELECT * FROM pricing_insured WHERE term = 20").set_index(["sex", "issue_age"])
    rows = [("M", 30), ("M", 40), ("M", 50), ("F", 30), ("F", 40), ("F", 50)]
    assert [round(insured.loc[r, "gross_premium_per_1000"], 2) for r in rows] == [
        1.13,
        1.57,
        2.86,
        0.77,
        1.04,
        1.83,
    ]
    assert [round(insured.loc[r, "saving_vs_cnsf"] * 100) for r in rows] == [27, 32, 33, 50, 55, 57]
    assert [
        round(insured.loc[r, "irr_best_estimate"] * 100, 1) for r in (("M", 40), ("F", 40))
    ] == [14.6, 11.7]
