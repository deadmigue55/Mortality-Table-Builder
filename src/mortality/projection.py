"""Stochastic mortality projection: Lee-Carter and Cairns-Blake-Dowd.

* **Lee-Carter** (1992): ``ln m(x,t) = a(x) + b(x) k(t)``, fitted by Poisson maximum likelihood
  (Brouhns, Denuit and Vermunt, 2002) so every age is weighted by its exposure. The period index
  ``k(t)`` is forecast as a random walk with drift.
* **Cairns-Blake-Dowd** (2006), "M5": ``logit q(x,t) = k1(t) + k2(t) (x - mean age)`` for ages
  60 to 99, with the pair ``(k1, k2)`` a bivariate random walk with drift. It is built for the
  ages that matter for pensions and annuities.

Uncertainty has two parts: the random innovations of the walk, and the uncertainty in its drift
(estimated from a short, trending series). Both are simulated, so a fan chart of life expectancy
or of an annuity value reflects longevity risk rather than only noise.

Everything is vectorised: a table of rates ``(paths, years, ages)`` becomes life expectancy and
annuity values for every path at once. Old ages are closed exactly as in the graduated tables
(``graduation.py``): ages 90 and over come from a logistic fitted to ages 75 to 89.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import special

from mortality import graduation, rates

AGES = np.arange(0, 100)  # ages the models are fitted on
CBD_AGES = np.arange(60, 100)
TERMINAL = 110
KANNISTO_FIT = graduation.KANNISTO_AGES  # 75 to 89
BLEND = graduation.BLEND  # 84 to 90


# ── Data ────────────────────────────────────────────────────────────────────


def history_arrays(
    df: pd.DataFrame, sex: str, years=None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Deaths and exposure as ``(ages, years)`` arrays for one sex.

    ``df``: year, sex, age, deaths, exposure. Only complete rectangles are returned: every age
    0 to 99 in every year, otherwise ``ValueError``.
    """
    d = df[(df["sex"] == sex) & (df["age"] < 100)]
    if years is not None:
        d = d[d["year"].isin(list(years))]
    deaths = d.pivot_table(index="age", columns="year", values="deaths", aggfunc="sum")
    exposure = d.pivot_table(index="age", columns="year", values="exposure", aggfunc="sum")
    if deaths.shape[0] != len(AGES) or deaths.isna().any().any() or exposure.isna().any().any():
        raise ValueError("Deaths and exposure must cover ages 0 to 99 in every year.")
    return deaths.to_numpy(float), exposure.to_numpy(float), deaths.columns.to_numpy(int)


# ── Lee-Carter ──────────────────────────────────────────────────────────────


@dataclass
class LeeCarter:
    ax: np.ndarray
    bx: np.ndarray
    kt: np.ndarray
    years: np.ndarray
    deviance: float
    iterations: int

    def fitted_rates(self) -> np.ndarray:
        return np.exp(self.ax[:, None] + self.bx[:, None] * self.kt[None, :])


def fit_lee_carter(
    deaths: np.ndarray, exposure: np.ndarray, years=None, max_iter: int = 2000, tol: float = 1e-9
) -> LeeCarter:
    """Poisson Lee-Carter by the one-step Newton updates of Brouhns et al. (2002).

    Identification: ``sum b(x) = 1`` and ``sum k(t) = 0``. Starts from the singular value
    decomposition of the log rates.
    """
    d = np.asarray(deaths, dtype=float)
    e = np.asarray(exposure, dtype=float)
    _n_ages, n_years = d.shape
    log_m = np.log((d + 0.5) / e)
    a = log_m.mean(axis=1)
    u, s, vt = np.linalg.svd(log_m - a[:, None], full_matrices=False)
    b, k = u[:, 0], s[0] * vt[0]
    if b.sum() < 0:
        b, k = -b, -k
    scale = b.sum()
    b, k = b / scale, k * scale

    def expected():
        return e * np.exp(a[:, None] + b[:, None] * k[None, :])

    previous = np.inf
    iterations = 0
    for iterations in range(1, max_iter + 1):  # noqa: B007
        fit = expected()
        k = k + ((d - fit) * b[:, None]).sum(axis=0) / (fit * b[:, None] ** 2).sum(axis=0)
        fit = expected()
        a = a + (d - fit).sum(axis=1) / fit.sum(axis=1)
        fit = expected()
        b = b + ((d - fit) * k[None, :]).sum(axis=1) / (fit * k[None, :] ** 2).sum(axis=1)
        shift = k.mean()  # re-impose sum k = 0 and sum b = 1 without changing the fit
        a, k = a + b * shift, k - shift
        scale = b.sum()
        b, k = b / scale, k * scale
        deviance = graduation.poisson_deviance(d.ravel(), expected().ravel())
        if abs(previous - deviance) < tol * max(deviance, 1.0):
            break
        previous = deviance
    years = np.arange(n_years) if years is None else np.asarray(years)
    return LeeCarter(a, b, k, years, deviance, iterations)


@dataclass
class RandomWalk:
    """A (multivariate) random walk with drift fitted to a series of indices."""

    last: np.ndarray  # final observed value(s)
    drift: np.ndarray
    cov: np.ndarray  # covariance of the innovations
    n: int  # number of observations


