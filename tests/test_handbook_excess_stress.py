"""Numerical proof of the formulas in docs/handbook/09-excess-stress.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mortality import excess as xs
from mortality import rates
from mortality import stress as st

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.filterwarnings(
    "ignore:Perfect separation"
)  # exact data are fitted exactly


# ── 9.1 and 9.2: the baselines ───────────────────────────────────────────────


def test_flat_baseline_keeps_the_2019_rate():
    """(9.2): E = m_2019 x exposure, band by band."""
    out = xs.flat_baseline(np.array([0.01, 0.02]), np.array([[1000.0, 1100.0], [500.0, 600.0]]))
    assert out == pytest.approx(np.array([[10.0, 11.0], [10.0, 12.0]]))


def test_interpolation_baseline_moves_the_log_rate_in_a_straight_line():
    """(9.4): log m goes from its 2019 value to its 2023 value; 2021 is the geometric mean."""
    r19, r23 = np.array([0.010]), np.array([0.016])
    years = [2019, 2020, 2021, 2023]
    exposure = np.full((1, 4), 1000.0)
    out = xs.interpolation_baseline(r19, r23, years, exposure)[0]
    assert out[0] == pytest.approx(10.0) and out[3] == pytest.approx(16.0)
    assert out[2] == pytest.approx(1000 * np.sqrt(0.010 * 0.016))  # 12.649
    assert round(out[2], 3) == 12.649
    assert out[1] == pytest.approx(1000 * 0.010 * (0.016 / 0.010) ** 0.25)


def test_trend_baseline_is_a_poisson_regression_that_keeps_the_pre_pandemic_totals():
    """(9.3): the fitted trend reproduces the fitting years' deaths and their time-weighted sum."""
    rng = np.random.default_rng(2)
    years = np.arange(2014, 2020)
    exposure = np.tile(np.linspace(1e6, 1.1e6, 6), (3, 1))
    rate = np.array([0.002, 0.01, 0.04])[:, None] * np.exp(-0.01 * (years - 2014))
    deaths = rng.poisson(exposure * rate).astype(float)
    expected, _ = xs.trend_baseline(deaths, exposure, years, years, exposure)
    assert expected.sum(axis=1) == pytest.approx(deaths.sum(axis=1), rel=1e-8)
    t = years - years.mean()
    assert ((deaths - expected) * t).sum(axis=1) == pytest.approx(0.0, abs=1e-5)


def test_trend_baseline_continues_an_exact_exponential_trend():
    """(9.3): noise-free log-linear rates are carried forward without error, with a small se."""
    years = np.arange(2014, 2020)
    exposure_fit = np.full((1, 6), 2e6)
    rate = lambda y: 0.01 * np.exp(-0.02 * (y - 2014))  # noqa: E731
    deaths = exposure_fit * rate(years)
    ahead = np.array([2020, 2021, 2022])
    exposure_ahead = np.full((1, 3), 2.1e6)
    expected, se = xs.trend_baseline(deaths, exposure_fit, years, ahead, exposure_ahead)
    assert expected[0] == pytest.approx(exposure_ahead[0] * rate(ahead), rel=1e-9)
    assert (se / expected).max() < 0.02


def test_lee_carter_baseline_is_proportional_to_the_inegi_level_and_the_exposure():
    """(9.5): the baseline is the banded Lee-Carter path times INEGI 2019 / CONAPO 2019 times exposure."""
    rng = np.random.default_rng(1)
    ages, years = np.arange(100), np.arange(1970, 2020)
    a = np.where(ages < 5, -6.0 - 0.8 * ages, -9.0 + 0.085 * ages)
    b = np.exp(-(((ages - 40) / 35.0) ** 2)) + 0.3
    b = b / b.sum()
    k = -1.2 * np.arange(len(years)) + np.cumsum(rng.normal(0, 0.3, len(years)))
    k -= k.mean()
    exposure = 3e5 * np.exp(-0.02 * ages)
    rate = np.exp(a[:, None] + b[:, None] * k[None, :])
    history = pd.DataFrame(
        [
            {
                "year": int(y),
                "sex": "M",
                "age": int(x),
                "deaths": exposure[x] * rate[x, j],
                "exposure": exposure[x],
            }
            for j, y in enumerate(years)
            for x in ages
        ]
    )
    population = pd.DataFrame(
        [
            {"year": y, "sex": "M", "age": int(x), "population": exposure[x]}
            for y in range(2019, 2025)
            for x in ages
        ]
    )
    n_bands = len(rates.BAND_LABELS)
    r19 = np.full(n_bands, 0.01)
    expo = np.full((n_bands, 3), 1e5)
    one = xs.lee_carter_baseline(history, population, "M", [2020, 2021, 2022], r19, expo)
    two = xs.lee_carter_baseline(history, population, "M", [2020, 2021, 2022], 2 * r19, expo)
    three = xs.lee_carter_baseline(history, population, "M", [2020, 2021, 2022], r19, 3 * expo)
    assert two == pytest.approx(2 * one) and three == pytest.approx(3 * one)
    assert one[:, 1].sum() < one[:, 0].sum()  # the 1970-2019 trend keeps lowering mortality


