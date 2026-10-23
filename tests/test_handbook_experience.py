"""Numerical proof of the formulas in docs/handbook/07-experience-study.md.

Each test states the equation it checks. A formula in the handbook that the code does not obey
makes one of these fail, so the documentation cannot drift away from the software.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import optimize

from mortality import experience as ex
from mortality import rates
from mortality.lifetable import Commutation, build_life_table

ROOT = Path(__file__).resolve().parents[1]
AGE_CENTRES_CHECK = tuple(ex.AGE_CENTRES[g] for g in ex.AGE_LABELS)


# ── 7.1: expected deaths ─────────────────────────────────────────────────────


def test_expected_deaths_use_the_constant_force_that_reproduces_q():
    """(7.1), (7.2): mu = -ln(1 - q) and expected = exposure x mu; a full year gives -ln(1 - q)."""
    q = pd.Series([0.01, 0.02, 0.5], index=[40, 41, 42])
    seg = pd.DataFrame({"attained_age": [40, 41, 42, 99], "exposure": [1.0, 0.5, 0.25, 2.0]})
    out = ex.add_expected(seg, q)
    assert out["expected"].tolist() == pytest.approx(
        [-np.log(0.99), 0.5 * -np.log(0.98), 0.25 * -np.log(0.5), 2.0 * -np.log(0.5)]
    )  # age 99 is past the table: its last q is used
    assert -np.log(0.99) == pytest.approx(0.0100503, abs=1e-7)  # slightly above q = 0.01
    # a life that survives a year with probability p = 1 - q has exp(-mu) = p exactly
    mu = -np.log(0.99)
    assert np.exp(-mu) == pytest.approx(0.99)


# ── 7.2: actual to expected ──────────────────────────────────────────────────


def test_count_and_amount_actual_to_expected_and_their_intervals():
    """(7.3), (7.4): A/E by count has the Garwood interval; by amount, a compound-Poisson one."""
    cells = pd.DataFrame(
        {
            "deaths": [4.0],
            "expected": [5.0],
            "exposure": [1000.0],
            "death_amount": [10_000_000.0],  # claims of 1M, 2M, 3M, 4M
            "death_amount_sq": [(1 + 4 + 9 + 16) * 1e12],
            "expected_amount": [12_000_000.0],
            "exposure_amount": [1e9],
        }
    )
    out = ex.actual_to_expected(cells, [])
    lower, upper = rates.poisson_interval(4.0)
    assert out["ae"].iloc[0] == pytest.approx(0.8)
    assert (out["ae_lower"].iloc[0], out["ae_upper"].iloc[0]) == pytest.approx(
        (lower / 5, upper / 5)
    )
    assert out["ae_amount"].iloc[0] == pytest.approx(10 / 12)
    half = 1.959964 * np.sqrt(30e12) / 12e6
    assert out["ae_amount_upper"].iloc[0] == pytest.approx(10 / 12 + half)
    assert 10 / 12 - half < 0  # four claims cannot pin the amount down...
    assert out["ae_amount_lower"].iloc[0] == 0.0  # ...and the lower limit stops at zero


def test_the_variance_of_total_claims_is_the_sum_of_squared_amounts_times_the_rates():
    """(7.4): for Poisson claim counts, Var(sum of sum assured x deaths) = sum(lambda_i SA_i^2)."""
    rng = np.random.default_rng(12)
    sa = np.array([2e5, 1e6, 5e6])
    lam = np.array([40.0, 12.0, 1.5])
    draws = rng.poisson(lam, (300_000, 3)) @ sa
    assert draws.var() == pytest.approx((lam * sa**2).sum(), rel=0.02)
    assert draws.mean() == pytest.approx((lam * sa).sum(), rel=0.005)


# ── 7.3: credibility ─────────────────────────────────────────────────────────


def test_limited_fluctuation_credibility_is_the_square_root_rule():
    """(7.5), (7.6): Z = sqrt(D / 1082) up to 1; then the credible A/E mixes A/E and 1."""
    assert ex.FULL_CREDIBILITY_DEATHS == 1082
    assert ex.credibility_z([270.5, 1082, 5000]).tolist() == pytest.approx([0.5, 1.0, 1.0])
    d = np.array([100.0, 500.0, 1000.0])
    z = ex.credibility_z(d)
    assert z**2 * (1 / d) == pytest.approx(1 / 1082)  # the fluctuation of Z x (A/E) is constant
    cells = pd.DataFrame({"deaths": [45.0], "expected": [125.0]})
    for column in ("exposure_amount", "expected_amount", "death_amount", "death_amount_sq"):
        cells[column] = 1.0
    out = ex.actual_to_expected(cells, [])
    assert out["credibility"].iloc[0] == pytest.approx(np.sqrt(45 / 1082))
    assert out["ae_credible"].iloc[0] == pytest.approx(
        out["credibility"].iloc[0] * 0.36 + (1 - out["credibility"].iloc[0])
    )


def test_buhlmann_straub_toy_example():
    """(7.8), (7.9): two classes, two periods: s2 = 0.2, v = 0.07, K = 2.857, Z = 0.875."""
    ratios = np.array([[0.8, 1.0], [1.2, 1.4]])
    weights = np.full((2, 2), 10.0)
    out = ex.buhlmann_straub(ratios, weights)
    assert out["class_mean"].tolist() == pytest.approx([0.9, 1.3])
    assert out["grand_mean"] == pytest.approx(1.1)
    assert out["s2"] == pytest.approx(0.2)
    assert out["v"] == pytest.approx(0.07)
    assert out["k"] == pytest.approx(0.2 / 0.07)
    assert out["z"].tolist() == pytest.approx([20 / (20 + 0.2 / 0.07)] * 2)
    assert out["z"][0] == pytest.approx(0.875)
    assert out["credible_mean"].tolist() == pytest.approx(
        [0.875 * 0.9 + 0.125 * 1.1, 0.875 * 1.3 + 0.125 * 1.1]
    )


def test_buhlmann_straub_weight_minimises_the_error_when_the_variances_are_known():
    """(7.7): the error Z^2 s2 / w + (1 - Z)^2 v is smallest at Z = w / (w + K) with K = s2 / v."""
    s2, v, w = 0.9, 0.08, 40.0
    best = optimize.minimize_scalar(
        lambda z: z**2 * s2 / w + (1 - z) ** 2 * v, bounds=(0, 1), method="bounded"
    )
    assert best.x == pytest.approx(w / (w + s2 / v), abs=1e-4)


def test_buhlmann_straub_recovers_known_variances_and_shrinks_the_extremes():
    """(7.8): the estimates of s2 and v from simulated classes are close to what generated them."""
    rng = np.random.default_rng(14)
    classes, periods, s2, v = 400, 6, 0.9, 0.08
    weights = rng.uniform(20, 120, (classes, periods))
    theta = 0.77 + np.sqrt(v) * rng.standard_normal(classes)
    ratios = theta[:, None] + np.sqrt(s2 / weights) * rng.standard_normal((classes, periods))
    out = ex.buhlmann_straub(ratios, weights)
    assert out["s2"] == pytest.approx(s2, rel=0.1)
    assert out["v"] == pytest.approx(v, rel=0.2)
    assert out["grand_mean"] == pytest.approx(0.77, abs=0.03)
    raw = out["class_mean"]
    assert np.var(out["credible_mean"]) < np.var(raw)  # shrinkage pulls the class means together
    assert out["z"].min() > 0 and out["z"].max() < 1


def test_the_credibility_example_of_section_7_8():
    """Section 7.8: 45 deaths, A/E 0.36: Z = 0.204 gives 0.87 and Z = 0.916 gives 0.40."""
    z_classical = np.sqrt(45 / 1082)
    assert z_classical * 0.36 + (1 - z_classical) == pytest.approx(0.8693, abs=1e-3)
    expected_deaths = 45 / 0.36
    z_bs = expected_deaths / (expected_deaths + 11.5)
    assert z_bs == pytest.approx(0.916, abs=1e-3)
    assert z_bs * 0.36 + (1 - z_bs) * 0.77 == pytest.approx(0.395, abs=1e-3)


# ── 7.4: relativities, a Poisson GLM ─────────────────────────────────────────


@pytest.mark.filterwarnings("ignore:Perfect separation")  # the table is fitted without error
def test_glm_recovers_an_exactly_multiplicative_table_by_hand():
    """Section 7.8: four cells with deaths = expected x relativity are fitted with no error."""
    cells = pd.DataFrame(
        {
            "sex": ["M", "M", "F", "F"],
            "uw_class": ["STANDARD", "RATED", "STANDARD", "RATED"],
            "expected": [100.0, 80.0, 100.0, 50.0],
            "deaths": [100.0, 120.0, 60.0, 45.0],
        }
    )
    t = ex.fit_relativities(cells, ["sex", "uw_class"])["table"].set_index(["factor", "level"])
    assert t.loc[("(intercept)", ""), "relativity"] == pytest.approx(1.0, rel=1e-6)
    assert t.loc[("sex", "F"), "relativity"] == pytest.approx(0.6, rel=1e-6)
    assert t.loc[("uw_class", "RATED"), "relativity"] == pytest.approx(1.5, rel=1e-6)


def random_cells(seed: int = 0, n: int = 4000):
    rng = np.random.default_rng(seed)
    sex = rng.choice(["M", "F"], n)
    cls = rng.choice(["STANDARD", "PREFERRED", "RATED"], n)
    ageg = rng.choice(["40-49", "30-39", "50-59"], n)
    expected = rng.gamma(2.0, 6.0, n)
    mult = (
        0.9
        * np.where(sex == "F", 0.7, 1.0)
        * np.select([cls == "PREFERRED", cls == "RATED"], [0.8, 1.5], 1.0)
        * np.select([ageg == "30-39", ageg == "50-59"], [0.9, 1.2], 1.0)
    )
    deaths = rng.poisson(mult * expected).astype(float)
    return pd.DataFrame(
        {"sex": sex, "uw_class": cls, "age_group": ageg, "expected": expected, "deaths": deaths}
    )


def test_the_fitted_glm_reproduces_the_deaths_of_every_level_of_every_factor():
    """(7.11): score equations of a Poisson GLM with log link: fitted totals = observed totals."""
    cells = random_cells()
    fit = ex.fit_relativities(cells, ["sex", "uw_class", "age_group"])
    fitted = pd.Series(fit["model"].mu, index=cells.index)
    for factor in ("sex", "uw_class", "age_group"):
        observed = cells.groupby(factor)["deaths"].sum()
        assert fitted.groupby(cells[factor]).sum().loc[observed.index].to_numpy() == pytest.approx(
            observed.to_numpy(), rel=1e-8
        )
    assert fitted.sum() == pytest.approx(cells["deaths"].sum())


def test_quasi_poisson_scales_the_standard_errors_by_the_root_of_the_dispersion():
    """(7.12): se_log = se_Poisson x sqrt(dispersion); the interval is exp(coef +- 1.96 se)."""
    cells = random_cells(seed=1)
    fit = ex.fit_relativities(cells, ["sex", "uw_class"])
    plain = smf.glm(
        "deaths ~ C(sex, Treatment(reference='M')) + C(uw_class, Treatment(reference='STANDARD'))",
        data=cells,
        family=sm.families.Poisson(),
        offset=np.log(cells["expected"]),
    ).fit()
    row = fit["table"].set_index(["factor", "level"]).loc[("sex", "F")]
    assert row["se_log"] == pytest.approx(plain.bse.iloc[1] * np.sqrt(fit["dispersion"]))
    assert row["lower"] == pytest.approx(
        np.exp(np.log(row["relativity"]) - 1.959964 * row["se_log"])
    )
    assert row["relativity"] == pytest.approx(0.7, rel=0.08)


def test_the_binned_dispersion_is_near_one_for_poisson_and_near_psi_when_overdispersed():
    """(7.12): bins of about 10 expected deaths: Poisson gives 1, a variance of 2 x mean gives 2."""
    rng = np.random.default_rng(31)
    n = 400_000
    expected = rng.gamma(0.7, 0.04, n) + 1e-3  # sparse: most cells expect a fraction of a death
    group = rng.integers(0, 4, n)
    mu = expected * np.array([1.0, 1.2, 0.8, 1.5])[group]
    results = {}
    for name, counts in {
        "poisson": rng.poisson(mu),
        "overdispersed": rng.poisson(rng.gamma(mu, 1.0)),  # variance = 2 x mean
    }.items():
        frame = pd.DataFrame(
            {"deaths": counts.astype(float), "expected": expected, "g": group.astype(str)}
        )
        model = smf.glm(
            "deaths ~ C(g)",
            data=frame,
            family=sm.families.Poisson(),
            offset=np.log(frame["expected"]),
        ).fit()
        results[name] = (
            ex.binned_dispersion(frame["deaths"], model.mu, len(model.params)),
            model.pearson_chi2 / model.df_resid,
        )
    assert results["poisson"][0] == pytest.approx(1.0, abs=0.1)
    assert results["poisson"][1] == pytest.approx(1.0, abs=0.05)  # the plain statistic is fine too
    assert results["overdispersed"][0] == pytest.approx(2.0, abs=0.3)
    assert results["overdispersed"][1] == pytest.approx(2.0, abs=0.25)


# ── 7.5: the select period ───────────────────────────────────────────────────


def test_pool_adjacent_violators_toy_example_and_properties():
    """(7.13): closest non-decreasing sequence: (0.55, 0.50, 0.88) becomes (0.525, 0.525, 0.88)."""
    out = ex.pool_adjacent_violators([0.55, 0.50, 0.88], [1, 1, 1])
    assert out.tolist() == pytest.approx([0.525, 0.525, 0.88])
    weighted = ex.pool_adjacent_violators([0.8, 0.5, 0.9], [1, 3, 1])
    assert weighted.tolist() == pytest.approx([(0.8 + 1.5) / 4] * 2 + [0.9])
    rng = np.random.default_rng(0)
    for _ in range(25):
        v, w = rng.uniform(0.3, 1.3, 6), rng.uniform(0.5, 3.0, 6)
        fitted = ex.pool_adjacent_violators(v, w)
        assert (np.diff(fitted) >= -1e-12).all()  # non-decreasing
        assert (w * fitted).sum() == pytest.approx((w * v).sum())  # preserves the weighted total
        assert ex.pool_adjacent_violators(fitted, w).tolist() == pytest.approx(fitted.tolist())
        cons = [{"type": "ineq", "fun": lambda u, i=i: u[i + 1] - u[i]} for i in range(5)]
        direct = optimize.minimize(
            lambda u, w=w, v=v: (w * (u - v) ** 2).sum(), np.sort(v), constraints=cons
        )
        assert (w * (fitted - v) ** 2).sum() <= direct.fun + 1e-7  # no better sequence exists


def test_monotone_input_is_returned_unchanged():
    """Section 7.5: smoothing never alters factors that already rise toward ultimate."""
    v = [0.5, 0.65, 0.8, 0.9, 1.0]
    assert ex.pool_adjacent_violators(v, [1, 2, 3, 2, 1]).tolist() == pytest.approx(v)


# ── 7.6: the claims reporting lag ────────────────────────────────────────────


def test_lag_distribution_and_quarter_completion_by_hand():
    """(7.14), (7.15): a lag of 0 to 29 days uniform; the last quarter is 83.9% complete."""
    grid = np.arange(0, 60)
    cdf = np.minimum((grid + 1) / 30, 1.0)  # everything is reported within 30 days
    # extract on the last day of the quarter: day d has waited (31 March - d) days
    completion = ex.completion_by_quarter(grid, cdf, "2023-03-31", [(2023, 1)])
    assert completion[(2023, 1)] == pytest.approx((sum((w + 1) / 30 for w in range(29)) + 61) / 90)
    assert round(completion[(2023, 1)], 4) == 0.8389
    long_ago = ex.completion_by_quarter(grid, cdf, "2024-03-31", [(2023, 1)])
    assert long_ago[(2023, 1)] == 1.0


def test_the_empirical_lag_distribution_uses_only_mature_deaths():
    """(7.14): F(l) = share of mature deaths reported within l days; recent deaths are left out."""
    rng = np.random.default_rng(3)
    n = 4000
    exit_ = np.datetime64("2020-01-01") + rng.integers(0, 600, n).astype("timedelta64[D]")
    lag = rng.integers(0, 60, n)
    frame = pd.DataFrame(
        {
            "status": "DEATH",
            "exit_date": exit_,
            "notification_date": exit_ + lag.astype("timedelta64[D]"),
        }
    )
    grid, cdf = ex.estimate_lag_distribution(frame, "2022-06-01", mature_days=540)
    assert grid.max() == 59 and cdf[-1] == 1.0
    assert cdf[29] == pytest.approx(0.5, abs=0.03)
    assert (np.diff(cdf) >= 0).all()
    recent = frame.assign(exit_date=np.datetime64("2022-05-01"))  # nothing mature enough
    with pytest.raises(ValueError):
        ex.estimate_lag_distribution(recent, "2022-06-01", mature_days=540)


def test_quarterly_experience_conserves_exposure_expected_and_deaths():
    """(7.16): pieces are shared among quarters by days; A/E completed = A/E / completion."""
    seg = pd.DataFrame(
        {
            "start": np.array(["2023-01-01", "2023-02-15", "2023-04-10"], dtype="datetime64[D]"),
            "end": np.array(["2023-04-10", "2023-09-01", "2023-12-31"], dtype="datetime64[D]"),
            "calendar_year": [2023, 2023, 2023],
            "exposure": [99 / 365.25, 198 / 365.25, 265 / 365.25],
            "expected": [0.30, 0.45, 0.60],
            "deaths": [0, 1, 1],
        }
    )
    completion = pd.Series({(2023, 1): 0.9, (2023, 2): 0.95, (2023, 3): 1.0, (2023, 4): 1.0})
    out = ex.quarterly_experience(seg, completion)
    assert out["exposure"].sum() == pytest.approx(seg["exposure"].sum())
    assert out["expected"].sum() == pytest.approx(seg["expected"].sum())
    assert out["deaths"].sum() == 2
    assert (out["ae_completed"] * out["completion"]).to_numpy() == pytest.approx(
        out["ae"].to_numpy()
    )
    q3 = out[out["quarter"] == 3].iloc[0]  # a death on 31 Aug 2023 belongs to the third quarter
    assert q3["deaths"] == 1


# ── 7.7: the basis and its price ─────────────────────────────────────────────


def basis_cells(scale: float, seed: int = 5):
    rng = np.random.default_rng(seed)
    grid = pd.MultiIndex.from_product(
        [["M", "F"], ex.AGE_LABELS, ex.DURATION_LABELS, range(4)],
        names=["sex", "age_group", "duration_group", "rep"],
    ).to_frame(index=False)
    grid["expected"] = rng.gamma(4.0, scale / 4.0, len(grid))
    mult = (
        0.8
        * np.where(grid["sex"] == "F", 0.7, 1.0)
        * np.where(grid["duration_group"] == "1", 0.6, 1.0)
    )
    grid["deaths"] = rng.poisson(mult * grid["expected"]).astype(float)
    return grid.drop(columns="rep")


def test_the_basis_multiplier_is_shrunk_toward_one_and_the_prudent_one_is_above():
    """(7.17), (7.18): thin data move the multiplier toward 1; the 95% upper bound sits above it."""
    q = pd.Series(0.0005 * np.exp(0.09 * np.arange(0, 111)), index=np.arange(0, 111)).clip(upper=1)
    thick = ex.build_basis(basis_cells(scale=4000.0), q)
    thin = ex.build_basis(basis_cells(scale=20.0), q)
    for table in (thick, thin):
        assert (table["multiplier_upper"] >= table["multiplier"]).all()
        assert (table["q_experience_prudent"] >= table["q_experience"] - 1e-12).all()
        assert table["q_experience"].between(0, 1).all()
    raw_level = 0.8 * 0.7  # women at ultimate duration: the multiplier planted in the data
    pick = lambda t: t[(t["sex"] == "F") & (t["duration_group"] == "6-10") & (t["age"] == 44)]  # noqa: E731
    assert abs(pick(thick)["multiplier"].item() - raw_level) < abs(
        pick(thin)["multiplier"].item() - raw_level
    )
    assert abs(pick(thin)["multiplier"].item() - 1.0) < abs(pick(thick)["multiplier"].item() - 1.0)


def test_the_multiplier_is_interpolated_between_age_group_centres_on_the_log_scale():
    """(7.17): log multiplier is a straight line in age between the centres 34.5 and 44.5."""
    q = pd.Series(0.0005 * np.exp(0.09 * np.arange(0, 111)), index=np.arange(0, 111)).clip(upper=1)
    table = ex.build_basis(basis_cells(scale=4000.0), q)
    row = table[(table["sex"] == "M") & (table["duration_group"] == "6-10")].set_index("age")
    log_m = np.log(row["multiplier"])
    inside = log_m.loc[36:43].to_numpy()  # both neighbours of every age here are in one segment
    assert np.diff(inside, 2) == pytest.approx(0.0, abs=1e-12)
    slope_here = np.diff(inside).mean()
    slope_below = np.diff(log_m.loc[26:33].to_numpy()).mean()  # a different segment, another slope
    assert slope_here != pytest.approx(slope_below, abs=1e-9)
    assert AGE_CENTRES_CHECK == (24.0, 34.5, 44.5, 54.5, 65.0)


def test_term_net_premium_matches_the_chapter_5_formula():
    """(7.19): P = sum v^(t+1) tp q_t / sum v^t tp, the same number as A1 / a-due of chapter 5."""
    ages = np.arange(0, 111)
    q = np.clip(0.0004 * np.exp(0.095 * ages), 0, 1)
    q[-1] = 1.0
    table = build_life_table(ages, q)
    commutation = Commutation.from_table(table, 0.04)
    x, n = 40, 20
    premium = ex.term_net_premium(q[x : x + n][None, :], 0.04)[0]
    assert premium == pytest.approx(commutation.term_premium(x, n), rel=1e-12)
    survival = np.concatenate([[1.0], np.cumprod(1 - q[x : x + n - 1])])
    v = 1.04 ** -np.arange(1, n + 1)
    assert premium == pytest.approx(
        (survival * q[x : x + n] * v).sum() / (survival * v * 1.04).sum()
    )


def test_the_present_value_of_death_benefits_is_the_term_insurance_of_chapter_5():
    """(7.20): one policy with n years left: pv = SA x A1 (end-of-year-of-death benefit)."""
    ages = np.arange(0, 111)
    q = np.clip(0.0004 * np.exp(0.095 * ages), 0, 1)
    q[-1] = 1.0
    commutation = Commutation.from_table(build_life_table(ages, q), 0.04)
    block = pd.DataFrame(
        {
            "sex": ["M"],
            "attained_age": [40],
            "duration": [1],
            "years_left": [20],
            "sum_assured": [1e6],
        }
    )
    out = ex.pv_death_benefits(block, pd.Series(q, index=ages), None, 0.04)
    assert out["pv_cnsf"].item() == pytest.approx(
        1e6 * commutation.term_insurance(40, 20), rel=1e-12
    )
    assert out["claims_next_12m_cnsf"].item() == pytest.approx(1e6 * q[40])
    assert out["pv_experience"].item() == out["pv_cnsf"].item()  # no basis: the same table


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
    """Section 7.9: validation, A/E, credibility, recovery, select, lag, basis, price and impact."""
    q = lambda sql: pd.read_sql(sql, demo)  # noqa: E731
    checks = q("SELECT * FROM experience_dq_checks").set_index("check")["records"]
    assert checks["duplicate_record"] == 573 and checks["non_positive_sum_assured"] == 276
    assert checks["exit_before_issue"] == 393 and checks["issue_after_extract"] == 115
    recon = q("SELECT * FROM experience_dq_reconciliation").set_index("step")
    assert recon.loc["records in the extract", "records"] == 573_082
    assert recon.loc["records in the clean file", ["records", "deaths"]].tolist() == [
        571_211,
        4_336,
    ]
    overview = q("SELECT * FROM experience_overview").iloc[0]
    assert round(overview["expected_deaths"]) == 5184 and overview["deaths"] == 4336

    ae = q("SELECT * FROM experience_ae WHERE years = 'excluding_2020_2022'")
    total = ae[ae["dimension"] == "all"].iloc[0]
    assert (round(total["ae"], 2), round(total["ae_lower"], 2), round(total["ae_upper"], 2)) == (
        0.77,
        0.74,
        0.80,
    )
    assert round(total["ae_amount"], 2) == 0.68
    one_way = ae.set_index(["dimension", "level"])["ae"].round(2)
    assert (one_way[("sex", "M")], one_way[("sex", "F")]) == (0.91, 0.59)

    cred = q("SELECT * FROM experience_credibility").iloc[0]
    assert (round(cred["bs_k"], 1), round(cred["bs_v"], 3), round(cred["bs_s2"], 2)) == (
        11.5,
        0.080,
        0.92,
    )
    standard_bank = q("SELECT * FROM experience_credibility WHERE class = 'F/STANDARD/BANK'").iloc[
        0
    ]
    assert standard_bank["deaths"] == 45 and round(standard_bank["ae"], 2) == 0.36
    assert (round(standard_bank["ae_credible"], 2), round(standard_bank["bs_credible_ae"], 2)) == (
        0.87,
        0.40,
    )

    rec = q("SELECT * FROM experience_recovery")
    assert len(rec) == 15 and rec["inside_interval"].sum() == 15
    rec = rec.set_index(["factor", "level"])
    assert (
        round(rec.loc[("sex", "F"), "relativity"], 2),
        round(rec.loc[("sex", "F"), "planted"], 2),
    ) == (0.65, 0.66)
    assert (
        round(rec.loc[("uw_class", "RATED"), "relativity"], 2),
        rec.loc[("uw_class", "RATED"), "planted"],
    ) == (1.53, 1.55)
    assert round(q("SELECT dispersion FROM experience_relativities").iloc[0, 0], 2) == 1.27

    sel = q("SELECT * FROM experience_select")
    full = sel[sel["underwriting"] == "fully underwritten"]
    assert full["relativity"].round(2).tolist() == [0.55, 0.66, 0.88, 0.99, 1.01]
    assert full["planted"].tolist() == [0.50, 0.65, 0.78, 0.88, 0.95]
    assert sel["inside_interval"].all() and (sel["select_period"] == 2).all()

    lag = q("SELECT * FROM experience_lag_validation ORDER BY year, quarter").iloc[-1]
    assert (round(lag["completion"], 2), round(lag["raw_error_pct"] * 100, 1)) == (0.82, -19.5)
    assert round(lag["completed_error_pct"] * 100, 1) == -2.0 and lag["true_deaths"] == 190
    reported = q("SELECT * FROM experience_claims_lag").set_index("days")["share_reported"]
    assert [round(reported.loc[d], 2) for d in (30, 60, 90, 180)] == [0.49, 0.73, 0.84, 0.95]
    assert (reported >= 0.5).idxmax() == 32
    quarterly = q("SELECT * FROM experience_ae_quarterly ORDER BY year, quarter").iloc[-1]
    assert (round(quarterly["ae"], 2), round(quarterly["ae_completed"], 2)) == (0.72, 0.88)

    pricing = q("SELECT * FROM experience_pricing").set_index(["sex", "issue_age"])
    assert round(pricing.loc[("F", 40), "change_pct"] * 100) == -34
    assert [
        round(pricing.loc[("F", 40), c], 2)
        for c in ("premium_experience_per_1000", "premium_cnsf_per_1000")
    ] == [1.15, 1.74]
    assert round(pricing.loc[("M", 40), "premium_experience_per_1000"], 2) == 1.69
    assert round(pricing.loc[("M", 30), "change_pct"] * 100) == 3
    assert round(pricing.loc[("M", 40), "premium_prudent_per_1000"], 2) == 1.93

    impact = q("SELECT * FROM experience_impact").set_index("product")
    assert impact.loc["ALL", "policies"] == 392_274
    assert round(impact.loc["ALL", "pv_cnsf"] / 1e9, 1) == 31.0
    assert round(impact.loc["ALL", "pv_experience"] / 1e9, 1) == 27.4
    assert [
        round(impact.loc[p, "pv_change_pct"] * 100)
        for p in ("ALL", "TERM", "ENDOWMENT", "WHOLE_LIFE")
    ] == [-12, -19, -19, -8]
    assert round(impact.loc["ALL", "claims_12m_change_pct"] * 100) == -18
