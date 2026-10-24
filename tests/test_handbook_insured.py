"""Numerical proof of the formulas in docs/handbook/11-insured-lives.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import optimize, special

from mortality import insured, insured_analysis, insured_sensitivity, pricing

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.filterwarnings(
    "ignore:Perfect separation"
)  # exact data are fitted exactly
SPRAIN = "LUXACION, ESGUINCE Y TORCEDURA DE ARTICULACIONES Y LIGAMENTOS DEL TOBILLO"


# ── 11.1: deaths, exposure and the three traps ───────────────────────────────


def claims_frame() -> pd.DataFrame:
    """Rows of one year: known deaths, a cancellation, a ledger row, a rider and a maturity."""
    rows = [
        # year, coverage, age, sex, claims, amount, cause
        (2023, "Fallecimiento", 40, "M", 10.0, 1_000_000.0, "INFARTO AGUDO DEL MIOCARDIO"),
        (2023, "Fallecimiento", 40, "M", 4.0, 500_000.0, "TUMOR MALIGNO DEL PULMON"),
        (2023, "Fallecimiento", 40, "F", 6.0, 800_000.0, "NEUMONIA"),
        (2023, "Fallecimiento", 40, "M", 3.0, -200_000.0, "NEUMONIA"),  # a cancelled claim
        (2023, "Fallecimiento", np.nan, np.nan, 5.0, 300_000.0, "NEUMONIA"),  # ledger: positive
        (2023, "Fallecimiento", np.nan, np.nan, 7.0, -100_000.0, "NEUMONIA"),  # ledger: negative
        (2023, "Fallecimiento", 65, "M", 8.0, 2_000_000.0, SPRAIN),  # a maturity, not a death
        (2023, "Gastos funerarios", 40, "M", 9.0, 50_000.0, "NEUMONIA"),  # a rider, same death
    ]
    return pd.DataFrame(
        rows, columns=["year", "coverage", "age", "sex", "claims", "amount_claimed", "cause"]
    )


def deaths_of(rule: str) -> pd.Series:
    out = insured.death_cells(claims_frame(), rule)
    return out.set_index(["age", "sex"])["deaths"]


def test_the_base_rule_counts_only_known_positive_deaths_on_the_death_cover():
    """Section 11.1: ledger rows, cancellations, riders and maturities are not deaths."""
    base = deaths_of("base")
    assert base.to_dict() == {(40, "F"): 6.0, (40, "M"): 14.0}  # 10 + 4 men, 6 women
    assert deaths_of("with_maturities")[(65, "M")] == 8.0  # the maturities, if left in
    assert deaths_of("net")[(40, "M")] == 14.0 - 3.0  # minus the cancelled claims


def test_spreading_extra_deaths_pro_rata_adds_exactly_that_many_and_creates_no_cell():
    """(11.1): d' = d (1 + extra / total) per year, so the year grows by exactly the extra."""
    deaths = pd.DataFrame(
        {"year": [2023, 2023, 2024], "age": [40, 41, 40], "sex": "M", "deaths": [30.0, 10.0, 20.0]}
    )
    out = insured.spread_pro_rata(deaths, pd.Series({2023: 8.0, 2024: 5.0}))
    assert out.groupby("year")["deaths"].sum().to_dict() == pytest.approx({2023: 48.0, 2024: 25.0})
    assert out["deaths"].tolist() == pytest.approx([30 * 1.2, 10 * 1.2, 20 * 1.25])
    assert len(out) == len(deaths)
    # the readings that add the no-detail rows spread them over every cell in proportion
    plus = deaths_of("plus_positive")
    assert plus.sum() == pytest.approx(20.0 + 5.0)  # the 5 positive ledger claims, not the -7
    assert plus[(40, "M")] / plus[(40, "F")] == pytest.approx(14 / 6)  # proportions are kept
    assert (plus[(40, "M")], plus[(40, "F")]) == pytest.approx(
        (14 * 1.25, 6 * 1.25)
    )  # 17.5 and 7.5


