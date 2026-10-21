"""Tests for graduation: smoothers, parametric laws, fit tests and the final table."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mortality import graduation as g


def gompertz_data(seed=0, size=2e5, lo=30, hi=89):
    """Poisson deaths from a known Gompertz curve, with its true rates."""
    rng = np.random.default_rng(seed)
    ages = np.arange(lo, hi + 1)
    truth = 0.00012 * np.exp(0.095 * ages)
    exposure = size * np.exp(-0.02 * (ages - lo))
    return ages, rng.poisson(exposure * truth), exposure, truth


def test_bspline_basis_is_a_partition_of_unity():
    basis = g.bspline_basis(np.arange(1, 90), 1, 89, 40)
    assert basis.shape == (89, 43)
    assert basis.sum(axis=1) == pytest.approx(1.0)
    assert (basis >= 0).all()


def test_difference_penalty_ignores_polynomials_up_to_its_order():
    n = 12
    constant, line, curve = np.ones(n), np.arange(n, dtype=float), np.arange(n, dtype=float) ** 2
    second = g.difference_penalty(n, 2)
    assert constant @ second @ constant == pytest.approx(0)
    assert line @ second @ line == pytest.approx(0)
    assert curve @ second @ curve > 0  # a second-order penalty does punish curvature
    assert curve @ g.difference_penalty(n, 3) @ curve == pytest.approx(0)


def test_poisson_deviance_is_zero_for_a_perfect_fit():
    assert g.poisson_deviance([5, 0, 9], [5, 0.0001, 9]) == pytest.approx(0.0002, abs=1e-3)
    assert g.poisson_deviance([10, 20], [10, 20]) == pytest.approx(0)
    assert g.poisson_deviance([10], [20]) > 0


def test_noise_dispersion_is_one_for_poisson_and_larger_with_extra_scatter():
    rng = np.random.default_rng(1)
    ages = np.arange(30, 90)
    expected = 2e5 * 0.0002 * np.exp(0.09 * (ages - 30)) * np.exp(-0.02 * (ages - 30))
    plain = rng.poisson(expected)
    noisy = rng.poisson(expected * np.exp(rng.normal(0, 0.06, len(ages))))
    assert g.noise_dispersion(plain) == pytest.approx(1.0, abs=0.35)
    assert g.noise_dispersion(noisy) > 2.0


def test_pspline_recovers_a_known_curve_and_conserves_deaths():
    ages, deaths, exposure, truth = gompertz_data()
    fit = g.pspline(ages, deaths, exposure)
    assert np.max(np.abs(fit.mx / truth - 1)) < 0.05
    assert np.sum(exposure * fit.mx) == pytest.approx(deaths.sum(), rel=1e-6)
    lower, upper = fit.interval()
    assert (lower < fit.mx).all() and (fit.mx < upper).all()
    inside = np.mean((lower <= truth) & (truth <= upper))
    assert inside > 0.8  # the interval should cover the truth most of the time


def test_a_huge_lambda_gives_a_straight_line_in_log_rates():
    ages, deaths, exposure, _ = gompertz_data()
    fit = g.pspline(ages, deaths, exposure, lam=1e10)
    assert np.max(np.abs(np.diff(np.log(fit.mx), 2))) < 1e-3
    assert fit.edf == pytest.approx(2.0, abs=0.1)  # intercept and slope only


def test_whittaker_henderson_limits():
    ages, deaths, exposure, truth = gompertz_data()
    smooth = g.whittaker_henderson(ages, deaths, exposure, lam=1e12)
    assert np.max(np.abs(np.diff(np.log(smooth.mx), 3))) < 1e-3  # a quadratic in log m
    rough = g.whittaker_henderson(ages, deaths, exposure, lam=1e-6)
    assert rough.mx == pytest.approx(deaths / exposure, rel=1e-3)  # lam -> 0 interpolates
    chosen = g.whittaker_henderson(ages, deaths, exposure)
    assert np.max(np.abs(chosen.mx / truth - 1)) < 0.06


def test_lambda_selection_prefers_the_straight_line_when_the_truth_is_one():
    ages, deaths, exposure, _ = gompertz_data()
    fit = g.pspline(ages, deaths, exposure)
    assert fit.edf < 3.5  # Gompertz is linear in log m: the smoothest fit is the right one
    assert {"log10_lambda", "deviance", "edf", "qaic"} <= set(fit.path.columns)
    assert fit.path["edf"].is_monotonic_decreasing  # more smoothing, fewer parameters


def test_lambda_selection_stays_flexible_when_the_curve_bends():
    ages, deaths, exposure, truth = gompertz_data(lo=20)
    bend = 1 + 2 * np.exp(-(((ages - 45) / 8.0) ** 2))  # a bump the line cannot follow
    deaths = np.random.default_rng(2).poisson(exposure * truth * bend)
    fit = g.pspline(ages, deaths, exposure)
    assert fit.edf > 6
    assert g.LAMBDA_GRID.min() < fit.lam < g.LAMBDA_GRID.max()


def test_gompertz_makeham_fit_recovers_parameters():
    ages = np.arange(35, 90)
    truth = (4e-4, 3e-5, 1.1)
    exposure = np.full(len(ages), 5e7)
    deaths = np.random.default_rng(0).poisson(exposure * g.gompertz_makeham(ages, truth))
    params, _ = g.fit_parametric(
        g.gompertz_makeham, ages, deaths, exposure, g.GM_START, g.GM_BOUNDS
    )
    assert params == pytest.approx(truth, rel=0.05)


def test_heligman_pollard_fit_recovers_its_own_curve():
    ages = np.arange(1, 90)
    truth = (5.4e-4, 9.5e-3, 0.06, 2.8e-4, 8.5, 23.8, 3e-5, 1.097)
    exposure = np.full(len(ages), 2e7)
    deaths = np.random.default_rng(0).poisson(exposure * g.heligman_pollard(ages, truth))
    params, deviance = g.fit_parametric(
        g.heligman_pollard, ages, deaths, exposure, g.HP_START, g.HP_BOUNDS, starts=12
    )
    fitted = g.heligman_pollard(ages, params)
    assert np.max(np.abs(fitted / g.heligman_pollard(ages, truth) - 1)) < 0.06
    assert deviance < 3 * len(ages)  # about one unit of deviance per age for a correct law


def test_kannisto_is_a_logistic_bounded_by_one():
    m = g.kannisto(np.arange(60, 130), (0.06, 0.1))
    assert (np.diff(m) > 0).all()
    assert m.max() < 1.0
    assert g.kannisto(80, (0.06, 0.1)) == pytest.approx(0.06 / 1.06)


def test_fit_tests_detect_alternating_residuals():
    n = 60
    exposure = np.full(n, 1e6)
    mx = np.full(n, 0.01)
    deaths = exposure * mx + np.where(np.arange(n) % 2 == 0, 100.0, -100.0)
    result = g.fit_tests(deaths, exposure, mx, edf=2)
    assert result["serial_corr"] < -0.9
    assert result["serial_p"] < 0.001
    assert result["runs_p"] < 0.001
    assert result["share_beyond_2"] == 0.0 or result["share_beyond_2"] >= 0
    assert result["dispersion"] == pytest.approx(result["chi2"] / (n - 2))


def test_fit_tests_accept_pure_noise():
    rng = np.random.default_rng(3)
    exposure = np.full(200, 1e6)
    mx = np.full(200, 0.01)
    deaths = rng.poisson(exposure * mx)
    result = g.fit_tests(deaths, exposure, mx, edf=1)
    assert result["chi2_p"] > 0.01
    assert result["signs_p"] > 0.01
    assert 0.0 <= result["share_beyond_2"] < 0.12


def test_blend_weight_runs_from_one_to_zero():
    w = g.blend_weight([60, 84, 87, 90, 100])
    assert w.tolist() == [1.0, 1.0, 0.5, 0.0, 0.0]


def _synthetic_cell(seed=0):
    rng = np.random.default_rng(seed)
    ages = np.arange(0, 100)
    mx = 0.00025 + 0.00003 * np.exp(0.095 * ages)
    mx[0] = 0.008
    exposure = 1.2e6 * np.exp(-0.022 * ages)
    return pd.DataFrame(
        {"sex": "F", "age": ages, "deaths": rng.poisson(exposure * mx), "exposure": exposure}
    )


def test_graduate_cell_builds_a_complete_monotone_table():
    result = g.graduate_cell(_synthetic_cell())
    table = result["table"]
    assert table["age"].tolist() == list(range(0, 111))
    assert table.loc[table["age"] == 110, "qx"].iloc[0] == 1.0
    assert ((table["qx"] >= 0) & (table["qx"] <= 1)).all()
    assert (np.diff(table.loc[table["age"].between(30, 109), "qx"]) > 0).all()
    assert set(table["source"]) == {"crude", "pspline", "blend", "kannisto"}
    assert set(result["tests"]) == {
        "pspline", "whittaker_henderson", "heligman_pollard", "gompertz_makeham"
    }  # fmt: skip
    # the spline and the closure meet without a jump
    seam = table.set_index("age")["mx"]
    assert abs(np.log(seam[90] / seam[89])) < 0.2


def test_the_spline_follows_a_young_adult_plateau_the_law_cannot():
    cell = _synthetic_cell()
    hump = 1 + 4 * np.exp(-(((cell["age"] - 24) / 6.0) ** 2))  # a broad plateau at 18-30
    cell["deaths"] = np.random.default_rng(5).poisson(
        cell["exposure"] * (0.00025 + 0.00003 * np.exp(0.095 * cell["age"])) * hump
    )
    cell.loc[0, "deaths"] = 9000
    fits = g.graduate_cell(cell)["fits"]
    assert fits["pspline"].deviance < fits["heligman_pollard"].deviance / 5


def test_enforce_sex_order_raises_men_to_women_only_where_needed():
    ages = np.arange(80, 100)
    male = pd.DataFrame({"age": ages, "mx": np.linspace(0.08, 0.2, 20), "qx": 0.1})
    female = pd.DataFrame({"age": ages, "mx": np.linspace(0.06, 0.4, 20), "qx": 0.1})
    for column in ("mx_lower", "mx_upper"):
        male[column] = 0.01
    out = g.enforce_sex_order(male, female)
    assert (out["mx"] >= female["mx"].where(out["age"] >= 84, 0)).all()
    assert out.loc[out["age"] < 84, "mx"].tolist() == male.loc[male["age"] < 84, "mx"].tolist()
    assert out["sex_floor"].any() and not out.loc[out["age"] < 84, "sex_floor"].any()
    flagged = out[out["sex_floor"]]
    assert flagged["mx_lower"].isna().all()  # no interval claim on a rate we overrode


def test_graduate_all_returns_every_table_and_orders_the_sexes():
    cells = []
    for year in (2022, 2023):
        for sex, factor in (("M", 1.5), ("F", 1.0)):
            cell = _synthetic_cell(seed=year)
            cell["sex"], cell["year"] = sex, year
            cell["deaths"] = (cell["deaths"] * factor).round()
            cells.append(cell)
    out = g.graduate_all(pd.concat(cells, ignore_index=True))
    assert set(out) == set(g.DESCRIPTIONS)
    final = out["graduated_qx"]
    assert len(final) == 2 * 2 * 111
    wide = final.pivot_table(index=["year", "age"], columns="sex", values="mx")
    assert (wide["M"] >= wide["F"] - 1e-12).all()
    assert out["graduation_fit_tests"]["method"].nunique() == 4


def test_graduable_rejects_partial_or_zero_cells():
    cell = _synthetic_cell()
    assert g.graduable(cell)
    assert not g.graduable(cell.iloc[:50])
    zero = cell.copy()
    zero.loc[10, "deaths"] = 0
    assert not g.graduable(zero)


def test_graduate_all_skips_cells_it_cannot_fit():
    partial = _synthetic_cell().iloc[:30].assign(year=2023)
    assert g.graduate_all(partial) == {}


def test_digit_preference_finds_planted_heaping_and_nothing_else():
    ages = np.arange(25, 71)
    exposure = np.full(len(ages), 1e6)
    truth = 0.001 * np.exp(0.06 * (ages - 25))
    fitted = pd.DataFrame({"year": 2023, "sex": "M", "age": ages, "mx": truth})
    rng = np.random.default_rng(4)
    heaped = truth * np.where(ages % 5 == 0, 1.03, 1.0)
    clean = pd.DataFrame(
        {"year": 2023, "sex": "M", "age": ages, "exposure": exposure,
         "deaths": rng.poisson(exposure * truth)}
    )  # fmt: skip
    dirty = clean.assign(deaths=rng.poisson(exposure * heaped))
    assert abs(g.digit_preference(clean, fitted)["excess_at_0_5"].iloc[0]) < 0.01
    found = g.digit_preference(dirty, fitted).iloc[0]
    assert found["excess_at_0_5"] == pytest.approx(0.03, abs=0.012)
    assert found["mean_z_at_0_5"] > 2 > abs(found["mean_z_elsewhere"])
