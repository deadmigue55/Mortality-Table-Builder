"""Numerical proof of the formulas in docs/handbook/03-crude-rates.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from mortality import rates
from mortality.lifetable import average_years_in_death_year

ROOT = Path(__file__).resolve().parents[1]


# ── 3.1: exposure ────────────────────────────────────────────────────────────


def test_mid_year_population_is_the_person_years_of_a_steady_trend():
    """(3.2): exact for a straight-line population; the error for exponential growth is r^2 / 24."""
    t = np.linspace(0, 1, 100_001)
    line = 1000 + 50 * t
    assert np.trapezoid(line, t) == pytest.approx(1000 + 50 * 0.5)  # equals the 1 July value
    for growth in (0.01, 0.05, 0.10):
        exact = (np.exp(growth) - 1) / growth  # integral of exp(r t) over the year
        midyear = np.exp(growth / 2)
        assert midyear / exact == pytest.approx(1 - growth**2 / 24, rel=0.02)
        assert midyear / exact == pytest.approx(growth / (2 * np.sinh(growth / 2)))


# ── 3.2: intervals ───────────────────────────────────────────────────────────


def test_garwood_limits_are_chi_square_quantiles():
    """(3.4): the limits are chi-square quantiles with 2d and 2d + 2 degrees of freedom, over 2."""
    d = np.array([1, 5, 12, 40, 300])
    lower, upper = rates.poisson_interval(d)
    assert lower == pytest.approx(stats.chi2.ppf(0.025, 2 * d) / 2)
    assert upper == pytest.approx(stats.chi2.ppf(0.975, 2 * d + 2) / 2)


def test_garwood_limits_solve_the_tail_equations():
    """(3.3): P(N >= d | lower) = 2.5% and P(N <= d | upper) = 2.5%, for integer counts."""
    for d in (1, 4, 12, 90):
        lower, upper = rates.poisson_interval(d)
        assert stats.poisson.sf(d - 1, lower) == pytest.approx(0.025)
        assert stats.poisson.cdf(d, upper) == pytest.approx(0.025)


def test_garwood_toy_example_and_the_zero_count():
    """Section 3.10: 12 deaths in 1,000 person-years; zero deaths: upper limit -ln(0.025)."""
    lower, upper = rates.rate_interval(12, 1000)
    assert (lower, upper) == pytest.approx((0.0062006, 0.0209616), abs=1e-7)
    assert rates.poisson_interval(0)[0] == 0.0
    assert rates.poisson_interval(0)[1] == pytest.approx(-np.log(0.025))


def test_garwood_never_covers_less_than_95_percent():
    """(3.5): the exact interval is conservative: coverage is at least 95% for every true mean."""
    for mean in (0.5, 1, 3.7, 12, 50, 200):
        counts = np.arange(0, int(mean * 4 + 40))
        lower, upper = rates.poisson_interval(counts)
        covered = (lower <= mean) & (mean <= upper)
        coverage = (stats.poisson.pmf(counts, mean) * covered).sum()
        assert 0.95 <= coverage <= 1.0


def test_for_large_counts_garwood_is_the_normal_interval():
    """(3.6): d +- 1.96 sqrt(d) once the count is in the thousands."""
    lower, upper = rates.poisson_interval(40_000)
    assert lower == pytest.approx(40_000 - 1.96 * 200, rel=2e-4)
    assert upper == pytest.approx(40_000 + 1.96 * 200, rel=2e-4)


# ── 3.3: from a rate to a probability ────────────────────────────────────────


def test_q_from_m_and_back():
    """(3.7), (3.8): q = m / (1 + (1 - a) m); above infancy the inverse is m = q / (1 - q / 2)."""
    m = np.linspace(0.0005, 0.4, 40)
    q = rates.mx_to_qx(m, np.full(40, 30), np.full(40, "M"))
    assert q == pytest.approx(m / (1 + 0.5 * m))
    assert rates.qx_to_mx(q) == pytest.approx(m)
    assert average_years_in_death_year(q, m) == pytest.approx(0.5)  # chapter 5's phi, recovered


def test_the_infant_separation_factor_and_its_two_regimes():
    """(3.9): a0 rises with infant mortality; above m0 = 0.107 it is the constant 0.33 or 0.35."""
    assert rates.infant_ax(0.01, "M") == pytest.approx(0.045 + 2.684 * 0.01)
    assert rates.infant_ax(0.01, "F") == pytest.approx(0.053 + 2.800 * 0.01)
    assert rates.infant_ax(0.2, "M") == 0.33 and rates.infant_ax(0.2, "F") == 0.35
    # the two regimes nearly meet at the switch point (within 0.003)
    assert abs(rates.infant_ax(0.107, "M") - (0.045 + 2.684 * 0.107)) < 0.003
    assert abs(rates.infant_ax(0.107, "F") - (0.053 + 2.800 * 0.107)) < 0.003
    # Mexico's infant rate (m0 about 0.008) gives a0 of about 0.07, as chapter 5 says
    assert rates.infant_ax(0.0082, "F") == pytest.approx(0.076, abs=0.005)


# ── 3.4 and 3.5: tidying the counts ──────────────────────────────────────────


def test_pooling_the_open_age_conserves_deaths_and_exposure():
    """(3.10): ages at and above 100 are added on both sides, so no death or person-year is lost."""
    ages = np.arange(95, 106)
    deaths = pd.DataFrame({"year": 2020, "sex": "M", "age": ages, "deaths": np.arange(11.0)})
    pop = pd.DataFrame({"year": 2020, "sex": "M", "age": ages, "population": 100.0 + ages})
    out = rates.crude_single(deaths, pop)
    assert out["deaths"].sum() == deaths["deaths"].sum()
    assert out["exposure"].sum() == pop["population"].sum()
    top = out[out["age"] == 100].iloc[0]
    assert top["deaths"] == deaths.loc[deaths["age"] >= 100, "deaths"].sum()
    assert top["mx"] == pytest.approx(top["deaths"] / top["exposure"])


def test_unknown_sex_and_age_are_spread_in_proportion_and_nothing_is_lost():
    """(3.11), (3.12): the allocation keeps the yearly total and the male-to-female ratio."""
    cube = pd.DataFrame(
        {
            "reg_year": 2016,
            "age_lo": [30.0, 30.0, 30.0, 60.0, 60.0, 60.0, np.nan, np.nan, np.nan],
            "sex": ["M", "F", "U", "M", "F", "U", "M", "F", "U"],
            "deaths": [60.0, 20.0, 20.0, 150.0, 50.0, 0.0, 10.0, 10.0, 0.0],
        }
    )
    out = rates.allocate_cube_unknowns(cube)
    assert out["deaths"].sum() == pytest.approx(cube["deaths"].sum())  # 320 in, 320 out
    # step 1 sends 3/4 of the unknown-sex deaths at 30 to men and 1/4 to women: 75 and 25
    # step 2 then adds the unknown-age deaths of each sex (10 and 10) in proportion to the
    # known deaths of that sex: men are 225 known, women 75 known
    row30 = out[out["band"] == rates.band_index(30)].set_index("sex")["deaths"]
    assert row30["M"] == pytest.approx(75 * (1 + 10 / 225))
    assert row30["F"] == pytest.approx(25 * (1 + 10 / 75))
    row60 = out[out["band"] == rates.band_index(60)].set_index("sex")["deaths"]
    assert row60["M"] / row30["M"] == pytest.approx(150 / 75)  # ages keep their relative sizes
    assert out.groupby("sex")["deaths"].sum().to_dict() == pytest.approx({"F": 85.0, "M": 235.0})


# ── 3.6: age standardisation ─────────────────────────────────────────────────


def test_the_segi_weights_add_to_100000():
    """The Segi world standard has 18 groups and 100,000 people."""
    assert len(rates.SEGI_WEIGHTS) == 18 and sum(rates.SEGI_WEIGHTS) == 100_000


def test_standardisation_toy_two_populations_one_set_of_rates():
    """(3.13): same rates, different age mix: crude rates differ, the standardised rate does not."""
    rate = np.array([0.001, 0.02])
    young_heavy = np.array([80_000.0, 20_000.0])
    old_heavy = np.array([20_000.0, 80_000.0])
    crude = [(rate * n).sum() / n.sum() for n in (young_heavy, old_heavy)]
    assert crude == pytest.approx([0.0048, 0.0162])
    for n in (young_heavy, old_heavy):
        assert rates.standardise(rate * n, n, [1, 1])["asr"] == pytest.approx(0.0105)  # (3.13)


def test_the_standardised_rate_is_a_weighted_mean_of_the_group_rates():
    """(3.13): weights are rescaled to add to 1, so only their proportions matter."""
    d, n = np.array([5.0, 30.0, 90.0]), np.array([1e4, 8e3, 5e3])
    a = rates.standardise(d, n, [1, 2, 3])["asr"]
    b = rates.standardise(d, n, [100, 200, 300])["asr"]
    assert a == pytest.approx(b) == pytest.approx((np.array([1, 2, 3]) / 6 * d / n).sum())


def test_fay_feuer_with_one_group_is_the_garwood_interval():
    """(3.15), (3.16): for a single age group the gamma interval reduces to (3.4) exactly."""
    out = rates.standardise([12.0], [1000.0], [1.0])
    lower, upper = rates.rate_interval(12, 1000)
    assert out["asr"] == pytest.approx(0.012)
    assert out["asr_lower"] == pytest.approx(lower)
    assert out["asr_upper"] == pytest.approx(upper)


def test_fay_feuer_brackets_the_rate_and_matches_the_variance_formula():
    """(3.14): v = sum of w^2 d / n^2, and the interval is the gamma with that mean and variance."""
    d, n, w = np.array([40.0, 120.0, 400.0]), np.array([2e4, 1e4, 4e3]), np.array([3, 2, 1.0])
    out = rates.standardise(d, n, w)
    wn = w / w.sum()
    y, v = (wn * d / n).sum(), (wn**2 * d / n**2).sum()
    assert out["asr"] == pytest.approx(y)
    assert out["asr_lower"] == pytest.approx(v / (2 * y) * stats.chi2.ppf(0.025, 2 * y**2 / v))
    assert out["asr_lower"] < y < out["asr_upper"]
    # the interval widens with the weights on thin groups: halve the exposure, widen the interval
    thin = rates.standardise(d / 2, n / 2, w)
    assert thin["asr_upper"] - thin["asr_lower"] > out["asr_upper"] - out["asr_lower"]


# ── 3.7: indirect standardisation ────────────────────────────────────────────


def test_smr_toy_example_and_conservation():
    """(3.17): expected deaths add up to observed deaths; the toy SMRs are 1.152 and 0.960."""
    obs = pd.DataFrame(
        {
            "state": ["X", "X", "Y", "Y"],
            "sex": "M",
            "band": [0, 1, 0, 1],
            "deaths": [12.0, 60.0, 30.0, 200.0],
        }
    )
    pop = pd.DataFrame(
        {
            "state": ["X", "X", "Y", "Y"],
            "sex": "M",
            "band": [0, 1, 0, 1],
            "exposure": [10_000.0, 2_000.0, 30_000.0, 8_000.0],
        }
    )
    out = rates.smr_table(obs, pop, region="state").set_index("state")
    assert out["observed"].sum() == pytest.approx(out["expected"].sum()) == pytest.approx(302)
    assert out.loc["X", "expected"] == pytest.approx(10_000 * 42 / 40_000 + 2_000 * 260 / 10_000)
    assert out.loc["X", "smr"] == pytest.approx(72 / 62.5)
    assert out.loc["Y", "smr"] == pytest.approx(230 / 239.5)
    lower, upper = rates.ae_interval(72, 62.5)
    assert (out.loc["X", "smr_lower"], out.loc["X", "smr_upper"]) == pytest.approx((lower, upper))


# ── 3.8: actual versus expected ──────────────────────────────────────────────


def test_ae_with_a_flat_table_and_its_interval():
    """(3.18): expected = exposure x the table's central rate; the interval treats it as fixed."""
    ages = np.arange(25, 85)
    pop = pd.DataFrame({"year": 2019, "sex": "M", "age": ages, "population": 1e5})
    q = pd.Series(0.004, index=np.arange(0, 111))
    expected = rates.expected_deaths(pop, q, "M")
    assert expected["expected"].sum() == pytest.approx(
        60 * 1e5 * 0.004 / (1 - 0.002)
    )  # m = q/(1-q/2)
    lower, upper = rates.ae_interval(1500, 1200)
    half = 1.96 * np.sqrt(1500)
    assert (lower, upper) == pytest.approx(((1500 - half) / 1200, (1500 + half) / 1200), rel=3e-3)