def test_the_exposure_keeps_known_ages_and_the_central_exposure_shortens_the_head_count():
    """(11.2): central = count x (1 - f / 2), so the rate rises by 1 / (1 - f / 2) - 1."""
    exposure = pd.DataFrame(
        {
            "year": 2023, "age": [40, 40, np.nan], "sex": ["M", "M", "F"],
            "insured": [600.0, 400.0, 50.0],
        }
    )  # fmt: skip
    cells = insured.exposure_cells(exposure)
    assert cells["exposure"].tolist() == [1000.0]  # the row without an age is not exposure
    for share, rise in ((0.10, 0.0526), (0.20, 0.1111)):
        central = insured.central_exposure(cells, share)["exposure"].iloc[0]
        assert central == pytest.approx(1000 * (1 - share / 2))
        assert 1000 / central - 1 == pytest.approx(rise, abs=1e-4)
    with pytest.raises(ValueError):
        insured.central_exposure(cells, 1.5)


def test_using_every_life_instead_of_those_holding_the_death_cover_lowers_the_rate():
    """(11.3): rate = deaths / lives, so a denominator 12% too large lowers it by 1 - 1/1.12 = 10.7%."""
    deaths = pd.DataFrame({"year": 2023, "age": [40], "sex": ["M"], "deaths": [53.0]})
    holding = pd.DataFrame({"year": 2023, "age": [40], "sex": ["M"], "exposure": [100_000.0]})
    anyone = holding.assign(exposure=holding["exposure"] * 1.12)
    right = insured.crude_cells(deaths, holding)["rate"].iloc[0]
    wrong = insured.crude_cells(deaths, anyone)["rate"].iloc[0]
    assert wrong / right == pytest.approx(1 / 1.12)
    assert 1 - wrong / right == pytest.approx(0.107, abs=1e-3)


# ── 11.2: graduating against the population ──────────────────────────────────

AGES = np.arange(25, 66)
Q_POP = 0.0004 * np.exp(0.085 * (AGES - 25)) + 0.0008


def test_brass_recovers_a_planted_curve_and_solves_its_score_equations():
    """(11.4), (11.5): logit q = a + b logit q_ref; the fit reproduces deaths and logit-weighted deaths."""
    a, b = -0.10, 1.32
    q = special.expit(a + b * special.logit(Q_POP))
    exposure = np.full(AGES.size, 3e6)
    deaths = exposure * q  # no sampling noise: the planted curve is recovered exactly
    fit = insured.fit_brass(deaths, exposure, Q_POP)
    assert (fit.a, fit.b) == pytest.approx((a, b), abs=1e-6)
    rng = np.random.default_rng(3)
    noisy = rng.poisson(deaths).astype(float)
    fit = insured.fit_brass(noisy, exposure, Q_POP)
    se = np.sqrt(np.diag(fit.cov))
    assert abs(fit.a - a) < 4 * se[0] and abs(fit.b - b) < 4 * se[1]
    x = special.logit(Q_POP)
    fitted = exposure * fit.predict(Q_POP)
    assert (noisy - fitted).sum() == pytest.approx(0.0, abs=1e-3)  # total deaths
    assert ((noisy - fitted) * x).sum() == pytest.approx(0.0, abs=1e-2)  # (11.5)


def test_brass_with_a_zero_shift_and_unit_slope_is_the_reference_and_the_odds_change_by_exp_a():
    """(11.4): a = 0, b = 1 is the identity; a shifts every odds ratio by exp(a) when b = 1."""
    q = 0.005
    assert special.expit(0.0 + 1.0 * special.logit(q)) == pytest.approx(q)
    shifted = special.expit(-0.5 + 1.0 * special.logit(q))
    assert (shifted / (1 - shifted)) / (q / (1 - q)) == pytest.approx(np.exp(-0.5))
    # the market table of the project: a = -0.10, b = 1.32 against a population rate of 0.5%
    market = special.expit(-0.10 + 1.32 * special.logit(0.005))
    assert (round(market, 6), round(market / 0.005, 3)) == (
        0.000835,
        0.167,
    )  # 17% of the population


def test_the_relational_fit_smooths_the_ratio_to_the_reference():
    """(11.6): the Poisson P-spline on deaths against expected-under-the-reference gives the ratio."""
    exposure = np.full(AGES.size, 2e6)
    ratio = 0.2 + 0.1 * (AGES - 25) / 40  # a ratio rising smoothly with age
    deaths = exposure * Q_POP * ratio
    fit = insured.relational_fit(AGES, deaths, exposure, Q_POP, lam=100.0)
    assert fit.mx == pytest.approx(
        ratio, rel=1e-3
    )  # the fitted "rate" is the insured / reference ratio
    assert (exposure * Q_POP * fit.mx).sum() == pytest.approx(
        deaths.sum(), rel=1e-6
    )  # conservation (4.14)


