"""Insured-lives mortality from the CNSF individual life statistics.

The CNSF sheets are industry statistics, not a policy-level extract, so the rules for what
counts as a death and as exposure matter a great deal. They are written down here once, as
small functions, so every figure and every sensitivity in the project uses the same definition.

**What counts as a death** (``death_cells``). A row of the claims sheet with cover
``Fallecimiento``, a known age and sex and a positive claimed amount. Rows without age and sex
are *not* deaths: they are an adjustment ledger (settlements and cancellations of claims
reported in earlier years; see ``docs/insured-lives.md``). Alternative readings are provided as
named rules so their effect on the premium can be shown rather than argued.

**What counts as exposure** (``exposure_cells``). The insured lives of the exposure sheet
(policies exposed at any time during the year). It is a head count, not person-years, so a
turnover allowance can shorten it (``central_exposure``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import special, stats

DEATH_COVER = "Fallecimiento"
CELL = ["year", "age", "sex"]

# The readings of the claims sheet, from the one used for the table to the extremes.
RULES = {
    "base": "known age and sex, positive claimed amount",
    "net": "base minus the cancelled claims (negative claimed amount)",
    "plus_positive": "base plus the no-detail rows with a positive amount, spread pro rata",
    "plus_all": "base plus every no-detail row, spread pro rata (the reading the evidence rejects)",
}


def _death_rows(claims: pd.DataFrame) -> pd.DataFrame:
    return claims[claims["coverage"] == DEATH_COVER]


def death_cells(claims: pd.DataFrame, rule: str = "base") -> pd.DataFrame:
    """Deaths per year, age and sex under one of the named ``RULES``."""
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; choose from {sorted(RULES)}")
    rows = _death_rows(claims)
    known = rows["age"].notna() & rows["sex"].notna()
    amount = rows["amount_claimed"]

    def count(mask: pd.Series) -> pd.Series:
        picked = rows[mask]
        return picked.groupby(CELL)["claims"].sum()

    base = count(known & (amount > 0))
    if rule == "net":
        base = base.sub(count(known & (amount < 0)), fill_value=0.0)
    out = base.rename("deaths").reset_index()
    if rule in ("plus_positive", "plus_all"):
        extra_mask = ~known & (amount > 0) if rule == "plus_positive" else ~known
        extra = rows[extra_mask].groupby("year")["claims"].sum()
        out = spread_pro_rata(out, extra)
    out["deaths"] = out["deaths"].clip(lower=0.0)
    out["age"] = out["age"].astype(int)
    return out.sort_values(CELL, ignore_index=True)


def spread_pro_rata(deaths: pd.DataFrame, extra: pd.Series) -> pd.DataFrame:
    """Add ``extra`` deaths per year to the cells in proportion to the deaths already there.

    The total of every year grows by exactly ``extra`` and no cell is created or emptied.
    """
    out = deaths.copy()
    totals = out.groupby("year")["deaths"].transform("sum")
    add = out["year"].map(extra).fillna(0.0)
    out["deaths"] = out["deaths"] * (1.0 + add / totals)
    return out


def exposure_cells(exposure: pd.DataFrame, *, plans: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Insured lives per year, age and sex (rows with a known age and sex only)."""
    rows = exposure[exposure["age"].notna() & exposure["sex"].notna()]
    if plans is not None:
        rows = rows[rows["plan"].isin(plans)]
    out = rows.groupby(CELL)["insured"].sum().rename("exposure").reset_index()
    out["age"] = out["age"].astype(int)
    return out.sort_values(CELL, ignore_index=True)


def central_exposure(exposure: pd.DataFrame, turnover: float = 0.0) -> pd.DataFrame:
    """Shorten the head count for lives that enter or leave during the year.

    ``turnover`` is the share of the head count that is exposed for only part of the year, on
    average half of it (entries and exits spread evenly), so central exposure is
    ``count * (1 - turnover / 2)``.
    """
    if not 0.0 <= turnover <= 1.0:
        raise ValueError("turnover is a share between 0 and 1")
    out = exposure.copy()
    out["exposure"] = out["exposure"] * (1.0 - turnover / 2.0)
    return out