# ── 9.3: excess and its range ────────────────────────────────────────────────


def small_world():
    """One year, one sex, two bands, the four baselines of the worked example."""
    grouped = pd.DataFrame(
        {
            "year": [2021, 2021], "sex": ["M", "M"], "band": [10, 11],
            "deaths": [120.0, 60.0], "exposure": [1e4, 1e4],
        }
    )  # fmt: skip
    expected = {
        10: {
            "flat_2019": 100.0,
            "trend_2014_2019": 105.0,
            "interpolation_to_2023": 95.0,
            "lee_carter": 110.0,
        },
        11: {
            "flat_2019": 50.0,
            "trend_2014_2019": 50.0,
            "interpolation_to_2023": 54.0,
            "lee_carter": 56.0,
        },
    }
    rows = [
        {"year": 2021, "sex": "M", "band": band, "age_group": "x", "method": method,
         "expected": value, "expected_se": 4.0 if method == "trend_2014_2019" else np.nan}
        for band, methods in expected.items() for method, value in methods.items()
    ]  # fmt: skip
    return grouped, pd.DataFrame(rows)


def test_excess_toy_example_centre_range_and_p_score():
    """(9.6), (9.7): central = median of the baselines; the range runs from the highest to the lowest."""
    grouped, baselines = small_world()
    out = xs.excess_by_band(grouped, baselines).set_index("band")
    first = out.loc[10]
    assert first["expected_central"] == pytest.approx(102.5)  # median of 95, 100, 105, 110
    assert (first["expected_low"], first["expected_high"]) == (95.0, 110.0)
    assert first["excess"] == pytest.approx(17.5)
    assert (first["excess_low"], first["excess_high"]) == (
        10.0,
        25.0,
    )  # from the highest and lowest baseline
    assert first["p_score"] == pytest.approx(17.5 / 102.5)
    assert first["stat_se"] == pytest.approx(np.sqrt(120 + 4.0**2))  # (9.7)
    assert round(first["p_score"] * 100, 1) == 17.1
    total = xs.summarise(out.reset_index())
    both = total[(total["sex"] == "M") & (total["year"] == 2021)].iloc[0]
    assert both["excess"] == pytest.approx(17.5 + (60 - 52.0))  # band 11: median 52, excess 8
    assert xs.summarise(out.reset_index()).query("sex == 'T'")["excess"].iloc[0] == pytest.approx(
        both["excess"]
    )


def test_years_of_life_lost_weight_the_excess_by_remaining_life():
    """(9.8): YLL = sum over bands of excess x remaining life expectancy."""
    grouped, baselines = small_world()
    by_band = xs.excess_by_band(grouped, baselines)
    remaining = pd.DataFrame({"sex": ["M", "M"], "band": [10, 11], "remaining_life": [30.0, 25.0]})
    out = xs.summarise(by_band, remaining_life=remaining)
    row = out[(out["sex"] == "M")].iloc[0]
    excess = by_band.set_index("band")["excess"]
    assert row["years_lost"] == pytest.approx(excess[10] * 30 + excess[11] * 25)
    assert row["years_lost"] / row["excess"] == pytest.approx(row["years_lost"] / excess.sum())