def test_the_shape_error_ignores_the_level_of_a_held_out_year():
    """(11.7): the deviance after rescaling the prediction to the year's total: level is not the contest."""
    expected = np.array([10.0, 20.0, 40.0, 80.0])
    deaths = expected * 0.7  # a year of lower mortality, same shape
    assert insured.shape_error(deaths, expected) == pytest.approx(0.0, abs=1e-9)
    assert insured.deviance(deaths, expected) > 1.0  # the plain deviance would punish the level
    assert (
        insured.shape_error(deaths * np.array([2, 1, 1, 1]), expected) > 1.0
    )  # but not a bad shape


def test_the_method_rule_picks_the_cheapest_among_those_close_to_the_best_out_of_sample():
    """(11.7): lowest quasi-AIC among methods whose shape error is within 5% of the best."""
    table = pd.DataFrame(
        {
            "method": ["relational", "direct", "makeham", "brass"],
            "qaic": [48.8, 47.4, 50.4, 63.6],
            "cv_shape_deviance": [379.1, 370.5, 360.8, 388.9],
        }
    )
    assert insured.select_method(table) == "direct"  # makeham has the best cv but a higher qaic
    table.loc[table["method"] == "direct", "cv_shape_deviance"] = 600.0  # now too far from the best
    table.loc[table["method"] == "relational", "cv_shape_deviance"] = (
        370.0  # close to makeham's 360.8
    )
    assert (
        insured.select_method(table) == "relational"
    )  # lower quasi-AIC than makeham, both within 5%


# ── 11.3: where the data stop ────────────────────────────────────────────────


def test_the_credible_range_ends_where_the_ratio_to_the_population_collapses():
    """(11.8): first age from 55 whose 3-age smoothed ratio is below 85% of the 40-60 median, minus 1."""
    ages = np.arange(18, 91)
    q_ref = 0.0004 * np.exp(0.09 * (ages - 18)) + 0.0006
    exposure = np.full(ages.size, 1e6)
    ratio = np.where(ages < 70, 0.20, 0.10)  # the ratio halves from age 70
    deaths = exposure * q_ref * ratio
    last = insured.last_credible_age(ages, deaths, exposure, q_ref)
    assert (
        last == 68
    )  # the smoothed value at 69 averages 68, 69 and 70: (0.2 + 0.2 + 0.1) / 3 < 0.17
    assert abs(last - 69) <= 1  # found within one age of the planted collapse
    rising = np.where(
        ages < 70, 0.20, 0.30
    )  # a product mix moving toward whole life is not a collapse
    assert insured.last_credible_age(ages, exposure * q_ref * rising, exposure, q_ref) == 90


def test_the_extension_moves_the_ratio_to_one_along_a_smooth_s_curve():
    """(11.9): r(x) = r_end + (1 - r_end) (3 w^2 - 2 w^3), w = (x - last) / (105 - last)."""
    ages = np.arange(0, 111)
    q_ref = np.clip(0.0004 * np.exp(0.09 * ages), 0, 1)
    last, r_end = 60, 0.25
    q_fit = q_ref * 0.25
    q_fit[last + 1 :] = 0.0  # whatever the fit says above its last credible age is ignored
    out = insured.extend_to_reference(ages, q_fit, q_ref, last_age=last, converge_age=105)
    ratio = out / q_ref
    assert ratio[last] == pytest.approx(r_end)
    mid = last + (105 - last) / 2
    assert np.interp(mid, ages, ratio) == pytest.approx(
        (r_end + 1) / 2, rel=0.02
    )  # the S-curve passes the middle
    assert out[106:] == pytest.approx(q_ref[106:])  # above 105 the table is the population's
    assert (np.diff(out[last:]) >= 0).all()  # non-decreasing from the last credible age
    w = np.linspace(0, 1, 11)
    s = 3 * w**2 - 2 * w**3
    assert (s[0], s[5], s[-1]) == (0.0, 0.5, 1.0) and (6 * w * (1 - w))[[0, -1]].tolist() == [
        0.0,
        0.0,
    ]
    with pytest.raises(ValueError):
        insured.extend_to_reference(ages, q_fit, q_ref, last_age=60, converge_age=60)