def crude_cells(deaths: pd.DataFrame, exposure: pd.DataFrame) -> pd.DataFrame:
    """Deaths, exposure and the crude rate per cell; cells without exposure are dropped."""
    merged = exposure.merge(deaths, on=CELL, how="left")
    merged["deaths"] = merged["deaths"].fillna(0.0)
    merged["rate"] = merged["deaths"] / merged["exposure"]
    return merged


# ── The relational (Brass) model ────────────────────────────────────────────


def logit(p) -> np.ndarray:
    return special.logit(np.asarray(p, dtype=float))


@dataclass(frozen=True)
class BrassFit:
    """``logit q_insured = a + b * logit q_reference`` fitted to deaths out of an exposure.

    ``a`` shifts the whole curve (how much lighter the insured mortality is), ``b`` tilts it
    (``b < 1`` means the gap narrows as mortality rises with age). Two numbers describe the
    selection of an insured group against the population, which makes them stable where the
    data are thin and easy to compare between groups and countries.
    """

    a: float
    b: float
    cov: np.ndarray  # covariance of (a, b), already scaled by the dispersion
    dispersion: float
    deviance: float
    n_ages: int

    def predict(self, q_reference) -> np.ndarray:
        return special.expit(self.a + self.b * logit(q_reference))

    def interval(self, q_reference, level: float = 0.95) -> tuple[np.ndarray, np.ndarray]:
        """Interval for the fitted rate, from the covariance of (a, b) on the logit scale."""
        x = logit(q_reference)
        design = np.column_stack([np.ones_like(x), x])
        var = np.einsum("ij,jk,ik->i", design, self.cov, design)
        half = stats.norm.ppf(0.5 + level / 2) * np.sqrt(var)
        centre = self.a + self.b * x
        return special.expit(centre - half), special.expit(centre + half)


def fit_brass(deaths, exposure, q_reference) -> BrassFit:
    """Binomial maximum likelihood for (a, b); intervals widened by the Pearson dispersion."""
    d = np.asarray(deaths, dtype=float)
    e = np.asarray(exposure, dtype=float)
    x = logit(q_reference)
    keep = np.isfinite(x) & (e > 0)
    d, e, x = d[keep], e[keep], x[keep]
    model = sm.GLM(
        d / e,
        sm.add_constant(x),
        family=sm.families.Binomial(),
        var_weights=e,
    )
    result = model.fit()
    dispersion = max(1.0, float(result.pearson_chi2 / result.df_resid))
    return BrassFit(
        a=float(result.params[0]),
        b=float(result.params[1]),
        cov=np.asarray(result.cov_params()) * dispersion,
        dispersion=dispersion,
        deviance=float(result.deviance),
        n_ages=int(keep.sum()),
    )


def extend_to_reference(
    ages, q_fit, q_reference, *, last_age: int, converge_age: int = 105
) -> np.ndarray:
    """Carry a fitted curve beyond ``last_age`` by moving its ratio to the reference toward 1.

    Insured and population mortality draw together at the very old ages (the advantages of
    wealth and underwriting wear off), and the insured data above about 85 are not reliable
    (lives who died stay in the books). Above ``last_age`` the ratio of the insured to the
    reference rate rises from its value at ``last_age`` to 1 at ``converge_age`` along a
    smooth S-curve, and the result is kept non-decreasing in age.
    """
    ages = np.asarray(ages, dtype=float)
    q_fit = np.asarray(q_fit, dtype=float)
    q_ref = np.asarray(q_reference, dtype=float)
    if converge_age <= last_age:
        raise ValueError("converge_age must be above last_age")
    at = int(np.flatnonzero(ages == last_age)[0])
    ratio_end = q_fit[at] / q_ref[at]
    out = q_fit.copy()
    above = ages > last_age
    w = np.clip((ages[above] - last_age) / (converge_age - last_age), 0.0, 1.0)
    smooth = 3 * w**2 - 2 * w**3
    out[above] = (ratio_end + (1.0 - ratio_end) * smooth) * q_ref[above]
    out[ages > converge_age] = q_ref[ages > converge_age]
    # Mortality rises with age from here on, but not below: infancy and the young-adult dip
    # are real, so the monotone rule applies only from the last fitted age upward.
    old = ages >= last_age
    out[old] = np.maximum.accumulate(np.minimum(out[old], 1.0))
    return out


