"""Crude mortality rates, standardisation and first benchmarks.

Everything is built from three inputs, all already in the warehouse:

* **Deaths**: ``deaths_adjusted`` (2020-2024, by year of occurrence, single age) and the INEGI
  interactive tables ``inegi_cube_registered`` (2014-2019, by year of registration, 5-year groups).
* **Exposure**: CONAPO mid-year population (1 July), which approximates the person-years lived
  in the calendar year. A central rate is ``m = deaths / mid-year population``.
* **Benchmarks**: CNSF 2013 and the SOA Mexican tables (expected deaths), the Human Mortality
  Database (other countries).

The functions are plain pandas/NumPy so they can be tested without a database;
``build_tables`` wires them to the warehouse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

# ── Age bands ───────────────────────────────────────────────────────────────

TERMINAL_AGE = 100  # single-age rates pool ages 100 and over (CONAPO stops at 109)
BAND_LOWER = (0, 1, *range(5, 90, 5))  # 0, 1-4, 5-9, ..., 85+
BAND_LABELS = ("0", "1-4", *(f"{a}-{a + 4}" for a in range(5, 85, 5)), "85+")

# Segi world standard population (per 100,000), the usual choice for comparing mortality
# across years and places. Its first group is 0-4, so our bands "0" and "1-4" merge there.
SEGI_LOWER = tuple(range(0, 90, 5))
SEGI_WEIGHTS = (
    12000, 10000, 9000, 9000, 8000, 8000, 6000, 6000, 6000,
    6000, 5000, 4000, 4000, 3000, 2000, 1000, 500, 500,
)  # fmt: skip

# Minimum deaths for a cell to be called credible on its own (full credibility needs ~1,082
# under the classical limited-fluctuation rule; 30 is the floor below which a rate is noise)
THIN_CELL_DEATHS = 30


def band_index(age) -> np.ndarray:
    """Position of each age in ``BAND_LOWER`` (0 = under 1, 18 = 85 and over)."""
    return np.searchsorted(BAND_LOWER, np.asarray(age), side="right") - 1


def band_label(index) -> np.ndarray:
    return np.asarray(BAND_LABELS)[np.asarray(index)]


def segi_group(band: int) -> int:
    """Segi group (0-4, 5-9, ..., 85+) that contains a 5-year band index."""
    return max(int(band) - 1, 0)  # bands 0 and 1 both fall in 0-4


# ── Confidence intervals ────────────────────────────────────────────────────


def poisson_interval(deaths, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Exact (Garwood) interval for a Poisson count; also valid for non-integer counts.

    The gamma form is used so that adjusted (fractional) death counts work too.
    """
    d = np.asarray(deaths, dtype=float)
    with np.errstate(invalid="ignore"):
        lower = np.where(d > 0, stats.gamma.ppf(alpha / 2, np.where(d > 0, d, 1.0)), 0.0)
        upper = stats.gamma.ppf(1 - alpha / 2, d + 1)
    return lower, upper


def rate_interval(deaths, exposure, alpha: float = 0.05):
    """Poisson interval for ``deaths / exposure``."""
    lower, upper = poisson_interval(deaths, alpha)
    e = np.asarray(exposure, dtype=float)
    return lower / e, upper / e


# ── Rates ───────────────────────────────────────────────────────────────────


def infant_ax(m0, sex):
    """Average years lived in the first year by those who die in it (Preston et al., 2001).

    Deaths in infancy cluster in the first weeks, so ``a0`` is far below 0.5 and depends on
    the level of infant mortality. Used only to turn ``m0`` into ``q0``.
    """
    m0 = np.asarray(m0, dtype=float)
    male = np.asarray(sex) == "M"
    return np.where(
        m0 >= 0.107,
        np.where(male, 0.33, 0.35),
        np.where(male, 0.045 + 2.684 * m0, 0.053 + 2.800 * m0),
    )


def mx_to_qx(mx, age, sex):
    """Probability of dying within a year from the central rate: ``q = m / (1 + (1 - a) m)``."""
    m = np.asarray(mx, dtype=float)
    a = np.where(np.asarray(age) == 0, infant_ax(m, sex), 0.5)
    return m / (1 + (1 - a) * m)


def qx_to_mx(qx, age=None):
    """Inverse of ``mx_to_qx`` with a = 0.5 (used for ages above infancy)."""
    q = np.asarray(qx, dtype=float)
    return q / (1 - 0.5 * q)


