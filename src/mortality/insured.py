"""Insured-lives mortality from the CNSF individual life statistics.

The CNSF sheets are industry statistics, not a policy-level extract, so the rules for what
counts as a death and as exposure matter a great deal. They are written down here once, as
small functions, so every figure and every sensitivity in the project uses the same definition.

**What counts as a death** (``death_cells``). A row of the claims sheet with cover
``Fallecimiento``, a known age and sex, a positive claimed amount and a cause that can cause a
death. Two kinds of rows are *not* deaths: rows without age and sex are an adjustment ledger
(settlements and cancellations of claims reported in earlier years), and rows whose cause is a
sprained ankle are endowment maturities booked under the death cover with a placeholder cause.
See ``docs/insured-lives.md``. Alternative readings are provided as named rules so their effect
on the premium can be shown rather than argued.

**What counts as exposure** (``exposure_cells``). The insured lives holding the death cover
(the issue sheet reports lives by cover, so numerator and denominator refer to the same
benefit). It is a head count, not person-years, so a turnover allowance can shorten it
(``central_exposure``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import special, stats

DEATH_COVER = "Fallecimiento"
CELL = ["year", "age", "sex"]

# Mortality differs a great deal between the products of one market (a term cover for a
# borrower, a traditional term policy, a whole-life universal policy), so a table is built for
# each segment as well as for the market as a whole. A segment is a filter on the plan and the
# modality of the policy as the CNSF reports them.
SEGMENTS: dict[str, dict] = {
    "all": {"label": "All individual life", "plan": None, "modality": None},
    "term": {"label": "Term (all modalities)", "plan": ("Temporal",), "modality": None},
    "term_traditional": {
        "label": "Term, traditional",
        "plan": ("Temporal",),
        "modality": ("Tradicional",),
    },
    "credit": {"label": "Term, credit life", "plan": ("Temporal",), "modality": ("Deudores",)},
    "term_other": {
        "label": "Term, other modalities",
        "plan": ("Temporal",),
        "modality_not": ("Tradicional", "Deudores"),
    },
    "permanent": {
        "label": "Whole life and endowment",
        "plan": ("Vitalicio", "Dotal Mixto"),
        "modality": None,
    },
}

# The products are graduated on their own; the two market-wide tables are exposure-weighted
# blends of them, so the market table is always consistent with its parts and carries the mix
# of business of the base years.
GRADUATED = ("term_traditional", "credit", "permanent")
# A segment too thin to graduate on its own is a multiple of a reference segment's table.
RELATIVE = {"term_other": "term_traditional"}
PARTS = (*GRADUATED, *RELATIVE)  # the partition of the business that the blends add up
BLENDS = {
    "term": ("term_traditional", "credit", "term_other"),
    "all": PARTS,
}
RELATIVITY_AGES = (25, 65)  # ages over which a segment's multiplier is estimated
RELATIVITY_REFERENCE = "term_traditional"  # the standard product, the base of the relativities


def segment_rows(frame: pd.DataFrame, segment: str = "all") -> pd.DataFrame:
    """The rows of a claims or exposure frame that belong to a segment."""
    if segment not in SEGMENTS:
        raise ValueError(f"unknown segment {segment!r}; choose from {sorted(SEGMENTS)}")
    spec = SEGMENTS[segment]
    keep = pd.Series(True, index=frame.index)
    if spec.get("plan") is not None:
        keep &= frame["plan"].isin(spec["plan"])
    if spec.get("modality") is not None:
        keep &= frame["modality"].isin(spec["modality"])
    if spec.get("modality_not") is not None:
        keep &= ~frame["modality"].isin(spec["modality_not"])
    return frame[keep]


# The readings of the claims sheet, from the one used for the table to the extremes.
RULES = {
    "base": "known age and sex, positive claimed amount, a cause that can cause a death",
    "net": "base minus the cancelled claims (negative claimed amount)",
    "plus_positive": "base plus the no-detail rows with a positive amount, spread pro rata",
    "plus_all": "base plus every no-detail row, spread pro rata (the reading the evidence rejects)",
    "with_maturities": "base without removing the maturity payments coded as sprains",
}


def _death_rows(claims: pd.DataFrame) -> pd.DataFrame:
    return claims[claims["coverage"] == DEATH_COVER]


def _without_maturities(rows: pd.DataFrame) -> pd.DataFrame:
    """Drop the claims whose cause text is a sprain.

    Those entries are endowment maturities booked under the death cover with a placeholder
    cause: they sit at ages 60 to 69 (spread of 4 years against 14 for all claims), average
    3.6 times a death claim, start in 2022 and lie on savings-type plans. They are not deaths.
    """
    if "cause" not in rows.columns:
        # silently skipping this would leave maturity payments in the deaths
        raise ValueError("the claims need their cause column to remove the maturity payments")
    from mortality import insured_causes

    return rows[insured_causes.group_causes(rows["cause"]) != insured_causes.IMPLAUSIBLE]


def death_cells(claims: pd.DataFrame, rule: str = "base", segment: str = "all") -> pd.DataFrame:
    """Deaths per year, age and sex under one of the named ``RULES``, for one segment.

    The no-detail rows have no plan or modality either, so they cannot be assigned to a segment:
    the alternative readings that add them spread the market's extra deaths over every
    segment in proportion to its known deaths (the same factor for all).
    """
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; choose from {sorted(RULES)}")
    market = _death_rows(claims)
    if rule != "with_maturities":
        market = _without_maturities(market)
    rows = segment_rows(market, segment)

    def known_rows(frame: pd.DataFrame) -> pd.DataFrame:
        known = frame["age"].notna() & frame["sex"].notna()
        return frame[known & (frame["amount_claimed"] > 0)]

    base = known_rows(rows).groupby(CELL)["claims"].sum()
    if rule == "net":
        known = rows["age"].notna() & rows["sex"].notna()
        cancelled = rows[known & (rows["amount_claimed"] < 0)].groupby(CELL)["claims"].sum()
        base = base.sub(cancelled, fill_value=0.0)
    out = base.rename("deaths").reset_index()
    if rule in ("plus_positive", "plus_all"):
        no_detail = market["age"].isna() | market["sex"].isna()
        extra_rows = (
            market[no_detail & (market["amount_claimed"] > 0)]
            if rule == "plus_positive"
            else market[no_detail]
        )
        extra = extra_rows.groupby("year")["claims"].sum()
        market_known = known_rows(market).groupby("year")["claims"].sum()
        segment_known = known_rows(rows).groupby("year")["claims"].sum()
        out = spread_pro_rata(out, extra * segment_known / market_known)
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


def exposure_cells(exposure: pd.DataFrame, segment: str = "all") -> pd.DataFrame:
    """Insured lives per year, age and sex (rows with a known age and sex only).

    The lives should be those holding the death cover, so that numerator and denominator refer
    to the same benefit (the issue sheet reports lives by cover; the exposure sheet counts
    every life with any cover, 11% to 15% more for term business).
    """
    rows = segment_rows(exposure, segment)
    rows = rows[rows["age"].notna() & rows["sex"].notna()]
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
    window: tuple[int, int] = (40, 60),
    keep: float = 0.85,
    bounds: tuple[int, int] = (55, 90),
) -> int:
    """The last age at which the insured data can be trusted.

    Over ``window`` (ages where the insured are a settled, underwritten group) the ratio of the
    insured rate to the reference is steady. At older ages it can collapse: a term policy ends
    and the lives that remain are few and unrepresentative, and lives who died stay in the
    books with their deaths never reported. The rule: the first age from ``bounds[0]`` whose
    ratio (smoothed over three ages) falls below ``keep`` times its median over the window
    ends the credible range at the age before. A ratio that rises (a product mix that moves
    towards whole life) is not a collapse.
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