def test_men_are_floored_at_women_and_the_changed_ages_are_flagged():
    """(11.10): men's rate is raised to women's where an extension leaves them below."""
    ages = np.arange(18, 31)
    women = pd.DataFrame(
        {"sex": "F", "age": ages, "qx": 0.002, "qx_lower": 0.001, "qx_upper": 0.003}
    )
    men = women.assign(sex="M", qx=np.where(ages >= 25, 0.0015, 0.004))
    out = insured.floor_men_at_women(pd.concat([women, men], ignore_index=True))
    m = out[out["sex"] == "M"].set_index("age")
    assert m.loc[25:, "qx"].eq(0.002).all() and m.loc[:24, "qx"].eq(0.004).all()
    assert m["sex_floor"].tolist() == [bool(a >= 25) for a in ages]
    assert m.loc[25:, ["qx_lower", "qx_upper"]].isna().all().all()  # a floor is not an estimate


# ── 11.4: products, multipliers and blends ───────────────────────────────────


def test_a_segment_multiplier_is_total_deaths_over_total_expected_deaths():
    """(11.11): the Poisson maximum-likelihood k of deaths ~ Poisson(k x exposure x q_ref)."""
    exposure = np.linspace(2e5, 5e4, AGES.size)
    expected = exposure * Q_POP
    pooled = pd.DataFrame({"age": AGES, "deaths": 1.5 * expected, "exposure": exposure})
    out = insured.relativity(pooled, pd.Series(Q_POP, index=AGES), ages=(25, 65))
    assert out["k"] == pytest.approx(1.5)
    assert out["lower"] < 1.5 < out["upper"] and out["dispersion"] == 1.0
    rng = np.random.default_rng(4)
    noisy = rng.poisson(1.3 * expected).astype(float)
    k = noisy.sum() / expected.sum()
    best = optimize.minimize_scalar(
        lambda x: -(noisy * np.log(x * expected) - x * expected).sum(),
        bounds=(0.5, 3.0),
        method="bounded",
    )
    assert best.x == pytest.approx(k, rel=1e-5)


def test_the_age_varying_multiplier_recovers_a_planted_straight_line_in_the_log():
    """(11.12): log k(x) = a + b (x - 45) / 20, fitted by a Poisson regression with the table as offset."""
    exposure = np.linspace(2e5, 5e4, AGES.size)
    a, b = 0.30, 0.45
    deaths = exposure * Q_POP * np.exp(a + b * (AGES - 45) / 20)
    fit = insured.fit_relative_curve(
        pd.DataFrame({"age": AGES, "deaths": deaths, "exposure": exposure}),
        pd.Series(Q_POP, index=AGES),
        ages=(25, 65),
    )
    assert (fit["a"], fit["b"]) == pytest.approx((a, b), abs=1e-6)


def test_the_market_blend_is_the_exposure_weighted_mean_of_the_products():
    """(11.13): q_market(x) = sum over products of L_s(x) q_s(x) / sum of L_s(x)."""
    ages = np.arange(30, 34)

    def table(q: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sex": "M",
                "age": ages,
                "qx": q,
                "qx_lower": q * 0.9,
                "qx_upper": q * 1.1,
                "source": "graduated",
            }
        )

    tables = {"term": table(0.001), "credit": table(0.003)}
    pooled = {
        "term": pd.DataFrame({"sex": "M", "age": ages, "exposure": [900.0, 800.0, 700.0, 600.0]}),
        "credit": pd.DataFrame({"sex": "M", "age": ages, "exposure": [100.0, 200.0, 300.0, 400.0]}),
    }
    out = insured.blend_tables(tables, pooled).set_index("age")
    weight = np.array([0.9, 0.8, 0.7, 0.6])
    assert out["qx"].to_numpy() == pytest.approx(weight * 0.001 + (1 - weight) * 0.003)
    assert out["qx_upper"].to_numpy() == pytest.approx(1.1 * out["qx"].to_numpy())
    assert (out["qx"] > 0.001).all() and (out["qx"] < 0.003).all()  # always between its parts


# ── 11.5: time ───────────────────────────────────────────────────────────────