def fit_random_walk(series: np.ndarray) -> RandomWalk:
    """Drift and innovation covariance from the first differences. ``series``: (n,) or (p, n)."""
    x = np.atleast_2d(np.asarray(series, dtype=float))
    diff = np.diff(x, axis=1)
    drift = diff.mean(axis=1)
    cov = np.atleast_2d(np.cov(diff, ddof=1))
    return RandomWalk(x[:, -1], drift, cov, x.shape[1])


def simulate_walk(
    walk: RandomWalk,
    horizon: int,
    n_paths: int,
    rng: np.random.Generator,
    drift_uncertainty: bool = True,
) -> np.ndarray:
    """Paths ``(n_paths, horizon, p)`` of the walk, one row per future year.

    With ``drift_uncertainty`` each path also draws its own drift from its sampling distribution
    (``cov / (n - 1)``): a trend estimated from 40 years is not known exactly, and ignoring that
    makes long-run intervals too narrow.
    """
    p = len(walk.drift)
    chol = np.linalg.cholesky(walk.cov + 1e-14 * np.eye(p))
    shocks = rng.standard_normal((n_paths, horizon, p)) @ chol.T
    drift = np.broadcast_to(walk.drift, (n_paths, p)).copy()
    if drift_uncertainty:
        drift += rng.standard_normal((n_paths, p)) @ (chol / np.sqrt(walk.n - 1)).T
    steps = drift[:, None, :] + shocks
    return walk.last + np.cumsum(steps, axis=1)


def forecast_lee_carter(
    fit: LeeCarter,
    horizon: int,
    n_paths: int = 1000,
    seed: int = 0,
    jump_off: np.ndarray | None = None,
    drift_uncertainty: bool = True,
    drift_from: int | None = None,
) -> np.ndarray:
    """Simulated rates ``(paths, horizon, ages)``.

    ``jump_off``: observed rates at the last year (ages 0 to 99). If given, the projection
    starts exactly there: ``m(x, T+h) = m_obs(x) exp(b(x) (k(T+h) - k(T)))``, which removes the
    gap between the fitted and the actual last year. ``drift_from``: estimate the drift from the
    last years only (a trend that changed, as for Mexican men, is better described by recent ones).
    """
    kt = fit.kt if drift_from is None else fit.kt[-drift_from:]
    walk = fit_random_walk(kt)
    walk.last = fit.kt[-1:]
    paths = simulate_walk(walk, horizon, n_paths, np.random.default_rng(seed), drift_uncertainty)
    change = paths[..., 0] - fit.kt[-1]  # k(T+h) - k(T)
    if jump_off is None:
        return np.exp(
            fit.ax[None, None, :] + fit.bx[None, None, :] * (fit.kt[-1] + change)[..., None]
        )
    return np.asarray(jump_off)[None, None, :] * np.exp(fit.bx[None, None, :] * change[..., None])


# ── Cairns-Blake-Dowd ───────────────────────────────────────────────────────


@dataclass
class CBD:
    kappa: np.ndarray  # (2, years)
    years: np.ndarray
    mean_age: float

    def fitted_rates(self) -> np.ndarray:
        return _cbd_rates(self.kappa, self.mean_age)


def _cbd_rates(kappa: np.ndarray, mean_age: float) -> np.ndarray:
    """Rates from the two factors: ``kappa`` is (2, years) or (..., 2); ages come last or first."""
    x = CBD_AGES - mean_age
    if kappa.shape[0] == 2 and kappa.ndim == 2:
        q = special.expit(kappa[0][None, :] + kappa[1][None, :] * x[:, None])
        return q / (1 - 0.5 * q)
    q = special.expit(kappa[..., 0][..., None] + kappa[..., 1][..., None] * x)
    return q / (1 - 0.5 * q)


def fit_cbd(deaths: np.ndarray, exposure: np.ndarray, years=None) -> CBD:
    """CBD M5 by least squares on the logit of q for ages 60 to 99, one regression per year.

    ``deaths`` and ``exposure`` are the (ages 0-99, years) arrays; ``q = m / (1 + m / 2)``.
    """
    m = (np.asarray(deaths)[CBD_AGES] / np.asarray(exposure)[CBD_AGES]).clip(1e-9, 5.0)
    q = m / (1 + 0.5 * m)
    y = special.logit(q.clip(1e-12, 1 - 1e-12))
    mean_age = float(CBD_AGES.mean())
    design = np.column_stack([np.ones(len(CBD_AGES)), CBD_AGES - mean_age])
    kappa = np.linalg.lstsq(design, y, rcond=None)[0]
    years = np.arange(y.shape[1]) if years is None else np.asarray(years)
    return CBD(kappa, years, mean_age)


def forecast_cbd(
    fit: CBD,
    horizon: int,
    n_paths: int = 1000,
    seed: int = 0,
    drift_uncertainty: bool = True,
    jump_off: np.ndarray | None = None,
) -> np.ndarray:
    """Simulated rates ``(paths, horizon, 40 ages from 60)`` from the bivariate random walk.

    ``jump_off``: observed rates at ages 60 to 99 in the last year. The projection then starts
    from them: the logit of q moves by the change in the two factors, so the fitted-versus-actual
    gap of the last year is not carried into the future.
    """
    walk = fit_random_walk(fit.kappa)
    paths = simulate_walk(walk, horizon, n_paths, np.random.default_rng(seed), drift_uncertainty)
    if jump_off is None:
        return _cbd_rates(paths, fit.mean_age)
    change = paths - fit.kappa[:, -1]
    m = np.asarray(jump_off, dtype=float)
    base = special.logit((m / (1 + 0.5 * m)).clip(1e-12, 1 - 1e-12))
    x = CBD_AGES - fit.mean_age
    q = special.expit(base + change[..., 0][..., None] + change[..., 1][..., None] * x)
    return q / (1 - 0.5 * q)


