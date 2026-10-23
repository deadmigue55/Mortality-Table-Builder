"""Data quality for the mortality inputs.

* **Age heaping** (digit preference): Whipple, Myers and Noumbissi indices.
* **Unknowns**: deaths with unknown sex or age are allocated in proportion to the known
  distribution, so no death is silently dropped.
* **Scope**: deaths of people living in Mexico, including those with unknown state of
  residence (they died in Mexico); known residents abroad are excluded because the
  population exposure does not include them.

Everything here is a plain function on pandas objects so it can be tested without a database.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ── Age heaping ─────────────────────────────────────────────────────────────

# UN scale for the Whipple index (100 = no preference for ages ending in 0 or 5)
WHIPPLE_SCALE = ((105.0, "highly accurate"), (110.0, "fairly accurate"), (125.0, "approximate"),
                 (175.0, "rough"))  # fmt: skip


def whipple_class(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    for limit, label in WHIPPLE_SCALE:
        if value < limit:
            return label
    return "very rough"


def _by_age(counts: pd.Series, lo: int, hi: int) -> pd.Series:
    """Counts for every age lo..hi (missing ages as 0)."""
    return counts.reindex(range(lo, hi + 1), fill_value=0).astype(float)


def whipple_index(counts: pd.Series, lo: int = 23, hi: int = 62) -> float:
    """Whipple index: 100 when ages ending in 0 or 5 hold exactly their fair fifth.

    ``counts`` is indexed by single year of age. 500 means every record is on a 0 or 5.
    The eight heaped ages have the same mean age as the forty, so any straight-line age
    profile scores exactly 100; a smooth curve moves it by under a point.
    """
    c = _by_age(counts, lo, hi)
    total = c.sum()
    if total == 0:
        return float("nan")
    heaped = c[[a for a in c.index if a % 5 == 0]].sum()
    return float(500.0 * heaped / total)


def myers_index(counts: pd.Series) -> float:
    """Myers' blended index over ages 10-99: 0 = no digit preference, 90 = all on one digit.

    Each terminal digit is tallied twice, from age 10 and from age 20, and the two tallies are
    blended with weights that cancel the effect of an age distribution that changes with age.
    """
    c = _by_age(counts, 10, 99)
    blended = np.empty(10)
    for d in range(10):
        first = sum(c[10 * k + d] for k in range(1, 9))  # ages 10+d, 20+d, ..., 80+d
        second = sum(c[10 * k + d] for k in range(2, 10))  # ages 20+d, 30+d, ..., 90+d
        blended[d] = (d + 1) * first + (9 - d) * second
    total = blended.sum()
    if total == 0:
        return float("nan")
    return float(0.5 * np.abs(100.0 * blended / total - 10.0).sum())


def noumbissi_index(counts: pd.Series, digit: int, lo: int = 20, hi: int = 69) -> float:
    """Noumbissi's index for one terminal digit: 1.0 = none, above 1 = preferred.

    Compares ages ending in ``digit`` with the average of their two neighbours, so a smooth
    upward trend (as in deaths) does not register as heaping.
    """
    c = _by_age(counts, lo - 1, hi + 1)
    ages = [a for a in range(lo, hi + 1) if a % 10 == digit]
    if not ages:
        raise ValueError(f"No ages ending in {digit} between {lo} and {hi}.")
    num = sum(c[a] for a in ages)
    den = sum(c[a - 1] + c[a] + c[a + 1] for a in ages) / 3.0
    return float("nan") if den == 0 else float(num / den)


def heaping_row(counts: pd.Series) -> dict[str, float | str]:
    whipple = whipple_index(counts)
    return {
        "whipple": whipple,
        "whipple_class": whipple_class(whipple),
        "myers": myers_index(counts),
        "noumbissi_0": noumbissi_index(counts, 0),
        "noumbissi_5": noumbissi_index(counts, 5),
    }


def heaping_table(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Heaping indices per dataset, year and sex.

    Each frame needs columns ``year``, ``sex`` (M or F), ``age`` and ``value``.
    """
    rows = []
    for name, frame in datasets.items():
        for (year, sex), part in frame.groupby(["year", "sex"]):
            counts = part.groupby("age")["value"].sum()
            rows.append({"dataset": name, "year": int(year), "sex": sex, **heaping_row(counts)})
    return pd.DataFrame(rows)


# ── Unknown sex and age ─────────────────────────────────────────────────────