# ── Graduation of the pooled insured experience ─────────────────────────────

BASE_YEARS = (2023, 2024, 2025)  # post-COVID, the years the table is built from
FIT_FROM_AGE = 18  # youngest age with enough insured lives to graduate
TERMINAL_AGE = 110


def pooled_cells(crude: pd.DataFrame, years=BASE_YEARS) -> pd.DataFrame:
    """Deaths and exposure per sex and age, summed over ``years``."""
    keep = crude[crude["year"].isin(years)]
    out = keep.groupby(["sex", "age"])[["deaths", "exposure"]].sum().reset_index()
    out["age"] = out["age"].astype(int)
    return out


def last_credible_age(
    ages,
    deaths,
    exposure,
    q_reference,
    *,
    window: tuple[int, int] = (60, 80),
    keep: float = 0.85,
    bounds: tuple[int, int] = (75, 90),
) -> int:
    """The last age at which the insured data can be trusted.

    Over ``window`` the ratio of the insured rate to the reference is steady. Beyond some age it
    collapses, because lives who died stay in the books and their deaths are never reported.
    The rule: the first age whose ratio (smoothed over three ages) falls below ``keep`` times
    its median over the window ends the credible range at the age before.
    """
    ages = np.asarray(ages, dtype=int)
    ratio = pd.Series(
        (np.asarray(deaths, float) / np.asarray(exposure, float)) / np.asarray(q_reference, float),
        index=ages,
    )
    smooth = ratio.rolling(3, center=True).mean()
    reference = float(ratio.loc[window[0] : window[1]].median())
    candidates = smooth.loc[bounds[0] : bounds[1]]
    below = candidates[candidates < keep * reference]
    return int(below.index[0] - 1) if len(below) else int(bounds[1])


def relational_fit(ages, deaths, exposure, q_reference, lam: float | None = None):
    """P-spline on the *ratio* to a reference table.

    Expected deaths under the reference (``exposure * q_reference``) are passed to the Poisson
    P-spline as if they were the exposure, so the fitted "rate" is the insured/reference ratio:
    smooth in age, and the population's shape (the young-adult hump, the old-age rise) is
    inherited instead of re-estimated from thin data.
    """
    from mortality import graduation

    expected = np.asarray(exposure, float) * np.asarray(q_reference, float)
    return graduation.pspline(ages, deaths, expected, lam=lam)


def direct_fit(ages, deaths, exposure, lam: float | None = None):
    """P-spline of the insured rate itself, with no reference."""
    from mortality import graduation

    return graduation.pspline(ages, deaths, exposure, lam=lam)


def makeham_fit(ages, deaths, exposure):
    """Gompertz-Makeham law by Poisson maximum likelihood (three parameters)."""
    from mortality import graduation

    fit, params = graduation.parametric(
        "gompertz_makeham",
        graduation.gompertz_makeham,
        ages,
        deaths,
        exposure,
        graduation.GM_START,
        graduation.GM_BOUNDS,
        n_params=3,
    )
    return fit, params


def deviance(deaths, expected) -> float:
    from mortality import graduation

    return graduation.poisson_deviance(deaths, expected)


def shape_error(deaths, expected) -> float:
    """Poisson deviance after removing any difference in level between data and prediction.

    A held-out year can be lower or higher overall than the years the model was fitted on
    (mortality improves, the book changes). Rescaling the prediction to the year's total makes
    the comparison about the *shape* by age, which is what the choice of method decides.
    """
    d = np.asarray(deaths, float)
    mu = np.asarray(expected, float)
    return deviance(d, mu * d.sum() / mu.sum())


METHODS = ("relational", "direct", "makeham", "brass")


@dataclass
class SexFits:
    """Everything fitted for one sex on the credible ages, pooled over the base years."""

    sex: str
    ages: np.ndarray
    last_age: int
    deaths: np.ndarray
    exposure: np.ndarray
    q_reference: np.ndarray
    rate: dict[str, np.ndarray]  # method -> fitted insured rate on ``ages``
    graduation: dict  # method -> fitted object (Graduation or BrassFit)
    comparison: pd.DataFrame  # one row per method


