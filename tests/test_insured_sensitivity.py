import numpy as np
import pandas as pd
import pytest

from mortality import insured
from mortality import insured_sensitivity as sens


def test_premium_is_the_level_net_premium_of_the_term():
    q = np.full(111, 0.01)
    # constant q = 1%, 4% interest, 10 years: the premium is positive and below the claim rate
    p = sens.premium_per_1000(q, issue_age=40, term=10)
    assert 0 < p < 10
    assert sens.premium_per_1000(q * 2, 40, 10) == pytest.approx(2 * p, rel=0.05)
    # a longer term at a rising rate costs more per year
    rising = 0.0002 * np.exp(0.09 * np.arange(111))
    assert sens.premium_per_1000(rising, 40, 20) > sens.premium_per_1000(rising, 40, 10)


def test_improvement_factor_applies_the_rate_per_year():
    rates = pd.DataFrame(
        {"sex": ["M"] * 111, "age": range(111), "annual_improvement": np.full(111, 0.02)}
    )
    assert sens.improvement_factor(rates, "M", 2.0) == pytest.approx(np.full(111, 0.98**2))
    # a negative rate (mortality projected to rise) is not applied: no credit for it
    worse = rates.assign(annual_improvement=-0.01)
    assert sens.improvement_factor(worse, "M", 2.0) == pytest.approx(np.ones(111))


def test_margin_is_the_adverse_changes_in_quadrature_rounded_up():
    s = pd.DataFrame(
        {
            "sex": ["M"] * 4,
            "issue_age": [40] * 4,
            "term": [20] * 4,
            "adverse": [True, True, False, True],
            "change_vs_base": [
                0.06,
                0.08,
                0.50,
                -0.02,
            ],  # the unflagged and the favourable do not count
        }
    )
    out = sens.margin_table(s)
    assert out["adverse_choices"].iloc[0] == 2
    assert out["quadrature_margin"].iloc[0] == pytest.approx(0.10)
    assert out["recommended_margin"].iloc[0] == pytest.approx(0.10)  # 0.10 already on the 5% grid
    s.loc[1, "change_vs_base"] = 0.09
    assert sens.margin_table(s)["recommended_margin"].iloc[0] == pytest.approx(0.15)


def test_the_scenarios_cover_every_documented_choice():
    choices = {s.choice for s in sens.SCENARIOS}
    assert {
        "What counts as a death",
        "Exposure",
        "Years pooled",
        "Graduation",
        "Old ages meet the population",
    } <= choices
    assert all(
        s.kwargs.keys() <= {"rule", "years", "method", "converge_age", "turnover"}
        for s in sens.SCENARIOS
    )
    assert all(s.kwargs.get("rule", "base") in insured.RULES for s in sens.SCENARIOS)