# ── 3.9: credibility threshold ───────────────────────────────────────────────


def test_classical_full_credibility_standard_is_1082_deaths():
    """(3.19): n_F = (z / k)^2 = 1,082 for 90% confidence of being within 5%."""
    z = stats.norm.ppf(0.95)
    assert (z / 0.05) ** 2 == pytest.approx(1082.2, abs=0.1)
    # and a Poisson count of that size really lands within 5% about 90% of the time
    rng = np.random.default_rng(9)
    draws = rng.poisson(1082, 400_000)
    assert np.mean(np.abs(draws - 1082) <= 0.05 * 1082) == pytest.approx(0.90, abs=0.01)
    assert rates.THIN_CELL_DEATHS == 30  # the project's floor for "noise", far below 1,082


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
    """Section 3.11: standardised rates, the two bases, the CNSF A/E and the state extremes."""
    asr = pd.read_sql("SELECT * FROM age_standardised_rates WHERE sex IN ('M', 'F')", demo)
    asr = asr.set_index(["sex", "year"])["asr"] * 1e5
    men_before = asr.loc["M"].loc[2014:2019]
    assert (round(men_before.min()), round(men_before.max())) == (615, 637)
    assert round(asr.loc[("M", 2020)]) == 960 and round(asr.loc[("M", 2024)]) == 614
    assert asr.loc[("M", 2020)] / asr.loc[("M", 2019)] - 1 == pytest.approx(0.507, abs=0.002)
    assert round(asr.loc[("F", 2019)]) == 417 and round(asr.loc[("F", 2021)]) == 588

    bridge = pd.read_sql("SELECT * FROM basis_bridge WHERE year >= 2020", demo)
    assert bridge["registered_to_occurred"].between(0.994, 1.007).all()

    ae = pd.read_sql(
        "SELECT * FROM benchmark_ae WHERE benchmark LIKE 'CNSF M 2013%' AND age_group = '25-84' "
        "AND year = 2019",
        demo,
    ).set_index("sex")["ae"]
    assert (round(ae["M"], 2), round(ae["F"], 2)) == (3.03, 1.85)

    smr = pd.read_sql("SELECT state_name, smr FROM state_smr", demo).set_index("state_name")["smr"]
    assert len(smr) == 32
    assert smr.idxmax() == "Chihuahua" and round(smr.max(), 2) == 1.19
    assert smr.idxmin() == "Sinaloa" and round(smr.min(), 2) == 0.81

    cube = pd.read_sql("SELECT reg_year, age_lo, sex, deaths FROM inegi_cube_registered", demo)
    unknown = cube[(cube["sex"] == "U") | cube["age_lo"].isna()].groupby("reg_year")["deaths"].sum()
    share = unknown / cube.groupby("reg_year")["deaths"].sum() * 100
    assert (round(share.min(), 1), round(share.max(), 1)) == (0.5, 0.7)

    single = pd.read_sql("SELECT credible FROM crude_rates_single", demo)
    assert len(single) == 1010 and single["credible"].all()