def _fit_all(ages, deaths, exposure, q_ref) -> tuple[dict, dict]:
    """Fit the four candidate methods; returns (rates by method, fitted objects by method)."""
    rel = relational_fit(ages, deaths, exposure, q_ref)
    direct = direct_fit(ages, deaths, exposure)
    gm, _ = makeham_fit(ages, deaths, exposure)
    brass = fit_brass(deaths, exposure, q_ref)
    rate = {
        "relational": rel.mx * q_ref,
        "direct": direct.mx,
        "makeham": gm.mx,
        "brass": brass.predict(q_ref),
    }
    return rate, {"relational": rel, "direct": direct, "makeham": gm, "brass": brass}


def graduate_sex(
    crude: pd.DataFrame, q_population: pd.Series, sex: str, *, years=BASE_YEARS, last_age=None
) -> SexFits:
    """Fit and compare the four methods for one sex, with leave-one-year-out shape errors."""
    from mortality import graduation

    pool = pooled_cells(crude, years)
    pool = pool[(pool["sex"] == sex) & (pool["age"] >= FIT_FROM_AGE)].sort_values("age")
    q_all = q_population.reindex(pool["age"]).to_numpy()
    if last_age is None:
        last_age = last_credible_age(pool["age"], pool["deaths"], pool["exposure"], q_all)
    pool = pool[pool["age"] <= last_age]
    ages = pool["age"].to_numpy()
    d, e = pool["deaths"].to_numpy(), pool["exposure"].to_numpy()
    q_ref = q_population.reindex(ages).to_numpy()
    rate, objects = _fit_all(ages, d, e, q_ref)

    # leave one year out: fit on the other years, score the shape on the held-out year
    folds = {m: 0.0 for m in METHODS}
    for held in years:
        train = pooled_cells(crude, tuple(y for y in years if y != held))
        train = train[(train["sex"] == sex) & train["age"].between(FIT_FROM_AGE, last_age)]
        train = train.sort_values("age")
        test = crude[(crude["year"] == held) & (crude["sex"] == sex)]
        test = test[test["age"].between(FIT_FROM_AGE, last_age)].sort_values("age")
        test = test.set_index("age").reindex(train["age"].to_numpy())
        t_rate, _ = _fit_all(
            train["age"].to_numpy(),
            train["deaths"].to_numpy(),
            train["exposure"].to_numpy(),
            q_population.reindex(train["age"]).to_numpy(),
        )
        for m in METHODS:
            folds[m] += shape_error(
                test["deaths"].fillna(0).to_numpy(), test["exposure"].to_numpy() * t_rate[m]
            )

    # One dispersion for every method, estimated from the crude counts themselves (their own
    # high-order differences). Taking it from each fit would let a badly fitting method shrink
    # its own penalty: the worse the fit, the larger its dispersion, the smaller deviance/phi.
    disp = graduation.noise_dispersion(d)
    rows = []
    for m in METHODS:
        obj = objects[m]
        edf = float(obj.edf) if hasattr(obj, "edf") else 2.0
        dev = deviance(d, e * rate[m])
        tests = graduation.fit_tests(d, e, rate[m], edf)
        rows.append(
            {
                "sex": sex,
                "method": m,
                "edf": edf,
                "deviance": dev,
                "dispersion": disp,
                "qaic": dev / max(disp, 1.0) + 2 * edf,
                "chi2_dispersion": tests["dispersion"],
                "share_beyond_2": tests["share_beyond_2"],
                "cv_shape_deviance": folds[m],
                "n_ages": len(ages),
            }
        )
    return SexFits(sex, ages, int(last_age), d, e, q_ref, rate, objects, pd.DataFrame(rows))


def full_table(
    fits: SexFits,
    method: str,
    q_population: pd.Series,
    *,
    converge_age: int = 105,
) -> pd.Series:
    """The insured qx for ages 0 to 110 from a fitted method.

    Below the youngest fitted age the population rate is scaled by the insured/population
    ratio at that age (those ages are not priced; the table stays complete). Above the last
    credible age the ratio moves to 1 at ``converge_age``. The last age has q = 1.
    """
    ages = np.arange(0, TERMINAL_AGE + 1)
    q_pop = q_population.reindex(ages).to_numpy()
    q = q_pop.copy()
    fitted = fits.rate[method]
    first = int(fits.ages[0])
    q[first : fits.last_age + 1] = fitted
    q[:first] = q_pop[:first] * (fitted[0] / q_pop[first])
    q = extend_to_reference(ages, q, q_pop, last_age=fits.last_age, converge_age=converge_age)
    q[-1] = 1.0
    return pd.Series(q, index=ages, name=f"{fits.sex}_{method}")


