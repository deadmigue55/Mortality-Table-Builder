"""Tests for excess mortality: baselines, excess, causes, months, states."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import excess as xs
from mortality import rates

pytestmark = pytest.mark.filterwarnings("ignore:Perfect separation")  # noise-free test data

N = len(rates.BAND_LABELS)


def world(shock=0.40, shock_bands=range(8, 19), noise=0.0, seed=0):
    """Deaths and exposure by year, sex and band with a known pandemic shock in 2021.

    Rates fall 1% a year; exposure grows 1% a year; in 2021 the bands in ``shock_bands`` have
    ``shock`` more deaths than normal."""
    rng = np.random.default_rng(seed)
    rows = []
    for sex, level in (("M", 1.0), ("F", 0.7)):
        for year in range(2014, 2025):
            for band in range(N):
                rate = level * 0.0002 * np.exp(0.09 * band) * 0.99 ** (year - 2014)
                exposure = 2e6 * 1.01 ** (year - 2014)
                mult = 1 + shock if (year == 2021 and band in shock_bands) else 1.0
                deaths = rate * exposure * mult
                if noise:
                    deaths = float(rng.poisson(deaths))
                rows.append(
                    {"year": year, "sex": sex, "band": band, "deaths": deaths, "exposure": exposure}
                )
    return pd.DataFrame(rows)


def test_flat_baseline_applies_the_2019_rate_to_each_years_exposure():
    out = xs.flat_baseline(np.array([0.01, 0.02]), np.array([[100.0, 200.0], [300.0, 400.0]]))
    assert out.tolist() == [[1.0, 2.0], [6.0, 8.0]]


def test_trend_baseline_recovers_a_known_log_linear_trend():
    rng = np.random.default_rng(1)
    years = np.arange(2014, 2020)
    expo = np.full((4, 6), 5e6)
    true = 0.002 * np.exp(0.1 * np.arange(4))[:, None] * 0.97 ** (years - 2014)[None, :]
    deaths = rng.poisson(true * expo).astype(float)
    pred_years = np.array([2020, 2021, 2022])
    pred_expo = np.full((4, 3), 5e6)
    expected, se = xs.trend_baseline(deaths, expo, years, pred_years, pred_expo)
    truth = 0.002 * np.exp(0.1 * np.arange(4))[:, None] * 0.97 ** (pred_years - 2014)[None, :] * 5e6
    assert expected == pytest.approx(truth, rel=0.06)
    assert (se > 0).all() and (se[:, 2] > se[:, 0]).all()  # farther out is less certain


def test_interpolation_goes_from_2019_to_the_anchor_in_a_straight_line_on_the_log_scale():
    r19, r23 = np.array([0.01]), np.array([0.0064])
    expo = np.full((1, 5), 1000.0)
    out = xs.interpolation_baseline(r19, r23, [2019, 2021, 2023, 2020, 2022], expo)[0] / 1000
    assert out[0] == pytest.approx(0.01) and out[2] == pytest.approx(0.0064)
    assert out[1] == pytest.approx(np.sqrt(0.01 * 0.0064))  # halfway on the log scale


def test_excess_is_recovered_by_the_baselines():
    g = world()
    base = xs.baseline_set(g, None, None)
    assert set(base["method"]) == {"flat_2019", "trend_2014_2019", "interpolation_to_2023"}
    by = xs.excess_by_band(g, base)
    y = by[(by["year"] == 2021) & (by["sex"] == "M")]
    shocked = y[y["band"] >= 8]
    assert shocked["p_score"].mean() == pytest.approx(0.40, abs=0.05)
    assert abs(y[y["band"] < 8]["p_score"].mean()) < 0.05  # nothing happened to the young
    assert (y["excess_low"] <= y["excess"] + 1e-9).all() and (
        y["excess"] <= y["excess_high"] + 1e-9
    ).all()
    assert (y["expected_low"] <= y["expected_central"]).all()
    total = by[by["year"] == 2021]["excess"].sum()
    truth = sum(
        0.40 * lvl * 0.0002 * np.exp(0.09 * b) * 0.99**7 * 2e6 * 1.01**7
        for lvl in (1.0, 0.7) for b in range(8, 19)
    )  # fmt: skip
    assert total == pytest.approx(truth, rel=0.06)


def test_a_year_without_a_pandemic_has_no_excess():
    by = xs.excess_by_band(world(shock=0.0), xs.baseline_set(world(shock=0.0), None, None))
    t = by[by["year"] == 2021]["excess"].sum()
    assert abs(t) < 0.01 * by[by["year"] == 2021]["observed"].sum()


def test_summary_adds_the_sexes_and_relates_excess_to_certified_deaths():
    g = world()
    by = xs.excess_by_band(g, xs.baseline_set(g, None, None))
    life = pd.DataFrame(
        [{"sex": s, "band": b, "remaining_life": 30.0 - b} for s in "MF" for b in range(N)]
    )
    s = xs.summarise(by, pd.Series({2020: 100.0, 2021: 5000.0}), life)
    t = s[(s["year"] == 2021)].set_index("sex")
    assert t.loc["T", "excess"] == pytest.approx(t.loc["M", "excess"] + t.loc["F", "excess"])
    assert t.loc["T", "observed"] == pytest.approx(t.loc["M", "observed"] + t.loc["F", "observed"])
    assert t.loc["T", "covid_coded"] == 5000.0 and np.isnan(t.loc["M", "covid_coded"])
    assert t.loc["T", "excess_per_covid_coded"] == pytest.approx(t.loc["T", "excess"] / 5000.0)
    assert t.loc["T", "years_lost"] > 0
    plain = xs.summarise(by)
    assert plain["years_lost"].isna().all() and "covid_coded" not in plain


def test_cause_excess_uses_the_anchor_year_and_never_expects_covid():
    causes = pd.DataFrame(
        [(y, c, d) for y, vals in {2020: (50, 120, 10), 2021: (60, 130, 12), 2022: (5, 100, 10),
                                   2023: (0, 100, 10)}.items()
         for c, d in zip(("U", "I", "J"), vals, strict=True)],
        columns=["year", "chapter", "deaths"],
    )  # fmt: skip
    pop = pd.Series({2020: 100.0, 2021: 102.0, 2022: 104.0, 2023: 105.0})
    out = xs.cause_excess(causes, pop).set_index(["year", "chapter"])
    assert out.loc[(2021, "U"), "expected"] == 0 and out.loc[(2021, "U"), "excess"] == 60
    assert out.loc[(2021, "I"), "expected"] == pytest.approx(100 * 102 / 105)
    assert out.loc[(2020, "I"), "excess"] == pytest.approx(120 - 100 * 100 / 105)
    assert out.loc[(2021, "U"), "label"] == "COVID-19"


def test_monthly_baseline_follows_the_seasonal_shape_and_ties_to_the_annual_total():
    rows = []
    season = np.array([1.2, 1.1, 1.0, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 1.0, 1.1, 1.2])
    season = season / season.sum()
    for year, total in ((2021, 1500.0), (2023, 1000.0), (2024, 1000.0)):
        for m in range(12):
            rows.append((year, m + 1, total * season[m], 10.0 if year == 2021 else 0.0))
    monthly = pd.DataFrame(rows, columns=["year", "month", "deaths", "covid_deaths"])
    out = xs.monthly_excess(monthly, pd.Series({2021: 1000.0}))
    y = out[out["year"] == 2021]
    assert y["baseline"].sum() == pytest.approx(1000.0)
    assert y["excess"].sum() == pytest.approx(500.0)
    assert (
        y["excess"] / y["baseline"]
    ).std() < 1e-9  # the shock is proportional: the shape is kept


def state_inputs(multiplier=1.0):
    d, p = [], []
    for year in (2020, 2021, 2022, 2023):
        for state in (1, 2):
            for sex in ("M", "F"):
                for age in (30, 60):
                    pop = 10_000.0 * state
                    rate = 0.001 if age == 30 else 0.01
                    m = multiplier if (year == 2021 and state == 2) else 1.0
                    p.append((year, state, sex, age, pop))
                    d.append((year, state, sex, age, pop * rate * m))
    return (pd.DataFrame(d, columns=["year", "state", "sex", "age", "deaths"]),
            pd.DataFrame(p, columns=["year", "state", "sex", "age", "population"]))  # fmt: skip


def test_state_excess_is_zero_when_nothing_changed_and_the_shock_when_it_did():
    d, p = state_inputs()
    assert xs.state_excess(d, p)["excess"].abs().max() < 1e-9
    d, p = state_inputs(multiplier=2.0)
    out = xs.state_excess(d, p).set_index(["year", "state"])
    assert out.loc[(2021, 2), "p_score"] == pytest.approx(1.0)
    assert out.loc[(2021, 1), "p_score"] == pytest.approx(0.0)
    assert out.loc[(2021, 2), "excess"] == pytest.approx(out.loc[(2021, 2), "observed"] / 2)
    assert set(out.index.get_level_values("year")) == {2020, 2021, 2022}
