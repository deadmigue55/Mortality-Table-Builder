"""Tests for life tables and actuarial functions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import lifetable as lt


def gompertz_table(radix=lt.RADIX):
    """A realistic table from ages 0 to 110 with a closing q = 1."""
    age = np.arange(0, lt.OMEGA + 1)
    mx = 0.0003 + 0.00003 * np.exp(0.095 * age)
    mx[0] = 0.008
    qx = mx / (1 + 0.5 * mx)
    qx[0] = mx[0] / (1 + 0.9 * mx[0])
    qx[-1] = 1.0
    ax = lt.average_years_in_death_year(qx, mx)
    return lt.build_life_table(age, qx, ax=ax, terminal_mx=mx[-1], radix=radix), mx


def test_a_three_age_table_matches_the_hand_calculation():
    table = lt.build_life_table([0, 1, 2], [0.5, 0.5, 1.0], terminal_mx=1.0)
    assert table["lx"].tolist() == [100000, 50000, 25000]
    assert table["dx"].tolist() == [50000, 25000, 25000]
    assert table["Lx"].tolist() == [75000, 37500, 25000]
    assert table["Tx"].tolist() == [137500, 62500, 25000]
    assert table["ex"].iloc[0] == pytest.approx(1.375)


def test_the_table_must_close():
    with pytest.raises(ValueError, match="q = 1"):
        lt.build_life_table([0, 1], [0.1, 0.2])


def test_ax_is_recovered_from_m_and_q():
    m = np.array([0.02, 0.05, 0.4])
    for a in (0.1, 0.5, 0.7):
        q = m / (1 + (1 - a) * m)
        assert lt.average_years_in_death_year(q, m) == pytest.approx(a)
    assert lt.average_years_in_death_year([0.0], [0.0])[0] == 0.5


def test_deaths_add_up_and_survivors_fall():
    table, mx = gompertz_table()
    assert table["dx"].sum() == pytest.approx(lt.RADIX)
    assert (np.diff(table["lx"]) < 0).all()
    assert table["Tx"].iloc[0] == pytest.approx(table["Lx"].sum())
    assert table["ex"].iloc[-1] == pytest.approx(1 / mx[-1])  # the open last interval: L = l / m


def test_life_expectancy_is_close_to_the_curtate_expectation():
    table, _ = gompertz_table()
    curtate = table["lx"].iloc[1:].sum() / table["lx"].iloc[0]
    assert table["ex"].iloc[0] == pytest.approx(curtate + 0.5, abs=0.1)


def test_summary_measures_are_ordered_and_plausible():
    table, _ = gompertz_table()
    s = lt.summary(table)
    assert s["e0"] > s["e15"] - 20 and s["e65"] < s["e40"] < s["e15"]
    assert 0 < s["q5_0"] < 0.05 and 0 < s["q45_15"] < 0.5
    assert 0 < s["survive_to_80"] < s["survive_to_65"] < 1
    # half the cohort is dead at the median age: l(median) is 50% of the radix
    ages, share = table["age"].to_numpy(), table["lx"].to_numpy() / lt.RADIX
    assert np.interp(s["median_age_at_death"], ages, share) == pytest.approx(0.5, abs=0.01)
    assert s["median_age_at_death"] > 60
    assert 60 <= s["modal_age_at_death"] <= 100
    assert 0 < s["lifespan_disparity"] < s["e0"]


def test_lifespan_disparity_is_zero_when_everyone_dies_at_the_same_age():
    # everybody survives to 70 and dies during the year at 70 (a = 0.5): no inequality... almost
    age = np.arange(0, 72)
    q = np.zeros(len(age))
    q[70], q[71] = 1.0, 1.0
    table = lt.build_life_table(age, q, terminal_mx=1.0)
    assert lt.lifespan_disparity(table) < 1.0


def test_combine_sexes_mixes_rates_by_weight():
    male = pd.DataFrame({"age": [0, 1], "qx": [0.4, 0.6], "mx": [0.5, 0.8]})
    female = pd.DataFrame({"age": [0, 1], "qx": [0.2, 0.2], "mx": [0.3, 0.3]})
    both = lt.combine_sexes(male, female, [0.5, 0.25])
    assert both["qx"].tolist() == pytest.approx([0.3, 0.3])
    assert both["mx"].tolist() == pytest.approx([0.4, 0.425])


def commutation(interest=0.04):
    table, _ = gompertz_table()
    return table, lt.Commutation.from_table(table, interest)


def test_insurance_and_annuity_are_linked_by_the_discount_rate():
    _, c = commutation()
    x = np.arange(0, 100)
    assert c.whole_life_insurance(x) == pytest.approx(1 - c.discount_rate * c.annuity_due(x))


def test_the_premium_pays_for_the_insurance():
    _, c = commutation()
    x = np.arange(20, 70, 5)
    assert c.whole_life_premium(x) * c.annuity_due(x) == pytest.approx(c.whole_life_insurance(x))
    assert c.term_premium(x, 20) * c.temporary_annuity_due(x, 20) == pytest.approx(
        c.term_insurance(x, 20)
    )


def test_decompositions_hold():
    _, c = commutation()
    x, n = np.arange(25, 66, 10), 15
    assert c.whole_life_insurance(x) == pytest.approx(
        c.term_insurance(x, n) + c.deferred_insurance(x, n)
    )
    assert c.annuity_due(x) == pytest.approx(
        c.temporary_annuity_due(x, n) + c.deferred_annuity_due(x, n)
    )
    assert c.deferred_annuity_due(x, n) == pytest.approx(
        c.pure_endowment(x, n) * c.annuity_due(x + n)
    )
    assert c.endowment_insurance(x, n) == pytest.approx(
        c.term_insurance(x, n) + c.pure_endowment(x, n)
    )
    assert c.annuity_immediate(x) == pytest.approx(c.annuity_due(x) - 1)


def test_at_zero_interest_the_annuity_counts_expected_payments():
    table, c = commutation(0.0)
    x = 40
    expected_payments = (
        table.loc[table["age"] >= x, "lx"].sum() / table.loc[table["age"] == x, "lx"].iloc[0]
    )
    assert float(c.annuity_due(x)) == pytest.approx(expected_payments)
    assert float(c.whole_life_insurance(x)) == pytest.approx(1.0)  # death is certain


def test_values_move_the_right_way_with_age_and_interest():
    table, c4 = commutation(0.04)
    c2 = lt.Commutation.from_table(table, 0.02)
    assert c2.annuity_due(65) > c4.annuity_due(65)  # lower interest, dearer annuity
    assert c2.whole_life_insurance(40) > c4.whole_life_insurance(40)
    assert float(c4.whole_life_insurance(30)) < float(c4.whole_life_insurance(60))
    assert float(c4.annuity_due(30)) > float(c4.annuity_due(60))
    assert float(c4.pure_endowment(40, 10)) < 1


def test_ages_beyond_the_table_pay_nothing_and_before_it_are_undefined():
    _, c = commutation()
    assert float(c.pure_endowment(105, 20)) == 0.0
    assert np.isnan(float(c.annuity_due(-5)))
    assert float(c.term_insurance(100, 30)) == pytest.approx(float(c.whole_life_insurance(100)))


def test_reserve_starts_at_zero_and_is_positive_afterwards():
    _, c = commutation()
    reserve = c.whole_life_reserve(40, np.arange(0, 40, 5))
    assert reserve[0] == pytest.approx(0.0, abs=1e-12)
    assert (np.diff(reserve) > 0).all()


def test_monthly_annuity_is_a_little_below_the_annual_one():
    _, c = commutation()
    assert float(c.annuity_due_monthly(65)) == pytest.approx(float(c.annuity_due(65)) - 11 / 24)
    assert c.udd_factor(12) > 1.0


def test_a_table_can_start_above_age_zero():
    age = np.arange(12, 101)
    q = np.minimum(0.0004 * np.exp(0.09 * (age - 12)), 1.0)
    q[-1] = 1.0
    table = lt.build_life_table(age, q)
    c = lt.Commutation.from_table(table, 0.04)
    assert table["lx"].iloc[0] == lt.RADIX
    assert 0 < float(c.whole_life_insurance(40)) < 1
    assert float(c.annuity_due(40)) == pytest.approx(
        (1 - float(c.whole_life_insurance(40))) / c.discount_rate
    )
    assert np.isnan(float(c.annuity_due(5)))


def test_values_table_has_every_age_and_consistent_columns():
    table, c = commutation()
    values = c.values(term=20)
    assert len(values) == len(table)
    ok = values.dropna()
    young = ok[ok["age"] < 90]
    assert (young["P_endowment_20"] > young["P_term_20"]).all()
    assert (ok["P_endowment_20"] >= ok["P_term_20"] - 1e-12).all()
    assert (ok["a_due_monthly"] < ok["a_due"]).all()
    assert {"A_whole_life", "P_whole_life", "E_20"} <= set(values.columns)