def allocate_unknowns(cells: pd.DataFrame, max_key: int | None = None) -> pd.DataFrame:
    """Allocate deaths with unknown sex and/or age in proportion to the known deaths.

    ``cells`` has columns ``year``, ``sex`` (M, F or missing), ``key`` (an integer position on
    the age axis: single year of age, or the lower bound of an age group; missing if unknown)
    and ``deaths``. Within each year:

    1. unknown sex, known age: split between M and F as the known deaths at that age are;
       where there are no known deaths at that age, as the year as a whole is split;
    2. known sex, unknown age: spread over ages as that sex's known deaths are;
    3. unknown sex and age: spread over the whole sex-by-age table as it now stands.

    No death is created or lost. Returns one row per year, sex and key with the recorded
    deaths, what each step added (unknown sex, unknown age, unknown both) and the adjusted total.
    """
    out = []
    for year, part in cells.groupby("year"):
        keys = sorted({int(k) for k in part["key"].dropna()})
        if max_key is not None:
            keys = sorted(set(keys) | {max_key})
        pos = {k: i for i, k in enumerate(keys)}
        recorded = np.zeros((2, len(keys)))
        unk_sex = np.zeros(len(keys))
        unk_age = np.zeros(2)
        unk_both = 0.0
        for sex, key, deaths in zip(part["sex"], part["key"], part["deaths"], strict=True):
            if pd.isna(sex) and pd.isna(key):
                unk_both += deaths
            elif pd.isna(sex):
                unk_sex[pos[int(key)]] += deaths
            elif pd.isna(key):
                unk_age[0 if sex == "M" else 1] += deaths
            else:
                recorded[0 if sex == "M" else 1, pos[int(key)]] += deaths

        # 1) unknown sex, known age
        known_total = recorded.sum()
        share_m_year = recorded[0].sum() / known_total if known_total else 0.5
        at_age = recorded.sum(axis=0)
        share_m = np.where(at_age > 0, recorded[0] / np.where(at_age > 0, at_age, 1), share_m_year)
        added_sex = np.vstack([unk_sex * share_m, unk_sex * (1 - share_m)])
        table = recorded + added_sex

        # 2) known sex, unknown age
        added_age = np.zeros_like(recorded)
        for s in (0, 1):
            total = table[s].sum()
            if unk_age[s] and total:
                added_age[s] = unk_age[s] * table[s] / total
            elif unk_age[s]:  # that sex has no known deaths at all: use both sexes' shape
                both = table.sum(axis=0)
                added_age[s] = unk_age[s] * both / both.sum()
        table = table + added_age

        # 3) unknown sex and age
        added_both = np.zeros_like(recorded)
        if unk_both and table.sum():
            added_both = unk_both * table / table.sum()
        final = table + added_both

        for s, sex in enumerate(("M", "F")):
            for k in keys:
                i = pos[k]
                out.append(
                    {
                        "year": int(year),
                        "sex": sex,
                        "key": k,
                        "recorded": recorded[s, i],
                        "added_unknown_sex": added_sex[s, i],
                        "added_unknown_age": added_age[s, i],
                        "added_unknown_both": added_both[s, i],
                        "adjusted": final[s, i],
                    }
                )
    return pd.DataFrame(out)


# ── Late registration: a chain-ladder triangle ─────────────────────────────

# A death is registered some years after it occurs; the latest years are always incomplete.
# Rows are year of occurrence, columns are the lag (file year minus occurrence year), exactly
# like a claims-development triangle, so the actuarial chain-ladder method applies. Late
# registration depends on age (infants are registered almost on time, the very old and
# unknown-age records much later), so there is one triangle per age band.

AGE_BANDS = (
    (0, 0, "0"),
    (1, 14, "1-14"),
    (15, 29, "15-29"),
    (30, 44, "30-44"),
    (45, 64, "45-64"),
    (65, 79, "65-79"),
    (80, 200, "80+"),
)
UNKNOWN_BAND = "unknown"
BAND_ORDER = [b[2] for b in AGE_BANDS] + [UNKNOWN_BAND]


def age_band(age) -> str:
    """Broad age band used for late-registration triangles ("unknown" for a missing age)."""
    if pd.isna(age):
        return UNKNOWN_BAND
    for lo, hi, label in AGE_BANDS:
        if lo <= age <= hi:
            return label
    raise ValueError(f"Age out of range: {age}")