# ── Closing the table and measuring it ──────────────────────────────────────


def close_old_ages(mx: np.ndarray, first_age: int = 0) -> np.ndarray:
    """Extend rates for ages ``first_age..99`` to age 110 with a logistic old-age closure.

    A line is fitted by least squares to ``logit(m)`` at ages 75 to 89 (the closed form of the
    Kannisto logistic fitted in ``graduation.py``) and used from age 90; between 84 and 90 the
    projected rates fade into it on the log scale. Ages 90 to 99 of the input are not used,
    because the data above 90 are not credible (see docs/graduation.md).
    """
    mx = np.asarray(mx, dtype=float)
    ages = np.arange(first_age, TERMINAL + 1)
    lo, hi = KANNISTO_FIT
    fit_idx = np.arange(lo, hi + 1) - first_age
    x = np.arange(lo, hi + 1, dtype=float)
    y = special.logit(mx[..., fit_idx].clip(1e-9, 1 - 1e-9))
    xc = x - x.mean()
    slope = (y * xc).sum(axis=-1) / (xc**2).sum()
    intercept = y.mean(axis=-1)
    logistic = special.expit(
        intercept[..., None] + slope[..., None] * (ages - x.mean())
    )  # Kannisto closure at every age
    w = graduation.blend_weight(ages)
    spline = np.concatenate([mx, np.ones((*mx.shape[:-1], TERMINAL + 1 - 100))], axis=-1)
    spline = np.where(spline > 0, spline, 1e-12)
    out = np.where(
        w >= 1.0,
        spline,
        np.where(w <= 0.0, logistic, np.exp(w * np.log(spline) + (1 - w) * np.log(logistic))),
    )
    return out


def period_measures(
    mx: np.ndarray, first_age: int = 0, sex: str = "M", interest: float = 0.04
) -> dict[str, np.ndarray]:
    """Life expectancy and annuity values for every table in ``mx`` (``(..., ages)``).

    ``mx`` covers ages ``first_age`` to 99 and is closed to 110 first. Returns ``e65``,
    ``a65`` (annuity-due at 65 at the given interest) and, if ``first_age == 0``, ``e0``.
    """
    m = close_old_ages(mx, first_age)
    ages = np.arange(first_age, TERMINAL + 1)
    q = m / (1 + 0.5 * m)
    if first_age == 0:
        q[..., 0] = rates.mx_to_qx(m[..., 0], 0, sex)
    q[..., -1] = 1.0
    surv = np.concatenate([np.ones((*q.shape[:-1], 1)), np.cumprod(1 - q[..., :-1], axis=-1)], -1)
    deaths = surv * q
    a = np.full(q.shape, 0.5)
    if first_age == 0:
        a[..., 0] = np.clip(1 - (m[..., 0] / q[..., 0] - 1) / m[..., 0], 0, 1)
    person_years = np.empty_like(surv)
    person_years[..., :-1] = surv[..., 1:] + a[..., :-1] * deaths[..., :-1]
    person_years[..., -1] = surv[..., -1] / m[..., -1]
    total = np.cumsum(person_years[..., ::-1], axis=-1)[..., ::-1]
    i65 = 65 - first_age
    out = {"e65": total[..., i65] / surv[..., i65]}
    v = (1.0 + interest) ** -ages.astype(float)
    discounted = np.cumsum((v * surv)[..., ::-1], axis=-1)[..., ::-1]
    out["a65"] = discounted[..., i65] / (v * surv)[..., i65]
    if first_age == 0:
        out["e0"] = total[..., 0] / surv[..., 0]
    return out


def quantiles(values: np.ndarray, levels=(0.05, 0.25, 0.5, 0.75, 0.95)) -> np.ndarray:
    """Percentiles over the path axis (axis 0): returns ``(levels, ...)``."""
    return np.quantile(values, levels, axis=0)


# ── Data from the warehouse ─────────────────────────────────────────────────

LAST_HISTORY_YEAR = 2019  # CONAPO's retrospective series ends here; later years are its projection


def load_history(con) -> pd.DataFrame:
    """CONAPO deaths and mid-year population, 1950 to 2019, national, by sex and age 0 to 99."""
    return pd.read_sql(
        "SELECT d.year, d.sex, d.age, d.deaths, e.population AS exposure "
        "FROM conapo_deaths d JOIN conapo_population e ON e.year = d.year AND e.sex = d.sex "
        "AND e.age = d.age AND e.state_code = d.state_code "
        f"WHERE d.state_code = 0 AND d.sex IN ('M', 'F') AND d.age < 100 "
        f"AND d.year <= {LAST_HISTORY_YEAR}",
        con,
    )


def load_observed(con, year: int | None = None) -> pd.DataFrame:
    """Our graduated rates (2020 onwards) at ages 0 to 99: the observed post-pandemic years."""
    where = f"AND year = {year}" if year else ""
    return pd.read_sql(f"SELECT year, sex, age, mx FROM graduated_qx WHERE age < 100 {where}", con)


# ── Backtest ────────────────────────────────────────────────────────────────