def test_the_analysis_recovers_a_known_shock_above_age_40():
    """Section 9.3: a +40% shock in one year, above age 40, is found by the baselines."""
    n_bands = len(rates.BAND_LABELS)
    exposure = {y: 1e6 * (1 + 0.01 * (y - 2014)) for y in range(2014, 2025)}
    base = np.exp(-9.0 + 0.4 * np.arange(n_bands))  # rates rise with the band
    rows = []
    for year in exposure:
        trend = np.exp(-0.015 * (year - 2014))
        for band in range(n_bands):
            shock = 1.4 if year == 2021 and band >= int(rates.band_index(40)) else 1.0
            rows.append(
                {"year": year, "sex": "M", "band": band, "deaths": exposure[year] * base[band] * trend * shock,
                 "exposure": exposure[year]}
            )  # fmt: skip
    grouped = pd.concat([pd.DataFrame(rows), pd.DataFrame(rows).assign(sex="F")], ignore_index=True)
    baselines = xs.baseline_set(grouped, None, None, years=(2020, 2021, 2022, 2023, 2024))
    by_band = xs.excess_by_band(grouped, baselines)
    by_band = by_band[by_band["sex"] == "M"]
    adult = by_band[(by_band["year"] == 2021) & (by_band["band"] >= int(rates.band_index(40)))]
    planted = (adult["observed"] * (1 - 1 / 1.4)).sum()
    assert adult["excess"].sum() == pytest.approx(
        planted, rel=0.06
    )  # the baselines differ by a few percent
    assert adult["p_score"].median() == pytest.approx(0.40, abs=0.04)
    young = by_band[(by_band["year"] == 2021) & (by_band["band"] < int(rates.band_index(40)))]
    assert (young["p_score"].abs() < 0.04).all()  # no shock below 40, no excess
    quiet = by_band[(by_band["year"] == 2020)]
    assert quiet["p_score"].abs().max() < 0.04


# ── 9.4: cause, month and state ──────────────────────────────────────────────


def test_cause_excess_uses_the_anchor_year_scaled_by_population_and_zero_for_covid():
    """(9.9): expected = deaths in 2023 x population ratio; COVID-19 has no baseline."""
    causes = pd.DataFrame(
        [{"year": y, "chapter": c, "deaths": d} for (y, c, d) in [
            (2020, "I", 1000.0), (2021, "I", 1100.0), (2022, "I", 900.0), (2023, "I", 800.0),
            (2020, "U", 500.0), (2021, "U", 700.0), (2022, "U", 100.0), (2023, "U", 10.0),
        ]]
    )  # fmt: skip
    population = pd.Series({2020: 120.0, 2021: 121.0, 2022: 122.0, 2023: 125.0})
    out = xs.cause_excess(causes, population).set_index(["year", "chapter"])
    assert out.loc[(2021, "I"), "expected"] == pytest.approx(800 * 121 / 125)
    assert out.loc[(2021, "I"), "excess"] == pytest.approx(1100 - 800 * 121 / 125)
    assert out.loc[(2021, "U"), "expected"] == 0.0 and out.loc[(2021, "U"), "excess"] == 700.0
    assert out.loc[(2020, "U"), "label"] == "COVID-19"


def test_monthly_baseline_keeps_the_seasonal_shape_of_the_post_pandemic_years():
    """(9.10): baseline = the year's baseline x the month's average share in 2023 and 2024."""
    months = np.arange(1, 13)
    shape = np.array([1.2, 1.1, 1.0, 0.9, 0.9, 0.8, 0.8, 0.9, 0.9, 1.0, 1.1, 1.3])
    rows = []
    for year, scale in ((2020, 1.0), (2023, 1.0), (2024, 1.1)):
        for m, s in zip(months, shape, strict=True):
            rows.append({"year": year, "month": m, "deaths": 1000 * s * scale, "covid_deaths": 0.0})
    monthly = pd.DataFrame(rows)
    out = (
        xs.monthly_excess(monthly, pd.Series({2020: float(1000 * shape.sum())}))
        .query("year == 2020")
        .set_index("month")
    )
    share = shape / shape.sum()
    assert out["baseline"].to_numpy() == pytest.approx(1000 * shape.sum() * share)
    assert out["baseline"].sum() == pytest.approx(1000 * shape.sum())
    assert out["excess"].abs().max() < 1e-6  # deaths in 2020 follow the same shape: no excess