def test_improvement_is_the_geometric_average_rate_of_the_projection():
    """(11.14): r = 1 - (q_2045 / q_2025)^(1 / 20); rolling two years multiplies q by (1 - r)^2."""
    projected = pd.DataFrame(
        {"year": [2025, 2045, 2025, 2045], "sex": ["M", "M", "F", "F"], "age": [40, 40, 40, 40],
         "qx": [0.0010, 0.0008, 0.0005, 0.0003]}
    )  # fmt: skip
    out = insured_analysis.improvement_table(projected).set_index("sex")["annual_improvement"]
    assert out["M"] == pytest.approx(1 - 0.8 ** (1 / 20))
    assert round(out["M"], 4) == 0.0111
    assert (1 - out["M"]) ** 20 == pytest.approx(0.8)
    factor = insured_sensitivity.improvement_factor(out.reset_index().assign(age=40), "M", 2.0)
    assert factor[40] == pytest.approx(0.8 ** (2 / 20))


def test_the_standardised_trend_uses_fixed_age_weights_and_the_annual_change_is_a_log_slope():
    """(11.15), (11.16): a changing age mix cannot move the trend; q falls 5% a year -> change = -5%."""
    ages = np.arange(25, 80)
    q = 0.0003 * np.exp(0.09 * (ages - 25))
    rows = []
    for year in (2023, 2024, 2025):
        for sex in ("M", "F"):
            exposure = np.where(ages < 50, 2e5, 1e5) * (
                1.5 if year == 2025 else 1.0
            )  # the mix shifts
            for a, e, r in zip(ages, exposure, q, strict=True):
                rows.append(
                    {
                        "year": year,
                        "sex": sex,
                        "age": int(a),
                        "exposure": float(e),
                        "deaths": e * r * 0.95 ** (year - 2024),
                    }
                )
    crude = pd.DataFrame(rows)
    trend = insured.standardised_trend(crude, weights_year=2024).set_index(["year", "sex"])["rate"]
    assert trend[(2025, "M")] / trend[(2024, "M")] == pytest.approx(0.95, rel=1e-9)
    q_table = pd.concat([pd.DataFrame({"sex": s, "age": ages, "qx": q}) for s in ("M", "F")])
    change = insured.annual_change(crude, q_table).set_index("sex")
    assert change.loc["M", "annual_change"] == pytest.approx(-0.05, abs=1e-9)
    assert change.loc["M", "lower"] <= -0.05 <= change.loc["M", "upper"]


# ── 11.6: the price, the margin and the law of large numbers ─────────────────


def test_the_premium_of_a_table_is_the_net_term_premium_of_chapter_8():
    """(11.17): 1,000 x P of (8.1) on the q of the policy years at 4%."""
    q_by_age = np.clip(0.0004 * np.exp(0.095 * np.arange(111)), 0, 1)
    got = insured_sensitivity.premium_per_1000(q_by_age, 40, 20)
    assert got == pytest.approx(1000 * pricing.net_premium(q_by_age[40:60], 0.04))


def test_the_margin_adds_the_adverse_readings_in_quadrature_and_rounds_up_to_5_percent():
    """(11.18): sqrt(11.1%^2 + 5.3%^2) = 12.3%, rounded up to 15%."""
    sens = pd.DataFrame(
        {
            "choice": ["a", "b", "c", "d"], "sex": "M", "issue_age": 40, "term": 20,
            "adverse": [True, True, True, False], "change_vs_base": [0.111, 0.053, -0.04, 0.40],
        }
    )  # fmt: skip
    out = insured_sensitivity.margin_table(sens)
    assert (
        out["adverse_choices"].iloc[0] == 2
    )  # the favorable and the non-adverse ones are not counted
    assert out["quadrature_margin"].iloc[0] == pytest.approx(np.sqrt(0.111**2 + 0.053**2))
    assert round(out["quadrature_margin"].iloc[0], 3) == 0.123
    assert out["recommended_margin"].iloc[0] == pytest.approx(0.15)
    assert np.ceil(0.1500001 / 0.05) * 0.05 == pytest.approx(0.20)  # 5% steps, upward only


def test_the_law_of_large_numbers_for_a_book_of_equal_policies():
    """(11.19): CV = sqrt((1 - q) / (n q)); a 15% margin covers one standard deviation from n = 83,000."""
    q = 0.000533
    cv = lambda n: np.sqrt((1 - q) / (n * q))  # noqa: E731
    assert [round(cv(n) * 100) for n in (10_000, 100_000, 1_000_000)] == [43, 14, 4]
    n_for_margin = (1 - q) / (q * 0.15**2)
    assert round(n_for_margin, -3) == 83_000
    assert cv(n_for_margin) == pytest.approx(0.15)
    rng = np.random.default_rng(6)
    sims = rng.binomial(10_000, q, 400_000)
    assert sims.std() / sims.mean() == pytest.approx(cv(10_000), rel=0.02)