BACKTEST_ORIGINS = (1979, 1989, 1999, 2009)
BACKTEST_STARTS = (1950, 1970, 1990)
BACKTEST_HORIZONS = (10, 20)
MIN_FIT_YEARS = 20


def _actual_measures(deaths, exposure, years, year: int, sex: str) -> dict[str, float]:
    i = int(np.where(years == year)[0][0])
    m = deaths[:, i] / exposure[:, i]
    full = period_measures(m, 0, sex)
    adult = period_measures(m[60:], 60, sex)
    return {"e0": float(full["e0"]), "e65": float(adult["e65"]), "a65": float(adult["a65"])}


def backtest(
    history: pd.DataFrame,
    origins=BACKTEST_ORIGINS,
    starts=BACKTEST_STARTS,
    horizons=BACKTEST_HORIZONS,
    n_paths: int = 500,
    seed: int = 0,
) -> pd.DataFrame:
    """Rolling-origin test: fit on the years up to an origin, forecast, compare with what happened.

    For each sex, fitting window and origin it fits Lee-Carter (starting from the fitted last
    year, and from the observed one) and CBD, forecasts to 10 and 20 years ahead, and measures the
    error in life expectancy at birth (``e0``, Lee-Carter only) and at 65, the annuity value at 65
    (as a percentage) and the log-rate error. ``in_90`` says whether the actual e65 fell inside
    the 5%-95% band of the simulated paths. "Actual" is CONAPO's retrospective series, measured
    with the same code.
    """
    rows = []
    for sex in ("M", "F"):
        deaths, exposure, years = history_arrays(history, sex)
        for origin in origins:
            for start in starts:
                keep = (years >= start) & (years <= origin)
                if keep.sum() < MIN_FIT_YEARS:
                    continue
                d, e, y = deaths[:, keep], exposure[:, keep], years[keep]
                lc = fit_lee_carter(d, e, y)
                cbd = fit_cbd(d, e, y)
                h_max = (
                    max(h for h in horizons if origin + h <= LAST_HISTORY_YEAR)
                    if any(origin + h <= LAST_HISTORY_YEAR for h in horizons)
                    else 0
                )
                if h_max == 0:
                    continue
                last_obs = d[:, -1] / e[:, -1]
                sims = {
                    "lee_carter": forecast_lee_carter(lc, h_max, n_paths, seed),
                    "lee_carter_jump_off": forecast_lee_carter(
                        lc, h_max, n_paths, seed, jump_off=last_obs
                    ),
                    "cbd": forecast_cbd(cbd, h_max, n_paths, seed),
                }
                for model, paths in sims.items():
                    first_age = 60 if model == "cbd" else 0
                    for h in horizons:
                        if origin + h > LAST_HISTORY_YEAR:
                            continue
                        actual = _actual_measures(deaths, exposure, years, origin + h, sex)
                        target = paths[:, h - 1, :]
                        measures = period_measures(target, first_age, sex)
                        if model == "cbd":
                            adult = measures
                        else:
                            adult = period_measures(target[:, 60:], 60, sex)
                        central = np.median(target, axis=0)
                        actual_m = (
                            deaths[:, years == origin + h][:, 0]
                            / exposure[:, years == origin + h][:, 0]
                        )
                        lo, hi = np.quantile(adult["e65"], [0.05, 0.95])
                        rows.append(
                            {
                                "sex": sex,
                                "model": model,
                                "fit_start": start,
                                "origin": origin,
                                "horizon": h,
                                "e0_error": float(np.median(measures["e0"]) - actual["e0"])
                                if "e0" in measures
                                else np.nan,
                                "e65_forecast": float(np.median(adult["e65"])),
                                "e65_actual": actual["e65"],
                                "e65_error": float(np.median(adult["e65"]) - actual["e65"]),
                                "a65_error_pct": float(
                                    np.median(adult["a65"]) / actual["a65"] - 1.0
                                ),
                                "rmse_log_m": float(
                                    np.sqrt(
                                        np.mean(
                                            (np.log(central) - np.log(actual_m[first_age:])) ** 2
                                        )
                                    )
                                ),
                                "in_90": bool(lo <= actual["e65"] <= hi),
                            }
                        )
    return pd.DataFrame(rows)


# ── Scenarios ───────────────────────────────────────────────────────────────

FIT_START = 1970  # the backtest prefers this window to 1950: the 1950s were a different regime
LAST_YEAR = 2070  # the horizon of CONAPO's official projection
COHORT_HORIZON = 2115  # long enough for someone reaching 65 in 2070 to reach 110
RECENT_YEARS = 20  # the "recent drift" scenario uses the last 20 years of the series
FAN_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)


def central_lee_carter(
    fit: LeeCarter, horizon: int, jump_off: np.ndarray | None = None, drift_from: int | None = None
) -> np.ndarray:
    """Deterministic central path ``(horizon, ages)``: k(t) moves by its drift, no noise."""
    kt = fit.kt if drift_from is None else fit.kt[-drift_from:]
    drift = fit_random_walk(kt).drift[0]
    change = drift * np.arange(1, horizon + 1)
    if jump_off is None:
        return np.exp(fit.ax[None, :] + fit.bx[None, :] * (fit.kt[-1] + change)[:, None])
    return np.asarray(jump_off)[None, :] * np.exp(fit.bx[None, :] * change[:, None])