def test_state_excess_removes_age_structure_and_population_growth():
    """(9.11): each state's own 2023 band rates times each year's population."""
    ages = [30, 70]
    pop = pd.DataFrame(
        [{"year": y, "state": 1, "sex": "M", "age": a, "population": p * (1.0 + 0.05 * (y - 2020))}
         for y in (2020, 2021, 2023) for a, p in zip(ages, (5000.0, 1000.0), strict=True)]
    )  # fmt: skip
    rate = {30: 0.001, 70: 0.03}
    deaths = pd.DataFrame(
        [{"year": y, "state": 1, "sex": "M", "age": a, "deaths": r.population * rate[a] * (1.5 if y == 2021 else 1.0)}
         for _, r in pop.iterrows() for y in [int(r.year)] for a in [int(r.age)]]
    )  # fmt: skip
    out = xs.state_excess(deaths, pop).set_index("year")
    assert out.loc[2021, "p_score"] == pytest.approx(0.5)
    assert out.loc[2021, "expected"] == pytest.approx((5000 * 0.001 + 1000 * 0.03) * 1.05)


# ── 9.5: the pandemic replay ─────────────────────────────────────────────────


def excess_frame() -> pd.DataFrame:
    labels = list(rates.BAND_LABELS)
    scores = np.linspace(-0.1, 0.6, len(labels))
    return pd.DataFrame(
        [{"year": 2021, "sex": s, "band": b, "age_group": g, "p_score": v + (0.1 if s == "M" else 0.0)}
         for s in ("M", "F") for b, (g, v) in enumerate(zip(labels, scores, strict=True))]
    )  # fmt: skip


def test_p_scores_are_spread_over_single_ages_and_never_negative():
    """(9.12): each band's P-score covers its ages; the open band takes all older ages; below 0 is 0."""
    out = st.pscore_by_age(excess_frame(), 2021)
    labels = list(rates.BAND_LABELS)
    raw = np.linspace(-0.1, 0.6, len(labels)) + 0.1
    assert out["M"].shape == (111,)
    assert out["M"][0] == 0.0  # the first band's score is below zero
    assert out["M"][40:45] == pytest.approx(np.full(5, max(raw[labels.index("40-44")], 0)))
    assert out["M"][85:] == pytest.approx(np.full(26, raw[-1]))  # the open band
    assert (out["M"] >= 0).all() and (out["F"] >= 0).all()


def toy_book():
    inforce = pd.DataFrame(
        {
            "sum_assured": [1e6, 2e6, 5e5, 3e6],
            "attained_age": [30, 45, 60, 90],
            "sex": ["M", "F", "M", "F"],
        }
    )
    return st.Book(inforce, np.array([0.001, 0.003, 0.02, 0.2]))


def test_stressed_claims_scale_the_probability_by_one_plus_dampening_severity_and_p_score():
    """(9.13): q' = min(q (1 + d s P), 1); the extra claims are linear in d x s until the cap."""
    book, scores = toy_book(), {"M": np.full(111, 0.5), "F": np.full(111, 0.4)}
    plain = st.stressed_claims(book, scores, 1.0, 1.0)
    sa, q = book.inforce["sum_assured"].to_numpy(), book.q
    p = np.array([0.5, 0.4, 0.5, 0.4])
    assert plain == pytest.approx(sa * np.minimum(q * (1 + p), 1.0))
    extra = lambda d, s: st.stressed_claims(book, scores, d, s).sum() - book.claims  # noqa: E731
    assert extra(0.5, 2.0) == pytest.approx(extra(1.0, 1.0))  # only the product d x s matters
    assert extra(0.5, 1.0) == pytest.approx(0.5 * extra(1.0, 1.0))
    capped = st.stressed_claims(book, scores, 1.0, 10.0)
    assert capped[3] == pytest.approx(3e6)  # q = 0.2 x 5 would exceed 1: capped at certain death


