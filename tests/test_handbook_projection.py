"""Numerical proof of the formulas in docs/handbook/06-projection.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import special

from mortality import projection as proj
from mortality import rates
from mortality.lifetable import Commutation, build_life_table

ROOT = Path(__file__).resolve().parents[1]
AGES = proj.AGES
YEARS = 40


def synthetic_history(seed: int = 1):
    """Poisson deaths from a known Lee-Carter surface: returns deaths, exposure and the truth."""
    rng = np.random.default_rng(seed)
    a = np.where(AGES < 5, -6.0 - 0.8 * AGES, -9.0 + 0.085 * AGES)
    b = np.exp(-(((AGES - 40) / 35.0) ** 2)) + 0.3
    b = b / b.sum()
    k = -1.2 * np.arange(YEARS) + np.cumsum(rng.normal(0, 0.4, YEARS))
    k = k - k.mean()
    exposure = np.tile(3e5 * np.exp(-0.02 * AGES)[:, None], (1, YEARS))
    deaths = rng.poisson(exposure * np.exp(a[:, None] + b[:, None] * k[None, :])).astype(float)
    return deaths, exposure, (a, b, k)


@pytest.fixture(scope="module")
def fitted():
    deaths, exposure, truth = synthetic_history()
    return proj.fit_lee_carter(deaths, exposure), deaths, exposure, truth


# ── 6.2: Lee-Carter ──────────────────────────────────────────────────────────


def test_lee_carter_identification(fitted):
    """(6.2): the fit satisfies sum b = 1 and sum k = 0, which pin down the otherwise free scale."""
    fit, *_ = fitted
    assert fit.bx.sum() == pytest.approx(1.0)
    assert fit.kt.sum() == pytest.approx(0.0, abs=1e-9)


def test_shifting_and_rescaling_leave_the_fitted_rates_unchanged(fitted):
    """(6.2): (a + b s, k - s) and (b / c, c k) describe the same surface, hence the constraints."""
    fit, *_ = fitted
    base = fit.ax[:, None] + fit.bx[:, None] * fit.kt[None, :]
    shift, scale = 0.7, 3.0
    shifted = (fit.ax + fit.bx * shift)[:, None] + fit.bx[:, None] * (fit.kt - shift)[None, :]
    rescaled = fit.ax[:, None] + (fit.bx / scale)[:, None] * (scale * fit.kt)[None, :]
    assert shifted == pytest.approx(base)
    assert rescaled == pytest.approx(base)


def test_lee_carter_solves_the_poisson_score_equations(fitted):
    """(6.4): at the optimum each age reproduces its deaths and every score is zero."""
    fit, deaths, exposure, _ = fitted
    gap = deaths - exposure * fit.fitted_rates()
    scale = deaths.sum(axis=1).max()
    assert np.abs(gap.sum(axis=1)).max() / scale < 1e-6  # d logL / d a_x
    assert np.abs((gap * fit.bx[:, None]).sum(axis=0)).max() / scale < 1e-6  # d logL / d k_t
    assert np.abs((gap * fit.kt[None, :]).sum(axis=1)).max() / scale < 1e-6  # d logL / d b_x
    assert (exposure * fit.fitted_rates()).sum(axis=1) == pytest.approx(
        deaths.sum(axis=1), rel=1e-6
    )


def test_lee_carter_recovers_a_known_surface(fitted):
    """Section 6.2: Poisson data from a known surface give back its index and its shape."""
    fit, deaths, _exposure, (a, b, k) = fitted
    assert np.corrcoef(fit.kt, k)[0, 1] > 0.999
    assert np.corrcoef(fit.bx, b)[0, 1] > 0.97
    truth = np.exp(a[:, None] + b[:, None] * k[None, :])
    well_measured = deaths > 2000  # cells with enough deaths to judge
    ratio = fit.fitted_rates()[well_measured] / truth[well_measured]
    assert np.abs(ratio - 1).max() < 0.03


# ── 6.3: forecasting the index ───────────────────────────────────────────────


def test_the_drift_is_the_mean_first_difference_which_telescopes():
    """(6.6): drift = (k_T - k_1) / (T - 1); the variance is that of the differences."""
    rng = np.random.default_rng(3)
    series = np.cumsum(rng.normal(-1.0, 0.5, 45))
    walk = proj.fit_random_walk(series)
    assert walk.drift[0] == pytest.approx((series[-1] - series[0]) / 44)
    assert walk.cov[0, 0] == pytest.approx(np.var(np.diff(series), ddof=1))
    assert walk.n == 45 and walk.last[0] == series[-1]


def test_the_forecast_spread_grows_with_the_square_root_of_the_horizon_plus_the_drift_term():
    """(6.7): Var k(T+h) = h s^2 + h^2 s^2 / (n - 1); the second term is the uncertain drift."""
    rng = np.random.default_rng(5)
    series = np.cumsum(rng.normal(-1.0, 0.5, 41))
    walk = proj.fit_random_walk(series)
    s2, n = walk.cov[0, 0], walk.n
    for h in (1, 10, 30):
        with_drift = proj.simulate_walk(walk, h, 200_000, np.random.default_rng(h))[:, h - 1, 0]
        without = proj.simulate_walk(walk, h, 200_000, np.random.default_rng(h), False)[:, h - 1, 0]
        assert with_drift.mean() == pytest.approx(walk.last[0] + h * walk.drift[0], abs=0.03 * h)
        assert with_drift.var() == pytest.approx(h * s2 + h**2 * s2 / (n - 1), rel=0.03)
        assert without.var() == pytest.approx(h * s2, rel=0.03)
    # at 30 years the uncertain drift contributes 30 / (n - 1) = 75% as much variance as the noise
    assert 30**2 * s2 / (n - 1) / (30 * s2) == pytest.approx(0.75)


def test_drift_example_by_hand():
    """Section 6.8: k = 0, -1.2, ... gives drift -1.1, noise 0.06 and variance 2.1 at h = 10."""
    series = np.array([0.0, -1.2, -2.1, -3.5, -4.4])
    walk = proj.fit_random_walk(series)
    assert walk.drift[0] == pytest.approx(-1.1)
    assert walk.cov[0, 0] == pytest.approx(0.06)
    h, n = 10, 5
    assert series[-1] + h * walk.drift[0] == pytest.approx(-15.4)
    noise, drift_part = h * 0.06, h**2 * 0.06 / (n - 1)
    assert (noise, drift_part, noise + drift_part) == pytest.approx((0.6, 1.5, 2.1))
    paths = proj.simulate_walk(walk, h, 400_000, np.random.default_rng(0))[:, h - 1, 0]
    assert paths.var() == pytest.approx(2.1, rel=0.02)


def test_jump_off_restarts_from_the_observed_rates(fitted):
    """(6.8): m(x, T + h) = m_obs(x) exp(b(x) [k(T + h) - k(T)])."""
    fit, deaths, exposure, _ = fitted
    last = deaths[:, -1] / exposure[:, -1]
    paths = proj.forecast_lee_carter(fit, 6, n_paths=4, seed=9, jump_off=last)
    walk = proj.fit_random_walk(fit.kt)
    walk.last = fit.kt[-1:]
    k_paths = proj.simulate_walk(walk, 6, 4, np.random.default_rng(9))[..., 0]
    manual = last[None, None, :] * np.exp(fit.bx[None, None, :] * (k_paths - fit.kt[-1])[..., None])
    assert paths == pytest.approx(manual)
    plain = proj.forecast_lee_carter(fit, 6, n_paths=4, seed=9)
    fitted_last = np.exp(fit.ax + fit.bx * fit.kt[-1])
    assert plain == pytest.approx(
        fitted_last[None, None, :]
        * np.exp(fit.bx[None, None, :] * (k_paths - fit.kt[-1])[..., None])
    )
    assert not np.allclose(plain, paths)  # the two restarts differ by the gap in the last year


def test_the_central_path_moves_by_the_drift_alone(fitted):
    """Section 6.3: the central projection is the random walk with its noise switched off."""
    fit, deaths, exposure, _ = fitted
    last = deaths[:, -1] / exposure[:, -1]
    drift = (fit.kt[-1] - fit.kt[0]) / (len(fit.kt) - 1)
    central = proj.central_lee_carter(fit, 5, jump_off=last)
    assert central[2] == pytest.approx(last * np.exp(fit.bx * 3 * drift))


# ── 6.4: Cairns-Blake-Dowd ───────────────────────────────────────────────────


def test_cbd_factors_are_the_intercept_and_slope_of_logit_q_on_age():
    """(6.9): kappa1 is the mean of logit q over 60-99 and kappa2 the least-squares slope in age."""
    ages = proj.CBD_AGES
    x = ages - ages.mean()
    kappa_true = np.array([-3.2, 0.095])
    q = special.expit(kappa_true[0] + kappa_true[1] * x)
    m = q / (1 - 0.5 * q)
    deaths = np.tile(np.concatenate([np.zeros(60), m * 1e6])[:, None], (1, 3))
    exposure = np.full_like(deaths, 1e6)
    fit = proj.fit_cbd(deaths[:100], exposure[:100])
    assert fit.kappa[:, 0] == pytest.approx(kappa_true, rel=1e-9)  # exact when logit q is linear
    noisy = np.log(q / (1 - q)) + np.sin(np.arange(40))  # add wiggles
    slope = ((x * (noisy - noisy.mean())).sum()) / (x**2).sum()
    assert slope == pytest.approx(np.polyfit(x, noisy, 1)[0])  # (6.9), second form
    assert ages.mean() == 79.5


def test_cbd_forecast_with_jump_off_starts_from_the_observed_logit():
    """(6.10): the logit of q moves by the change in kappa1 plus that in kappa2 times (x - mean)."""
    deaths, exposure, _ = synthetic_history(2)
    fit = proj.fit_cbd(deaths, exposure, np.arange(YEARS))
    last = deaths[60:, -1] / exposure[60:, -1]
    out = proj.forecast_cbd(fit, 4, n_paths=3, seed=4, jump_off=last)
    walk = proj.fit_random_walk(fit.kappa)
    kp = proj.simulate_walk(walk, 4, 3, np.random.default_rng(4))
    change = kp - fit.kappa[:, -1]
    base = special.logit(last / (1 + 0.5 * last))
    x = proj.CBD_AGES - fit.mean_age
    q = special.expit(base + change[..., 0][..., None] + change[..., 1][..., None] * x)
    assert out == pytest.approx(q / (1 - 0.5 * q))


# ── 6.5: closing the table and measuring it ──────────────────────────────────


def test_the_closure_of_an_exact_logistic_is_that_logistic_at_every_age():
    """(6.11): a logit line through ages 75-89 carries rates to 110; exact data stay as they are."""
    a, b = 0.068, 0.091
    all_ages = np.arange(0, 111)
    logistic = special.expit(np.log(a) + b * (all_ages - 80))
    closed = proj.close_old_ages(logistic[:100])
    assert closed == pytest.approx(logistic)
    # ages 90 and over of the input are ignored, so a bad tail changes nothing above 89
    spoiled = logistic[:100].copy()
    spoiled[90:] = 0.02
    assert proj.close_old_ages(spoiled)[90:] == pytest.approx(closed[90:])
    assert proj.close_old_ages(spoiled)[:84] == pytest.approx(closed[:84])


def test_period_measures_agree_with_the_life_table_of_chapter_5():
    """(6.12): e0, e65 and the annuity at 65 equal the life table built the chapter-5 way."""
    ages = np.arange(0, 100)
    mx = 0.0005 + 0.00004 * np.exp(0.1 * ages)
    mx[0] = 0.008
    closed = proj.close_old_ages(mx)
    q = closed / (1 + 0.5 * closed)
    q[0] = rates.mx_to_qx(closed[0], 0, "F")
    q[-1] = 1.0
    phi = np.full(111, 0.5)
    phi[0] = np.clip(1 - (closed[0] / q[0] - 1) / closed[0], 0, 1)
    table = build_life_table(np.arange(111), q, ax=phi, terminal_mx=closed[-1])
    measures = proj.period_measures(mx, 0, "F", interest=0.04)
    assert measures["e0"] == pytest.approx(table["ex"].iloc[0], rel=1e-9)
    assert measures["e65"] == pytest.approx(table["ex"].iloc[65], rel=1e-9)
    commutation = Commutation.from_table(table, 0.04)
    assert measures["a65"] == pytest.approx(commutation.annuity_due(65), rel=1e-9)


# ── 6.6: cohort versus period ────────────────────────────────────────────────


def cohort_by_hand(closed: np.ndarray, first_year: int, year: int, interest: float = 0.04):
    """Annuity-due at 65 for someone who is 65 in ``year``: period table and cohort path."""
    ages = np.arange(65, 111)
    out = []
    for kind in ("period", "cohort"):
        survival, value = 1.0, 0.0
        for j, age in enumerate(ages):
            value += survival / (1 + interest) ** j
            row = year - first_year + (j if kind == "cohort" else 0)
            m = closed[row, age]
            q = 1.0 if age == 110 else m / (1 + 0.5 * m)
            survival *= 1 - q
        out.append(value)
    return out


def test_cohort_annuity_uses_the_rates_of_the_year_each_age_is_reached():
    """(6.13), (6.14): the cohort follows q(65, Y), q(66, Y + 1), ...; a period table stays at Y."""
    first, n_years = 2025, 100
    ages = np.arange(0, 111)
    improvement = 0.015  # mortality falls 1.5% a year at every age
    base = 0.0005 + 0.00004 * np.exp(0.1 * ages)
    closed = base[None, :] * np.exp(-improvement * np.arange(n_years))[:, None]
    rows = {
        r["year_at_65"]: r
        for r in proj._cohort_rows("M", np.arange(first, first + n_years), closed)
    }
    for year in (2030, 2050):
        period, cohort = cohort_by_hand(closed, first, year)
        assert rows[year]["period_a65"] == pytest.approx(period)
        assert rows[year]["cohort_a65"] == pytest.approx(cohort)
        assert rows[year]["annuity_understated_pct"] == pytest.approx(cohort / period - 1)
        assert rows[year]["cohort_e65"] > rows[year]["period_e65"]
    flat = np.tile(base, (n_years, 1))  # no improvement: the two coincide
    still = proj._cohort_rows("M", np.arange(first, first + n_years), flat)[0]
    assert still["cohort_a65"] == pytest.approx(still["period_a65"])
    assert still["cohort_e65"] == pytest.approx(still["period_e65"])


def test_cohort_toy_example_by_arithmetic():
    """Section 6.8: q65 = 0.1, q66 = 0.2, then everything improves 10% a year, no interest."""
    period = 1 + 0.9 + 0.9 * 0.8
    cohort = 1 + 0.9 + 0.9 * (1 - 0.2 * 0.9)
    assert (period, cohort) == pytest.approx((2.62, 2.638))
    assert cohort / period - 1 == pytest.approx(0.0069, abs=1e-4)


# ── 6.7: the backtest and its calibration ────────────────────────────────────


def test_calibration_constant_is_the_root_mean_square_of_error_over_root_horizon():
    """(6.15), (6.16): err = c sqrt(h), so c^2 = mean(err^2 / h); the band is +- 1.645 c sqrt(h)."""
    bt = pd.DataFrame(
        {
            "sex": "M",
            "model": "lee_carter_jump_off",
            "fit_start": proj.FIT_START,
            "horizon": [10, 20],
            "e0_error": [1.0, -2.0],
            "e65_error": [0.5, 0.5],
            "a65_error_pct": [0.01, 0.02],
        }
    )
    cal = proj.backtest_calibration(bt).set_index("measure")
    assert cal.loc["e0", "c"] == pytest.approx(np.sqrt((1 / 10 + 4 / 20) / 2))  # 0.387
    assert round(cal.loc["e0", "c"], 3) == 0.387
    rng = np.random.default_rng(6)
    h = rng.choice([10, 20], 20_000)
    simulated = pd.DataFrame(
        {
            "sex": "F", "model": "lee_carter_jump_off", "fit_start": proj.FIT_START, "horizon": h,
            "e0_error": 0.44 * np.sqrt(h) * rng.standard_normal(h.size),
            "e65_error": 0.0, "a65_error_pct": 0.0,
        }
    )  # fmt: skip
    c = proj.backtest_calibration(simulated).set_index("measure").loc["e0", "c"]
    assert c == pytest.approx(0.44, rel=0.02)
    assert 1.645 * 0.5748 * np.sqrt(26) == pytest.approx(4.82, abs=0.01)  # men's e0 in 2050


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
    """Section 6.9: the period index, the backtest, the calibration, the scenarios, the cohorts."""
    par = pd.read_sql("SELECT * FROM projection_parameters WHERE model = 'lee_carter'", demo)
    for sex, early, late in (("M", -1.86, -0.28), ("F", -2.61, -0.48)):
        k = par[(par["sex"] == sex) & (par["parameter"] == "kt")].sort_values("index")
        year, value = k["index"].to_numpy(), k["value"].to_numpy()
        assert value.sum() == pytest.approx(0.0, abs=1e-6)
        slope_early = np.polyfit(year[year <= 1999], value[year <= 1999], 1)[0]
        slope_late = np.polyfit(year[year >= 2000], value[year >= 2000], 1)[0]
        assert (round(slope_early, 2), round(slope_late, 2)) == (early, late)
        b = par[(par["sex"] == sex) & (par["parameter"] == "bx")]["value"]
        assert b.sum() == pytest.approx(1.0)

    bt = pd.read_sql("SELECT * FROM projection_backtest", demo)
    best = bt[(bt["model"] == "lee_carter_jump_off") & (bt["fit_start"] == 1970)]
    mae = best.groupby("sex")["e65_error"].apply(lambda s: s.abs().mean())
    assert (round(mae["M"], 2), round(mae["F"], 2)) == (0.52, 0.35)
    annuity = best.groupby("sex")["a65_error_pct"].apply(lambda s: s.abs().mean())
    assert (round(annuity["M"] * 100, 1), round(annuity["F"] * 100, 1)) == (1.8, 1.5)
    covered = best.groupby("sex")["in_90"].mean()
    assert (covered["M"], covered["F"]) == (0.4, 0.6)
    old = bt[(bt["model"] == "lee_carter_jump_off") & (bt["fit_start"] == 1950)]
    old_mae = old.groupby("sex")["e65_error"].apply(lambda s: s.abs().mean())
    assert (round(old_mae["M"], 2), round(old_mae["F"], 2)) == (0.66, 0.83)
    cbd = bt[(bt["model"] == "cbd") & (bt["fit_start"] == 1970)]
    cbd_mae = cbd.groupby("sex")["e65_error"].apply(lambda s: s.abs().mean())
    assert (round(cbd_mae["M"], 2), round(cbd_mae["F"], 2)) == (0.56, 0.58)
    shot = best[(best["origin"] == 1999) & (best["horizon"] == 20)].set_index("sex")["e0_error"]
    assert (round(shot["M"], 1), round(shot["F"], 1)) == (3.9, 2.3)

    cal = pd.read_sql("SELECT * FROM projection_calibration", demo).set_index(["sex", "measure"])
    assert [round(cal.loc[("M", m), "c"], 2) for m in ("e0", "e65")] == [0.57, 0.20]
    assert round(cal.loc[("M", "a65"), "c"] * 100, 2) == 0.64
    assert [round(cal.loc[("F", m), "c"], 2) for m in ("e0", "e65")] == [0.44, 0.12]

    sc = pd.read_sql("SELECT * FROM projection_scenarios", demo)

    def median(scenario, sex, measure, year):
        row = sc[(sc["scenario"] == scenario) & (sc["sex"] == sex) & (sc["measure"] == measure)]
        return round(row.loc[row["year"] == year, "p50"].item(), 2)

    assert [median("rebased_long_run", "M", "e0", y) for y in (2030, 2050, 2070)] == [
        74.05, 76.99, 79.51,
    ]  # fmt: skip
    assert [median("rebased_recent", "M", "e0", y) for y in (2030, 2050, 2070)] == [
        73.37, 74.30, 75.09,
    ]  # fmt: skip
    assert median("observed", "M", "a65", 2024) == 12.30
    assert (
        median("rebased_long_run", "M", "a65", 2050),
        median("rebased_recent", "M", "a65", 2050),
    ) == (13.09, 12.52)

    cohort = pd.read_sql("SELECT * FROM cohort_tables WHERE year_at_65 = 2025", demo).set_index(
        "sex"
    )
    assert (round(cohort.loc["M", "period_e65"], 2), round(cohort.loc["M", "cohort_e65"], 2)) == (
        17.61,
        18.43,
    )
    assert round(cohort.loc["M", "annuity_understated_pct"] * 100, 1) == 2.6
    assert round(cohort.loc["F", "annuity_understated_pct"] * 100, 1) == 2.6
    band = sc[(sc["scenario"] == "rebased_long_run") & (sc["sex"] == "M") & (sc["measure"] == "e0")]
    band = band[band["year"] == 2050].iloc[0]
    assert (round(band["p05"], 1), round(band["p95"], 1)) == (75.6, 78.3)

    cross = pd.read_sql("SELECT * FROM projection_r_crosscheck", demo)
    lc = cross[(cross["model"] == "lee_carter") & cross["quantity"].str.contains("in 20")]
    assert lc["difference"].abs().max() < 2e-5
    cbd_kappa = cross[cross["quantity"].str.startswith("kappa")]
    assert cbd_kappa["difference"].abs().max() < 0.054
    gap = pd.read_sql("SELECT * FROM source_gap WHERE year = 2023 AND sex = 'M'", demo)
    gap = gap.set_index("age_band")
    assert 1 - gap.loc["15-39", "ratio"] == pytest.approx(0.34, abs=0.005)
    assert gap.loc[["60-74", "75-89", "90-99"], "ratio"].between(1.10, 1.17).all()
