"""Numerical proof of the formulas in docs/handbook/04-graduation.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from mortality import graduation as g
from mortality.lifetable import average_years_in_death_year

ROOT = Path(__file__).resolve().parents[1]
AGES = np.arange(1, 90)


def gompertz_exact(size: float = 1e6):
    """Exposure and the exact expected deaths of a Gompertz curve (no sampling noise)."""
    truth = 0.00012 * np.exp(0.095 * AGES)
    exposure = size * np.exp(-0.03 * (AGES - 1))
    return exposure * truth, exposure, truth


def noisy_curve(seed: int = 3):
    """Poisson deaths around a smooth curve that is not exactly Gompertz."""
    rng = np.random.default_rng(seed)
    truth = 0.0003 * np.exp(0.085 * AGES) + 0.0004 * np.exp(-0.15 * AGES)
    exposure = 3e5 * np.exp(-0.025 * (AGES - 1))
    return rng.poisson(exposure * truth).astype(float), exposure, truth


# The toy example of section 4.9: three ages, 4 deaths each, exposures 400, 100, 400
TOY_D = np.array([4.0, 4.0, 4.0])
TOY_E = np.array([400.0, 100.0, 400.0])


# ── 4.1 and 4.2: the Poisson model, deviance ─────────────────────────────────


def test_log_of_a_poisson_count_has_variance_one_over_the_mean():
    """(4.2): Var(log D) is about 1 / E[D] for a large count (delta method)."""
    rng = np.random.default_rng(11)
    for mean in (100, 400, 5000):
        draws = rng.poisson(mean, 400_000)
        assert np.var(np.log(draws)) * mean == pytest.approx(1.0, rel=0.03)


def test_deviance_is_twice_the_log_likelihood_gap_to_the_saturated_model():
    """(4.3): deviance = 2 [log L(saturated) - log L(fitted)]; the toy value is 16 sqrt(2) - 20."""
    d = np.array([3.0, 8.0, 15.0, 40.0])
    mu = np.array([4.0, 7.0, 18.0, 35.0])
    saturated = stats.poisson.logpmf(d, d).sum()
    fitted = stats.poisson.logpmf(d, mu).sum()
    assert g.poisson_deviance(d, mu) == pytest.approx(2 * (saturated - fitted))
    near = np.array(
        [100.0, 200.0, 300.0]
    )  # close to the data: deviance is about Pearson's chi-square
    assert g.poisson_deviance(near, near * 1.01) == pytest.approx(
        np.sum((near * 0.01) ** 2 / (near * 1.01)), rel=0.02
    )
    toy_mu = TOY_E * np.array([np.sqrt(2) * 0.01, 0.02, np.sqrt(2) * 0.01])
    assert g.poisson_deviance(TOY_D, toy_mu) == pytest.approx(16 * np.sqrt(2) - 20)


# ── 4.3: Whittaker-Henderson ─────────────────────────────────────────────────


def test_whittaker_henderson_toy_matches_the_handbook():
    """The hand-solved example: smoothed rates (sqrt 2 / 100, 1/50, sqrt 2 / 100) and edf 7/4."""
    fit = g.whittaker_henderson(np.array([1, 2, 3]), TOY_D, TOY_E, order=1, lam=4.0)
    assert fit.mx == pytest.approx([np.sqrt(2) * 0.01, 0.02, np.sqrt(2) * 0.01], rel=1e-12)
    assert fit.edf == pytest.approx(1.75)
    assert fit.deviance == pytest.approx(16 * np.sqrt(2) - 20)
    # the log-variance of (4.8): diag of inv W inv with inv = (I + P)^-1
    inv = np.linalg.inv(np.eye(3) * 4 + 4 * g.difference_penalty(3, 1))
    assert fit.log_var == pytest.approx(np.diag(inv @ (np.eye(3) * 4) @ inv))


def test_whittaker_henderson_solves_the_normal_equations():
    """(4.6): (W + lambda D'D) z = W y, with z the log of the fitted rates; edf is trace(S)."""
    d, e, _ = noisy_curve()
    lam = 80.0
    fit = g.whittaker_henderson(AGES, d, e, order=3, lam=lam)
    y, w = np.log(d / e), np.diag(d)
    lhs = w + lam * g.difference_penalty(len(AGES), 3)
    z = np.log(fit.mx)
    assert lhs @ z == pytest.approx(w @ y, rel=1e-9)
    smoother = np.linalg.solve(lhs, w)
    assert fit.edf == pytest.approx(np.trace(smoother))  # (4.7)
    assert smoother.sum(axis=1) == pytest.approx(
        1.0
    )  # each fitted value is a weighted mean of the y


def test_whittaker_henderson_limits_of_the_smoothing_parameter():
    """(4.9): lambda -> 0 interpolates the crude rates; lambda -> infinity leaves a polynomial."""
    d, e, _ = noisy_curve()
    rough = g.whittaker_henderson(AGES, d, e, order=3, lam=1e-9)
    assert rough.mx == pytest.approx(d / e, rel=1e-5)
    assert rough.edf == pytest.approx(len(AGES), abs=0.01)
    smooth = g.whittaker_henderson(AGES, d, e, order=3, lam=1e12)
    assert np.abs(np.diff(np.log(smooth.mx), 3)).max() < 1e-6  # third differences vanish
    assert smooth.edf == pytest.approx(3.0, abs=0.05)  # the null space has dimension = order


def test_a_curve_in_the_null_space_is_recovered_for_any_smoothing():
    """Order 3 does not touch a parabola in log m; order 2 does not touch a Gompertz line."""
    parabola = np.exp(-7.0 + 0.09 * AGES + 0.0002 * AGES**2)
    e = 1e6 * np.ones(len(AGES))
    for lam in (1.0, 1e4, 1e9):
        fit = g.whittaker_henderson(AGES, parabola * e, e, order=3, lam=lam)
        assert fit.mx == pytest.approx(parabola, rel=1e-6)
    deaths, exposure, truth = gompertz_exact()
    fit = g.whittaker_henderson(AGES, deaths, exposure, order=2, lam=1e8)
    assert fit.mx == pytest.approx(truth, rel=1e-6)


# ── 4.4: Poisson P-spline ────────────────────────────────────────────────────


def spline_coefficients(fit: g.Graduation) -> np.ndarray:
    """Recover theta from the fitted curve: log mx lies exactly in the span of the basis."""
    basis = g.bspline_basis(fit.ages, fit.ages.min(), fit.ages.max(), g.SPLINE_SEGMENTS)
    return np.linalg.lstsq(basis, np.log(fit.mx), rcond=None)[0], basis


def test_pspline_satisfies_the_penalised_score_equation():
    """(4.12): B'(D - mu) = lambda P theta at the optimum, with mu the fitted deaths."""
    d, e, _ = noisy_curve()
    lam = 30.0
    fit = g.pspline(AGES, d, e, lam=lam)
    theta, basis = spline_coefficients(fit)
    penalty = g.difference_penalty(basis.shape[1], 2)
    mu = e * fit.mx
    score = basis.T @ (d - mu)
    assert score == pytest.approx(lam * penalty @ theta, rel=1e-4, abs=1e-4 * np.abs(score).max())


def test_pspline_reproduces_total_deaths():
    """(4.10), (4.14): rows of B add to 1 and P ignores constants, so sum(mu) = sum(D) exactly."""
    d, e, _ = noisy_curve()
    for lam in (0.1, 30.0, 1e5):
        fit = g.pspline(AGES, d, e, lam=lam)
        assert (e * fit.mx).sum() == pytest.approx(d.sum(), rel=1e-6)


def test_pspline_effective_parameters_run_from_the_basis_size_down_to_two():
    """(4.15): edf = K (43) as lambda -> 0 and 2 (its null space) as lambda grows."""
    d, e, _ = noisy_curve()
    assert g.pspline(AGES, d, e, lam=1e-8).edf == pytest.approx(43, abs=0.2)
    assert g.pspline(AGES, d, e, lam=1e10).edf == pytest.approx(2.0, abs=0.02)
    deaths, exposure, truth = gompertz_exact()
    straight = g.pspline(AGES, deaths, exposure, lam=1e10)
    assert straight.mx == pytest.approx(truth, rel=1e-5)  # a Gompertz line is in the null space


def test_pspline_interval_is_the_log_scale_band_scaled_by_the_dispersion():
    """(4.16): the interval is mx * exp(+-z sqrt(v max(psi, 1)))."""
    d, e, _ = noisy_curve()
    fit = g.pspline(AGES, d, e, lam=30.0)
    lower, upper = fit.interval(0.95)
    half = stats.norm.ppf(0.975) * np.sqrt(fit.log_var * max(fit.dispersion, 1.0))
    assert np.log(upper / fit.mx) == pytest.approx(half)
    assert np.log(fit.mx / lower) == pytest.approx(half)


# ── 4.5: choosing the smoothing ──────────────────────────────────────────────


def test_squared_binomial_coefficients_add_to_a_central_binomial():
    """(4.18): the sum of C(k, j)^2 over j is C(2k, k); for k = 4 it is 70."""
    for k in (3, 4, 5):
        assert sum(comb(k, j) ** 2 for j in range(k + 1)) == comb(2 * k, k)
    assert comb(8, 4) == 70


def test_dispersion_is_one_for_poisson_noise_and_recovers_extra_scatter():
    """(4.18): about 1 for pure Poisson counts, about psi when the counts are psi times as noisy.

    One sample of 89 ages is noisy (the differences overlap), so the estimator is judged on the
    average of 200 samples: it is unbiased for psi, and floored at 1 for Poisson data.
    """
    rng = np.random.default_rng(5)
    mean = 2e4 * np.ones(89)

    def average(psi: float) -> float:
        out = []
        for _ in range(200):
            if psi == 1.0:
                counts = rng.poisson(mean)
            else:
                shape = mean / (psi - 1)  # gamma-Poisson mixture: variance = psi * mean
                counts = rng.poisson(rng.gamma(shape, mean / shape))
            out.append(g.noise_dispersion(counts))
        return float(np.mean(out))

    assert 1.0 <= average(1.0) <= 1.15
    assert average(3.0) == pytest.approx(3.0, rel=0.1)
    smooth = np.exp(
        8 + 0.03 * np.arange(89) - 0.0002 * np.arange(89) ** 2
    )  # exactly a parabola in log
    assert g.noise_dispersion(smooth) == 1.0  # nothing left after four differences: the floor of 1


def test_quasi_aic_is_deviance_over_dispersion_plus_twice_the_parameters():
    """(4.17): the table that select_lambda returns obeys it, and the minimum is the choice."""
    d, e, _ = noisy_curve()
    fit = g.pspline(AGES, d, e)
    path = fit.path
    assert path["qaic"].to_numpy() == pytest.approx(
        (path["deviance"] / fit.dispersion + 2 * path["edf"]).to_numpy()
    )
    best = path.loc[path["qaic"].idxmin()]
    assert 10 ** best["log10_lambda"] == pytest.approx(fit.lam)
    assert fit.edf == pytest.approx(best["edf"], rel=1e-6)


# ── 4.6: the laws ────────────────────────────────────────────────────────────


def test_gompertz_doubles_the_force_every_ln2_over_ln_c_years():
    """(4.19): with A = 0, mu(x + ln 2 / ln c) = 2 mu(x); for c = 1.1 that is 7.27 years."""
    c = 1.1
    t = np.log(2) / np.log(c)
    assert t == pytest.approx(7.2725, abs=1e-3)
    x = np.array([40.0, 60.0])
    mu = g.gompertz_makeham(x, (0.0, 3e-5, c))
    assert g.gompertz_makeham(x + t, (0.0, 3e-5, c)) == pytest.approx(2 * mu)
    makeham = g.gompertz_makeham(x, (5e-4, 3e-5, c))
    assert makeham - 5e-4 == pytest.approx(mu)  # A is the age-independent part


def test_heligman_pollard_is_defined_through_the_odds():
    """(4.20): q / p is a sum of three terms; the code returns m = q / (1 - q / 2)."""
    p = (0.0005, 0.01, 0.1, 0.0008, 10.0, 22.0, 4e-5, 1.1)
    a, b, c, d, e, f, gg, h = p
    x = np.arange(1.0, 90.0)
    odds = a ** ((x + b) ** c) + d * np.exp(-e * np.log(x / f) ** 2) + gg * h**x
    q = odds / (1 + odds)
    assert g.heligman_pollard(x, p) == pytest.approx(q / (1 - 0.5 * q))
    assert g.mx_to_q(g.heligman_pollard(x, p)) == pytest.approx(q)  # (4.24) undoes it
    # the three terms dominate in turn: childhood, the hump, old age
    child, hump, old = (a ** ((x + b) ** c)), d * np.exp(-e * np.log(x / f) ** 2), gg * h**x
    assert np.argmax(child) == 0 and 10 < x[np.argmax(hump)] < 30 and np.argmax(old) == len(x) - 1


def test_kannisto_has_linear_log_odds_and_stays_below_one():
    """(4.21): m / (1 - m) = a exp(b (x - 80)); the curve flattens toward 1 instead of exploding."""
    a, b = 0.068, 0.091
    x = np.arange(75.0, 111.0)
    m = g.kannisto(x, (a, b))
    assert np.log(m / (1 - m)) == pytest.approx(np.log(a) + b * (x - 80))
    assert m.max() < 1.0
    assert g.kannisto(np.array([300.0]), (a, b))[0] == pytest.approx(1.0, abs=1e-6)
    gompertz = g.gompertz_makeham(np.array([110.0, 140.0]), (0.0, 3e-5, 1.1))
    assert gompertz[1] > 1.0  # an unbounded exponential passes 1 sooner or later


def test_a_law_is_fitted_by_least_squares_on_deviance_residuals():
    """(4.22): the sum of squared signed deviance residuals is the Poisson deviance."""
    d, e, _ = noisy_curve()
    params, deviance = g.fit_parametric(
        g.gompertz_makeham, AGES[30:], d[30:], e[30:], g.GM_START, g.GM_BOUNDS
    )
    mu = e[30:] * g.gompertz_makeham(AGES[30:], params)
    assert deviance == pytest.approx(g.poisson_deviance(d[30:], mu), rel=1e-9)


# ── 4.7: tests of fit ────────────────────────────────────────────────────────


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # three ages have no third difference
def test_fit_tests_on_the_toy_example():
    """Section 4.9: chi-square, signs and runs of the standardised residuals by hand."""
    mx = np.array([np.sqrt(2) * 0.01, 0.02, np.sqrt(2) * 0.01])
    t = g.fit_tests(TOY_D, TOY_E, mx, edf=1.75)
    expected = TOY_E * mx
    z = (TOY_D - expected) / np.sqrt(expected)
    assert z == pytest.approx([-0.69662, 1.41421, -0.69662], abs=1e-5)
    assert t["chi2"] == pytest.approx(2 * (4 - 4 * np.sqrt(2) / 1) ** 2 / (4 * np.sqrt(2)) + 2.0)
    assert t["df"] == pytest.approx(1.25)
    assert t["runs"] == 3  # the signs go -, +, -: two changes, three runs
    assert t["serial_corr"] == pytest.approx(2 * z[0] * z[1] / (z[0] ** 2 + z[1] ** 2))
    assert t["share_beyond_2"] == 0.0
    assert t["cumulative_dev_z"] == pytest.approx((12 - expected.sum()) / np.sqrt(expected.sum()))


def test_a_perfect_fit_puts_4_point_55_percent_of_residuals_beyond_two():
    """The benchmark quoted for 'share beyond 2': the normal tail beyond two standard deviations."""
    assert 2 * stats.norm.sf(2) == pytest.approx(0.0455, abs=1e-4)
    rng = np.random.default_rng(1)
    mu = 1e5 * np.ones(200_000)
    z = (rng.poisson(mu) - mu) / np.sqrt(mu)
    assert np.mean(np.abs(z) > 2) == pytest.approx(0.0455, abs=0.002)


def test_runs_test_formulas_match_a_direct_count():
    """The mean and variance of the number of runs for n+ positives and n- negatives."""
    z = np.array([1, 1, -1, 1, -1, -1, -1, 1, 1, -1], dtype=float)
    pos, neg = (z > 0).sum(), (z < 0).sum()
    runs = 1 + np.sum(np.sign(z[1:]) != np.sign(z[:-1]))
    n = pos + neg
    mean = 2 * pos * neg / n + 1
    var = 2 * pos * neg * (2 * pos * neg - n) / (n**2 * (n - 1))
    assert (runs, mean) == (6, 6.0)
    assert var == pytest.approx(2 * 5 * 5 * (50 - 10) / (100 * 9))
    # exact enumeration of every arrangement agrees with the formula
    from itertools import combinations

    counts = []
    for chosen in combinations(range(n), pos):
        s = np.full(n, -1.0)
        s[list(chosen)] = 1.0
        counts.append(1 + np.sum(s[1:] != s[:-1]))
    assert np.mean(counts) == pytest.approx(mean)
    assert np.var(counts) == pytest.approx(var)


# ── 4.8: closing the table ───────────────────────────────────────────────────


def test_blend_weights_and_the_geometric_mean():
    """(4.23): the spline weight falls from 1 at 84 to 0 at 90; the mix is on the log scale."""
    ages = np.array([80, 84, 87, 90, 95])
    assert g.blend_weight(ages) == pytest.approx([1.0, 1.0, 0.5, 0.0, 0.0])
    spline_m, kannisto_m = 0.08, 0.2
    w = g.blend_weight(np.array([87.0]))[0]
    mixed = np.exp(w * np.log(spline_m) + (1 - w) * np.log(kannisto_m))
    assert mixed == pytest.approx(np.sqrt(0.08 * 0.2))  # the geometric mean at the midpoint


def test_q_from_m_is_the_separation_factor_formula_with_one_half():
    """(4.24) is (5.5) with phi = 1/2, so chapter 5 recovers phi = 1/2 above infancy."""
    assert g.mx_to_q(0.2) == pytest.approx(0.2 / 1.1)
    m = np.linspace(0.0005, 0.4, 50)
    q = g.mx_to_q(m)
    assert average_years_in_death_year(q, m) == pytest.approx(0.5)


def test_the_assembled_table_runs_from_0_to_110_and_closes_at_one():
    """Section 4.8: infant row, spline to 84, blend 85 to 89, Kannisto from 90, q = 1 at 110."""
    deaths, exposure, _ = gompertz_exact(size=2e6)
    spline = g.pspline(AGES, deaths, exposure)
    age0 = {"mx": 0.008, "mx_lower": 0.0078, "mx_upper": 0.0082, "qx": 0.0079}
    table = g.assemble_table(age0, spline, (0.068, 0.091))
    assert table["age"].tolist() == list(range(0, 111))
    assert table["qx"].iloc[-1] == 1.0
    assert table.loc[table["age"] == 0, "source"].item() == "crude"
    assert set(table.loc[table["age"].between(1, 84), "source"]) == {"pspline"}
    assert set(table.loc[table["age"].between(85, 89), "source"]) == {"blend"}
    assert set(table.loc[table["age"] >= 90, "source"]) == {"kannisto"}
    kan = g.kannisto(np.array([95.0]), (0.068, 0.091))[0]
    assert table.loc[table["age"] == 95, "mx"].item() == pytest.approx(kan)


def test_the_sex_floor_lifts_male_rates_to_female_rates_and_marks_them():
    """(4.25): from age 84 men are never below women; the changed ages carry sex_floor = True."""
    ages = np.arange(0, 111)
    base = pd.DataFrame(
        {"age": ages, "mx": 0.001 * np.exp(0.09 * ages) / (1 + 0.001 * np.exp(0.09 * ages))}
    )
    base["mx_lower"] = base["mx_upper"] = base["mx"]
    base["qx"] = g.mx_to_q(base["mx"])
    base.loc[base["age"] == 110, "qx"] = 1.0
    female = base.copy()
    male = base.copy()
    male.loc[male["age"] >= 92, "mx"] *= 0.8  # men dip below women from 92
    out = g.enforce_sex_order(male, female)
    assert (
        out.loc[out["age"] >= 84, "mx"] >= female.loc[female["age"] >= 84, "mx"].to_numpy()
    ).all()
    assert (
        out.loc[out["age"] >= 92, "sex_floor"].all()
        and not out.loc[out["age"] < 92, "sex_floor"].any()
    )
    assert out.loc[out["age"] == 110, "qx"].item() == 1.0


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
    """Section 4.10: deviance ratios, effective parameters and noise dispersion, from the data."""
    fits = pd.read_sql("select * from graduation_fit_tests", demo)
    d23 = fits[fits["year"] == 2023].set_index(["sex", "method"])
    ratio_f = d23.loc[("F", "heligman_pollard"), "deviance"] / d23.loc[("F", "pspline"), "deviance"]
    ratio_m = d23.loc[("M", "heligman_pollard"), "deviance"] / d23.loc[("M", "pspline"), "deviance"]
    assert (round(ratio_f, 1), round(ratio_m, 1)) == (8.8, 8.7)
    mean_dev = fits.groupby(["sex", "method"])["deviance"].mean().round()
    assert (mean_dev[("F", "pspline")], mean_dev[("M", "pspline")]) == (77, 122)
    assert (mean_dev[("F", "heligman_pollard")], mean_dev[("M", "heligman_pollard")]) == (
        1159,
        2052,
    )
    ps = fits[fits["method"] == "pspline"]
    assert (round(ps["edf"].min()), round(ps["edf"].max())) == (33, 39)
    assert fits[fits["method"] == "heligman_pollard"]["share_beyond_2"].between(0.43, 0.74).all()
    crude = pd.read_sql("select * from crude_rates_single where age between 1 and 89", demo)
    psi = {
        key: g.noise_dispersion(cell["deaths"].to_numpy())
        for key, cell in crude.groupby(["sex", "year"])
    }
    women = [v for (s, _), v in psi.items() if s == "F"]
    men = [v for (s, _), v in psi.items() if s == "M"]
    assert (round(min(women), 2), round(max(women), 2)) == (1.0, 1.69)
    assert (round(min(men), 2), round(max(men), 2)) == (1.85, 3.09)