def test_stress_toy_example_by_hand():
    """Section 9.8: SA 1,000,000, q = 0.002, P = 0.6, d = 0.5: q' = 0.0026 and 600 of extra claims."""
    book = st.Book(
        pd.DataFrame({"sum_assured": [1e6], "attained_age": [50], "sex": ["M"]}), np.array([0.002])
    )
    scores = {"M": np.full(111, 0.6), "F": np.full(111, 0.6)}
    stressed = st.stressed_claims(book, scores, dampening=0.5, severity=1.0)[0]
    assert stressed == pytest.approx(2600.0)
    assert stressed - book.claims == pytest.approx(0.5 * 0.6 * 2000.0)  # d x s x P x base claims
    assert stressed / book.claims - 1 == pytest.approx(0.30)


def test_the_constant_probability_annuity_example_by_hand():
    """Section 9.8: q = 0.03, i = 4%: 40 years 13.942; 25 years 12.255; a death frees 1.414 million."""
    q, i = 0.03, 0.04
    vp = (1 - q) / (1 + i)
    assert st.annuity_due_from_q(np.full((1, 40), q), i)[0] == pytest.approx(13.9420, abs=1e-4)
    assert st.annuity_due_from_q(np.full((1, 25), q), i)[0] == pytest.approx(12.2546, abs=1e-4)
    assert 1 / (1 - vp) == pytest.approx(14.857, abs=1e-3)  # the limit as the horizon grows
    assert pytest.approx(1_414_000, rel=1e-3) == 120_000 * (1 / 1.04) * 12.2546


def test_the_scenario_table_has_the_replays_the_severities_and_the_regulatory_row():
    """Section 9.5: rows for each year and dampening, the severity multiples and the heavier table."""
    book = toy_book()
    heavy = book.q * 1.5
    out = st.pandemic_scenarios(book, excess_frame(), q_regulatory=heavy, years=(2021,))
    assert set(out["kind"]) == {"replay", "severity", "regulatory"}
    reg = out[out["kind"] == "regulatory"].iloc[0]
    sa = book.inforce["sum_assured"].to_numpy()
    assert reg["stressed_claims"] == pytest.approx((sa * heavy).sum())
    assert reg["extra_pct"] == pytest.approx(0.5)
    replay = out[(out["kind"] == "replay") & (out["dampening"] == 0.5)].iloc[0]
    full = out[(out["kind"] == "replay") & (out["dampening"] == 1.0)].iloc[0]
    assert replay["extra_claims"] == pytest.approx(0.5 * full["extra_claims"])


def test_insured_p_scores_come_from_the_rate_relative_to_2023_and_never_below_zero():
    """(9.14): P = max(index - 1, 0) in each band; ages outside the bands take the nearest band's value."""
    pandemic = pd.DataFrame(
        {"source": "insured", "year": 2021, "sex": "M", "band": ["25-44", "45-64", "65-79"],
         "index_vs_2023": [2.03, 2.72, 0.9]}
    )  # fmt: skip
    out = st.insured_pscores(pandemic, 2021)["M"]
    assert out[30] == pytest.approx(1.03) and out[50] == pytest.approx(1.72)
    assert out[70] == 0.0  # a band below its 2023 level gets no credit
    assert out[10] == pytest.approx(1.03) and out[100] == pytest.approx(
        0.0
    )  # edges take the nearest band


# ── 9.6 and 9.7: longevity and the hedge ─────────────────────────────────────


def test_the_annuity_of_a_constant_probability_is_a_geometric_series():
    """(9.15): a-due = sum (v p)^t = (1 - (v p)^N) / (1 - v p) for N years at a constant q."""
    q, i, n = 0.03, 0.04, 40
    got = st.annuity_due_from_q(np.full((1, n), q), i)[0]
    vp = (1 - q) / (1 + i)
    assert got == pytest.approx((1 - vp**n) / (1 - vp))
    assert st.annuity_due_from_q(np.full((1, n), 0.0), i)[0] == pytest.approx(
        sum(1.04**-t for t in range(n))
    )


