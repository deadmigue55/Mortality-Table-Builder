"""Graduation: smooth, credible death rates from noisy crude ones.

Crude single-age rates carry random noise and, at the oldest ages, data problems (see
docs/graduation.md). Graduation fits a smooth curve through them. Four methods are compared on
the same data, then an old-age closure completes the table to age 110:

* **Poisson P-spline** (Eilers and Marx): a B-spline curve for log m with a penalty on second
  differences of its coefficients, fitted by penalized maximum likelihood.
* **Whittaker-Henderson**: the classic actuarial graduation, a weighted least-squares fit on
  log m with a penalty on third differences. It is the P-spline with one coefficient per age.
* **Heligman-Pollard** (1980): eight-parameter law for the whole age range.
* **Gompertz-Makeham**: the textbook adult-age law, a baseline that is expected to fit badly.
* **Kannisto** logistic: the closure for the oldest ages (Thatcher, Kannisto and Vaupel, 1998).

The smoothing parameter is chosen by a quasi-AIC. Counts here are in the hundreds of thousands,
so any smooth curve is statistically "rejected" by a plain chi-square (the crude rates contain
systematic irregularities, not just Poisson noise). QAIC divides the deviance by a dispersion
estimated from the crude rates' own high-order differences, so the penalty is not drowned by
that irregularity and the choice does not depend on any fitted curve.

Everything is a plain function on NumPy arrays; ``build_tables`` wires it to the warehouse.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import comb

import numpy as np
import pandas as pd
from scipy import optimize, special, stats
from scipy.interpolate import BSpline

from mortality import rates

DEGREE = 3  # cubic B-splines
FIT_AGES = (1, 89)  # ages the smoothers are fitted on (age 0 is kept crude: its own curve)
KANNISTO_AGES = (75, 89)  # ages the old-age closure is fitted on
BLEND = (84, 90)  # the spline fades out and Kannisto takes over between these ages
TERMINAL = 110  # q = 1 at this age
LAMBDA_GRID = np.logspace(-2, 8, 61)
SPLINE_SEGMENTS = 40  # knot intervals across the fitting range: generous, the penalty smooths
DISPERSION_ORDER = 4  # difference order for the noise estimate


# ── Building blocks ─────────────────────────────────────────────────────────


def bspline_basis(x, lo: float, hi: float, segments: int, degree: int = DEGREE) -> np.ndarray:
    """Equally spaced B-spline design matrix over [lo, hi] (one row per x)."""
    x = np.asarray(x, dtype=float)
    step = (hi - lo) / segments
    inner = np.linspace(lo, hi, segments + 1)
    left = lo - step * np.arange(degree, 0, -1)
    right = hi + step * np.arange(1, degree + 1)
    knots = np.concatenate([left, inner, right])
    return BSpline.design_matrix(x, knots, degree, extrapolate=False).toarray()


def difference_penalty(n: int, order: int) -> np.ndarray:
    """``D'D`` for the ``order``-th difference operator on ``n`` coefficients."""
    diff = np.diff(np.eye(n), order, axis=0)
    return diff.T @ diff


