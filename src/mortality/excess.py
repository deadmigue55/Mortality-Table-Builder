"""Excess mortality: how many more people died than would have without the pandemic.

"Excess" is observed deaths minus the deaths a baseline expects, and the baseline is the whole
difficulty: it is a counterfactual nobody observed. A single baseline gives a single number that
looks more certain than it is, so this module builds four, from different assumptions, and
reports the range:

* **flat 2019**: every age and sex keeps its 2019 death rate;
* **trend 2014-2019**: a log-linear trend per age band and sex, fitted by Poisson regression to
  the six pre-pandemic years and carried forward;
* **interpolation to 2023**: the log rate moves in a straight line from its 2019 value to its
  observed 2023 value, using the recovery as a second anchor;
* **Lee-Carter**: the pre-pandemic trend of CONAPO's 1970-2019 series (step 7), scaled to the
  INEGI level of 2019 band by band, because the two sources disagree on the age pattern.

Observed deaths are INEGI's by year of occurrence, completed for late registrations (step 3);
exposure is CONAPO's mid-year population. Everything is in 5-year age bands and by sex.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mortality import rates

METHODS = ("flat_2019", "trend_2014_2019", "interpolation_to_2023", "lee_carter")
PANDEMIC_YEARS = (2020, 2021, 2022)
PRE_YEARS = tuple(range(2014, 2020))
ANCHOR_YEAR = 2023
CAUSE_LABELS = {
    "U": "COVID-19", "I": "Circulatory (heart disease, stroke)", "E": "Endocrine (diabetes)",
    "J": "Respiratory", "C": "Neoplasms", "K": "Digestive", "N": "Genitourinary",
    "X": "External causes (accidents, violence)", "R": "Symptoms and ill-defined",
}  # fmt: skip


# ── Baselines ───────────────────────────────────────────────────────────────


def flat_baseline(rate_2019: np.ndarray, exposure: np.ndarray) -> np.ndarray:
    """Expected deaths if the 2019 rate had continued (``rate`` per band, ``exposure`` by year)."""
    return rate_2019[:, None] * exposure


def trend_baseline(
    deaths: np.ndarray, exposure: np.ndarray, years_fit, years_pred, exposure_pred
) -> tuple[np.ndarray, np.ndarray]:
    """Log-linear trend per band by Poisson regression, carried to ``years_pred``.

    ``deaths`` and ``exposure`` are ``(bands, years_fit)``. Returns the expected deaths and their
    standard error ``(bands, years_pred)``; the standard error uses the covariance of the fit,
    inflated by the dispersion pooled over all bands (a band alone has too few years to
    estimate it).
    """
    import statsmodels.api as sm

    t = np.asarray(years_fit, dtype=float) - float(np.mean(years_fit))
    tp = np.asarray(years_pred, dtype=float) - float(np.mean(years_fit))
    design = sm.add_constant(t)
    new = np.column_stack([np.ones(len(tp)), tp])
    expected = np.zeros((deaths.shape[0], len(tp)))
    log_var = np.zeros_like(expected)
    chi2 = dof = 0.0
    fits = []
    for b in range(deaths.shape[0]):
        fit = sm.GLM(
            deaths[b], design, family=sm.families.Poisson(), offset=np.log(exposure[b])
        ).fit()
        fits.append(fit)
        chi2 += float(fit.pearson_chi2)
        dof += float(fit.df_resid)
    dispersion = max(1.0, chi2 / dof) if dof > 0 else 1.0
    for b, fit in enumerate(fits):
        cov = fit.cov_params() * dispersion
        log_rate = new @ fit.params
        expected[b] = np.exp(log_rate) * exposure_pred[b]
        log_var[b] = np.einsum("ij,jk,ik->i", new, cov, new)
    return expected, expected * np.sqrt(log_var)


def interpolation_baseline(
    rate_2019: np.ndarray,
    rate_anchor: np.ndarray,
    years,
    exposure: np.ndarray,
    anchor_year=ANCHOR_YEAR,
) -> np.ndarray:
    """Log rate interpolated in a straight line from 2019 to the anchor year."""
    w = (np.asarray(years, dtype=float) - 2019.0) / (anchor_year - 2019.0)
    log_rate = (1 - w)[None, :] * np.log(rate_2019)[:, None] + w[None, :] * np.log(rate_anchor)[
        :, None
    ]
    return np.exp(log_rate) * exposure


def lee_carter_baseline(
    history: pd.DataFrame,
    population: pd.DataFrame,
    sex: str,
    years,
    rate_2019_inegi: np.ndarray,
    exposure: np.ndarray,
) -> np.ndarray:
    """The pre-pandemic Lee-Carter trend, banded and scaled to the INEGI level of 2019.

    The model is fitted to CONAPO 1970-2019 and restarted at CONAPO's 2019 rates. Single-age
    rates are combined into the 5-year bands with CONAPO's population as weights, then each band
    is multiplied by ``INEGI 2019 rate / CONAPO 2019 rate``: the two sources agree on the total
    but not on the age pattern (docs/projection.md), and this keeps the baseline on the INEGI
    footing of the observed deaths.
    """
    from mortality import projection as proj

    deaths, exposure_c, hist_years = proj.history_arrays(history, sex)
    fit = proj.fit_lee_carter(
        deaths[:, hist_years >= proj.FIT_START], exposure_c[:, hist_years >= proj.FIT_START]
    )
    last = deaths[:, -1] / exposure_c[:, -1]
    horizon = int(max(years)) - 2019
    path = proj.central_lee_carter(fit, horizon, jump_off=last)  # (horizon, 100 single ages)
    pop = population[population["sex"] == sex].pivot_table(
        index="age", columns="year", values="population"
    )
    ages = np.arange(100)
    band = rates.band_index(ages)
    n_bands = len(rates.BAND_LABELS)

    def banded(rate_by_age: np.ndarray, year: int) -> np.ndarray:
        weights = pop.loc[ages, year].to_numpy()
        num = np.bincount(band, weights=rate_by_age * weights, minlength=n_bands)
        den = np.bincount(band, weights=weights, minlength=n_bands)
        return num / den

    base_2019 = banded(last, 2019)
    scale = rate_2019_inegi / base_2019
    out = np.zeros((n_bands, len(years)))
    for j, year in enumerate(years):
        out[:, j] = banded(path[year - 2020], year) * scale * exposure[:, j]
    return out


def baseline_set(
    grouped: pd.DataFrame,
    history: pd.DataFrame | None,
    population: pd.DataFrame | None,
    years=(*PANDEMIC_YEARS, 2023, 2024),
) -> pd.DataFrame:
    """Expected deaths by sex, band and year under every baseline.

    ``grouped``: the warehouse's ``crude_rates_grouped`` (deaths and exposure by year, sex, band).
    ``history`` and ``population`` feed the Lee-Carter baseline; without them it is skipped.
    """
    rows = []
    n_bands = len(rates.BAND_LABELS)
    for sex in ("M", "F"):
        g = grouped[grouped["sex"] == sex]
        d = g.pivot_table(index="band", columns="year", values="deaths").reindex(range(n_bands))
        e = g.pivot_table(index="band", columns="year", values="exposure").reindex(range(n_bands))
        rate = d / e
        pred_exposure = e[list(years)].to_numpy()
        r19 = rate[2019].to_numpy()
        results = {"flat_2019": (flat_baseline(r19, pred_exposure), None)}
        trend, trend_se = trend_baseline(
            d[list(PRE_YEARS)].to_numpy(),
            e[list(PRE_YEARS)].to_numpy(),
            PRE_YEARS,
            years,
            pred_exposure,
        )
        results["trend_2014_2019"] = (trend, trend_se)
        results["interpolation_to_2023"] = (
            interpolation_baseline(r19, rate[ANCHOR_YEAR].to_numpy(), years, pred_exposure), None,
        )  # fmt: skip
        if history is not None and population is not None:
            results["lee_carter"] = (
                lee_carter_baseline(history, population, sex, years, r19, pred_exposure), None,
            )  # fmt: skip
        for method, (expected, se) in results.items():
            for j, year in enumerate(years):
                for b in range(n_bands):
                    rows.append(
                        {
                            "sex": sex, "band": b, "age_group": rates.BAND_LABELS[b], "year": year,
                            "method": method, "expected": float(expected[b, j]),
                            "expected_se": float(se[b, j]) if se is not None else np.nan,
                        }
                    )  # fmt: skip
    return pd.DataFrame(rows)


# ── Excess deaths ───────────────────────────────────────────────────────────


def excess_by_band(grouped: pd.DataFrame, baselines: pd.DataFrame) -> pd.DataFrame:
    """Observed against expected deaths by year, sex and band, with the range over baselines.

    ``expected_central`` is the median of the baselines, ``expected_low`` and ``expected_high``
    their extremes, so ``excess_low`` (from the highest baseline) and ``excess_high`` (from the
    lowest) bracket the answer. ``stat_se`` is the sampling noise of the observed count plus the
    standard error of the trend baseline."""
    obs = grouped[grouped["sex"].isin(["M", "F"])][["year", "sex", "band", "deaths", "exposure"]]
    wide = baselines.pivot_table(index=["year", "sex", "band"], columns="method", values="expected")
    se = baselines[baselines["method"] == "trend_2014_2019"].set_index(["year", "sex", "band"])[
        "expected_se"
    ]
    out = obs.merge(wide.reset_index(), on=["year", "sex", "band"])
    out = out.rename(columns={"deaths": "observed"})
    methods = [m for m in METHODS if m in out.columns]
    out["expected_central"] = out[methods].median(axis=1)
    out["expected_low"], out["expected_high"] = out[methods].min(axis=1), out[methods].max(axis=1)
    out["excess"] = out["observed"] - out["expected_central"]
    out["excess_low"] = out["observed"] - out["expected_high"]
    out["excess_high"] = out["observed"] - out["expected_low"]
    se_aligned = se.reindex(pd.MultiIndex.from_frame(out[["year", "sex", "band"]])).to_numpy()
    out["stat_se"] = np.sqrt(out["observed"] + np.nan_to_num(se_aligned) ** 2)
    out["p_score"] = out["excess"] / out["expected_central"]
    out["age_group"] = np.asarray(rates.BAND_LABELS)[out["band"].to_numpy()]
    return out.sort_values(["year", "sex", "band"], ignore_index=True)


def summarise(by_band: pd.DataFrame, covid_coded: pd.Series | None = None,
              remaining_life: pd.DataFrame | None = None) -> pd.DataFrame:  # fmt: skip
    """Totals by year and sex (and both sexes): excess, its range, P-score, years of life lost.

    ``covid_coded``: deaths certified as COVID-19, by year. ``remaining_life``: life expectancy by
    ``sex`` and ``band`` (a reference life table), used to turn excess deaths into years of
    life lost.
    """
    d = by_band.copy()
    sums = [
        "observed", "expected_central", "expected_low", "expected_high", "excess", "excess_low",
        "excess_high",
    ]  # fmt: skip
    if remaining_life is not None:
        d = d.merge(remaining_life, on=["sex", "band"], how="left")
        d["years_lost"] = d["excess"] * d["remaining_life"]
        sums.append("years_lost")  # an all-missing sum would read as 0, so only sum what exists
    aggregate = {**{c: "sum" for c in sums}, "stat_se": lambda x: float(np.sqrt((x**2).sum()))}
    by_sex = d.groupby(["year", "sex"], as_index=False)[[*sums, "stat_se"]].agg(aggregate)
    both = d.groupby("year", as_index=False)[[*sums, "stat_se"]].agg(aggregate).assign(sex="T")
    out = pd.concat([by_sex, both], ignore_index=True)
    if remaining_life is None:
        out["years_lost"] = np.nan
    out["p_score"] = out["excess"] / out["expected_central"]
    if covid_coded is not None:
        coded = out["year"].map(covid_coded)
        out["covid_coded"] = np.where(out["sex"] == "T", coded, np.nan)
        out["excess_per_covid_coded"] = out["excess"] / out["covid_coded"]
    return out.sort_values(["year", "sex"], ignore_index=True)


# ── By cause, by month, by state ────────────────────────────────────────────


def cause_excess(causes: pd.DataFrame, population: pd.Series, anchor=ANCHOR_YEAR) -> pd.DataFrame:
    """Deaths by cause chapter against the post-pandemic level, scaled by population growth.

    ``causes``: ``year, chapter, deaths``. For each pandemic year the baseline is the anchor
    year's count times the ratio of that year's population to the anchor's. There is no
    pre-pandemic cause-of-death microdata in the project, so the anchor year is the only baseline;
    a cause that was already falling or rising before 2020 is misread (diabetes and heart disease
    were rising), and the result is a lower bound for causes that were rising.
    """
    pivot = causes.pivot_table(
        index="chapter", columns="year", values="deaths", aggfunc="sum"
    ).fillna(0.0)
    rows = []
    for year in PANDEMIC_YEARS:
        factor = population[year] / population[anchor]
        for chapter, row in pivot.iterrows():
            expected = 0.0 if chapter == "U" else row[anchor] * factor
            rows.append(
                {"year": year, "chapter": chapter, "observed": row[year], "expected": expected,
                 "excess": row[year] - expected}
            )  # fmt: skip
    out = pd.DataFrame(rows)
    out["label"] = out["chapter"].map(CAUSE_LABELS).fillna("Other causes")
    return out


def monthly_excess(monthly: pd.DataFrame, annual_baseline: pd.Series, seasonal_years=(2023, 2024)):
    """Monthly deaths against a baseline that follows the normal seasonal shape.

    ``monthly``: ``year, month, deaths, covid_deaths`` (the microdata by month of occurrence).
    The baseline of a pandemic month is the year's central baseline (from the banded analysis)
    times that month's share of the year in the post-pandemic years, so winter peaks are not
    mistaken for excess.
    """
    m = monthly[monthly["month"].between(1, 12)].copy()
    post = (
        m[m["year"].isin(seasonal_years)].groupby(["year", "month"])["deaths"].sum().reset_index()
    )
    post["share"] = post["deaths"] / post.groupby("year")["deaths"].transform("sum")
    share = post.groupby("month")["share"].mean()
    out = m.groupby(["year", "month"], as_index=False)[["deaths", "covid_deaths"]].sum()
    out["baseline"] = [
        annual_baseline.get(y, np.nan) * share.get(mo, np.nan)
        for y, mo in zip(out["year"], out["month"], strict=True)
    ]
    out["excess"] = out["deaths"] - out["baseline"]
    return out


def state_excess(
    deaths: pd.DataFrame, population: pd.DataFrame, baseline_year: int = ANCHOR_YEAR
) -> pd.DataFrame:
    """Excess deaths by state against each state's own post-pandemic mortality.

    ``deaths``: ``year, state, sex, age, deaths`` (residents of a known state, by year of
    occurrence). ``population``: ``year, state, sex, age, population``. For each state and sex the
    5-year-band death rates of ``baseline_year`` are applied to each pandemic year's population,
    so the comparison removes the state's age structure and population growth. There is no
    state-level history before 2020 in the project, so this is excess *relative to 2023*, not to
    a pre-pandemic trend (the national analysis shows 2023 is within a few percent of trend).
    """

    def banded(df: pd.DataFrame, column: str) -> pd.DataFrame:
        b = df.assign(band=rates.band_index(df["age"]))
        return b.groupby(["year", "state", "sex", "band"], as_index=False)[column].sum()

    d, p = banded(deaths, "deaths"), banded(population, "population")
    m = p.merge(d, on=["year", "state", "sex", "band"], how="left").fillna({"deaths": 0.0})
    base = m[m["year"] == baseline_year].assign(rate=lambda x: x["deaths"] / x["population"])
    m = m.merge(base[["state", "sex", "band", "rate"]], on=["state", "sex", "band"])
    m["expected"] = m["population"] * m["rate"]
    out = (
        m[m["year"].isin(PANDEMIC_YEARS)]
        .groupby(["year", "state"], as_index=False)[["deaths", "expected"]]
        .sum()
    )
    out = out.rename(columns={"deaths": "observed"})
    out["excess"] = out["observed"] - out["expected"]
    out["p_score"] = out["excess"] / out["expected"]
    return out


# ── Warehouse tables ────────────────────────────────────────────────────────

DESCRIPTIONS = {
    "excess_baselines": (
        "Expected deaths by sex, 5-year band and year under four baselines: flat 2019 rates, "
        "the 2014-2019 trend, interpolation to 2023 and the Lee-Carter pre-pandemic trend"
    ),
    "excess_mortality": (
        "Observed against expected deaths by year, sex and age band, with the range over the four "
        "baselines, sampling noise and the P-score"
    ),
    "excess_summary": (
        "Excess deaths by year and sex (T = both): central estimate, range, P-score, certified "
        "COVID-19 deaths, the ratio of excess to certified, and years of life lost"
    ),
    "excess_monthly": (
        "Monthly deaths of the microdata against a seasonally shaped baseline, with the deaths "
        "certified as COVID-19"
    ),
    "excess_by_cause": (
        "Deaths by ICD-10 chapter in the pandemic years against the 2023 level scaled by "
        "population: where the excess was certified"
    ),
    "excess_state": ("Excess deaths by state and year against each state's own 2023 age-sex rates"),
}


def reference_life_expectancy(con) -> pd.DataFrame | None:
    """Life expectancy at the middle of each band from the 2023 life tables (step 6)."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "life_tables" not in names:
        return None
    ex = pd.read_sql(
        "SELECT sex, age, ex FROM life_tables WHERE year = 2023 AND sex IN ('M', 'F')", con
    ).pivot_table(index="age", columns="sex", values="ex")
    rows = []
    for band, (lo, hi) in enumerate(
        zip(rates.BAND_LOWER, (*rates.BAND_LOWER[1:], 110), strict=True)
    ):
        mid = int(min((lo + hi - 1) // 2, 100))
        for sex in ("M", "F"):
            rows.append({"sex": sex, "band": band, "remaining_life": float(ex.loc[mid, sex])})
    return pd.DataFrame(rows)


def build_tables(con) -> list[tuple[str, str]]:
    """Compute the excess-mortality tables from the warehouse."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    needed = {"crude_rates_grouped", "conapo_population", "year_flags", "deaths_by_cause_chapter"}
    if not needed <= names:
        return []
    grouped = pd.read_sql(
        "SELECT year, sex, band, deaths, exposure FROM crude_rates_grouped WHERE sex IN ('M', 'F')",
        con,
    )
    if not {*PRE_YEARS, ANCHOR_YEAR, *PANDEMIC_YEARS} <= set(grouped["year"]):
        return []
    history = population = None
    if {"conapo_deaths"} <= names:
        from mortality import projection as proj

        history = proj.load_history(con)
        population = pd.read_sql(
            "SELECT year, sex, age, population FROM conapo_population "
            "WHERE state_code = 0 AND year BETWEEN 2019 AND 2024",
            con,
        )
    baselines = baseline_set(grouped, history, population)
    by_band = excess_by_band(grouped, baselines)
    flags = pd.read_sql("SELECT year, covid_deaths FROM year_flags", con).set_index("year")[
        "covid_deaths"
    ]
    summary = summarise(by_band, flags, reference_life_expectancy(con))
    frames = {
        "excess_baselines": baselines,
        "excess_mortality": by_band,
        "excess_summary": summary,
    }

    causes = pd.read_sql(
        "SELECT occ_year AS year, occ_month AS month, chapter, covid, deaths "
        "FROM deaths_by_cause_chapter WHERE occ_year BETWEEN 2020 AND 2024",
        con,
    )
    national = pd.read_sql(
        "SELECT year, SUM(population) AS p FROM conapo_population WHERE state_code = 0 "
        "AND year BETWEEN 2020 AND 2024 GROUP BY year",
        con,
    ).set_index("year")["p"]
    frames["excess_by_cause"] = cause_excess(causes, national)
    monthly = causes.groupby(["year", "month"], as_index=False).agg(
        deaths=("deaths", "sum"),
        covid_deaths=("deaths", lambda s: float(s[causes.loc[s.index, "covid"] == 1].sum())),
    )
    both = summary[summary["sex"] == "T"].set_index("year")
    micro = monthly.groupby("year")["deaths"].sum()
    annual = {
        y: both.loc[y, "expected_central"] * micro[y] / both.loc[y, "observed"]
        for y in both.index
        if y in micro.index
    }
    frames["excess_monthly"] = monthly_excess(monthly, pd.Series(annual))

    if "deaths_by_occurrence" in names and "dim_state" in names:
        sd = pd.read_sql(
            "SELECT year, CAST(state_code_text AS INTEGER) AS state, sex, age, deaths "
            "FROM deaths_by_occurrence WHERE year BETWEEN 2020 AND 2023 "
            "AND CAST(state_code_text AS INTEGER) BETWEEN 1 AND 32 AND sex IN ('M', 'F')",
            con,
        )
        sp = pd.read_sql(
            "SELECT year, state_code AS state, sex, age, population FROM conapo_population "
            "WHERE year BETWEEN 2020 AND 2023 AND state_code BETWEEN 1 AND 32",
            con,
        )
        state = state_excess(sd, sp)
        names_df = pd.read_sql("SELECT state_code AS state, state_name FROM dim_state", con)
        frames["excess_state"] = state.merge(names_df, on="state", how="left")

    docs = []
    for name, frame in frames.items():
        if len(frame):
            frame.to_sql(name, con, if_exists="replace", index=False)
            docs.append((name, DESCRIPTIONS[name]))
    return docs