# ── Warehouse tables ────────────────────────────────────────────────────────

TREND_AGES = (25, 79)  # ages over which the year-on-year change is measured
CREDIBLE_DEATHS = 30  # same floor as the population rates: below it a rate is noise

DESCRIPTIONS = {
    "insured_ledger": (
        "Death-claim rows of the CNSF claims sheet split into those with and without age and sex "
        "and by sign of the claimed amount: the evidence that rows without detail are an "
        "adjustment ledger and not deaths"
    ),
    "insured_rules": (
        "Deaths per year under each reading of the claims sheet (base, net of cancellations, "
        "plus no-detail rows spread pro rata), and the change from the base reading"
    ),
    "insured_crude": (
        "Insured lives and death claims by year, sex and single age with exact intervals, and the "
        "ratio to the population (2023) and to CNSF 2013 (base rule for deaths)"
    ),
    "insured_pooled": (
        "Insured deaths and exposure of the base years pooled, by sex and single age, with "
        "intervals and ratios to the population and to CNSF 2013"
    ),
    "insured_methods": (
        "Comparison of the four graduation methods for the insured experience: deviance, "
        "dispersion, quasi-AIC and the out-of-sample shape error by sex; the chosen one is flagged"
    ),
    "insured_graduated": (
        "Graduated insured rates on the credible ages by sex and method, with 95% intervals for "
        "the smoothers; the chosen method is flagged"
    ),
    "insured_fit_tests": (
        "Goodness-of-fit tests of the chosen graduation of the insured experience by sex"
    ),
    "insured_table": (
        "The insured-lives mortality table (qx, ages 0 to 110, by sex) with 95% bands on the "
        "graduated ages, the segment each age comes from, and the ratios to the population and "
        "CNSF 2013"
    ),
    "insured_trend": (
        "Age-standardised insured death rates by year and sex, and the fitted annual change "
        "over the base years with its 95% interval"
    ),
}


def _has(con, *names: str) -> bool:
    found = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return all(n in found for n in names)


def select_method(comparison: pd.DataFrame, tolerance: float = 1.05) -> str:
    """Lowest quasi-AIC among the methods whose out-of-sample shape error is near the best."""
    ok = comparison[
        comparison["cv_shape_deviance"] <= tolerance * comparison["cv_shape_deviance"].min()
    ]
    return str(ok.loc[ok["qaic"].idxmin(), "method"])


def ledger_table(claims: pd.DataFrame) -> pd.DataFrame:
    """Death-claim rows by block (known detail or not) and sign of the claimed amount."""
    rows = _death_rows(claims).copy()
    rows["block"] = np.where(rows["age"].notna() & rows["sex"].notna(), "known", "no_detail")
    rows["sign"] = np.select(
        [rows["amount_claimed"] > 0, rows["amount_claimed"] < 0], ["positive", "negative"], "zero"
    )
    out = (
        rows.groupby(["year", "block", "sign"])
        .agg(
            rows=("claims", "size"),
            claims=("claims", "sum"),
            amount_claimed=("amount_claimed", "sum"),
            amount_paid=("amount_paid", "sum"),
        )
        .reset_index()
    )
    return out


def rules_table(claims: pd.DataFrame) -> pd.DataFrame:
    """Deaths per year under each named rule, and the change from the base rule."""
    frames = []
    for rule, text in RULES.items():
        d = death_cells(claims, rule).groupby("year")["deaths"].sum().rename("deaths").reset_index()
        d.insert(1, "rule", rule)
        d.insert(2, "reading", text)
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    base = out[out["rule"] == "base"].set_index("year")["deaths"]
    out["change_vs_base"] = out["deaths"] / out["year"].map(base) - 1.0
    return out


