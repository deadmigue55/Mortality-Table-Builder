"""Tests for Lee-Carter, CBD, simulation, closure, cohorts and the R cross-check."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import lifetable, rates
from mortality import projection as p


def synthetic(n_years=50, seed=0, exposure=5e6, drift=-1.0, sigma=0.0):
    """Poisson deaths from an exact Lee-Carter surface, with the truth."""
    rng = np.random.default_rng(seed)
    ages = p.AGES
    ax = -9.0 + 0.085 * ages
    bx = np.exp(-(((ages - 55) / 30.0) ** 2))
    bx = bx / bx.sum()
    k = drift * (np.arange(n_years) - (n_years - 1) / 2)
    if sigma:
        k = k + np.cumsum(rng.normal(0, sigma, n_years))
        k -= k.mean()
    m = np.exp(ax[:, None] + bx[:, None] * k[None, :] * 10)
    e = np.full(m.shape, exposure)
    return rng.poisson(m * e).astype(float), e, ax, bx, k * 10, m


def test_lee_carter_recovers_the_surface():
    d, e, _ax, _bx, k, m = synthetic()
    fit = p.fit_lee_carter(d, e, np.arange(1970, 2020))
    assert fit.bx.sum() == pytest.approx(1.0)
    assert fit.kt.mean() == pytest.approx(0.0, abs=1e-9)
    assert np.abs(fit.fitted_rates() / m - 1).max() < 0.06
    # the period index is recovered up to the identification (it is already centred)
    assert np.corrcoef(fit.kt, k)[0, 1] > 0.999
    assert np.diff(fit.kt).mean() == pytest.approx(np.diff(k).mean(), rel=0.02)


def test_lee_carter_converges_and_lowers_deviance():
    d, e, *_ = synthetic(n_years=40)
    short = p.fit_lee_carter(d, e, max_iter=2)
    full = p.fit_lee_carter(d, e)
    assert full.iterations < 2000
    assert full.deviance < short.deviance


def test_history_arrays_demands_a_complete_rectangle():
    d, e, *_ = synthetic(n_years=3)
    rows = [(2000 + j, "M", a, d[a, j], e[a, j]) for a in range(100) for j in range(3)]
    df = pd.DataFrame(rows, columns=["year", "sex", "age", "deaths", "exposure"])
    deaths, _, years = p.history_arrays(df, "M")
    assert deaths.shape == (100, 3) and years.tolist() == [2000, 2001, 2002]
    with pytest.raises(ValueError, match="ages 0 to 99"):
        p.history_arrays(df[df["age"] != 50], "M")


def test_random_walk_estimates_drift_and_noise():
    rng = np.random.default_rng(1)
    series = np.cumsum(rng.normal(-0.5, 0.3, 400))
    walk = p.fit_random_walk(series)
    assert walk.drift[0] == pytest.approx(-0.5, abs=0.05)
    assert np.sqrt(walk.cov[0, 0]) == pytest.approx(0.3, abs=0.03)
    assert walk.last[0] == series[-1]


def test_simulated_walk_has_the_right_mean_and_a_widening_fan():
    walk = p.RandomWalk(np.array([10.0]), np.array([-1.0]), np.array([[0.25]]), 41)
    paths = p.simulate_walk(walk, 30, 20000, np.random.default_rng(0), drift_uncertainty=False)
    assert paths.shape == (20000, 30, 1)
    assert paths[:, 9, 0].mean() == pytest.approx(10 - 10, abs=0.05)
    assert paths[:, 29, 0].std() == pytest.approx(0.5 * np.sqrt(30), rel=0.03)
    wider = p.simulate_walk(walk, 30, 20000, np.random.default_rng(0), drift_uncertainty=True)
    assert wider[:, 29, 0].std() > paths[:, 29, 0].std()  # an unknown drift adds spread
    assert wider[:, 29, 0].mean() == pytest.approx(paths[:, 29, 0].mean(), abs=0.1)


def test_multivariate_walk_keeps_the_correlation():
    cov = np.array([[1.0, 0.8], [0.8, 1.0]])
    walk = p.RandomWalk(np.zeros(2), np.zeros(2), cov, 100)
    paths = p.simulate_walk(walk, 1, 50000, np.random.default_rng(2), drift_uncertainty=False)
    assert np.corrcoef(paths[:, 0, 0], paths[:, 0, 1])[0, 1] == pytest.approx(0.8, abs=0.02)


def test_forecast_starts_at_the_jump_off_rates():
    d, e, *_ = synthetic()
    fit = p.fit_lee_carter(d, e, np.arange(1970, 2020))
    observed = d[:, -1] / e[:, -1]
    paths = p.forecast_lee_carter(fit, 5, 200, seed=1, jump_off=observed, drift_uncertainty=False)
    assert paths.shape == (200, 5, 100)
    # one step on: the observed rates moved by b(x) times the drift, nothing else
    drift = np.diff(fit.kt).mean()
    expected = observed * np.exp(fit.bx * drift)
    assert np.abs(np.median(paths[:, 0, :], axis=0) / expected - 1).max() < 0.01
    free = p.forecast_lee_carter(fit, 5, 200, seed=1, drift_uncertainty=False)
    assert free.shape == paths.shape
    assert np.isfinite(paths).all() and (paths > 0).all()


def test_central_path_follows_the_drift_with_no_noise():
    d, e, *_ = synthetic()
    fit = p.fit_lee_carter(d, e, np.arange(1970, 2020))
    central = p.central_lee_carter(fit, 10)
    drift = np.diff(fit.kt).mean()
    assert np.log(central[9] / central[0]) == pytest.approx(fit.bx * 9 * drift)
    recent = p.central_lee_carter(fit, 10, drift_from=10)
    assert recent.shape == central.shape


def test_lower_drift_means_slower_improvement():
    d, e, *_ = synthetic(sigma=0.05, n_years=60)
    fit = p.fit_lee_carter(d, e, np.arange(1960, 2020))
    fast = p.period_measures(p.central_lee_carter(fit, 30)[-1], 0, "M")["e65"]
    flat = fit.kt.copy()
    flat[-20:] = flat[-20]  # stagnation over the last 20 years
    fit_flat = p.LeeCarter(fit.ax, fit.bx, flat, fit.years, fit.deviance, fit.iterations)
    slow = p.period_measures(p.central_lee_carter(fit_flat, 30, drift_from=20)[-1], 0, "M")["e65"]
    assert fast > slow


def test_cbd_recovers_two_factors():
    ages = p.CBD_AGES
    years = np.arange(40)
    k1 = -2.8 - 0.012 * years
    k2 = 0.09 + 0.0002 * years
    x = ages - ages.mean()
    q = 1 / (1 + np.exp(-(k1[None, :] + k2[None, :] * x[:, None])))
    m = q / (1 - 0.5 * q)
    deaths = np.zeros((100, 40))
    exposure = np.full((100, 40), 1e7)
    deaths[60:] = m * exposure[60:]
    fit = p.fit_cbd(deaths, exposure, years)
    assert fit.kappa[0] == pytest.approx(k1, abs=0.01)
    assert fit.kappa[1] == pytest.approx(k2, abs=0.002)
    assert fit.fitted_rates() == pytest.approx(m, rel=0.02)
    sims = p.forecast_cbd(fit, 10, 100, seed=0, drift_uncertainty=False)
    assert sims.shape == (100, 10, 40)
    jumped = p.forecast_cbd(fit, 10, 100, seed=0, jump_off=m[:, -1] * 1.1, drift_uncertainty=False)
    assert np.median(jumped[:, 0], axis=0) == pytest.approx(m[:, -1] * 1.1, rel=0.05)


def full_rates(first_age=0):
    """Rates that the logistic closure reproduces exactly (logit m is linear in age)."""
    ages = np.arange(first_age, 111)
    m = 1 / (1 + np.exp(-(-9.0 + 0.1 * ages)))
    return ages, m


def test_closure_reproduces_a_logistic_and_leaves_young_ages_alone():
    _, m = full_rates()
    closed = p.close_old_ages(m[:100])
    assert closed.shape == (111,)
    assert closed == pytest.approx(m, rel=1e-6)
    _, adult = full_rates(60)
    assert p.close_old_ages(adult[:40], 60) == pytest.approx(adult, rel=1e-6)
    junk = m[:100].copy()
    junk[90:] = 0.9  # ages 90-99 are ignored
    assert p.close_old_ages(junk) == pytest.approx(m, rel=1e-6)


def test_vectorised_measures_match_the_life_table_module():
    ages, m = full_rates()
    q = m / (1 + 0.5 * m)
    q[0] = float(rates.mx_to_qx(m[0], 0, "F"))
    q[-1] = 1.0
    table = lifetable.build_life_table(
        ages, q, ax=lifetable.average_years_in_death_year(q, m), terminal_mx=m[-1]
    )
    measures = p.period_measures(m[:100], 0, "F")
    assert float(measures["e0"]) == pytest.approx(table["ex"].iloc[0], abs=1e-6)
    assert float(measures["e65"]) == pytest.approx(table["ex"].iloc[65], abs=1e-6)
    comm = lifetable.Commutation.from_table(table, 0.04)
    assert float(measures["a65"]) == pytest.approx(float(comm.annuity_due(65)), abs=1e-6)


def test_measures_work_on_whole_arrays_and_start_at_65():
    _, m = full_rates()
    batch = np.stack([m[:100], m[:100] * 0.9, m[:100] * 1.1])[None, :, :]  # (1, 3, 100)
    out = p.period_measures(batch, 0, "M")
    assert out["e0"].shape == (1, 3)
    assert out["e0"][0, 1] > out["e0"][0, 0] > out["e0"][0, 2]  # lower rates, longer lives
    adult = p.period_measures(batch[..., 60:], 60, "M")
    assert adult["e65"][0, 1] > adult["e65"][0, 2]
    assert "e0" not in adult


def test_quantiles_run_over_paths():
    values = np.arange(100.0)[:, None] * np.ones((100, 3))
    q = p.quantiles(values)
    assert q.shape == (5, 3)
    assert (np.diff(q, axis=0) >= 0).all()


def test_sex_floor_raises_men_only_where_below_women():
    ages = np.arange(0, 111)
    rows = []
    for sex, level in (("M", 0.9), ("F", 1.0)):
        base = 1 / (1 + np.exp(-(-9.0 + 0.1 * ages))) * (level if sex == "M" else 1.0)
        rows.append(pd.DataFrame({"year": 2030, "sex": sex, "age": ages, "mx": base,
                                  "qx": base / (1 + 0.5 * base)}))  # fmt: skip
    out = p.apply_sex_floor(pd.concat(rows, ignore_index=True))
    m = out[out["sex"] == "M"].set_index("age")
    f = out[out["sex"] == "F"].set_index("age")
    assert (m["mx"] >= f["mx"] - 1e-12)[ages >= 84].all()
    assert m.loc[40, "mx"] < f.loc[40, "mx"]  # below the floor age: untouched


def test_cohort_exceeds_period_when_mortality_improves():
    _ages, m = full_rates()
    years = np.arange(2025, 2116)
    improving = np.stack([m * np.exp(-0.01 * (y - 2025)) for y in years])
    closed = p.close_old_ages(improving[:, :100])
    rows = p._cohort_rows("M", years, closed)
    df = pd.DataFrame(rows)
    assert (df["cohort_e65"] > df["period_e65"]).all()
    assert (df["annuity_understated_pct"] > 0).all()
    flat = np.stack([m for _ in years])
    flat_rows = pd.DataFrame(p._cohort_rows("M", years, p.close_old_ages(flat[:, :100])))
    assert flat_rows["cohort_e65"].to_numpy() == pytest.approx(flat_rows["period_e65"].to_numpy())


def test_calibration_scale_follows_the_errors():
    bt = pd.DataFrame(
        {
            "model": "lee_carter_jump_off", "fit_start": p.FIT_START, "sex": "M",
            "horizon": [10, 20, 10], "e0_error": [1.0, 2.0, -1.0],
            "e65_error": [0.5, 0.5, 0.5], "a65_error_pct": [0.02, 0.02, 0.02],
        }
    )  # fmt: skip
    cal = p.backtest_calibration(bt).set_index("measure")
    assert cal.loc["e0", "c"] == pytest.approx(np.sqrt(np.mean([1 / 10, 4 / 20, 1 / 10])))
    assert cal.loc["a65", "kind"] == "relative"


def test_backtest_runs_on_a_small_history_and_scores_the_models():
    rows = []
    for sex, drift in (("M", -0.25), ("F", -0.3)):
        d, e, *_ = synthetic(n_years=60, drift=drift, sigma=0.02, seed=3, exposure=2e6)
        for j in range(60):
            for a in range(100):
                rows.append((1960 + j, sex, a, d[a, j], e[a, j]))
    hist = pd.DataFrame(rows, columns=["year", "sex", "age", "deaths", "exposure"])
    bt = p.backtest(hist, origins=(1989, 1999), starts=(1960,), horizons=(10,), n_paths=100)
    assert set(bt["model"]) == {"lee_carter", "lee_carter_jump_off", "cbd"}
    assert set(bt["sex"]) == {"M", "F"}
    assert (bt["horizon"] == 10).all()
    assert bt["e65_error"].abs().max() < 2.0  # a stable, correctly specified series
    assert bt.loc[bt["model"] == "cbd", "e0_error"].isna().all()


def test_r_crosscheck_returns_none_without_r(tmp_path):
    assert p.run_r_crosscheck(pd.DataFrame(), None, tmp_path / "x.R") is None
    assert p.run_r_crosscheck(pd.DataFrame(), tmp_path / "missing.exe", tmp_path / "x.R") is None
