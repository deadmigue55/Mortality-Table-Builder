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
    Deaths rise with age, which tilts the index slightly upward even without heaping.
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


# ── Building the warehouse tables ───────────────────────────────────────────

# Residents of Mexico, plus deaths whose state of residence is unspecified (99): they died in
# Mexico and almost all are residents. Known residents abroad (33-35) are excluded.
NATIONAL_SCOPE_SQL = """
    SELECT occ_year AS year, sex, age_years AS key, SUM(deaths) AS deaths
    FROM inegi_deaths_cells
    WHERE occ_year IS NOT NULL AND (state BETWEEN '01' AND '32' OR state = '99')
    GROUP BY occ_year, sex, age_years
"""


def _heaping_inputs(con) -> dict[str, pd.DataFrame]:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
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


def build_tables(con) -> list[tuple[str, str]]:
    """Create the quality tables inside the warehouse; returns (name, description) pairs."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    docs: list[tuple[str, str]] = []

    inputs = _heaping_inputs(con)
    if inputs:
        heaping = heaping_table(inputs)
        heaping.to_sql("quality_age_heaping", con, if_exists="replace", index=False)
        docs.append(
            (
                "quality_age_heaping",
                "Digit-preference indices (Whipple, Myers, Noumbissi) for INEGI deaths, CONAPO "
                "population and HMD deaths, by year and sex",
            )
        )

    if "inegi_deaths_cells" in tables:
        scope = pd.read_sql(NATIONAL_SCOPE_SQL, con)
        scope["sex"] = scope["sex"].where(scope["sex"].isin(["M", "F"]))
        adjusted = allocate_unknowns(scope).rename(columns={"key": "age"})
        adjusted.to_sql("deaths_adjusted", con, if_exists="replace", index=False)
        con.execute(
            "CREATE INDEX IF NOT EXISTS ix_deaths_adjusted ON deaths_adjusted (year, sex, age)"
        )
        docs.append(
            (
                "deaths_adjusted",
                "National deaths by year of occurrence, sex and single age, including unknown "
                "state of residence; deaths of unknown sex or age allocated proportionally "
                "(audit columns show what was added)",
            )
        )
    return docs
