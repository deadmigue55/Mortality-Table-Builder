"""Tests for crude rates, standardisation and benchmarks (pure functions, no database)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import rates


def test_band_index_edges():
    ages = [0, 1, 4, 5, 24, 25, 84, 85, 109]
    assert rates.band_index(ages).tolist() == [0, 1, 1, 2, 5, 6, 17, 18, 18]
    assert len(rates.BAND_LABELS) == len(rates.BAND_LOWER) == 19
    assert rates.BAND_LABELS[6] == "25-29"
    assert rates.BAND_LABELS[-1] == "85+"


def test_segi_standard_is_complete():
    assert len(rates.SEGI_WEIGHTS) == len(rates.SEGI_LOWER) == 18
    assert sum(rates.SEGI_WEIGHTS) == 100_000
    # our bands "0" and "1-4" both belong to Segi's first group
    assert [rates.segi_group(b) for b in (0, 1, 2, 3, 18)] == [0, 0, 1, 2, 17]


def test_poisson_interval_matches_published_values():
    lower, upper = rates.poisson_interval([0, 10])
    assert lower[0] == 0.0
    assert upper[0] == pytest.approx(3.689, abs=1e-3)  # the classic "rule of three" is ~3
    assert lower[1] == pytest.approx(4.795, abs=1e-3)
    assert upper[1] == pytest.approx(18.390, abs=1e-3)


def test_poisson_interval_handles_fractional_counts():
    lower, upper = rates.poisson_interval([99.6])
    assert lower[0] < 99.6 < upper[0]


def test_rate_interval_brackets_the_rate():
    lower, upper = rates.rate_interval([50.0], [10_000.0])
    assert lower[0] < 0.005 < upper[0]


def test_qx_is_below_mx_and_roundtrips():
    mx = np.array([0.001, 0.05, 0.4])
    q = rates.mx_to_qx(mx, np.array([40, 40, 99]), np.array(["M", "M", "F"]))
    assert np.all(q < mx)
    assert q[0] == pytest.approx(0.001 / 1.0005)
    assert rates.qx_to_mx(q) == pytest.approx(mx)


def test_infant_qx_uses_a_small_ax():
    # deaths in infancy happen early (a0 ~ 0.07), so fewer babies are at risk for the full year
    # and q0 = m / (1 + (1 - a0) m) is below the a = 0.5 value
    a0 = 0.045 + 2.684 * 0.01
    q0 = float(rates.mx_to_qx(0.01, 0, "M"))
    assert q0 == pytest.approx(0.01 / (1 + (1 - a0) * 0.01))
    assert q0 < 0.01 / (1 + 0.5 * 0.01)
    assert rates.infant_ax(0.2, "M") == pytest.approx(0.33)
    assert rates.infant_ax(0.2, "F") == pytest.approx(0.35)


def _population(ages, years=(2023,), sex=("M", "F"), size=1000.0):
    return pd.DataFrame(
        [(y, s, a, size) for y in years for s in sex for a in ages],
        columns=["year", "sex", "age", "population"],
    )


def test_crude_single_pools_the_open_age_and_conserves_deaths():
    ages = list(range(0, 110))
    pop = _population(ages)
    deaths = pop.rename(columns={"population": "deaths"}).assign(deaths=lambda d: d["age"] / 10.0)
    out = rates.crude_single(deaths, pop)
    assert out["deaths"].sum() == pytest.approx(deaths["deaths"].sum())
    assert out["age"].max() == rates.TERMINAL_AGE
    top = out[(out["sex"] == "M") & (out["age"] == rates.TERMINAL_AGE)].iloc[0]
    assert top["exposure"] == pytest.approx(10 * 1000.0)  # ages 100-109
    assert np.isnan(top["qx"])
    assert (out["mx_lower"] <= out["mx"]).all()
    assert (out["mx"] <= out["mx_upper"]).all()


def test_crude_single_flags_thin_cells():
    pop = _population([30, 31])
    deaths = pop.rename(columns={"population": "deaths"}).assign(deaths=[2.0, 50.0, 2.0, 50.0])
    out = rates.crude_single(deaths, pop)
    assert out["credible"].tolist() == [False, True, False, True]


def test_crude_grouped_adds_both_sexes_and_labels():
    deaths = pd.DataFrame(
        {"year": 2020, "sex": ["M", "F"], "band": 6, "basis": "occurrence", "deaths": [30, 10]}
    )
    exposure = pd.DataFrame(
        {"year": 2020, "sex": ["M", "F"], "band": 6, "exposure": [1000.0, 3000.0]}
    )
    out = rates.crude_grouped(deaths, exposure).set_index("sex")
    assert out.loc["T", "mx"] == pytest.approx(40 / 4000)
    assert out.loc["M", "age_group"] == "25-29"


def _cube():
    rows = [
        # (year, age_lo, sex, deaths): age 0 and 85+, plus unknown sex and unknown age rows
        (2018, 0, "M", 60),
        (2018, 0, "F", 40),
        (2018, 0, "U", 10),
        (2018, 85, "M", 100),
        (2018, 85, "F", 300),
        (2018, np.nan, "M", 4),
        (2018, np.nan, "F", 6),
        (2018, np.nan, "U", 2),
    ]
    return pd.DataFrame(rows, columns=["reg_year", "age_lo", "sex", "deaths"])


def test_cube_allocation_keeps_every_death():
    cube = _cube()
    out = rates.allocate_cube_unknowns(cube)
    assert out["deaths"].sum() == pytest.approx(cube["deaths"].sum())
    assert set(out["sex"]) == {"M", "F"}
    assert set(out["band"]) == {0, 18}


def test_cube_allocation_is_proportional():
    out = rates.allocate_cube_unknowns(_cube()).set_index(["sex", "band"])["deaths"]
    # unknown sex (10) split 60:40 in the age-0 row
    assert out[("M", 0)] > 60 and out[("F", 0)] > 40
    # unknown-age deaths follow the known age pattern, so the shares do not move: after the
    # sex split the female rows are 40 + 4 = 44 (age 0) and 300 (85+)
    known_f = out[("F", 0)] + out[("F", 18)]
    assert out[("F", 18)] / known_f == pytest.approx(300 / 344)


def test_standardised_rate_ignores_the_weights_when_rates_are_equal():
    n = np.full(18, 10_000.0)
    d = np.full(18, 20.0)  # every group has a rate of 0.002
    result = rates.standardise(d, n, rates.SEGI_WEIGHTS)
    assert result["asr"] == pytest.approx(0.002)
    assert result["asr_lower"] < 0.002 < result["asr_upper"]


def test_standardised_rate_removes_ageing():
    # Same age-specific rates, but population B is much older: crude rates differ, ASR does not
    weights = np.ones(18)
    rate = np.linspace(0.001, 0.1, 18)
    young, old = np.linspace(2, 1, 18) * 1e5, np.linspace(1, 2, 18) * 1e5
    a = rates.standardise(rate * young, young, weights)["asr"]
    b = rates.standardise(rate * old, old, weights)["asr"]
    assert a == pytest.approx(b)
    assert (rate * young).sum() / young.sum() < (rate * old).sum() / old.sum()


def test_age_standardised_skips_incomplete_cells():
    complete = pd.DataFrame(
        {
            "basis": "occurrence",
            "year": 2023,
            "sex": "T",
            "band": range(19),
            "deaths": 10.0,
            "exposure": 1000.0,
        }
    )
    out = rates.age_standardised(complete)
    assert len(out) == 1
    assert out["asr"].iloc[0] == pytest.approx(0.01)
    assert rates.age_standardised(complete.iloc[:5]).empty


def test_smr_expected_adds_up_to_observed():
    observed = pd.DataFrame(
        {
            "state": [1, 1, 2, 2],
            "sex": ["M", "F"] * 2,
            "band": 6,
            "deaths": [30.0, 10.0, 10.0, 10.0],
        }
    )
    population = pd.DataFrame(
        {
            "state": [1, 1, 2, 2],
            "sex": ["M", "F"] * 2,
            "band": 6,
            "exposure": [1000.0, 1000.0, 1000.0, 1000.0],
        }
    )
    out = rates.smr_table(observed, population).set_index("state")
    assert out["expected"].sum() == pytest.approx(out["observed"].sum())
    assert out.loc[1, "smr"] > 1 > out.loc[2, "smr"]
    assert (out["smr_lower"] < out["smr"]).all() and (out["smr"] < out["smr_upper"]).all()


def test_actual_versus_expected_with_a_flat_table():
    ages = range(25, 85)
    pop = _population(ages, size=10_000.0)
    # a table with q = 0.002 everywhere; actual deaths = exactly what it predicts
    table = pd.Series(0.002, index=range(0, 111))
    expected_rate = float(rates.qx_to_mx(0.002))
    deaths = pop.assign(band=rates.band_index(pop["age"]))
    deaths = deaths.groupby(["year", "sex", "band"], as_index=False)["population"].sum()
    deaths["deaths"] = deaths["population"] * expected_rate
    both = deaths.groupby(["year", "band"], as_index=False)["deaths"].sum().assign(sex="T")
    deaths = pd.concat([deaths[["year", "sex", "band", "deaths"]], both], ignore_index=True)
    out = rates.actual_versus_expected(deaths, pop, {"flat": (table, "T")})
    assert out["ae"].to_numpy() == pytest.approx(1.0)
    assert (out["age_group"] == "25-84").sum() == 3  # one total per sex (M, F, T)
    assert set(out["sex"]) == {"M", "F", "T"}


def test_sex_specific_tables_only_compare_their_own_sex():
    pop = _population(range(25, 85))
    table = pd.Series(0.01, index=range(0, 111))
    deaths = pop.assign(band=rates.band_index(pop["age"]))
    deaths = deaths.groupby(["year", "sex", "band"], as_index=False)["population"].sum()
    deaths = deaths.rename(columns={"population": "deaths"})
    out = rates.actual_versus_expected(deaths, pop, {"male only": (table, "M")})
    assert set(out["sex"]) == {"M"}


def test_country_ratios_divides_rates():
    mexico = pd.DataFrame({"year": 2019, "sex": ["M"], "band": [6], "mx": [0.003]})
    hmd = pd.DataFrame(
        {
            "country": "ESP",
            "year": 2019,
            "sex": "M",
            "band": 6,
            "deaths": [3.0, 3.0],
            "exposure": [10_000.0, 10_000.0],
        }
    )
    out = rates.country_ratios(mexico, hmd)
    assert out["mx_country"].iloc[0] == pytest.approx(0.0003)
    assert out["ratio"].iloc[0] == pytest.approx(10.0)
    assert out["age_group"].iloc[0] == "25-29"