def test_cohort_paths_scale_the_log_improvement_and_the_level():
    """(9.16): q = q_base (q_t / q_base)^s x level, along the diagonal of the projection."""
    ages = np.arange(0, 111)
    base = np.clip(0.0005 * np.exp(0.09 * ages), 0, 1)
    years = np.arange(0, 60)
    cube = base[None, :] * np.exp(-0.02 * years)[:, None]  # 2% a year improvement at every age
    cube[:, -1] = 1.0
    start = np.array([60, 70])
    zero = st.cohort_q_paths(cube, start, scale=0.0)
    one = st.cohort_q_paths(cube, start, scale=1.0)
    two = st.cohort_q_paths(cube, start, scale=2.0)
    j = 5
    assert zero[0, j] == pytest.approx(base[65])  # no improvement: the base-year rate at age 65
    assert one[0, j] == pytest.approx(cube[j, 65])  # the projection: the rate of year j at age 65
    assert np.log(two[0, j] / zero[0, j]) == pytest.approx(2 * np.log(one[0, j] / zero[0, j]))
    lowered = st.cohort_q_paths(cube, start, scale=1.0, level=0.8)
    assert lowered[0, :20] == pytest.approx(0.8 * one[0, :20])
    assert one[0, -1] == 1.0  # the table closes
    period = st.period_q_paths(base, start, level=0.8)
    assert period[1, 3] == pytest.approx(0.8 * base[73])


def test_annuity_release_is_the_pension_value_of_each_extra_death():
    """(9.17): each extra death at age x frees pension x v x a-due(x + 1); linear in the dampening."""
    ages = np.arange(0, 111)
    q_all = np.clip(0.0005 * np.exp(0.09 * ages), 0, 1)
    q_all[-1] = 1.0
    make = lambda x: st.period_q_paths(q_all, np.asarray(x))  # noqa: E731
    block = st.AnnuityBlock(lives=1000, male_share=0.5, pension=100_000.0, youngest=60, oldest=75)
    scores = {"M": np.full(111, 0.5), "F": np.full(111, 0.5)}
    full = st.annuity_release(block, {"M": make, "F": make}, scores, 1.0)
    half = st.annuity_release(block, {"M": make, "F": make}, scores, 0.5)
    assert full < 0 and half == pytest.approx(0.5 * full)
    # by hand for one age: weights of the cohort survivors times extra deaths times the pension value
    v = 1 / 1.04
    w = block.weights(q_all)
    a_next = st.annuity_due_from_q(make(np.minimum(np.arange(60, 76) + 1, 110)), 0.04)
    extra = q_all[60:76] * 0.5
    manual = -(1000 * 100_000.0 * (w * extra * v * a_next).sum())  # both sexes share the same table
    assert full == pytest.approx(manual, rel=1e-9)
    assert w.sum() == pytest.approx(1.0)


def test_reserves_are_the_weighted_annuities_and_scale_with_lives_and_pension():
    """(9.18), (9.19): reserve = lives x share x pension x sum of w_x a-due_x, for each sex."""
    ages = np.arange(0, 111)
    q_all = np.clip(0.0005 * np.exp(0.09 * ages), 0, 1)
    q_all[-1] = 1.0
    make = lambda x: st.period_q_paths(q_all, np.asarray(x))  # noqa: E731
    block = st.AnnuityBlock(lives=2000, male_share=0.6, pension=120_000.0)
    out = st.annuity_reserves(block, {"M": make, "F": make})
    a = st.annuity_due_from_q(make(np.arange(60, 96)), 0.04)
    w = block.weights(q_all)
    assert out["reserve_M"] == pytest.approx(2000 * 0.6 * 120_000 * (w * a).sum())
    assert out["reserve_T"] == pytest.approx(out["reserve_M"] + out["reserve_F"])
    assert out["reserve_M"] / out["reserve_F"] == pytest.approx(
        0.6 / 0.4
    )  # same table, so the shares
    double = st.annuity_reserves(
        st.AnnuityBlock(lives=4000, male_share=0.6, pension=120_000.0), {"M": make, "F": make}
    )
    assert double["reserve_T"] == pytest.approx(2 * out["reserve_T"])
    assert out["a65_M"] == pytest.approx(st.annuity_due_from_q(make(np.array([65])), 0.04)[0])


# ── The numbers quoted in the chapter come from the shipped database ─────────


@pytest.fixture(scope="module")
def demo():
    path = ROOT / "app" / "data" / "demo.sqlite"
    if not path.exists():
        pytest.skip("demo database not built")
    con = sqlite3.connect(path)
    yield con
    con.close()