def common_last_age(crude: pd.DataFrame, pop: pd.DataFrame, years=BASE_YEARS) -> int:
    """One last credible age for both sexes: the shorter of the two ranges.

    The boundary is noisy, and letting each sex have its own makes one sex's extension start
    before the other's, which can push women's rates up to men's. A product has one credible
    range, so both sexes are extended by the same rule from the same age.
    """
    pooled = pooled_cells(crude, years)
    last = []
    for sex in ("M", "F"):
        q_pop = pop[pop["sex"] == sex].set_index("age")["qx"]
        part = pooled[(pooled["sex"] == sex) & (pooled["age"] >= FIT_FROM_AGE)].sort_values("age")
        q_all = q_pop.reindex(part["age"]).to_numpy()
        last.append(last_credible_age(part["age"], part["deaths"], part["exposure"], q_all))
    return min(last)


MIN_LIVES = 500  # an age with fewer insured lives in any year is too thin to graduate
MIN_AGES = 30  # fewest ages a graduation is allowed to rest on


def first_fit_age(
    crude: pd.DataFrame, last_age: int, years=BASE_YEARS, *, floor: int = FIT_FROM_AGE
) -> int:
    """The youngest age from which every age up to ``last_age`` has deaths in every year.

    The smoothers work on the log of the counts, so an age without a single death in some year
    cannot be graduated. In a thin segment that moves the start of the fit up (below it the
    table follows the population shape scaled to the first fitted age).
    """
    cells = crude[crude["year"].isin(years)]
    per_age = cells.groupby("age").agg(
        deaths=("deaths", "min"), lives=("exposure", "min"), years=("year", "nunique")
    )
    ok = (
        (per_age["deaths"] >= 1)
        & (per_age["lives"] >= MIN_LIVES)
        & (per_age["years"] == len(years))
    )
    first = last_age + 1
    for age in range(last_age, floor - 1, -1):
        if age in ok.index and ok.loc[age]:
            first = age
        else:
            break
    if last_age - first + 1 < MIN_AGES:
        raise ValueError(f"too few usable ages ({first} to {last_age}) to graduate")
    return first


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
    first_age = first_fit_age(crude[crude["sex"] == sex], last_age, years)
    pool = pool[pool["age"].between(first_age, last_age)]
    ages = pool["age"].to_numpy()
    d, e = pool["deaths"].to_numpy(), pool["exposure"].to_numpy()
    q_ref = q_population.reindex(ages).to_numpy()
    rate, objects = _fit_all(ages, d, e, q_ref)

    # leave one year out: fit on the other years, score the shape on the held-out year
    folds = {m: 0.0 for m in METHODS}
    for held in years:
        train = pooled_cells(crude, tuple(y for y in years if y != held))
        train = train[(train["sex"] == sex) & train["age"].between(first_age, last_age)]
        train = train.sort_values("age")
        test = crude[(crude["year"] == held) & (crude["sex"] == sex)]
        test = test[test["age"].between(first_age, last_age)].sort_values("age")
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
    "insured_relativities": (
        "Multiplier of the traditional-term table that matches each segment's deaths, by sex and "
        "age range, with a 95% interval widened by the dispersion"
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
            seen = r.notna()  # a thin segment can lack an age in some year: weight what exists
            rows.append(
                {
                    "year": int(year),
                    "sex": sex,
                    "rate": float((r[seen] * wt[seen]).sum() / wt[seen].sum()),
                }
            )
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


def relativity(pooled: pd.DataFrame, q_reference: pd.Series, ages=RELATIVITY_AGES) -> dict:
    """Multiplier of a reference table that matches a segment's deaths (one sex).

    The Poisson maximum-likelihood estimate of a single factor ``k`` with expected deaths
    ``exposure * q_reference`` is total deaths over total expected deaths. Its interval is
    widened by the dispersion of the age-decade ratios, because the segment's age pattern is
    never exactly the reference's.
    """
    lo, hi = ages
    p = pooled[pooled["age"].between(lo, hi)].copy()
    p["expected"] = p["exposure"] * p["age"].map(q_reference)
    p = p.dropna(subset=["expected"])
    deaths, expected = float(p["deaths"].sum()), float(p["expected"].sum())
    k = deaths / expected
    decade = (p["age"] // 10) * 10
    g = p.groupby(decade)[["deaths", "expected"]].sum()
    g = g[g["expected"] > 0]
    pearson = float((((g["deaths"] - k * g["expected"]) ** 2) / (k * g["expected"])).sum())
    dispersion = max(1.0, pearson / max(len(g) - 1, 1))
    se = np.sqrt(dispersion / max(deaths, 1.0))
    z = stats.norm.ppf(0.975)
    return {
        "k": k,
        "lower": k * np.exp(-z * se),
        "upper": k * np.exp(z * se),
        "deaths": deaths,
        "expected": expected,
        "dispersion": dispersion,
        "ages": f"{lo}-{hi}",
    }


def fit_relative_curve(pooled: pd.DataFrame, q_reference: pd.Series, ages=RELATIVITY_AGES) -> dict:
    """Multiplier of a reference table that changes with age: ``log k(x) = a + b (x - 45) / 20``.

    A Poisson regression with offset ``log(exposure * q_reference)`` over ``ages``, standard
    errors scaled by the Pearson dispersion. Two parameters are all a thin segment can carry,
    and they capture what a single factor cannot (whole life against term pulls away from
    it as ages rise).
    """
    lo, hi = ages
    p = pooled[pooled["age"].between(lo, hi)].copy()
    p["expected"] = p["exposure"] * p["age"].map(q_reference)
    p = p.dropna(subset=["expected"])
    p = p[p["expected"] > 0]
    x = (p["age"].to_numpy(float) - 45.0) / 20.0
    res = sm.GLM(
        p["deaths"].to_numpy(float),
        sm.add_constant(x),
        family=sm.families.Poisson(),
        offset=np.log(p["expected"].to_numpy(float)),
    ).fit(scale="X2")
    return {
        "a": float(res.params[0]),
        "b": float(res.params[1]),
        "cov": np.asarray(res.cov_params()),
        "dispersion": float(res.scale),
        "ages": (lo, hi),
    }


def relative_table(
    curve: dict,
    reference: pd.DataFrame,
    q_population: pd.Series,
    reference_last_age: int,
    *,
    converge_age: int = 105,
) -> pd.DataFrame:
    """A segment's table as an age-varying multiple of a reference segment's table (one sex).

    Up to the reference's last credible age the rate is ``k(x) * q_reference(x)`` (the
    multiplier is held at its end values outside the ages it was fitted on). Above it the
    segment follows the same rule as every other table: its ratio to the population moves to 1
    at ``converge_age``. So a multiplier above 1 can never lift the old-age rates above the
    population's.
    """
    ages = reference["age"].to_numpy()
    lo, hi = curve["ages"]
    x = (np.clip(ages, lo, hi).astype(float) - 45.0) / 20.0
    design = np.column_stack([np.ones_like(x), x])
    centre = design @ np.array([curve["a"], curve["b"]])
    se = np.sqrt(np.einsum("ij,jk,ik->i", design, curve["cov"], design))
    z = stats.norm.ppf(0.975)
    q_ref = reference["qx"].to_numpy()
    q = np.minimum(q_ref * np.exp(centre), 1.0)
    out = reference.copy()
    out["qx_lower"] = np.minimum(reference["qx_lower"].to_numpy() * np.exp(centre - z * se), 1.0)
    out["qx_upper"] = np.minimum(reference["qx_upper"].to_numpy() * np.exp(centre + z * se), 1.0)
    out["qx"] = extend_to_reference(
        ages,
        q,
        q_population.reindex(ages).to_numpy(),
        last_age=reference_last_age,
        converge_age=converge_age,
    )
    out["method"] = "relativity"
    return out


def floor_men_at_women(table: pd.DataFrame, from_age: int = FIT_FROM_AGE) -> pd.DataFrame:
    """Raise men's rates to women's wherever the table leaves men below them.

    No population and no insured group shows women dying faster than men at working and old
    ages. It happens here only because the sexes are extended from different ages (women's
    credible range ends earlier) or through noise in thin cells, and the cure is the rule the
    population table already follows: men are floored at women. The changed ages are flagged in
    ``sex_floor`` and lose their interval.
    """
    out = table.copy()
    out["sex_floor"] = False
    men = out.index[out["sex"] == "M"]
    ages = out.loc[men, "age"].to_numpy()
    women = out[out["sex"] == "F"].set_index("age")["qx"].reindex(ages).to_numpy()
    low = (ages >= from_age) & (out.loc[men, "qx"].to_numpy() < women)
    out.loc[men[low], "qx"] = women[low]
    out.loc[men[low], ["qx_lower", "qx_upper"]] = np.nan
    out.loc[men[low], "sex_floor"] = True
    return out


def blend_tables(tables: dict[str, pd.DataFrame], pooled: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Exposure-weighted blend of segment tables (``insured_table`` frames without references).

    The weight of a segment at a sex and age is its share of the pooled insured lives there, so
    the blend is the table of the market as it was in the base years. Where no segment has
    lives (very young and very old ages) the weights of the nearest age with lives are used.
    Bands are blended only where every component has one.
    """
    weights = []
    for name, frame in pooled.items():
        weights.append(frame[["sex", "age", "exposure"]].assign(segment=name))
    w = pd.concat(weights).pivot_table(
        index=["sex", "age"], columns="segment", values="exposure", aggfunc="sum"
    )
    names = list(tables)
    w = w.reindex(columns=names).fillna(0.0)
    parts = []
    for name, frame in tables.items():
        parts.append(
            frame.set_index(["sex", "age"])[["qx", "qx_lower", "qx_upper", "source"]].add_prefix(
                f"{name}|"
            )
        )
    wide = pd.concat(parts, axis=1)
    index = wide.index
    share = w.reindex(index)
    share = share.groupby(level="sex", group_keys=False).apply(lambda g: g.ffill().bfill())
    share = share.div(share.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(1.0 / len(names))
    out = pd.DataFrame(index=index)
    for column in ("qx", "qx_lower", "qx_upper"):
        stacked = np.column_stack([wide[f"{n}|{column}"].to_numpy() for n in names])
        # NaN in any component gives NaN: a band exists only where every component has one
        out[column] = np.sum(stacked * share[names].to_numpy(), axis=1)
    # an age is "graduated" only if every product's rate there comes from data
    sources = np.column_stack([wide[f"{n}|source"].to_numpy() for n in names])
    out["source"] = np.where(
        (sources == "extended").any(axis=1),
        "extended",
        np.where((sources == "below_fit").any(axis=1), "below_fit", "graduated"),
    )
    out["method"] = "blend"
    return out.reset_index()


def segment_q(
    segment: str,
    claims: pd.DataFrame,
    exposure: pd.DataFrame,
    pop: pd.DataFrame,
    *,
    rule: str = "base",
    years=BASE_YEARS,
    method: str | None = None,
    converge_age: int = 105,
    turnover: float = 0.0,
) -> dict[str, pd.Series]:
    """The q table (ages 0 to 110) of a segment for each sex under alternative choices.

    This is the table-building pipeline with every modelling choice exposed as an argument, so
    the sensitivity analysis can change one choice at a time: the reading of the claims sheet
    (``rule``), the years pooled, the graduation ``method`` (default: the one selected), the
    age at which the insured table meets the population (``converge_age``) and the share of
    lives who are exposed only part of the year (``turnover``).
    """
    crude = crude_cells(
        death_cells(claims, rule, segment),
        central_exposure(exposure_cells(exposure, segment), turnover),
    )
    crude = crude[crude["age"] <= TERMINAL_AGE]
    out = {}
    last = common_last_age(crude, pop, years)
    for sex in ("M", "F"):
        q_pop = pop[pop["sex"] == sex].set_index("age")["qx"]
        fits = graduate_sex(crude, q_pop, sex, years=years, last_age=last)
        chosen = method or select_method(fits.comparison)
        out[sex] = full_table(fits, chosen, q_pop, converge_age=converge_age)
    return out


def _segment_frames(
    segment: str,
    claims: pd.DataFrame,
    exposure: pd.DataFrame,
    pop: pd.DataFrame,
    cnsf: pd.Series,
    *,
    graduate: bool = True,
) -> dict[str, pd.DataFrame]:
    """Every result table of one segment, before the segment column is added.

    With ``graduate=False`` only the crude and pooled experience are returned (for the blended
    market tables, which are built from their parts).
    """
    from mortality import graduation

    if segment_rows(exposure, segment).empty:
        raise ValueError(f"no insured lives in the segment {segment!r}")
    crude = crude_cells(death_cells(claims, segment=segment), exposure_cells(exposure, segment))
    crude = crude[crude["age"] <= TERMINAL_AGE]
    pooled = pooled_cells(crude)
    if not graduate:
        return {
            "insured_crude": _add_references(_with_intervals(crude), pop, cnsf),
            "insured_pooled": _add_references(_with_intervals(pooled), pop, cnsf),
        }

    methods, graduated, tests, table = [], [], [], []
    last = common_last_age(crude, pop)
    for sex in ("M", "F"):
        q_pop = pop[pop["sex"] == sex].set_index("age")["qx"]
        fits = graduate_sex(crude, q_pop, sex, last_age=last)
        chosen = select_method(fits.comparison)
        methods.append(
            fits.comparison.assign(
                selected=lambda f, c=chosen: f["method"] == c,
                first_age=int(fits.ages[0]),
                last_age=fits.last_age,
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
    table_df = _add_table_references(pd.concat(table, ignore_index=True), pop, cnsf)
    trend = standardised_trend(crude)
    change = annual_change(crude, table_df[["sex", "age", "qx"]])
    return {
        "insured_crude": _add_references(_with_intervals(crude), pop, cnsf),
        "insured_pooled": _add_references(_with_intervals(pooled), pop, cnsf),
        "insured_methods": pd.concat(methods, ignore_index=True),
        "insured_graduated": pd.concat(graduated, ignore_index=True),
        "insured_fit_tests": pd.concat(tests, ignore_index=True),
        "insured_table": table_df,
        "insured_trend": pd.concat(
            [trend.assign(kind="standardised_rate"), change.assign(kind="annual_change")],
            ignore_index=True,
        ),
    }


def build_tables(con) -> list[tuple[str, str]]:
    """Create the insured-lives tables from the CNSF statistics; returns (name, description)."""
    docs: list[tuple[str, str]] = []
    if not _has(con, "cnsf_vi_claims", "cnsf_vi_issued", "graduated_qx", "cnsf_rates"):
        return docs

    claims = pd.read_sql(
        "SELECT year, age, sex, plan, modality, coverage, cause, claims, amount_claimed, "
        f"amount_paid FROM cnsf_vi_claims WHERE coverage = '{DEATH_COVER}'",
        con,
    )
    # lives holding the death cover: the denominator that matches the numerator
    exposure = pd.read_sql(
        "SELECT year, age, sex, plan, modality, SUM(insured) AS insured FROM cnsf_vi_issued "
        f"WHERE coverage = '{DEATH_COVER}' GROUP BY year, age, sex, plan, modality",
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

    collected: dict[str, list[pd.DataFrame]] = {}

    def keep(segment: str, frames: dict[str, pd.DataFrame]) -> None:
        for name, frame in frames.items():
            collected.setdefault(name, []).append(frame.assign(segment=segment))

    graduated_frames: dict[str, dict[str, pd.DataFrame]] = {}
    for segment in GRADUATED:
        try:
            graduated_frames[segment] = _segment_frames(segment, claims, exposure, pop, cnsf)
        except ValueError:  # a segment too thin to graduate is left out, not forced
            continue
        keep(segment, graduated_frames[segment])
    relativity_rows: list[dict] = []
    for segment, reference in RELATIVE.items():
        if reference not in graduated_frames:
            continue
        try:
            frames = _segment_frames(segment, claims, exposure, pop, cnsf, graduate=False)
        except ValueError:  # no lives in this segment
            continue
        ref_table = graduated_frames[reference]["insured_table"]
        keep_columns = ["sex", "age", "qx", "qx_lower", "qx_upper", "source", "method"]
        tables = []
        for sex in ("M", "F"):
            ref = ref_table[ref_table["sex"] == sex]
            pooled_sex = frames["insured_pooled"][frames["insured_pooled"]["sex"] == sex]
            curve = fit_relative_curve(pooled_sex, ref.set_index("age")["qx"])
            last = int(ref.loc[ref["source"] == "graduated", "age"].max())
            q_pop = pop[pop["sex"] == sex].set_index("age")["qx"]
            tables.append(relative_table(curve, ref[keep_columns], q_pop, last))
        table = _add_table_references(pd.concat(tables, ignore_index=True), pop, cnsf)
        crude = frames["insured_crude"]
        frames["insured_table"] = table
        frames["insured_trend"] = pd.concat(
            [
                standardised_trend(crude).assign(kind="standardised_rate"),
                annual_change(crude, table[["sex", "age", "qx"]]).assign(kind="annual_change"),
            ],
            ignore_index=True,
        )
        graduated_frames[segment] = frames
        keep(segment, frames)
    reference = RELATIVITY_REFERENCE
    for segment, frames in graduated_frames.items():
        ref_table = graduated_frames[reference]["insured_table"]
        for sex in ("M", "F"):
            q_ref = ref_table[ref_table["sex"] == sex].set_index("age")["qx"]
            pooled_sex = frames["insured_pooled"]
            pooled_sex = pooled_sex[pooled_sex["sex"] == sex]
            for ages in (RELATIVITY_AGES, (25, 44), (45, 65)):
                if segment == reference and ages != RELATIVITY_AGES:
                    continue
                relativity_rows.append(
                    {"segment": segment, "sex": sex, "reference": reference}
                    | relativity(pooled_sex, q_ref, ages)
                )
    if relativity_rows:
        save("insured_relativities", pd.DataFrame(relativity_rows))
    for blend, members in BLENDS.items():
        members = [m for m in members if m in graduated_frames]
        if not members:
            continue
        frames = _segment_frames(blend, claims, exposure, pop, cnsf, graduate=False)
        columns = ["sex", "age", "qx", "qx_lower", "qx_upper", "source"]
        table = blend_tables(
            {m: graduated_frames[m]["insured_table"][columns] for m in members},
            {m: graduated_frames[m]["insured_pooled"] for m in members},
        )
        table = _add_table_references(table, pop, cnsf)
        crude = frames["insured_crude"]
        frames["insured_table"] = table
        frames["insured_trend"] = pd.concat(
            [
                standardised_trend(crude).assign(kind="standardised_rate"),
                annual_change(crude, table[["sex", "age", "qx"]]).assign(kind="annual_change"),
            ],
            ignore_index=True,
        )
        keep(blend, frames)
    for name, parts in collected.items():
        frame = pd.concat(parts, ignore_index=True)
        order = ["segment", *[c for c in frame.columns if c != "segment"]]
        save(name, frame[order])
    return docs


def _add_table_references(table: pd.DataFrame, pop: pd.DataFrame, cnsf: pd.Series) -> pd.DataFrame:
    out = floor_men_at_women(table).merge(
        pop.rename(columns={"qx": "q_population"}), on=["sex", "age"], how="left"
    )
    out["q_cnsf2013"] = out["age"].map(cnsf)
    out["ratio_population"] = out["qx"] / out["q_population"]
    out["ratio_cnsf2013"] = out["qx"] / out["q_cnsf2013"]
    return out