def _measure_rows(scenario, sex, years, measures: dict[str, np.ndarray]) -> list[dict]:
    """Rows of the scenarios table from measures of shape (paths, years) or (years,)."""
    rows = []
    for name, values in measures.items():
        values = np.asarray(values)
        if values.ndim == 1:
            band = np.tile(values[None, :], (len(FAN_LEVELS), 1))
            band[[0, 1, 3, 4]] = np.nan
        else:
            band = quantiles(values, FAN_LEVELS)
        for j, year in enumerate(years):
            rows.append(
                {
                    "scenario": scenario, "sex": sex, "year": int(year), "measure": name,
                    "p05": band[0, j], "p25": band[1, j], "p50": band[2, j],
                    "p75": band[3, j], "p95": band[4, j],
                }
            )  # fmt: skip
    return rows


def build_scenarios(
    history: pd.DataFrame,
    observed: pd.DataFrame,
    official: pd.DataFrame | None = None,
    n_paths: int = 2000,
    seed: int = 2024,
) -> dict[str, pd.DataFrame | dict]:
    """Fit the models and run every scenario.

    ``history``: CONAPO deaths and exposure to 2019. ``observed``: year, sex, age, mx for the
    graduated post-pandemic years (the last one is the jump-off). ``official``: year, sex, age, mx
    from CONAPO's projection, for comparison. Returns the scenario quantiles, the parameters, the
    central projected rates, and the cohort tables.
    """
    rows, params, central, cohorts = [], [], [], []
    last_obs = int(observed["year"].max())
    horizon = LAST_YEAR - last_obs
    for sex in ("M", "F"):
        deaths, exposure, years = history_arrays(history, sex)
        # the observed series: CONAPO's reconstruction, then our graduated rates
        hist_m = (deaths / exposure).T
        obs = observed[observed["sex"] == sex].pivot_table(index="year", columns="age", values="mx")
        obs_m = obs.to_numpy()
        obs_years = obs.index.to_numpy()
        series = np.vstack([hist_m, obs_m])
        series_years = np.concatenate([years, obs_years])
        adult = series[:, 60:]
        rows += _measure_rows(
            "observed", sex, series_years,
            {**{k: v for k, v in period_measures(series, 0, sex).items() if k != "e65"},
             "e65": period_measures(adult, 60, sex)["e65"],
             "a65": period_measures(adult, 60, sex)["a65"]},
        )  # fmt: skip

        keep = years >= FIT_START
        lc = fit_lee_carter(deaths[:, keep], exposure[:, keep], years[keep])
        cbd = fit_cbd(deaths[:, keep], exposure[:, keep], years[keep])
        params += _parameter_rows("lee_carter", sex, lc, cbd)

        jump_2019 = hist_m[-1]
        jump_obs = obs_m[-1]
        scenario_runs = {
            "pre_covid_trend": (
                forecast_lee_carter(lc, LAST_YEAR - 2019, n_paths, seed, jump_off=jump_2019),
                np.arange(2020, LAST_YEAR + 1),
            ),
            "rebased_long_run": (
                forecast_lee_carter(lc, horizon, n_paths, seed, jump_off=jump_obs),
                np.arange(last_obs + 1, LAST_YEAR + 1),
            ),
            "rebased_recent": (
                forecast_lee_carter(
                    lc, horizon, n_paths, seed, jump_off=jump_obs, drift_from=RECENT_YEARS
                ),
                np.arange(last_obs + 1, LAST_YEAR + 1),
            ),
        }
        for name, (paths, yrs) in scenario_runs.items():
            full = period_measures(paths, 0, sex)
            adult = period_measures(paths[..., 60:], 60, sex)
            rows += _measure_rows(
                name, sex, yrs, {"e0": full["e0"], "e65": adult["e65"], "a65": adult["a65"]}
            )
        cbd_paths = forecast_cbd(cbd, horizon, n_paths, seed, jump_off=jump_obs[60:])
        cbd_measures = period_measures(cbd_paths, 60, sex)
        rows += _measure_rows(
            "cbd_rebased", sex, np.arange(last_obs + 1, LAST_YEAR + 1),
            {"e65": cbd_measures["e65"], "a65": cbd_measures["a65"]},
        )  # fmt: skip

        if official is not None:
            off = official[official["sex"] == sex].pivot_table(
                index="year", columns="age", values="mx"
            )
            adult_off = period_measures(off.to_numpy()[:, 60:], 60, sex)
            rows += _measure_rows(
                "conapo_official", sex, off.index.to_numpy(),
                {"e0": period_measures(off.to_numpy(), 0, sex)["e0"],
                 "e65": adult_off["e65"], "a65": adult_off["a65"]},
            )  # fmt: skip

        # central rates for the recommended scenario, long enough for the cohort tables
        long_h = COHORT_HORIZON - last_obs
        rates_central = central_lee_carter(lc, long_h, jump_off=jump_obs)
        years_central = np.arange(last_obs + 1, COHORT_HORIZON + 1)
        closed = close_old_ages(rates_central)  # (years, 111)
        keep_years = years_central <= LAST_YEAR
        central.append(_central_rows(sex, years_central[keep_years], closed[keep_years]))
        cohorts += _cohort_rows(sex, years_central, closed)

    return {
        "scenarios": pd.DataFrame(rows),
        "parameters": pd.DataFrame(params),
        "projected_rates": apply_sex_floor(pd.concat(central, ignore_index=True)),
        "cohort_tables": pd.DataFrame(cohorts),
    }