def test_excess_numbers_match_the_database(demo):
    """Section 9.9: totals, ranges, baselines, sex split, years of life lost, causes, states."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    s = q("SELECT * FROM excess_summary WHERE sex = 'T' AND year BETWEEN 2020 AND 2022").set_index(
        "year"
    )
    assert s["observed"].round().astype(int).tolist() == [1093073, 1117650, 843757]
    assert s["excess"].round().astype(int).tolist() == [332448, 350778, 63203]
    assert s["excess_low"].round().astype(int).tolist() == [319970, 327669, 28295]
    assert s["excess_high"].round().astype(int).tolist() == [339894, 365700, 85732]
    assert (s["p_score"] * 100).round(1).tolist() == [43.7, 45.7, 8.1]
    assert s["covid_coded"].astype(int).tolist() == [201280, 238093, 38189]
    assert s["excess_per_covid_coded"].round(2).tolist() == [1.65, 1.47, 1.65]
    assert round(s["excess"].sum()) == 746429 and round(s["expected_central"].sum()) == 2308050
    assert round(s["excess"].sum() / s["covid_coded"].sum(), 2) == 1.56
    assert round(s["years_lost"].sum() / 1e6, 1) == 13.0
    assert round(s["years_lost"].sum() / s["excess"].sum(), 1) == 17.4

    by_sex = q(
        "SELECT sex, SUM(excess) AS excess, SUM(years_lost) AS yll FROM excess_summary WHERE year BETWEEN 2020 AND 2022 AND sex IN ('M', 'F') GROUP BY sex"
    ).set_index("sex")
    assert by_sex["excess"].round().astype(int).to_dict() == {"F": 283853, "M": 462576}
    assert round(by_sex.loc["M", "excess"] / by_sex["excess"].sum(), 2) == 0.62
    assert (round(by_sex.loc["M", "yll"] / 1e6, 1), round(by_sex.loc["F", "yll"] / 1e6, 1)) == (
        8.0,
        5.0,
    )

    all_years = q("SELECT * FROM excess_summary WHERE sex = 'T'").set_index("year")
    spread = (all_years["expected_high"] - all_years["expected_low"]) / all_years[
        "expected_central"
    ]
    assert (spread.loc[2020:2024] * 100).round(1).tolist() == [2.6, 5.0, 7.4, 9.7, 12.1]
    assert (
        round(all_years.loc[2023, "p_score"] * 100, 1) == -0.5
    )  # observed 2023 against the central baseline
    base = q(
        "SELECT method, SUM(expected) AS e FROM excess_baselines WHERE year = 2023 GROUP BY method"
    ).set_index("method")["e"]
    observed_2023 = all_years.loc[2023, "observed"]
    rel = (observed_2023 / base - 1) * 100
    assert rel.round(1).to_dict() == {
        "flat_2019": -2.2,
        "interpolation_to_2023": 0.0,
        "lee_carter": 2.0,
        "trend_2014_2019": -3.7,
    }

    by_cause = q(
        "SELECT chapter, SUM(excess) AS e FROM excess_by_cause GROUP BY chapter"
    ).set_index("chapter")["e"]
    assert by_cause[["U", "I", "E", "J"]].round().astype(int).tolist() == [
        477687,
        96433,
        89834,
        53864,
    ]
    assert round(746429 - by_cause[["U", "I", "E", "J"]].sum(), -3) == 29000

    state = q(
        "SELECT state_name, SUM(observed) AS o, SUM(expected) AS e, SUM(excess) AS x FROM excess_state GROUP BY state_name"
    )
    state["p"] = state["x"] / state["e"]
    nation = state["x"].sum() / state["e"].sum()
    assert round(nation, 2) == 0.35
    ranked = state.set_index("state_name")["p"].round(2)
    assert [ranked[n] for n in ("México", "Ciudad de México", "Tlaxcala", "Sinaloa", "Puebla")] == [
        0.49,
        0.48,
        0.48,
        0.42,
        0.39,
    ]
    assert [ranked[n] for n in ("Colima", "Quintana Roo", "Veracruz", "Yucatán", "Chiapas")] == [
        0.19,
        0.22,
        0.23,
        0.23,
        0.25,
    ]
    assert round(state.set_index("state_name").loc["México", "x"], -2) == 132500

    monthly = q("SELECT * FROM excess_monthly").set_index(["year", "month"])
    assert (
        monthly.loc[(2021, 1), "deaths"] == 174143
        and round(monthly.loc[(2021, 1), "baseline"], -3) == 74000
    )
    assert monthly.loc[(2020, 7), "deaths"] == 119564 and monthly.loc[(2021, 8), "deaths"] == 121845

    ages = q("SELECT * FROM excess_mortality WHERE year = 2021 AND sex IN ('M', 'F')").set_index(
        ["sex", "age_group"]
    )["p_score"]
    assert [
        round(ages[k] * 100)
        for k in (("M", "45-49"), ("M", "65-69"), ("F", "45-49"), ("F", "65-69"))
    ] == [68, 70, 66, 56]


def test_stress_numbers_match_the_database(demo):
    """Section 9.9: the replays, the age split, the longevity table, the hedge and the insured scenario."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    book = q("SELECT * FROM stress_pandemic_book").set_index("scenario")
    first = book[book["kind"] == "replay"]
    full = first[first["dampening"] == 1.0].set_index("year")
    assert (full["extra_claims"] / 1e6).round().astype(int).tolist() == [445, 447, 43]
    assert (full["extra_pct"] * 100).round(1).tolist() == [60.0, 60.3, 5.8]
    assert round(book["base_claims"].iloc[0] / 1e6) == 742
    half = first[first["dampening"] == 0.5].set_index("year")
    assert (half["extra_pct"] * 100).round().tolist() == [30, 30, 3]
    sev = book[book["kind"] == "severity"]["extra_pct"].round(2).tolist()
    assert sev == [0.30, 0.90, 1.20]
    assert round(book.loc["CNSF 99.5th percentile table", "extra_pct"] * 100, 1) == 50.7
    assert round(book.loc["2021 as insured lives lived it", "extra_pct"] * 100) == 133

    age = q("SELECT * FROM stress_pandemic_age WHERE year = 2021")
    share_old = (
        age[age["age_group"].isin(["50-59", "60+"])]["extra_claims"].sum()
        / age["extra_claims"].sum()
    )
    assert round(share_old * 100) == 71
    assert (
        round(age[age["sex"] == "M"]["extra_claims"].sum() / age["extra_claims"].sum() * 100) == 65
    )

    pandemic = q("SELECT * FROM insured_pandemic WHERE year = 2021")
    ratio = pandemic.groupby("source")["index_vs_2023"].agg(["min", "max"]).round(1)
    assert ratio.loc["insured"].tolist() == [1.8, 2.9]  # insured lives were not shielded
    assert ratio.loc["population"].tolist() == [1.4, 1.7]

    lon = q("SELECT * FROM stress_longevity").set_index("scenario")
    assert (lon["change_vs_central"] * 100).round(1).to_dict() == {
        "cnsf_pensions": 16.0, "cnsf_base": 7.8, "population_2023": -2.9, "no_improvement": -2.2,
        "central": 0.0, "improvement_x2": 2.3, "level_minus_20": 5.9, "interest_minus_1": 8.1,
        "interest_plus_1": -7.0,
    }  # fmt: skip
    assert round(lon.loc["central", "reserve_T"] / 1e9, 1) == 25.0
    assert (round(lon.loc["central", "a65_M"], 2), round(lon.loc["central", "a65_F"], 2)) == (
        12.62,
        13.65,
    )
    assert round(lon.loc["cnsf_pensions", "a65_M"], 2) == 16.10

    hedge = q("SELECT * FROM stress_hedge").set_index("shock")
    assert round(hedge.loc["2021 pandemic replay", "life_book_change"] / 1e6) == 447
    assert round(hedge.loc["2021 pandemic replay", "annuity_change"] / 1e6) == -374
    assert (
        round(
            -hedge.loc["2021 pandemic replay", "annuity_change"]
            / hedge.loc["2021 pandemic replay", "life_book_change"],
            2,
        )
        == 0.84
    )
    assert (
        round(
            hedge.loc["2021 pandemic replay", "annuity_block_to_offset"]
            / hedge.loc["2021 pandemic replay", "annuity_reserve"],
            1,
        )
        == 1.2
    )
    lower = hedge.loc["Mortality 20% lower for good"]
    assert (round(lower["life_book_change"] / 1e9, 1), round(lower["annuity_change"] / 1e9, 1)) == (
        -2.9,
        1.5,
    )