def test_the_market_table_and_the_pandemic_index_by_hand():
    """Section 11.4, 11.5: premium per 1,000 of cover, claims over premium, and the rate against 2023."""
    issued = pd.DataFrame(
        {"year": [2023, 2023], "age": [40, 41], "sex": "M", "plan": "Temporal", "modality": "Tradicional",
         "insured": [1000.0, 1000.0], "premium": [3_000.0, 3_000.0], "sum_assured": [1e6, 1e6]}
    )  # fmt: skip
    claims = pd.DataFrame(
        {"year": [2023], "age": [40], "sex": ["M"], "plan": "Temporal", "modality": "Tradicional",
         "coverage": "Fallecimiento", "cause": "NEUMONIA", "claims": [1.0], "amount_claimed": [660.0],
         "amount_paid": [400.0]}
    )  # fmt: skip
    out = insured_analysis.market_table(claims, issued, segments=("term_traditional",)).iloc[0]
    assert out["premium_per_1000"] == pytest.approx(1000 * 6000 / 2e6)
    assert out["claimed_to_premium"] == pytest.approx(660 / 6000) and out[
        "paid_to_premium"
    ] == pytest.approx(400 / 6000)
    crude = pd.DataFrame(
        {
            "year": [2023, 2021],
            "sex": "M",
            "age": 30,
            "deaths": [10.0, 20.0],
            "exposure": [1000.0, 1000.0],
        }
    )
    pop = crude.assign(deaths=[100.0, 140.0], exposure=[10_000.0, 10_000.0])
    table = insured_analysis.pandemic_table(crude, pop)
    row = table[
        (table["source"] == "insured") & (table["year"] == 2021) & (table["band"] == "25-44")
    ].iloc[0]
    assert row["index_vs_2023"] == pytest.approx(2.0)  # 2.0% against 1.0%: twice its 2023 rate


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
    """Section 11.8: the ledger, the rules, the methods, the gap, the premiums, the margin, the trend."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    ledger = q("SELECT * FROM insured_ledger WHERE year = 2023").groupby("block")["claims"].sum()
    assert round(ledger["no_detail"] / ledger.sum() * 100, 1) == 20.5

    rules = q("SELECT * FROM insured_rules").set_index(["year", "rule"])["deaths"]
    assert round(sum(rules[(y, "base")] for y in (2023, 2024, 2025)), -3) == 81_000

    sens = q(
        "SELECT * FROM insured_sensitivity WHERE sex = 'M' AND issue_age = 40 AND term = 20"
    ).set_index("alternative")
    change = (sens["change_vs_base"] * 100).round(1)
    assert change["net of cancelled claims"] == -2.3 and change["plus every no-detail row"] == 24.9
    assert change["plus the no-detail rows with a positive amount"] == 11.1
    assert (
        change["lives exposed part of the year: 10%"] == 5.3
        and change["lives exposed part of the year: 20%"] == 11.1
    )
    assert change["every insured life, whatever the cover (exposure sheet)"] == -11.4
    assert change["market blend of all products"] == 40.2 and change["all term"] == 14.6
    assert (
        change["Brass against the population"] == 2.6
        and change["by sum assured: larger policies die more"] == 36.9
    )
    assert change[["at age 95", "at age 115"]].tolist() == [
        0.0,
        0.0,
    ]  # old ages do not move a 20-year term at 40

    margin = q("SELECT * FROM insured_margin").set_index(["sex", "issue_age", "term"])[
        "quadrature_margin"
    ]
    assert (margin * 100).round(1).tolist() == [12.4, 12.3, 12.0]
    assert q("SELECT recommended_margin FROM insured_margin")[
        "recommended_margin"
    ].to_numpy() == pytest.approx(0.15)

    methods = q(
        "SELECT * FROM insured_methods WHERE segment = 'term_traditional' AND sex = 'M'"
    ).set_index("method")
    assert methods["qaic"].round(1).to_dict() == {
        "relational": 48.8,
        "direct": 47.4,
        "makeham": 50.4,
        "brass": 63.6,
    }
    assert methods.loc["direct", "selected"] == 1 and methods["n_ages"].eq(43).all()

    gap = q("SELECT * FROM insured_gap WHERE age BETWEEN 25 AND 65")
    market = (
        gap[gap["comparison"].str.contains("all individual life")]
        .groupby("sex")["ratio"]
        .agg(["min", "max"])
        .round(2)
    )
    assert market.loc["M"].tolist() == [0.14, 0.25] and market.loc["F"].tolist() == [0.18, 0.23]
    cnsf = gap[gap["comparison"].str.contains("CNSF 2013")].query("sex == 'M'")["ratio"]
    assert (round(cnsf.min(), 2), round(cnsf.max(), 2)) == (0.23, 0.31)

    prem = q("SELECT * FROM insured_premiums WHERE term = 20").pivot_table(
        index="table", columns=["sex", "issue_age"], values="premium_per_1000"
    )
    traditional = prem.loc["Mexico insured: Term, traditional"]
    assert traditional[[("M", 30), ("M", 40), ("M", 50), ("F", 40)]].round(2).tolist() == [
        0.50,
        0.85,
        2.01,
        0.38,
    ]
    assert prem.loc["Mexico insured: All individual life", ("M", 40)].round(2) == 1.20
    assert (
        prem.loc["CNSF 2013", ("M", 40)].round(2) == 1.74
        and prem.loc["Mexico population 2023", ("M", 40)].round(2) == 6.62
    )
    assert prem.loc["US 2017 Unloaded CSO composite male ALB", ("M", 40)].round(2) == 2.52
    assert (
        round(prem.loc["CNSF 2013", ("F", 40)] / traditional[("F", 40)], 1) == 4.6
    )  # the unisex table for a woman
    assert round(prem.loc["Mexico population 2023", ("M", 40)] / traditional[("M", 40)], 1) == 7.7

    market_rows = q(
        "SELECT * FROM insured_market WHERE segment = 'term_traditional' AND year BETWEEN 2023 AND 2025"
    )
    assert (
        round(market_rows["premium"].sum() / 1e9, 1) == 43.2
        and round(market_rows["claimed"].sum() / 1e9, 1) == 9.5
    )
    assert round(market_rows["claimed"].sum() / market_rows["premium"].sum() * 100) == 22
    assert round(market_rows["paid"].sum() / market_rows["premium"].sum() * 100) == 14
    assert round(1000 * market_rows["premium"].sum() / market_rows["sum_assured"].sum(), 2) == 4.07

    rel = q("SELECT * FROM insured_relativities").set_index(["segment", "sex", "ages"])["k"]
    assert [round(rel[("credit", s, "25-44")], 1) for s in "MF"] == [1.3, 1.6]
    assert [round(rel[("credit", s, "45-65")], 1) for s in "MF"] == [1.6, 2.1]
    assert [round(rel[("permanent", s, "25-44")], 1) for s in "MF"] == [1.9, 2.3]
    assert [round(rel[("permanent", s, "45-65")], 1) for s in "MF"] == [2.5, 3.6]

    trend = q(
        "SELECT * FROM insured_trend WHERE kind = 'annual_change' AND segment = 'all'"
    ).set_index("sex")
    assert (trend["annual_change"] * 100).round(1).to_dict() == {"M": -4.7, "F": -11.4}
    assert (trend.loc["M", "lower"] * 100, trend.loc["M", "upper"] * 100) == pytest.approx(
        (-8.2, -1.1), abs=0.06
    )
    standard = q(
        "SELECT * FROM insured_trend WHERE kind = 'standardised_rate' AND segment = 'all' AND year = 2025"
    ).set_index("sex")
    assert (1 - standard["index_vs_first_base_year"]).mul(100).round().to_dict() == {
        "M": 9.0,
        "F": 21.0,
    }
    improvement = q("SELECT * FROM insured_improvement WHERE age BETWEEN 25 AND 65")[
        "annual_improvement"
    ]
    assert improvement.min() * 100 == pytest.approx(0.65, abs=0.02)  # about 0.7% a year
    assert round(improvement.max() * 100, 1) == 2.7

    brass = q(
        "SELECT * FROM insured_brass WHERE \"table\" = 'Mexico insured: All individual life' AND sex = 'M'"
    ).iloc[0]
    assert (round(brass["a"], 2), round(brass["b"], 2)) == (-0.10, 1.32)