def build_triangle(cells: pd.DataFrame) -> pd.DataFrame:
    """Triangle of deaths by age band, year of occurrence and registration lag.

    ``cells`` has ``occ_year``, ``file_year``, ``age`` and ``deaths``. Only occurrence years
    that have their own file (lag 0 observed) form complete triangle rows.
    """
    df = cells.dropna(subset=["occ_year"]).copy()
    first_file = int(df["file_year"].min())
    df = df[df["occ_year"] >= first_file]
    df["lag"] = (df["file_year"] - df["occ_year"]).astype(int)
    df["band"] = df["age"].map(age_band)
    tri = df.groupby(["band", "occ_year", "lag"], as_index=False)["deaths"].sum()
    tri["occ_year"] = tri["occ_year"].astype(int)
    tri = tri.sort_values(["band", "occ_year", "lag"], ignore_index=True)
    tri["cumulative"] = tri.groupby(["band", "occ_year"])["deaths"].cumsum()
    return tri


def chain_ladder_factors(triangle: pd.DataFrame) -> pd.DataFrame:
    """Volume-weighted development factors: cumulative deaths at lag L+1 over lag L.

    Only occurrence years observed at both lags enter each factor.
    """
    rows = []
    for band, part in triangle.groupby("band"):
        wide = part.pivot_table(index="occ_year", columns="lag", values="cumulative")
        for lag in sorted(wide.columns)[:-1]:
            both = wide[[lag, lag + 1]].dropna()
            num, den = both[lag + 1].sum(), both[lag].sum()
            rows.append(
                {
                    "band": band,
                    "lag": int(lag),
                    "factor": float(num / den) if den else 1.0,
                    "years_used": len(both),
                }
            )
    return pd.DataFrame(rows)


def tail_factor(late_deaths: float, base_deaths: float) -> float:
    """1 + share of deaths registered more than the triangle's last lag after occurrence."""
    return 1.0 if base_deaths <= 0 else 1.0 + late_deaths / base_deaths


def completion_factors(
    triangle: pd.DataFrame, factors: pd.DataFrame, tail: float = 1.0
) -> pd.DataFrame:
    """Factor that turns deaths reported so far into the estimated final count.

    For an occurrence year seen up to lag ``k``, the factor is the product of the development
    factors from lag ``k`` onward, times the tail.
    """
    last_file_lag = triangle.groupby("occ_year")["lag"].max()
    rows = []
    for band in sorted(factors["band"].unique()):
        f = factors[factors["band"] == band].set_index("lag")["factor"]
        for occ_year, k in last_file_lag.items():
            ahead = f[f.index >= k]
            rows.append(
                {
                    "band": band,
                    "occ_year": int(occ_year),
                    "lags_seen": int(k),
                    "factor": float(ahead.prod() * tail),
                }
            )
    return pd.DataFrame(rows)