def _with_intervals(cells: pd.DataFrame) -> pd.DataFrame:
    from mortality import rates

    out = cells.copy()
    out["rate"] = out["deaths"] / out["exposure"]
    out["rate_lower"], out["rate_upper"] = rates.rate_interval(out["deaths"], out["exposure"])
    out["credible"] = out["deaths"] >= CREDIBLE_DEATHS
    return out


def _add_references(cells: pd.DataFrame, pop: pd.DataFrame, cnsf: pd.Series) -> pd.DataFrame:
    out = cells.merge(pop, on=["sex", "age"], how="left").rename(columns={"qx": "q_population"})
    out["q_cnsf2013"] = out["age"].map(cnsf)
    out["ratio_population"] = out["rate"] / out["q_population"]
    out["ratio_cnsf2013"] = out["rate"] / out["q_cnsf2013"]
    return out


def standardised_trend(crude: pd.DataFrame, weights_year: int = 2024) -> pd.DataFrame:
    """Insured death rate per year with fixed age weights, so a changing age mix cannot move it."""
    lo, hi = TREND_AGES
    c = crude[crude["age"].between(lo, hi)]
    w = c[c["year"] == weights_year].set_index(["sex", "age"])["exposure"]
    rows = []
    for year, g in c.groupby("year"):
        rate = (g["deaths"] / g["exposure"]).set_axis(pd.MultiIndex.from_frame(g[["sex", "age"]]))
        for sex in ("M", "F"):
            wt = w.loc[sex]
            r = rate.loc[sex].reindex(wt.index)
            rows.append({"year": int(year), "sex": sex, "rate": float((r * wt).sum() / wt.sum())})
    out = pd.DataFrame(rows)
    ref = out[out["year"] == BASE_YEARS[0]].set_index("sex")["rate"]
    out["index_vs_first_base_year"] = out["rate"] / out["sex"].map(ref)
    return out


def annual_change(crude: pd.DataFrame, q_table: pd.DataFrame, years=BASE_YEARS) -> pd.DataFrame:
    """Log-linear change per year of insured mortality over ``years``, by sex.

    A Poisson model with offset ``log(exposure * table q)`` and a linear year term, ages 25 to
    79, standard errors widened by the Pearson dispersion. With three post-pandemic years the
    interval is wide, and the book also changes (new business is freshly underwritten), so this
    is reported as evidence about the direction and size of the trend, not used as the
    improvement assumption.
    """
    lo, hi = TREND_AGES
    rows = []
    for sex in ("M", "F"):
        c = crude[(crude["sex"] == sex) & crude["age"].between(lo, hi) & crude["year"].isin(years)]
        c = c.merge(q_table[q_table["sex"] == sex][["age", "qx"]], on="age")
        c = c[c["deaths"].notna() & (c["qx"] > 0)]
        x = sm.add_constant((c["year"] - np.mean(years)).to_numpy(float))
        offset = np.log(c["exposure"].to_numpy(float) * c["qx"].to_numpy(float))
        res = sm.GLM(
            c["deaths"].to_numpy(float), x, family=sm.families.Poisson(), offset=offset
        ).fit(scale="X2")
        slope, se = float(res.params[1]), float(res.bse[1])
        z = stats.norm.ppf(0.975)
        rows.append(
            {
                "sex": sex,
                "first_year": min(years),
                "last_year": max(years),
                "annual_change": float(np.expm1(slope)),
                "lower": float(np.expm1(slope - z * se)),
                "upper": float(np.expm1(slope + z * se)),
                "dispersion": float(res.scale),
            }
        )
    return pd.DataFrame(rows)