def _parameter_rows(model: str, sex: str, lc: LeeCarter, cbd: CBD) -> list[dict]:
    rows = [{"model": model, "sex": sex, "parameter": "ax", "index": int(a), "value": float(v)}
            for a, v in zip(AGES, lc.ax, strict=True)]  # fmt: skip
    rows += [{"model": model, "sex": sex, "parameter": "bx", "index": int(a), "value": float(v)}
             for a, v in zip(AGES, lc.bx, strict=True)]  # fmt: skip
    rows += [{"model": model, "sex": sex, "parameter": "kt", "index": int(y), "value": float(v)}
             for y, v in zip(lc.years, lc.kt, strict=True)]  # fmt: skip
    for j, name in enumerate(("kappa1", "kappa2")):
        rows += [{"model": "cbd", "sex": sex, "parameter": name, "index": int(y), "value": float(v)}
                 for y, v in zip(cbd.years, cbd.kappa[j], strict=True)]  # fmt: skip
    return rows


def _central_rows(sex: str, years: np.ndarray, closed: np.ndarray) -> pd.DataFrame:
    """Projected rates and probabilities of death by year and age 0 to 110."""
    ages = np.arange(0, TERMINAL + 1)
    q = closed / (1 + 0.5 * closed)
    q[:, 0] = rates.mx_to_qx(closed[:, 0], 0, sex)
    q[:, -1] = 1.0
    return pd.DataFrame(
        {
            "year": np.repeat(years, len(ages)),
            "sex": sex,
            "age": np.tile(ages, len(years)),
            "mx": closed.ravel(),
            "qx": q.ravel(),
        }
    )


def _cohort_rows(
    sex: str, years: np.ndarray, closed: np.ndarray, interest: float = 0.04
) -> list[dict]:
    """Cohort versus period life expectancy and annuity value at 65.

    A person who is 65 in year Y lives through the rates of year Y at 65, Y + 1 at 66, and so on:
    the cohort. The period table applies the rates of year Y to every age. When mortality is
    improving the cohort lives longer, so a period table understates the cost of an annuity.
    """
    ages = np.arange(65, TERMINAL + 1)
    first = int(years[0])
    reach = np.arange(first, LAST_YEAR + 1)
    q_all = closed / (1 + 0.5 * closed)
    q_all[:, -1] = 1.0
    v = (1.0 + interest) ** -(ages - 65.0)
    out = []
    for kind in ("period", "cohort"):
        if kind == "period":
            q = q_all[np.ix_(reach - first, ages)]
            m = closed[np.ix_(reach - first, ages)]
        else:
            idx = reach[:, None] + (ages[None, :] - 65) - first
            q = q_all[idx, ages[None, :]]
            m = closed[idx, ages[None, :]]
        surv = np.concatenate([np.ones((len(reach), 1)), np.cumprod(1 - q[:, :-1], axis=1)], axis=1)
        deaths = surv * q
        big_l = np.empty_like(surv)
        big_l[:, :-1] = surv[:, 1:] + 0.5 * deaths[:, :-1]
        big_l[:, -1] = surv[:, -1] / m[:, -1]
        out.append((big_l.sum(axis=1), (v * surv).sum(axis=1)))
    (e_period, a_period), (e_cohort, a_cohort) = out
    return [
        {
            "sex": sex, "year_at_65": int(y), "period_e65": float(ep), "cohort_e65": float(ec),
            "period_a65": float(ap), "cohort_a65": float(ac),
            "annuity_understated_pct": float(ac / ap - 1.0),
        }
        for y, ep, ec, ap, ac in zip(reach, e_period, e_cohort, a_period, a_cohort, strict=True)
    ]  # fmt: skip


# ── Cross-check against R (StMoMo) ──────────────────────────────────────────