def poisson_deviance(deaths, expected) -> float:
    d = np.asarray(deaths, dtype=float)
    mu = np.asarray(expected, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(d > 0, d * np.log(d / mu), 0.0)
    return float(2 * np.sum(term - (d - mu)))


@dataclass
class Graduation:
    """A fitted smooth curve over some ages."""

    method: str
    ages: np.ndarray
    mx: np.ndarray  # fitted central death rate per age
    log_var: np.ndarray  # variance of log mx per age (unscaled by dispersion)
    lam: float | None
    edf: float
    deviance: float
    dispersion: float
    path: pd.DataFrame  # lambda search: log10_lambda, edf, deviance, qaic

    def interval(self, level: float = 0.95) -> tuple[np.ndarray, np.ndarray]:
        """Approximate interval for the rate; variance is scaled by the dispersion."""
        z = stats.norm.ppf(0.5 + level / 2)
        half = z * np.sqrt(self.log_var * max(self.dispersion, 1.0))
        return self.mx * np.exp(-half), self.mx * np.exp(half)


def noise_dispersion(deaths, order: int = DISPERSION_ORDER) -> float:
    """Overdispersion of the crude counts, estimated from their own high-order differences.

    For a smooth underlying curve the ``order``-th differences of ``log D`` are mostly noise,
    with a known variance under Poisson sampling (``sum C(k, j)^2 / D``). Their ratio is the
    dispersion: 1 means pure Poisson noise, 2 means twice as much scatter as sampling alone
    explains. It does not depend on any fitted curve, so it cannot be fooled by an over-flexible
    fit, and it is stable across difference orders 3 to 5.
    """
    d = np.asarray(deaths, dtype=float)
    k = order
    coef = np.array([(-1) ** j * comb(k, j) for j in range(k + 1)], dtype=float)
    diff = np.convolve(np.log(d), coef, mode="valid")
    var = np.convolve(1.0 / d, coef**2, mode="valid")
    return float(max(1.0, np.mean(diff**2 / var)))


def select_lambda(
    evaluate: Callable[[float], tuple[float, float]], dispersion: float, grid=LAMBDA_GRID
) -> tuple[float, pd.DataFrame]:
    """Choose lambda by quasi-AIC, ``deviance / dispersion + 2 edf`` (Burnham and Anderson, 2002).

    ``evaluate(lam)`` returns ``(deviance, effective degrees of freedom)``. Dividing the
    deviance by the dispersion stops systematic irregularity in the crude rates (not Poisson
    noise) from being chased by an over-flexible curve.
    """
    rows = [(lam, *evaluate(float(lam))) for lam in grid]
    path = pd.DataFrame(rows, columns=["lam", "deviance", "edf"])
    path["qaic"] = path["deviance"] / dispersion + 2 * path["edf"]
    path.insert(0, "log10_lambda", np.log10(path["lam"]))
    chosen = float(path.loc[int(path["qaic"].idxmin()), "lam"])
    return chosen, path.drop(columns="lam")


# ── Poisson P-spline ────────────────────────────────────────────────────────


def _pspline_solve(d, e, basis, penalty, lam, iterations=100, tol=1e-10):
    theta = np.linalg.lstsq(basis, np.log((d + 0.5) / e), rcond=None)[0]
    for _ in range(iterations):
        eta = basis @ theta
        mu = e * np.exp(eta)
        z = eta + (d - mu) / mu  # working response
        weighted = basis.T * mu
        lhs = weighted @ basis + lam * penalty + 1e-9 * np.eye(len(theta))
        new = np.linalg.solve(lhs, weighted @ z)
        if np.max(np.abs(new - theta)) < tol:
            theta = new
            break
        theta = new
    eta = basis @ theta
    mu = e * np.exp(eta)
    weighted = basis.T * mu
    lhs = weighted @ basis + lam * penalty + 1e-9 * np.eye(len(theta))
    cov = np.linalg.inv(lhs)
    edf = float(np.trace(cov @ (weighted @ basis)))
    return theta, mu, edf, cov


def pspline(ages, deaths, exposure, *, order: int = 2, lam: float | None = None) -> Graduation:
    """Poisson P-spline graduation of ``deaths / exposure`` over ``ages``."""
    x = np.asarray(ages, dtype=float)
    d = np.asarray(deaths, dtype=float)
    e = np.asarray(exposure, dtype=float)
    basis = bspline_basis(x, x.min(), x.max(), SPLINE_SEGMENTS)
    penalty = difference_penalty(basis.shape[1], order)

    def evaluate(value: float) -> tuple[float, float]:
        _, mu, edf, _ = _pspline_solve(d, e, basis, penalty, value)
        return poisson_deviance(d, mu), edf

    dispersion = noise_dispersion(d)
    path = pd.DataFrame()
    if lam is None:
        lam, path = select_lambda(evaluate, dispersion)
    _, mu, edf, cov = _pspline_solve(d, e, basis, penalty, lam)
    log_var = np.einsum("ij,jk,ik->i", basis, cov, basis)
    return Graduation(
        "pspline", x, mu / e, log_var, lam, edf, poisson_deviance(d, mu), dispersion, path
    )


# ── Whittaker-Henderson ─────────────────────────────────────────────────────


def whittaker_henderson(
    ages, deaths, exposure, *, order: int = 3, lam: float | None = None
) -> Graduation:
    """Classic Whittaker-Henderson graduation of log m with weights equal to deaths.

    ``var(log m) ~ 1 / deaths`` for a Poisson count, so deaths are the inverse-variance weights.
    The result minimizes ``sum w (y - z)^2 + lam * sum (diff^order z)^2``.
    """
    x = np.asarray(ages, dtype=float)
    d = np.asarray(deaths, dtype=float)
    e = np.asarray(exposure, dtype=float)
    y = np.log(d / e)
    w = d
    penalty = difference_penalty(len(x), order)
    weights = np.diag(w)

    def solve(value: float):
        lhs = weights + value * penalty
        inv = np.linalg.inv(lhs)
        z = inv @ (w * y)
        return z, inv

    def evaluate(value: float) -> tuple[float, float]:
        z, inv = solve(value)
        return float(np.sum(w * (y - z) ** 2)), float(np.trace(inv @ weights))

    dispersion = noise_dispersion(d)
    path = pd.DataFrame()
    if lam is None:
        lam, path = select_lambda(evaluate, dispersion)
    z, inv = solve(lam)
    log_var = np.diag(inv @ weights @ inv)
    mx = np.exp(z)
    deviance = poisson_deviance(d, e * mx)
    return Graduation(
        "whittaker_henderson",
        x,
        mx,
        log_var,
        lam,
        float(np.trace(inv @ weights)),
        deviance,
        dispersion,
        path,
    )


# ── Parametric laws ─────────────────────────────────────────────────────────


def heligman_pollard(x, p) -> np.ndarray:
    """Heligman-Pollard (1980) central rate: q/p = A^((x+B)^C) + D exp(-E ln(x/F)^2) + G H^x."""
    a, b, c, d, e, f, g, h = p
    x = np.asarray(x, dtype=float)
    odds = a ** ((x + b) ** c) + d * np.exp(-e * np.log(x / f) ** 2) + g * h**x
    q = odds / (1 + odds)
    return q / (1 - 0.5 * q)


def gompertz_makeham(x, p) -> np.ndarray:
    """Gompertz-Makeham force of mortality: A + B c^x."""
    a, b, c = p
    return a + b * np.asarray(c) ** np.asarray(x, dtype=float)


def kannisto(x, p) -> np.ndarray:
    """Kannisto logistic, anchored at age 80: m = a e^(b(x-80)) / (1 + a e^(b(x-80)))."""
    a, b = p
    t = a * np.exp(b * (np.asarray(x, dtype=float) - 80.0))
    return t / (1 + t)


HP_START = (0.0005, 0.01, 0.1, 0.0008, 10.0, 22.0, 4e-5, 1.1)
HP_BOUNDS = (
    (1e-6, 0.05),
    (1e-4, 1.0),
    (0.01, 0.7),
    (1e-6, 0.05),
    (0.5, 60.0),
    (8.0, 45.0),
    (1e-8, 1e-2),
    (1.02, 1.25),
)
GM_START = (5e-4, 3e-5, 1.1)
GM_BOUNDS = ((1e-7, 0.01), (1e-9, 1e-2), (1.02, 1.25))
KANNISTO_START = (0.15, 0.1)
KANNISTO_BOUNDS = ((1e-4, 5.0), (0.01, 0.6))


def fit_parametric(
    law: Callable, ages, deaths, exposure, start, bounds, *, starts: int = 6, seed: int = 0
) -> tuple[np.ndarray, float]:
    """Poisson maximum likelihood for a mortality law; returns (parameters, deviance).

    Minimizing the Poisson deviance is the same as maximizing the likelihood, and writing it as
    a sum of squared deviance residuals lets a least-squares solver with Jacobian-based scaling
    handle parameters whose effects differ by orders of magnitude (the childhood terms of
    Heligman-Pollard against the old-age terms), which a plain likelihood optimizer does not.
    The first start is ``start``; the others are random perturbations inside the bounds, since
    laws like Heligman-Pollard have several local optima. The lowest deviance wins.
    """
    x = np.asarray(ages, dtype=float)
    d = np.asarray(deaths, dtype=float)
    e = np.asarray(exposure, dtype=float)
    lo, hi = np.array(bounds).T
    rng = np.random.default_rng(seed)

    def residuals(p) -> np.ndarray:
        mu = e * np.clip(law(x, p), 1e-12, 5.0)
        dev = 2 * (special.xlogy(d, d / mu) - (d - mu))
        return np.sign(d - mu) * np.sqrt(np.clip(dev, 0.0, None))

    candidates = [np.clip(np.asarray(start, dtype=float), lo, hi)]
    for _ in range(starts - 1):
        jitter = np.exp(rng.normal(0, 0.35, len(start)))
        candidates.append(np.clip(np.asarray(start) * jitter, lo, hi))
    best = None
    for p0 in candidates:
        with np.errstate(all="ignore"):
            res = optimize.least_squares(
                residuals,
                p0,
                bounds=(lo, hi),
                x_scale="jac",
                xtol=1e-14,
                ftol=1e-14,
                gtol=1e-14,
                max_nfev=3000,
            )
        if np.isfinite(res.cost) and (best is None or res.cost < best.cost):
            best = res
    if best is None:
        raise RuntimeError("parametric fit failed from every start")
    return best.x, float(2 * best.cost)


def parametric(name: str, law, ages, deaths, exposure, start, bounds, *, n_params: int):
    """Fit a law and wrap it like a smoother so the comparison code treats all the same."""
    params, deviance = fit_parametric(law, ages, deaths, exposure, start, bounds)
    x = np.asarray(ages, dtype=float)
    mx = law(x, params)
    n = len(x)
    dispersion = max(1.0, deviance / max(n - n_params, 1))
    grad = np.zeros(n)  # no analytic interval for the laws
    return Graduation(
        name, x, mx, grad, None, float(n_params), deviance, dispersion, pd.DataFrame()
    ), params


# ── Fit tests ───────────────────────────────────────────────────────────────


def fit_tests(deaths, exposure, mx, edf: float) -> dict[str, float]:
    """The standard graduation tests on standardized residuals ``(D - E) / sqrt(E)``.

    With counts this large, the chi-square and the runs test almost always flag *some* lack of
    fit; the dispersion (chi-square per degree of freedom) says how large it is, and the share
    of residuals beyond 2 should be near 4.6% for a good fit.
    """
    d = np.asarray(deaths, dtype=float)
    exp = np.asarray(exposure, dtype=float) * np.asarray(mx, dtype=float)
    n = len(d)
    z = (d - exp) / np.sqrt(exp)
    chi2 = float(np.sum(z**2))
    df = max(n - edf, 1.0)
    positive = int((z > 0).sum())
    negative = n - positive
    signs_p = float(stats.binomtest(positive, n, 0.5).pvalue)
    changes = int(np.sum(np.sign(z[1:]) != np.sign(z[:-1])))
    runs = changes + 1
    n_total = positive + negative
    mean_runs = 2 * positive * negative / n_total + 1
    var_runs = (2 * positive * negative * (2 * positive * negative - n_total)) / (
        n_total**2 * (n_total - 1)
    )
    runs_p = float(2 * stats.norm.sf(abs((runs - mean_runs) / np.sqrt(var_runs))))
    r1 = float(np.sum(z[:-1] * z[1:]) / np.sqrt(np.sum(z[:-1] ** 2) * np.sum(z[1:] ** 2)))
    serial_p = float(2 * stats.norm.sf(abs(r1) * np.sqrt(n)))
    cum_z = float(np.sum(d - exp) / np.sqrt(np.sum(exp)))
    third = np.diff(np.log(np.asarray(mx, dtype=float)), 3)
    return {
        "n_ages": n,
        "edf": float(edf),
        "deviance": poisson_deviance(d, exp),
        "chi2": chi2,
        "df": df,
        "dispersion": chi2 / df,
        "chi2_p": float(stats.chi2.sf(chi2, df)),
        "signs_p": signs_p,
        "runs": runs,
        "runs_p": runs_p,
        "serial_corr": r1,
        "serial_p": serial_p,
        "cumulative_dev_z": cum_z,
        "share_beyond_2": float(np.mean(np.abs(z) > 2)),
        "smoothness": float(np.mean(np.abs(third))),
    }


# ── Old-age closure and the final table ─────────────────────────────────────


def blend_weight(ages) -> np.ndarray:
    """Weight on the spline: 1 up to ``BLEND[0]``, 0 from ``BLEND[1]``, linear in between."""
    lo, hi = BLEND
    return np.clip((hi - np.asarray(ages, dtype=float)) / (hi - lo), 0.0, 1.0)


def mx_to_q(mx) -> np.ndarray:
    """q from a central rate above infancy (a = 0.5)."""
    m = np.asarray(mx, dtype=float)
    return m / (1 + 0.5 * m)


def assemble_table(age0: dict[str, float], spline: Graduation, closure_params) -> pd.DataFrame:
    """Join infant, spline and Kannisto pieces into one table from age 0 to ``TERMINAL``.

    ``age0`` has the crude infant ``mx``, ``qx`` and its interval. The spline covers ages 1 to
    89, Kannisto covers 75 to 110; between ``BLEND`` ages the two are mixed on the log scale.
    """
    ages = np.arange(1, TERMINAL + 1)
    kan = kannisto(ages, closure_params)
    sp = np.full(len(ages), np.nan)
    inside = ages <= spline.ages.max()
    sp[inside] = np.interp(ages[inside], spline.ages, spline.mx)
    w = blend_weight(ages)
    mx = np.where(w >= 1, sp, np.where(w <= 0, kan, np.exp(w * np.log(sp) + (1 - w) * np.log(kan))))
    source = np.where(w >= 1, "pspline", np.where(w <= 0, "kannisto", "blend"))
    lower, upper = spline.interval()
    lo = np.full(len(ages), np.nan)
    hi = np.full(len(ages), np.nan)
    lo[inside], hi[inside] = (
        np.interp(ages[inside], spline.ages, lower),
        np.interp(ages[inside], spline.ages, upper),
    )
    keep = w >= 1
    table = pd.DataFrame(
        {
            "age": ages,
            "mx": mx,
            "mx_lower": np.where(keep, lo, np.nan),
            "mx_upper": np.where(keep, hi, np.nan),
            "qx": mx_to_q(mx),
            "source": source,
        }
    )
    table.loc[table["age"] == TERMINAL, "qx"] = 1.0
    infant = pd.DataFrame(
        {
            "age": [0],
            "mx": [age0["mx"]],
            "mx_lower": [age0["mx_lower"]],
            "mx_upper": [age0["mx_upper"]],
            "qx": [age0["qx"]],
            "source": ["crude"],
        }
    )
    return pd.concat([infant, table], ignore_index=True)


def graduate_cell(deaths: pd.DataFrame) -> dict:
    """Graduate one year-and-sex cell with every method.

    ``deaths``: age, deaths, exposure for ages 0 to 99. Returns the fitted objects, tests,
    parameters and the final table.
    """
    d = deaths.set_index("age")
    lo, hi = FIT_AGES
    fit = d.loc[lo:hi]
    ages, dd, ee = fit.index.to_numpy(), fit["deaths"].to_numpy(), fit["exposure"].to_numpy()

    fits: dict[str, Graduation] = {
        "pspline": pspline(ages, dd, ee),
        "whittaker_henderson": whittaker_henderson(ages, dd, ee),
    }
    params: dict[str, np.ndarray] = {}
    fits["heligman_pollard"], params["heligman_pollard"] = parametric(
        "heligman_pollard", heligman_pollard, ages, dd, ee, HP_START, HP_BOUNDS, n_params=8
    )
    adult = ages >= 35
    fits["gompertz_makeham"], params["gompertz_makeham"] = parametric(
        "gompertz_makeham",
        gompertz_makeham,
        ages[adult],
        dd[adult],
        ee[adult],
        GM_START,
        GM_BOUNDS,
        n_params=3,
    )

    k_lo, k_hi = KANNISTO_AGES
    old = d.loc[k_lo:k_hi]
    k_params, _ = fit_parametric(
        kannisto,
        old.index.to_numpy(),
        old["deaths"].to_numpy(),
        old["exposure"].to_numpy(),
        KANNISTO_START,
        KANNISTO_BOUNDS,
    )
    params["kannisto"] = k_params

    infant = deaths[deaths["age"] == 0].iloc[0]
    sex = deaths["sex"].iloc[0] if "sex" in deaths else "M"
    m0 = infant["deaths"] / infant["exposure"]
    m0_lo, m0_hi = rates.rate_interval(infant["deaths"], infant["exposure"])
    age0 = {
        "mx": m0,
        "mx_lower": float(m0_lo),
        "mx_upper": float(m0_hi),
        "qx": float(rates.mx_to_qx(m0, 0, sex)),
    }
    return {
        "fits": fits,
        "params": params,
        "table": assemble_table(age0, fits["pspline"], k_params),
        "tests": {
            name: fit_tests(dd[np.isin(ages, g.ages)], ee[np.isin(ages, g.ages)], g.mx, g.edf)
            for name, g in fits.items()
        },
    }


# ── Sex order at the oldest ages ────────────────────────────────────────────


def enforce_sex_order(male: pd.DataFrame, female: pd.DataFrame, from_age: int = BLEND[0]):
    """Make male rates at least the female rates from ``from_age`` upwards.

    In Mexican data women overtake men from about age 88 (see docs/graduation.md), which no
    population shows and which points to overstated age, and so overstated exposure, among the
    oldest men. Where the closure leaves men below women, the male rate is raised to the female
    one. Returns the adjusted male table with a ``sex_floor`` column marking the ages changed.
    """
    out = male.copy()
    fem = female.set_index("age")["mx"].reindex(out["age"]).to_numpy()
    low = (out["age"].to_numpy() >= from_age) & (out["mx"].to_numpy() < fem)
    out.loc[low, "mx"] = fem[low]
    out.loc[low, ["mx_lower", "mx_upper"]] = np.nan
    out["qx"] = np.where(out["age"] == TERMINAL, 1.0, mx_to_q(out["mx"]))
    out.loc[out["age"] == 0, "qx"] = male.loc[male["age"] == 0, "qx"].to_numpy()
    out["sex_floor"] = low
    return out


# ── Warehouse tables ────────────────────────────────────────────────────────


def digit_preference(
    crude: pd.DataFrame, fitted: pd.DataFrame, lo: int = 25, hi: int = 70
) -> pd.DataFrame:
    """Excess deaths at ages ending in 0 or 5, measured against the smooth fit.

    A smooth curve cannot follow digit preference, so it shows up in the residuals: a positive
    excess at ages 25, 30, ... 70 and a small deficit between them. This is more sensitive than
    the Whipple index, which averages over the whole age range and over both sexes.

    ``crude``: year, sex, age, deaths, exposure. ``fitted``: year, sex, age, mx (a smoother).
    """
    m = crude.merge(fitted[["year", "sex", "age", "mx"]], on=["year", "sex", "age"])
    m = m[m["age"].between(lo, hi)].copy()
    m["expected"] = m["exposure"] * m["mx"]
    m["z"] = (m["deaths"] - m["expected"]) / np.sqrt(m["expected"])
    m["round_age"] = m["age"] % 5 == 0
    rows = []
    for (year, sex), cell in m.groupby(["year", "sex"]):
        on, off = cell[cell["round_age"]], cell[~cell["round_age"]]
        rows.append(
            {
                "year": year,
                "sex": sex,
                "excess_at_0_5": on["deaths"].sum() / on["expected"].sum() - 1,
                "excess_elsewhere": off["deaths"].sum() / off["expected"].sum() - 1,
                "mean_z_at_0_5": on["z"].mean(),
                "mean_z_elsewhere": off["z"].mean(),
            }
        )
    return pd.DataFrame(rows)


def graduable(cell: pd.DataFrame) -> bool:
    """True when a year-and-sex cell has positive deaths and exposure at every age 0 to 99.

    The smoothers work on log rates, so a missing age or a zero count would break them; a
    partial warehouse (a handful of test records, say) is skipped rather than crashing the build.
    """
    ages = cell["age"].to_numpy()
    if not np.array_equal(np.sort(ages), np.arange(100)):
        return False
    return bool((cell["deaths"] > 0).all() and (cell["exposure"] > 0).all())


def graduate_all(crude: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Graduate every year and sex; returns the long tables the warehouse stores.

    ``crude``: year, sex, age, deaths, exposure for ages 0 to 99.
    """
    selection, path, tests, params, curves, tables = [], [], [], [], [], []
    for (year, sex), cell in crude.groupby(["year", "sex"]):
        cell = cell.sort_values("age").reset_index(drop=True)
        if not graduable(cell):
            continue
        result = graduate_cell(cell)
        noise = noise_dispersion(cell[cell["age"].between(*FIT_AGES)]["deaths"])
        for name, fit in result["fits"].items():
            key = {"year": year, "sex": sex, "method": name}
            selection.append(
                {
                    **key,
                    "age_lo": int(fit.ages.min()),
                    "age_hi": int(fit.ages.max()),
                    "lambda": fit.lam,
                    "edf": fit.edf,
                    "deviance": fit.deviance,
                    "crude_dispersion": noise,
                }
            )
            tests.append(
                {
                    **key,
                    "age_lo": int(fit.ages.min()),
                    "age_hi": int(fit.ages.max()),
                    **result["tests"][name],
                }
            )
            if len(fit.path):
                path.append(fit.path.assign(**key))
            lower, upper = fit.interval() if name in ("pspline", "whittaker_henderson") else (
                np.full(len(fit.ages), np.nan), np.full(len(fit.ages), np.nan))  # fmt: skip
            curves.append(
                pd.DataFrame(
                    {
                        **key,
                        "age": fit.ages.astype(int),
                        "mx": fit.mx,
                        "mx_lower": lower,
                        "mx_upper": upper,
                    }
                )
            )
        for law, values in result["params"].items():
            names = LAW_PARAMETERS[law]
            params += [
                {"year": year, "sex": sex, "law": law, "parameter": n, "value": float(v)}
                for n, v in zip(names, values, strict=True)
            ]
        tables.append(result["table"].assign(year=year, sex=sex))

    if not tables:
        return {}
    final = pd.concat(tables, ignore_index=True)
    final["sex_floor"] = False
    for year in final["year"].unique():
        m = final[(final["year"] == year) & (final["sex"] == "M")]
        f = final[(final["year"] == year) & (final["sex"] == "F")]
        if m.empty or f.empty:
            continue
        adjusted = enforce_sex_order(m.drop(columns=["year", "sex", "sex_floor"]),
                                     f.drop(columns=["year", "sex", "sex_floor"]))  # fmt: skip
        final.loc[m.index, ["mx", "mx_lower", "mx_upper", "qx", "sex_floor"]] = adjusted[
            ["mx", "mx_lower", "mx_upper", "qx", "sex_floor"]
        ].to_numpy()
    final["sex_floor"] = final["sex_floor"].astype(bool)
    all_curves = pd.concat(curves, ignore_index=True)
    return {
        "graduation_digit_preference": digit_preference(
            crude, all_curves[all_curves["method"] == "pspline"]
        ),
        "graduation_selection": pd.DataFrame(selection),
        "graduation_lambda_path": pd.concat(path, ignore_index=True),
        "graduation_fit_tests": pd.DataFrame(tests),
        "graduation_params": pd.DataFrame(params),
        "graduated_rates": all_curves,
        "graduated_qx": final[
            ["year", "sex", "age", "mx", "mx_lower", "mx_upper", "qx", "source", "sex_floor"]
        ],
    }


LAW_PARAMETERS = {
    "heligman_pollard": ("A", "B", "C", "D", "E", "F", "G", "H"),
    "gompertz_makeham": ("A", "B", "c"),
    "kannisto": ("a", "b"),
}

DESCRIPTIONS = {
    "graduation_selection": (
        "Per year, sex and method: ages fitted, selected smoothing parameter, effective degrees "
        "of freedom, deviance and the dispersion of the crude rates"
    ),
    "graduation_lambda_path": (
        "The smoothing-parameter search for the P-spline and Whittaker-Henderson fits: "
        "deviance, effective degrees of freedom and QAIC along the lambda grid"
    ),
    "graduation_fit_tests": (
        "Graduation tests per year, sex and method: chi-square, dispersion, signs, runs, serial "
        "correlation, cumulative deviation, share of residuals beyond 2, smoothness"
    ),
    "graduation_params": "Fitted parameters of Heligman-Pollard, Gompertz-Makeham and Kannisto",
    "graduation_digit_preference": (
        "Excess deaths at ages ending in 0 and 5 (ages 25 to 70) against the P-spline fit, by "
        "year and sex: digit preference in the death records that the Whipple index averages away"
    ),
    "graduated_rates": (
        "Graduated central death rates at single ages 1 to 89 for each method, with approximate "
        "95% intervals for the two smoothers"
    ),
    "graduated_qx": (
        "THE GRADUATED TABLE: q and m by year, sex and age 0 to 110. Age 0 crude, ages 1 to 89 "
        "P-spline, 84 to 89 blended, 90 onwards Kannisto; q = 1 at 110; male rates floored at "
        "female from age 84 (sex_floor). Input to the life tables"
    ),
}


def build_tables(con) -> list[tuple[str, str]]:
    """Graduate the crude single-age rates and store the results in the warehouse."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "crude_rates_single" not in names:
        return []
    crude = pd.read_sql(
        "SELECT year, sex, age, deaths, exposure FROM crude_rates_single WHERE age < 100", con
    )
    if crude.empty:
        return []
    docs = []
    for name, frame in graduate_all(crude).items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    if docs:
        con.execute("CREATE INDEX IF NOT EXISTS ix_graduated_qx ON graduated_qx (year, sex, age)")
    return docs