def build_tables(con) -> list[tuple[str, str]]:
    """Create the insured-lives tables from the CNSF statistics; returns (name, description)."""
    docs: list[tuple[str, str]] = []
    if not _has(con, "cnsf_vi_claims", "cnsf_vi_exposure", "graduated_qx", "cnsf_rates"):
        return docs
    from mortality import graduation

    claims = pd.read_sql(
        "SELECT year, age, sex, coverage, claims, amount_claimed, amount_paid FROM cnsf_vi_claims "
        f"WHERE coverage = '{DEATH_COVER}'",
        con,
    )
    exposure = pd.read_sql(
        "SELECT year, age, sex, plan, SUM(insured) AS insured FROM cnsf_vi_exposure "
        "GROUP BY year, age, sex, plan",
        con,
    )
    pop = pd.read_sql("SELECT sex, age, qx FROM graduated_qx WHERE year = 2023", con)
    cnsf = pd.read_sql(
        "SELECT age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' AND variant = 'base'", con
    ).set_index("age")["qx"]

    def save(name: str, frame: pd.DataFrame) -> None:
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))

    save("insured_ledger", ledger_table(claims))
    save("insured_rules", rules_table(claims))

    crude = crude_cells(death_cells(claims), exposure_cells(exposure))
    crude = crude[crude["age"] <= TERMINAL_AGE]
    save("insured_crude", _add_references(_with_intervals(crude), pop, cnsf))
    pooled = pooled_cells(crude)
    save("insured_pooled", _add_references(_with_intervals(pooled), pop, cnsf))

    methods, graduated, tests, table = [], [], [], []
    for sex in ("M", "F"):
        q_pop = pop[pop["sex"] == sex].set_index("age")["qx"]
        fits = graduate_sex(crude, q_pop, sex)
        chosen = select_method(fits.comparison)
        methods.append(
            fits.comparison.assign(
                selected=lambda f, c=chosen: f["method"] == c, last_age=fits.last_age
            )
        )
        for method in METHODS:
            obj = fits.graduation[method]
            rate = fits.rate[method]
            lower = upper = np.full(len(rate), np.nan)
            if method in ("direct", "relational"):
                lo_m, hi_m = obj.interval()
                scale = fits.q_reference if method == "relational" else 1.0
                lower, upper = lo_m * scale, hi_m * scale
            graduated.append(
                pd.DataFrame(
                    {
                        "sex": sex,
                        "age": fits.ages,
                        "method": method,
                        "rate": rate,
                        "lower": lower,
                        "upper": upper,
                        "selected": method == chosen,
                    }
                )
            )
        sel = fits.graduation[chosen]
        edf = float(getattr(sel, "edf", 2.0))
        tests.append(
            pd.DataFrame(
                [
                    {
                        "sex": sex,
                        "method": chosen,
                        **graduation.fit_tests(fits.deaths, fits.exposure, fits.rate[chosen], edf),
                    }
                ]
            )
        )
        q = full_table(fits, chosen, q_pop)
        first = int(fits.ages[0])
        lower = pd.Series(np.nan, index=q.index)
        upper = pd.Series(np.nan, index=q.index)
        if chosen in ("direct", "relational"):
            lo_m, hi_m = sel.interval()
            scale = fits.q_reference if chosen == "relational" else 1.0
            lower.loc[fits.ages] = lo_m * scale
            upper.loc[fits.ages] = hi_m * scale
        source = np.where(
            q.index < first,
            "below_fit",
            np.where(q.index <= fits.last_age, "graduated", "extended"),
        )
        table.append(
            pd.DataFrame(
                {
                    "sex": sex,
                    "age": q.index,
                    "qx": q.to_numpy(),
                    "qx_lower": lower.to_numpy(),
                    "qx_upper": upper.to_numpy(),
                    "source": source,
                    "method": chosen,
                }
            )
        )
    save("insured_methods", pd.concat(methods, ignore_index=True))
    save("insured_graduated", pd.concat(graduated, ignore_index=True))
    save("insured_fit_tests", pd.concat(tests, ignore_index=True))
    table_df = _add_table_references(pd.concat(table, ignore_index=True), pop, cnsf)
    save("insured_table", table_df)

    trend = standardised_trend(crude)
    change = annual_change(crude, table_df[["sex", "age", "qx"]])
    save(
        "insured_trend",
        pd.concat(
            [trend.assign(kind="standardised_rate"), change.assign(kind="annual_change")],
            ignore_index=True,
        ),
    )
    return docs


def _add_table_references(table: pd.DataFrame, pop: pd.DataFrame, cnsf: pd.Series) -> pd.DataFrame:
    out = table.merge(pop.rename(columns={"qx": "q_population"}), on=["sex", "age"], how="left")
    out["q_cnsf2013"] = out["age"].map(cnsf)
    out["ratio_population"] = out["qx"] / out["q_population"]
    out["ratio_cnsf2013"] = out["qx"] / out["q_cnsf2013"]
    return out