def run_r_crosscheck(history: pd.DataFrame, rscript, script, first_year: int = FIT_START,
                     horizon: int = 50) -> pd.DataFrame | None:  # fmt: skip
    """Fit the same Lee-Carter and CBD models with StMoMo in R and compare.

    Returns one row per quantity with the Python value, the R value and their difference, or
    ``None`` when R or the package is not available (the build must not depend on it).
    """
    import subprocess
    import tempfile
    from pathlib import Path

    if rscript is None or not Path(rscript).exists() or not Path(script).exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = history[history["year"] >= first_year].sort_values(["sex", "year", "age"])
        source.to_csv(tmp / "input.csv", index=False)
        try:
            result = subprocess.run(
                [str(rscript), str(script), str(tmp / "input.csv"), str(tmp),
                 str(first_year), str(LAST_HISTORY_YEAR), str(horizon)],
                capture_output=True, text=True, timeout=600,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not (tmp / "lc_kt.csv").exists():
            return None
        r = {n: pd.read_csv(tmp / f"{n}.csv") for n in
             ("lc_params", "lc_kt", "lc_forecast", "cbd_kappa", "cbd_forecast")}  # fmt: skip
    return _compare_with_r(history, r, first_year, horizon)


def _compare_with_r(history, r, first_year: int, horizon: int) -> pd.DataFrame:
    rows = []
    target = LAST_HISTORY_YEAR + horizon
    for sex in ("M", "F"):
        deaths, exposure, years = history_arrays(history, sex)
        keep = years >= first_year
        lc = fit_lee_carter(deaths[:, keep], exposure[:, keep], years[keep])
        cbd = fit_cbd(deaths[:, keep], exposure[:, keep], years[keep])
        kt_r = r["lc_kt"][r["lc_kt"]["sex"] == sex]["kt"].to_numpy()
        bx_r = r["lc_params"][r["lc_params"]["sex"] == sex]["bx"].to_numpy()
        rows.append(
            _row(
                sex, "lee_carter", "k(t) largest difference", float(np.abs(lc.kt - kt_r).max()), 0.0
            )
        )
        rows.append(
            _row(
                sex, "lee_carter", "b(x) largest difference", float(np.abs(lc.bx - bx_r).max()), 0.0
            )
        )
        drift_py = float(np.diff(lc.kt).mean())
        rows.append(_row(sex, "lee_carter", "drift of k(t)", drift_py, float(np.diff(kt_r).mean())))

        fc = r["lc_forecast"][r["lc_forecast"]["sex"] == sex].pivot_table(
            index="year", columns="age", values="rate"
        )
        py_fc = central_lee_carter(lc, horizon)
        for year in (2030, target):
            i = year - LAST_HISTORY_YEAR - 1
            m_py = period_measures(py_fc[i], 0, sex)
            m_r = period_measures(fc.loc[year].to_numpy(), 0, sex)
            rows.append(
                _row(sex, "lee_carter", f"e0 in {year}", float(m_py["e0"]), float(m_r["e0"]))
            )
            rows.append(
                _row(sex, "lee_carter", f"e65 in {year}", float(m_py["e65"]), float(m_r["e65"]))
            )

        kr = r["cbd_kappa"][r["cbd_kappa"]["sex"] == sex]
        for j, name in enumerate(("kappa1", "kappa2")):
            gap = float(np.abs(cbd.kappa[j] - kr[name].to_numpy()).max())
            rows.append(_row(sex, "cbd", f"{name} largest difference", gap, 0.0))
        cf = r["cbd_forecast"][r["cbd_forecast"]["sex"] == sex].pivot_table(
            index="year", columns="age", values="rate"
        )
        walk = fit_random_walk(cbd.kappa)
        steps = walk.last[None, :] + walk.drift[None, :] * np.arange(1, horizon + 1)[:, None]
        py_cbd = _cbd_rates(steps, cbd.mean_age)
        for year in (2030, target):
            i = year - LAST_HISTORY_YEAR - 1
            e_py = float(period_measures(py_cbd[i], 60, sex)["e65"])
            e_r = float(period_measures(cf.loc[year].to_numpy(), 60, sex)["e65"])
            rows.append(_row(sex, "cbd", f"e65 in {year}", e_py, e_r))
    return pd.DataFrame(rows)


def _row(sex: str, model: str, quantity: str, python: float, r: float) -> dict:
    return {"sex": sex, "model": model, "quantity": quantity, "python": python, "r": r,
            "difference": python - r}  # fmt: skip


# ── Calibration and the gap between sources ─────────────────────────────────

AGE_BANDS = (
    ("0", 0, 0), ("1-14", 1, 14), ("15-39", 15, 39), ("40-59", 40, 59),
    ("60-74", 60, 74), ("75-89", 75, 89), ("90-99", 90, 99),
)  # fmt: skip


def backtest_calibration(bt: pd.DataFrame) -> pd.DataFrame:
    """How wrong the forecasts actually were, as a scale that grows with the horizon.

    The model's own fan covers only the random walk, and the backtest shows that is too narrow
    (the structural change in Mexican men's mortality after 1999 is not noise). For the
    recommended model (Lee-Carter, restarted at the last observed rates, fitted from 1970) the
    errors of e0, e65 and the annuity value at 65 are fitted to ``error = c sqrt(horizon)``, the
    way a random walk's error grows, giving ``c`` per sex and measure.
    """
    sel = bt[(bt["model"] == "lee_carter_jump_off") & (bt["fit_start"] == FIT_START)]
    rows = []
    for sex, part in sel.groupby("sex"):
        for measure, column in (("e0", "e0_error"), ("e65", "e65_error"), ("a65", "a65_error_pct")):
            err = part[column].dropna()
            h = part.loc[err.index, "horizon"].astype(float)
            if len(err):
                rows.append(
                    {
                        "sex": sex, "measure": measure, "n_tests": len(err),
                        "c": float(np.sqrt(np.mean(err**2 / h))),
                        "kind": "relative" if measure == "a65" else "years",
                    }
                )  # fmt: skip
    return pd.DataFrame(rows)


def source_gap(con) -> pd.DataFrame:
    """INEGI-based graduated rates against CONAPO's modeled rates, by age band, 2020 onwards.

    Deaths are compared on the same population: the graduated rate times CONAPO's population
    against CONAPO's modeled deaths. A ratio below 1 means INEGI registers fewer deaths than
    CONAPO models in that age band.
    """
    df = pd.read_sql(
        "SELECT g.year, g.sex, g.age, g.mx * e.population AS deaths_inegi, "
        "d.deaths AS deaths_conapo FROM graduated_qx g JOIN conapo_population e "
        "ON e.year = g.year AND e.sex = g.sex "
        "AND e.age = g.age AND e.state_code = 0 "
        "JOIN conapo_deaths d ON d.year = g.year AND d.sex = g.sex AND d.age = g.age "
        "AND d.state_code = 0 WHERE g.age < 100",
        con,
    )
    rows = []
    for label, lo, hi in AGE_BANDS:
        part = df[df["age"].between(lo, hi)]
        grouped = (
            part.groupby(["year", "sex"])[["deaths_inegi", "deaths_conapo"]].sum().reset_index()
        )
        rows.append(grouped.assign(age_band=label))
    out = pd.concat(rows, ignore_index=True)
    out["ratio"] = out["deaths_inegi"] / out["deaths_conapo"]
    return out[["year", "sex", "age_band", "deaths_inegi", "deaths_conapo", "ratio"]]


# ── Warehouse tables ────────────────────────────────────────────────────────

DESCRIPTIONS = {
    "projection_parameters": (
        "Fitted Lee-Carter (a(x), b(x), k(t)) and CBD (kappa1, kappa2) parameters by sex, fitted "
        "to CONAPO's 1970-2019 series"
    ),
    "projection_backtest": (
        "Rolling-origin test of Lee-Carter and CBD forecasts against CONAPO's reconstruction: "
        "errors in e0, e65 and the annuity value at 65, and whether the actual e65 fell inside "
        "the 90% band"
    ),
    "projection_scenarios": (
        "Life expectancy at birth and 65 and the annuity value at 65 by scenario, sex and year "
        "to 2070, with the 5/25/50/75/95 percentiles of 2,000 simulated paths (fan charts)"
    ),
    "projected_qx": (
        "Central projected m and q by year (2025-2070), sex and age 0 to 110 for the rebased "
        "long-run scenario: the mortality-improvement table for pricing and reserving"
    ),
    "cohort_tables": (
        "Life expectancy and annuity value at 65 for the cohort reaching 65 in each year, "
        "against the period table of that year: how much a period table understates longevity"
    ),
    "projection_r_crosscheck": (
        "Python Lee-Carter and CBD against the same models fitted with StMoMo in R"
    ),
    "projection_calibration": (
        "Scale c of the backtest errors (error = c x sqrt(horizon)) for e0, e65 and the annuity "
        "value at 65: the empirical width of the fan, wider than the model's own"
    ),
    "source_gap": (
        "Deaths implied by INEGI-based graduated rates against CONAPO's modeled deaths on the "
        "same population, by year, sex and age band: the two sources disagree on the age pattern"
    ),
}


def build_tables(con, *, run_r: bool = True) -> list[tuple[str, str]]:
    """Fit, back-test and project; write the projection tables to the warehouse."""
    from mortality.config import find_rscript, get_paths

    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"conapo_deaths", "conapo_population", "graduated_qx"} <= names:
        return []
    history = load_history(con)
    observed = load_observed(con)
    if history.empty or observed.empty:
        return []
    try:
        for sex in ("M", "F"):
            history_arrays(history, sex)
            if len(observed[observed["sex"] == sex]) < 100:
                return []
    except ValueError:
        return []
    official = pd.read_sql(
        "SELECT d.year, d.sex, d.age, d.deaths / e.population AS mx FROM conapo_deaths d "
        "JOIN conapo_population e ON e.year = d.year AND e.sex = d.sex AND e.age = d.age "
        "AND e.state_code = d.state_code WHERE d.state_code = 0 AND d.sex IN ('M', 'F') "
        f"AND d.age < 100 AND d.year > {LAST_HISTORY_YEAR}",
        con,
    )
    frames = build_scenarios(history, observed, official if len(official) else None)
    frames["backtest"] = backtest(history)
    frames["calibration"] = backtest_calibration(frames["backtest"])
    frames["source_gap"] = source_gap(con)
    if run_r:
        script = get_paths().root / "r" / "projection_stmomo.R"
        check = run_r_crosscheck(history, find_rscript(), script)
        if check is not None:
            frames["r_crosscheck"] = check
    table_names = {
        "parameters": "projection_parameters",
        "backtest": "projection_backtest",
        "scenarios": "projection_scenarios",
        "projected_rates": "projected_qx",
        "cohort_tables": "cohort_tables",
        "r_crosscheck": "projection_r_crosscheck",
        "calibration": "projection_calibration",
        "source_gap": "source_gap",
    }
    docs = []
    for key, name in table_names.items():
        if key in frames and len(frames[key]):
            frames[key].to_sql(name, con, if_exists="replace", index=False)
            docs.append((name, DESCRIPTIONS[name]))
    return docs


def apply_sex_floor(projected: pd.DataFrame) -> pd.DataFrame:
    """Keep projected male rates at least equal to female ones from age 84 (see graduation.py).

    The closure is fitted to each sex separately; improvement can carry the male rate below the
    female one at the oldest ages, which no population shows.
    """
    out = projected.copy()
    male = out[out["sex"] == "M"].set_index(["year", "age"])
    female = out[out["sex"] == "F"].set_index(["year", "age"])
    low = (male["mx"] < female["mx"].reindex(male.index)) & (
        male.index.get_level_values("age") >= BLEND[0]
    )
    male.loc[low, "mx"] = female["mx"].reindex(male.index)[low]
    age = male.index.get_level_values("age")
    raised = low & (age < TERMINAL)
    male.loc[raised, "qx"] = male.loc[raised, "mx"] / (1 + 0.5 * male.loc[raised, "mx"])
    out.loc[out["sex"] == "M", ["mx", "qx"]] = male[["mx", "qx"]].to_numpy()
    return out