def complete_cells(cells: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Scale reported deaths up to their estimated final counts.

    ``cells`` has ``year``, ``sex``, ``key`` (age) and ``deaths``; ``factors`` comes from
    :func:`completion_factors`. Adds ``reported`` and ``completed`` columns.
    """
    lookup = factors.set_index(["band", "occ_year"])["factor"]
    out = cells.copy()
    bands = out["key"].map(age_band)
    mult = [lookup.get((b, y), 1.0) for b, y in zip(bands, out["year"], strict=True)]
    out["reported"] = out["deaths"]
    out["completed"] = out["deaths"] * np.array(mult)
    return out


# ── Building the warehouse tables ───────────────────────────────────────────

# Residents of Mexico, plus deaths whose state of residence is unspecified (99): they died in
# Mexico and almost all are residents. Known residents abroad (33-35) are excluded.
SCOPE_WHERE = "(state BETWEEN '01' AND '32' OR state = '99') AND occ_year IS NOT NULL"
TAIL_HORIZON = 5  # deaths registered this many years or more after occurrence form the tail
COVID_SHARE_THRESHOLD = 0.01  # a year with at least 1% COVID-coded deaths is a COVID year


def _table_names(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _heaping_inputs(con) -> dict[str, pd.DataFrame]:
    tables = _table_names(con)
    sets: dict[str, pd.DataFrame] = {}
    if "deaths_by_occurrence" in tables:
        sets["INEGI deaths"] = pd.read_sql(
            "SELECT year, sex, age, SUM(deaths) AS value FROM deaths_by_occurrence "
            "WHERE year >= 2020 GROUP BY year, sex, age",
            con,
        )
    if "conapo_population" in tables:
        sets["CONAPO population"] = pd.read_sql(
            "SELECT year, sex, age, population AS value FROM conapo_population "
            "WHERE state_code = 0 AND sex IN ('M', 'F') AND year BETWEEN 2020 AND 2024",
            con,
        )
    if "hmd_deaths" in tables:
        hmd = pd.read_sql(
            "SELECT country, year, sex, age, value FROM hmd_deaths "
            "WHERE sex IN ('M', 'F') AND year BETWEEN 2020 AND 2024 AND value IS NOT NULL",
            con,
        )
        for country, part in hmd.groupby("country"):
            sets[f"HMD deaths {country}"] = part.drop(columns="country")
    return sets


def estimate_tail(con) -> tuple[float, int]:
    """Tail factor from older occurrence years: late deaths over that year's registered total.

    Uses occurrence years early enough that lags of 5 and more are observed in the files, with
    the imported INEGI tables as the base. Returns (factor, number_of_years_used).
    """
    if "inegi_cube_registered" not in _table_names(con):
        return 1.0, 0
    first_file = con.execute("SELECT MIN(file_year) FROM inegi_deaths_cells").fetchone()[0]
    base = pd.read_sql(
        "SELECT reg_year AS year, SUM(deaths) AS base FROM inegi_cube_registered GROUP BY reg_year",
        con,
    )
    late = pd.read_sql(
        f"SELECT occ_year AS year, SUM(deaths) AS late FROM inegi_deaths_cells "
        f"WHERE {SCOPE_WHERE} AND file_year - occ_year >= {TAIL_HORIZON} GROUP BY occ_year",
        con,
    )
    both = base.merge(late, on="year")
    # the files cover lags 5 and up only for years early enough: first_file - 5 or before
    both = both[both["year"] <= first_file - TAIL_HORIZON]
    if both.empty:
        return 1.0, 0
    return tail_factor(float((both["late"] / both["base"]).mean()), 1.0), len(both)


def _registration_tables(con, docs: list[tuple[str, str]]) -> pd.DataFrame | None:
    """Build triangle, factors and completion; returns the per-band, per-year factors."""
    cells = pd.read_sql(
        f"SELECT occ_year, file_year, age_years AS age, SUM(deaths) AS deaths "
        f"FROM inegi_deaths_cells WHERE {SCOPE_WHERE} GROUP BY occ_year, file_year, age_years",
        con,
    )
    if cells.empty:
        return None
    triangle = build_triangle(cells)
    factors = chain_ladder_factors(triangle)
    if factors.empty:  # a single file year: no development to measure
        triangle.to_sql("registration_triangle", con, if_exists="replace", index=False)
        docs.append(
            ("registration_triangle", "Deaths by age band, year of occurrence and registration lag")
        )
        return None
    tail, tail_years = estimate_tail(con)
    comp = completion_factors(triangle, factors, tail)

    reported = triangle.groupby(["band", "occ_year"], as_index=False)["deaths"].sum()
    comp = comp.merge(reported.rename(columns={"deaths": "reported"}), on=["band", "occ_year"])
    comp["estimated_final"] = comp["reported"] * comp["factor"]
    comp["missing_deaths"] = comp["estimated_final"] - comp["reported"]
    order = {label: i for i, label in enumerate(BAND_ORDER)}
    comp = comp.sort_values(
        ["occ_year", "band"], key=lambda c: c.map(order) if c.name == "band" else c
    )

    triangle.to_sql("registration_triangle", con, if_exists="replace", index=False)
    factors.to_sql("registration_factors", con, if_exists="replace", index=False)
    comp.to_sql("registration_completion", con, if_exists="replace", index=False)
    pd.DataFrame(
        [{"tail_factor": tail, "years_used": tail_years, "horizon_lag": TAIL_HORIZON}]
    ).to_sql("registration_tail", con, if_exists="replace", index=False)
    docs += [
        (
            "registration_triangle",
            "Deaths by age band, year of occurrence and registration lag (a chain-ladder triangle)",
        ),
        ("registration_factors", "Chain-ladder development factors by age band and lag"),
        (
            "registration_completion",
            "Reported vs estimated final deaths by age band and year of occurrence",
        ),
        ("registration_tail", "Tail factor for deaths registered 5+ years after occurrence"),
    ]
    return comp[["band", "occ_year", "factor"]]


def build_tables(con) -> list[tuple[str, str]]:
    """Create the quality tables inside the warehouse; returns (name, description) pairs."""
    tables = _table_names(con)
    docs: list[tuple[str, str]] = []

    inputs = _heaping_inputs(con)
    if inputs:
        heaping_table(inputs).to_sql("quality_age_heaping", con, if_exists="replace", index=False)
        docs.append(
            (
                "quality_age_heaping",
                "Digit-preference indices (Whipple, Myers, Noumbissi) for INEGI deaths, CONAPO "
                "population and HMD deaths, by year and sex",
            )
        )

    if "inegi_deaths_cells" not in tables:
        return docs

    factors = _registration_tables(con, docs)

    # Only years with their own file; earlier years hold just a few late registrations
    first, last = con.execute(
        "SELECT MIN(file_year), MAX(file_year) FROM inegi_deaths_cells"
    ).fetchone()
    scope = pd.read_sql(
        f"SELECT occ_year AS year, sex, age_years AS key, SUM(deaths) AS deaths "
        f"FROM inegi_deaths_cells WHERE {SCOPE_WHERE} AND occ_year BETWEEN {first} AND {last} "
        f"GROUP BY occ_year, sex, age_years",
        con,
    )
    scope["sex"] = scope["sex"].where(scope["sex"].isin(["M", "F"]))
    if factors is not None:
        completed = complete_cells(scope, factors)
    else:
        completed = scope.assign(reported=scope["deaths"], completed=scope["deaths"])

    allocated = allocate_unknowns(completed.assign(deaths=completed["completed"]))
    known = completed.dropna(subset=["sex", "key"]).rename(columns={"key": "age"})
    known = known.assign(age=known["age"].astype(int))[["year", "sex", "age", "reported"]]
    adjusted = allocated.rename(columns={"key": "age", "recorded": "completed_known"}).merge(
        known, on=["year", "sex", "age"], how="left"
    )
    adjusted["reported"] = adjusted["reported"].fillna(0.0)
    adjusted["added_late_registration"] = adjusted["completed_known"] - adjusted["reported"]
    adjusted = adjusted[
        [
            "year",
            "sex",
            "age",
            "reported",
            "added_late_registration",
            "added_unknown_sex",
            "added_unknown_age",
            "added_unknown_both",
            "adjusted",
        ]
    ]
    adjusted.to_sql("deaths_adjusted", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_deaths_adjusted ON deaths_adjusted (year, sex, age)")
    docs.append(
        (
            "deaths_adjusted",
            "National deaths by year of occurrence, sex and single age (analysis-ready): late "
            "registrations completed by chain ladder, then unknown sex and age allocated "
            "proportionally. Audit columns show every addition",
        )
    )
    return docs


# ── Cause of death: COVID-19 and the pandemic years ─────────────────────────


def cause_tables(con, files: list) -> list[tuple[str, str]]:
    """Deaths by ICD-10 chapter letter and COVID flag, plus a flag for each COVID year.

    ICD-10 codes beginning ``U07`` (U07.1, U07.2) are COVID-19. A year with at least 1% of its
    deaths coded that way is flagged as a COVID year, so models can leave it out of baselines.
    """
    if not files:
        return []
    keys = ["occ_year", "occ_month", "sex", "chapter", "covid"]
    frames = []
    first_file = 9999
    for file in files:
        df = pd.read_parquet(file, columns=["file_year", "occ_year", "occ_month", "sex", "cause"])
        first_file = min(first_file, int(df["file_year"].min()))
        df["chapter"] = df["cause"].str[:1].fillna("?")
        df["covid"] = df["cause"].str.startswith("U07", na=False).astype(int)
        frames.append(df.groupby(keys, dropna=False).size().rename("deaths").reset_index())
    by_cause = pd.concat(frames, ignore_index=True).groupby(keys, dropna=False)["deaths"].sum()
    by_cause = by_cause.reset_index()
    by_cause["sex"] = by_cause["sex"].where(by_cause["sex"].isin(["M", "F"]))
    by_cause.to_sql("deaths_by_cause_chapter", con, if_exists="replace", index=False)

    known = by_cause.dropna(subset=["occ_year"])
    yearly = pd.DataFrame(
        {
            "deaths": known.groupby("occ_year")["deaths"].sum(),
            "covid_deaths": known[known["covid"] == 1].groupby("occ_year")["deaths"].sum(),
        }
    ).fillna(0)
    yearly = yearly.rename_axis("year").reset_index().astype({"year": int})
    yearly = yearly[yearly["year"] >= first_file]  # earlier years hold only late registrations
    yearly["covid_share"] = yearly["covid_deaths"] / yearly["deaths"]
    yearly["covid_year"] = (yearly["covid_share"] >= COVID_SHARE_THRESHOLD).astype(int)
    yearly.to_sql("year_flags", con, if_exists="replace", index=False)
    return [
        (
            "deaths_by_cause_chapter",
            "Deaths by year and month of occurrence, sex, ICD-10 chapter letter and COVID-19 flag",
        ),
        (
            "year_flags",
            "Per year of occurrence: COVID-coded deaths, their share, and a COVID-year flag (1%+)",
        ),
    ]