def pool_terminal(df: pd.DataFrame, value_columns: list[str]) -> pd.DataFrame:
    """Merge ages at and above ``TERMINAL_AGE`` into one open-ended row per group."""
    out = df.assign(age=df["age"].clip(upper=TERMINAL_AGE))
    keys = [c for c in out.columns if c not in value_columns]
    return out.groupby(keys, as_index=False)[value_columns].sum()


def crude_single(deaths: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    """Central rates by year, sex and single age.

    ``deaths``: year, sex, age, deaths. ``population``: year, sex, age, population. Ages at and
    above ``TERMINAL_AGE`` are pooled on both sides so numerator and denominator always match.
    """
    d = pool_terminal(deaths[["year", "sex", "age", "deaths"]], ["deaths"])
    p = pool_terminal(
        population[["year", "sex", "age", "population"]].rename(columns={"population": "exposure"}),
        ["exposure"],
    )
    # Start from the population so an age with exposure but no deaths keeps a rate of 0
    p = p[p["year"].isin(d["year"].unique())]
    out = p.merge(d, on=["year", "sex", "age"], how="left").fillna({"deaths": 0.0})
    out = out[out["exposure"] > 0].copy()
    out["mx"] = out["deaths"] / out["exposure"]
    out["mx_lower"], out["mx_upper"] = rate_interval(out["deaths"], out["exposure"])
    terminal = out["age"] >= TERMINAL_AGE
    out["qx"] = np.where(terminal, np.nan, mx_to_qx(out["mx"], out["age"], out["sex"]))
    out["credible"] = out["deaths"] >= THIN_CELL_DEATHS
    return out.sort_values(["year", "sex", "age"], ignore_index=True)


def crude_grouped(deaths: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    """Central rates by year, sex and 5-year band (``band`` = index into ``BAND_LOWER``).

    ``deaths``: year, sex, band, deaths (plus optional ``basis``). ``population``: year, sex,
    band, exposure. The sex ``T`` (both sexes) is added.
    """
    keys = [c for c in deaths.columns if c not in ("deaths", "exposure")]
    d = deaths.groupby(keys, as_index=False)["deaths"].sum()
    out = d.merge(population, on=["year", "sex", "band"], how="inner")
    total_keys = [k for k in keys if k != "sex"]
    both = out.groupby(total_keys, as_index=False)[["deaths", "exposure"]].sum()
    out = pd.concat([out, both.assign(sex="T")], ignore_index=True)
    out["age_group"] = band_label(out["band"])
    out["mx"] = out["deaths"] / out["exposure"]
    out["mx_lower"], out["mx_upper"] = rate_interval(out["deaths"], out["exposure"])
    out["credible"] = out["deaths"] >= THIN_CELL_DEATHS
    return out.sort_values([*total_keys, "sex"], ignore_index=True)


def allocate_cube_unknowns(cube: pd.DataFrame) -> pd.DataFrame:
    """Spread unknown sex, then unknown age, in the hand-exported INEGI tables.

    ``cube``: reg_year, age_lo (missing = age not specified), sex (M, F, U), deaths. The result
    has only M and F and known age groups, and the same total deaths in every year. Allocation
    is proportional, like ``quality.allocate_unknowns`` for the microdata.
    """
    unknown_age = -1.0  # a sentinel: pandas drops missing keys from pivots and group-bys
    df = cube.assign(
        age_lo=cube["age_lo"].astype("float64").fillna(unknown_age),
        deaths=cube["deaths"].astype("float64"),
    )
    key = ["reg_year", "age_lo"]

    # 1. unknown sex: split U between M and F in proportion to the known deaths of that row
    wide = df.pivot_table(index=key, columns="sex", values="deaths", aggfunc="sum", fill_value=0.0)
    wide = wide.reindex(columns=["M", "F", "U"], fill_value=0.0)
    known = wide["M"] + wide["F"]
    share_m = (wide["M"] / known.where(known > 0)).fillna(0.5)
    wide["M"] += wide["U"] * share_m
    wide["F"] += wide["U"] * (1 - share_m)
    long = wide[["M", "F"]].reset_index().melt(id_vars=key, var_name="sex", value_name="deaths")

    # 2. unknown age: spread over the known groups of the same year and sex
    is_unknown = long["age_lo"] == unknown_age
    unknown = long[is_unknown].groupby(["reg_year", "sex"])["deaths"].sum()
    out = long[~is_unknown].copy()
    base = out.groupby(["reg_year", "sex"])["deaths"].transform("sum")
    extra = unknown.reindex(pd.MultiIndex.from_frame(out[["reg_year", "sex"]])).to_numpy()
    out["deaths"] = out["deaths"] * (1 + np.nan_to_num(extra) / base)
    out["band"] = band_index(out["age_lo"])
    return out.groupby(["reg_year", "sex", "band"], as_index=False)["deaths"].sum()


# ── Age standardisation ─────────────────────────────────────────────────────


def standardise(deaths, exposure, weights, alpha: float = 0.05) -> dict[str, float]:
    """Directly age-standardised rate with a Fay-Feuer gamma interval.

    ``deaths`` and ``exposure`` are arrays over the standard's age groups. The rate answers
    "what would the death rate be if this population had the standard age structure?", which
    removes the effect of ageing when comparing years or places.
    """
    d = np.asarray(deaths, dtype=float)
    n = np.asarray(exposure, dtype=float)
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    y = float((w * d / n).sum())
    v = float((w**2 * d / n**2).sum())
    wm = float((w / n).max())
    if y <= 0 or v <= 0:
        return {"asr": y, "asr_lower": np.nan, "asr_upper": np.nan}
    lower = v / (2 * y) * stats.chi2.ppf(alpha / 2, 2 * y**2 / v)
    upper = (
        (v + wm**2)
        / (2 * (y + wm))
        * stats.chi2.ppf(1 - alpha / 2, 2 * (y + wm) ** 2 / (v + wm**2))
    )
    return {"asr": y, "asr_lower": float(lower), "asr_upper": float(upper)}


def age_standardised(grouped: pd.DataFrame) -> pd.DataFrame:
    """Segi-standardised rates per year, basis and sex from ``crude_grouped`` output."""
    g = grouped.assign(segi=[segi_group(b) for b in grouped["band"]])
    rows = []
    for (basis, year, sex), cell in g.groupby(["basis", "year", "sex"]):
        by_group = cell.groupby("segi")[["deaths", "exposure"]].sum().reindex(range(18))
        if by_group.isna().any().any():
            continue
        result = standardise(by_group["deaths"], by_group["exposure"], SEGI_WEIGHTS)
        rows.append(
            {
                "basis": basis,
                "year": year,
                "sex": sex,
                "deaths": cell["deaths"].sum(),
                "exposure": cell["exposure"].sum(),
                "crude_rate": cell["deaths"].sum() / cell["exposure"].sum(),
                **result,
            }
        )
    return pd.DataFrame(rows)


# ── Observed versus expected ────────────────────────────────────────────────


def ae_interval(actual, expected, alpha: float = 0.05):
    """Exact Poisson interval for an actual-to-expected ratio (expected treated as fixed)."""
    lower, upper = poisson_interval(actual, alpha)
    e = np.asarray(expected, dtype=float)
    return lower / e, upper / e


def smr_table(
    observed: pd.DataFrame, population: pd.DataFrame, region: str = "state"
) -> pd.DataFrame:
    """Indirectly standardised mortality ratios (SMR) of regions against their combined total.

    ``observed``: region, sex, band, deaths. ``population``: region, sex, band, exposure.
    Expected deaths apply the pooled sex-and-band rate to each region's population, so the
    expected total equals the observed total and a region with SMR 1.10 has 10% more deaths
    than its age-sex structure predicts.
    """
    pooled = (
        observed.groupby(["sex", "band"])["deaths"].sum()
        / population.groupby(["sex", "band"])["exposure"].sum()
    ).rename("ref_rate")
    cells = population.merge(observed, on=[region, "sex", "band"], how="left").fillna(
        {"deaths": 0.0}
    )
    cells = cells.merge(pooled.reset_index(), on=["sex", "band"])
    cells["expected"] = cells["exposure"] * cells["ref_rate"]
    out = cells.groupby(region, as_index=False)[["deaths", "expected", "exposure"]].sum()
    out = out.rename(columns={"deaths": "observed"})
    out["smr"] = out["observed"] / out["expected"]
    out["smr_lower"], out["smr_upper"] = ae_interval(out["observed"], out["expected"])
    return out.sort_values("smr", ascending=False, ignore_index=True)


# ── Benchmarks ──────────────────────────────────────────────────────────────

# Mexican tables used as yardsticks: label in soa_catalog -> sex the table was built for
# (T = both sexes). CNSF 2013 is handled separately because it lives in its own table.
SOA_BENCHMARKS: dict[str, str] = {
    "MEX 2000 male": "M",
    "MEX 2000 female": "F",
    "CNSF 2000-I individual insured lives (1991-1998)": "T",
    "CNSF 2000-G group life (1991-1998)": "T",
    "Experiencia Mexicana individual (1982-1989)": "T",
    "EMSSA 97 pension participants (H)": "M",
    "EMSSA 97 pension participants (M)": "F",
    "Seguro Popular 2008 males": "M",
    "Seguro Popular 2008 females": "F",
}
CNSF_BENCHMARK = "CNSF M 2013 (non-disabled lives, base)"
AE_BANDS = range(6, 18)  # 25-29 ... 80-84: ages every benchmark table covers


def expected_deaths(population: pd.DataFrame, table_rates: pd.Series, sex: str) -> pd.DataFrame:
    """Deaths a table predicts for a population: exposure times the table's central rate.

    ``population``: year, sex, age, population. ``table_rates``: q by age. For sex ``T`` both
    sexes are added. Returns year, band, expected for the bands in ``AE_BANDS`` that the table
    fully covers.
    """
    pop = population if sex == "T" else population[population["sex"] == sex]
    pop = pop.groupby(["year", "age"], as_index=False)["population"].sum()
    pop = pop.assign(rate=pop["age"].map(pd.Series(qx_to_mx(table_rates), index=table_rates.index)))
    pop["band"] = band_index(pop["age"])
    pop = pop[pop["band"].isin(list(AE_BANDS))]
    covered = pop.groupby(["year", "band"])["rate"].transform(lambda r: r.notna().all())
    pop = pop[covered]
    pop = pop.assign(expected=pop["population"] * pop["rate"])
    return pop.groupby(["year", "band"], as_index=False)["expected"].sum()


def actual_versus_expected(
    deaths: pd.DataFrame, population: pd.DataFrame, tables: dict[str, tuple[pd.Series, str]]
) -> pd.DataFrame:
    """Actual-to-expected ratios of the Mexican population against each benchmark table.

    ``deaths``: year, sex (M, F, T), band, deaths. ``tables``: name -> (q by age, sex it covers).
    Unisex tables are applied to men, women and both sexes. For each year and age band the
    ratio says how much heavier or lighter population mortality is than the table; the row
    "25-84" is the total over those bands.
    """
    rows = []
    for name, (rates, table_sex) in tables.items():
        for sex in ("M", "F", "T") if table_sex == "T" else (table_sex,):
            expected = expected_deaths(population, rates, sex)
            actual = deaths[deaths["sex"] == sex][["year", "band", "deaths"]]
            merged = actual.merge(expected, on=["year", "band"])
            total = merged.groupby("year", as_index=False)[["deaths", "expected"]].sum()
            # the total is only comparable when every band is present
            complete = merged.groupby("year")["band"].count() == len(AE_BANDS)
            total = total[total["year"].isin(complete[complete].index)].assign(band=-1)
            both = pd.concat([merged, total], ignore_index=True)
            both["benchmark"], both["sex"] = name, sex
            rows.append(both)
    out = pd.concat(rows, ignore_index=True).rename(columns={"deaths": "actual"})
    out["age_group"] = np.where(out["band"] < 0, "25-84", band_label(out["band"].clip(lower=0)))
    out["ae"] = out["actual"] / out["expected"]
    out["ae_lower"], out["ae_upper"] = ae_interval(out["actual"], out["expected"])
    cols = ["benchmark", "sex", "year", "age_group", "band", "actual", "expected", "ae"]
    return out[[*cols, "ae_lower", "ae_upper"]].sort_values(
        ["benchmark", "sex", "year", "band"], ignore_index=True
    )


def country_ratios(mexico: pd.DataFrame, hmd: pd.DataFrame) -> pd.DataFrame:
    """Mexico's rate divided by each country's, by year, sex and 5-year band.

    ``mexico``: year, sex, band, mx. ``hmd``: country, year, sex, band, deaths, exposure.
    Ratios above 1 mean Mexico dies faster than that country at that age.
    """
    keys = ["country", "year", "sex", "band"]
    g = hmd.groupby(keys, as_index=False)[["deaths", "exposure"]].sum()
    g["mx_country"] = g["deaths"] / g["exposure"]
    out = g.merge(mexico.rename(columns={"mx": "mx_mexico"}), on=["year", "sex", "band"])
    out["ratio"] = out["mx_mexico"] / out["mx_country"]
    out["age_group"] = band_label(out["band"])
    return out[["country", "year", "sex", "age_group", "band", "mx_mexico", "mx_country", "ratio"]]


# ── Warehouse tables ────────────────────────────────────────────────────────


def _has(con, *names: str) -> bool:
    found = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return all(n in found for n in names)


def _save(
    con, docs: list[tuple[str, str]], name: str, frame: pd.DataFrame, description: str
) -> None:
    """Write a result table and document it; an empty result (partial data) is skipped."""
    if frame.empty:
        return
    frame.to_sql(name, con, if_exists="replace", index=False)
    docs.append((name, description))


def _band_population(population: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sum single-age population into the 5-year bands."""
    p = population.assign(band=band_index(population["age"]))
    grouped = p.groupby([*by, "band"], as_index=False)["population"].sum()
    return grouped.rename(columns={"population": "exposure"})


def _benchmark_tables(con) -> dict[str, tuple[pd.Series, str]]:
    tables: dict[str, tuple[pd.Series, str]] = {}
    if _has(con, "cnsf_rates"):
        cnsf = pd.read_sql(
            "SELECT age, qx FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' AND variant = 'base'",
            con,
        )
        if len(cnsf):
            tables[CNSF_BENCHMARK] = (cnsf.set_index("age")["qx"], "T")
    if _has(con, "soa_rates", "soa_catalog"):
        soa = pd.read_sql(
            "SELECT c.label, r.age, r.rate FROM soa_rates r JOIN soa_catalog c USING (table_id) "
            "WHERE r.duration IS NULL",
            con,
        )
        for label, sex in SOA_BENCHMARKS.items():
            part = soa[soa["label"] == label]
            if len(part):
                tables[label] = (part.set_index("age")["rate"], sex)
    return tables


def build_tables(con) -> list[tuple[str, str]]:
    """Create the rate, standardisation and benchmark tables; returns (name, description)."""
    docs: list[tuple[str, str]] = []
    if not _has(con, "conapo_population", "deaths_adjusted"):
        return docs

    first, last = con.execute("SELECT MIN(year), MAX(year) FROM deaths_adjusted").fetchone()
    cube_first = None
    if _has(con, "inegi_cube_registered"):
        cube_first = con.execute("SELECT MIN(reg_year) FROM inegi_cube_registered").fetchone()[0]
    start = min(first, cube_first) if cube_first else first
    pop = pd.read_sql(
        "SELECT year, sex, age, population FROM conapo_population "
        f"WHERE state_code = 0 AND year BETWEEN {start} AND {last}",
        con,
    )

    # Single-age rates (occurrence basis, adjusted deaths)
    adjusted = pd.read_sql("SELECT year, sex, age, adjusted AS deaths FROM deaths_adjusted", con)
    single = crude_single(adjusted, pop)
    _save(
        con,
        docs,
        "crude_rates_single",
        single,
        "Crude central death rates by year of occurrence, sex and single age (100 = 100 and "
        "over), with exact Poisson 95% intervals, q approximations and a thin-cell flag",
    )

    # Five-year-band rates over the whole span: occurrence (2020+) and registration (before)
    exposure = _band_population(pop, ["year", "sex"])
    occurrence = adjusted.assign(band=band_index(adjusted["age"]))
    occurrence = occurrence.groupby(["year", "sex", "band"], as_index=False)["deaths"].sum()
    parts = [occurrence.assign(basis="occurrence")]
    if cube_first:
        cube = pd.read_sql("SELECT reg_year, age_lo, sex, deaths FROM inegi_cube_registered", con)
        registered = allocate_cube_unknowns(cube).rename(columns={"reg_year": "year"})
        older = registered[~registered["year"].isin(occurrence["year"])]
        parts.append(older.assign(basis="registration"))
    grouped = crude_grouped(pd.concat(parts, ignore_index=True), exposure)
    _save(
        con,
        docs,
        "crude_rates_grouped",
        grouped,
        "Crude central death rates by year, sex (M, F, T) and 5-year band, 2014 onwards: "
        "'registration' basis from the INEGI tables before 2020, 'occurrence' basis from "
        "adjusted microdata from 2020",
    )
    _save(
        con,
        docs,
        "age_standardised_rates",
        age_standardised(grouped),
        "Segi world-standard age-standardised death rate with Fay-Feuer 95% interval, by "
        "year and sex, next to the crude rate; removes the effect of population ageing",
    )

    _bridge_table(con, docs)
    _state_table(con, docs)

    tables = _benchmark_tables(con)
    if tables and not grouped.empty:
        _save(
            con,
            docs,
            "benchmark_ae",
            actual_versus_expected(grouped[["year", "sex", "band", "deaths"]], pop, tables),
            "Actual-to-expected deaths of the Mexican population against CNSF 2013 and the "
            "SOA Mexican tables, by year, sex and age band 25-84 (expected = CONAPO "
            "population times the table's rate), with exact Poisson 95% intervals",
        )
    if _has(con, "hmd_deaths", "hmd_exposures") and not grouped.empty:
        hmd = pd.read_sql(
            "SELECT d.country, d.year, d.sex, d.age, d.value AS deaths, e.value AS exposure "
            "FROM hmd_deaths d JOIN hmd_exposures e USING (country, year, sex, age) "
            f"WHERE d.year BETWEEN {start} AND {last}",
            con,
        )
        hmd["band"] = band_index(hmd["age"])
        _save(
            con,
            docs,
            "benchmark_countries",
            country_ratios(grouped[["year", "sex", "band", "mx"]], hmd),
            "Mexico's death rate divided by each Human Mortality Database country's, by "
            "year, sex and 5-year band (above 1 = Mexico higher)",
        )
    return docs


def _bridge_table(con, docs: list[tuple[str, str]]) -> None:
    """Registered versus occurred deaths per year: how far the two bases differ."""
    registered = pd.DataFrame(columns=["year", "registered", "source"])
    if _has(con, "inegi_cube_registered"):
        cube = pd.read_sql(
            "SELECT reg_year AS year, SUM(deaths) AS registered FROM inegi_cube_registered "
            "GROUP BY reg_year",
            con,
        )
        registered = cube.assign(source="interactive table")
    if _has(con, "inegi_deaths_cells"):
        cells = pd.read_sql(
            "SELECT file_year AS year, SUM(deaths) AS registered FROM inegi_deaths_cells "
            "GROUP BY file_year",
            con,
        )
        cells = cells[~cells["year"].isin(registered["year"])].assign(source="microdata")
        registered = pd.concat([registered, cells], ignore_index=True)
    occurred = pd.read_sql(
        "SELECT year, SUM(adjusted) AS occurred_adjusted FROM deaths_adjusted GROUP BY year", con
    )
    out = registered.merge(occurred, on="year", how="outer").sort_values("year", ignore_index=True)
    out["registered_to_occurred"] = out["registered"] / out["occurred_adjusted"]
    _save(
        con,
        docs,
        "basis_bridge",
        out,
        "Deaths registered in each year versus deaths that occurred in it (adjusted); shows "
        "how closely registration-year rates before 2020 stand in for occurrence-year rates",
    )


def _state_table(con, docs: list[tuple[str, str]]) -> None:
    """State SMRs for the latest complete non-COVID year."""
    if not _has(con, "deaths_by_occurrence", "inegi_completeness", "year_flags", "dim_state"):
        return
    row = con.execute(
        "SELECT MAX(c.year) FROM inegi_completeness c JOIN year_flags f USING (year) "
        "WHERE c.complete = 1 AND f.covid_year = 0"
    ).fetchone()
    if not row or row[0] is None:
        return
    year = row[0]
    obs = pd.read_sql(
        "SELECT CAST(state_code_text AS INTEGER) AS state, sex, age, deaths "
        f"FROM deaths_by_occurrence WHERE year = {year} AND "
        "CAST(state_code_text AS INTEGER) BETWEEN 1 AND 32",
        con,
    )
    obs = obs.assign(band=band_index(obs["age"]))
    obs = obs.groupby(["state", "sex", "band"], as_index=False)["deaths"].sum()
    pop = pd.read_sql(
        "SELECT state_code AS state, sex, age, population FROM conapo_population "
        f"WHERE year = {year} AND state_code BETWEEN 1 AND 32",
        con,
    )
    if obs.empty or pop.empty:
        return
    table = smr_table(obs, _band_population(pop, ["state", "sex"]), region="state")
    names = pd.read_sql("SELECT state_code AS state, state_name FROM dim_state", con)
    table = table.merge(names, on="state", how="left").assign(year=year)
    _save(
        con,
        docs,
        "state_smr",
        table,
        f"Standardised mortality ratio of each state in {year} (latest complete non-COVID "
        "year): observed deaths over the deaths its age-sex structure predicts at national "
        "rates, with exact 95% intervals. Deaths of people with unknown state are excluded",
    )
