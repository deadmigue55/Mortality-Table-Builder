"""Where the insured-lives table sits: against the population, the regulator and other countries.

Everything here is built with the same life-table and commutation code as the rest of the
project, at the same 4% interest, so differences between tables are differences in mortality
and nothing else.

* ``insured_comparison``: life expectancy, annuity and insurance values per table.
* ``insured_premiums``: net annual premium of a level term cover by issue age, term and table.
* ``insured_gap``: the insured/population ratio by age in Mexico (insured table and CNSF 2013)
  and in the United States (2017 Unloaded CSO against the national table), to see how unusual
  the Mexican gap is.
* ``insured_matches``: for each age band, the country and year whose national mortality is
  closest to the insured table ("who do insured Mexicans die like?").
* ``insured_brass``: two numbers per table (shift and tilt against the Mexican population).

Tables from the Human Mortality Database are used here for analysis only; derived tables that
hold HMD values are kept out of the public demo bundle (see ``demo.py``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mortality import lifetable
from mortality.insured import SEGMENTS, _has, logit

INTEREST = lifetable.INTEREST


def insured_label(segment: str) -> str:
    """Name of an insured table in the comparison tables."""
    return f"Mexico insured: {SEGMENTS[segment]['label']}"


MAIN = insured_label("all")  # the market-wide insured table, the headline comparison
TERM = insured_label("term_traditional")  # the standard term product
ISSUE_AGES = (25, 30, 35, 40, 45, 50, 55, 60)
TERMS = (10, 20)
GAP_AGES = range(20, 86)
MATCH_BANDS = tuple((lo, lo + 4) for lo in range(25, 85, 5))
HMD_COUNTRIES_FROM = 1950  # national tables older than this are not "modern" comparators
BRASS_AGES = (30, 80)

DESCRIPTIONS = {
    "insured_comparison": (
        "Life expectancy at 18, 40 and 65, annuity-due at 65, whole-life insurance at 40 and "
        "10- and 20-year term premiums at 40, at 4% interest, for the insured table, the Mexican "
        "population, CNSF 2013, the SOA Mexican and US tables and HMD countries"
    ),
    "insured_premiums": (
        "Net annual premium per 1,000 of a level 10- and 20-year term cover by sex, issue age "
        "and mortality table (insured, population, CNSF 2013 and its 99.5th percentile, US "
        "2017 CSO) at 4% interest"
    ),
    "insured_gap": (
        "Ratio of insured to population mortality by age and sex: the Mexican insured table, "
        "CNSF 2013 and the US 2017 Unloaded CSO against the US national table"
    ),
    "insured_matches": (
        "For each age band, the national mortality table (country and year, HMD, 1950 onward) "
        "closest to the insured table and to the Mexican population"
    ),
    "insured_brass": (
        "Shift (a) and tilt (b) of each table against the Mexican population on the logit "
        "scale, ages 30 to 80, with the root-mean-square difference of the fit"
    ),
}


def group_of(label: str) -> str:
    """The family of a reference table (HMD tables are tagged separately where they are read)."""
    if label.startswith("Mexico"):
        return "Mexico"
    return "CNSF" if label.startswith("CNSF") else "US insured"


def table_from_q(q: pd.Series) -> pd.DataFrame:
    """A life table from a series of q indexed by consecutive ages (the last q is set to 1)."""
    return lifetable._table_from_q(q.index, q.to_numpy())


def _value(c, fn, *args) -> float:
    try:
        return float(fn(*args))
    except (IndexError, KeyError, ValueError):
        return np.nan


def comparison_row(group: str, label: str, sex: str, q: pd.Series) -> dict:
    """The comparison measures of one table; blank where the table does not reach the age."""
    table = table_from_q(q.sort_index())
    ages = set(table["age"])
    c = lifetable.Commutation.from_table(table, INTEREST)

    def e(age):
        return float(table.loc[table["age"] == age, "ex"].iloc[0]) if age in ages else np.nan

    return {
        "group": group,
        "table": label,
        "sex": sex,
        "first_age": int(table["age"].iloc[0]),
        "e18": e(18),
        "e40": e(40),
        "e65": e(65),
        "a_due_65": _value(c, c.annuity_due, 65) if 65 in ages else np.nan,
        "A_40": _value(c, c.whole_life_insurance, 40) if 40 in ages else np.nan,
        "P_term_10_at_40": _value(c, c.term_premium, 40, 10) if {40, 50} <= ages else np.nan,
        "P_term_20_at_40": _value(c, c.term_premium, 40, 20) if {40, 60} <= ages else np.nan,
        "interest": INTEREST,
    }


def _q(con, sql: str) -> pd.Series:
    frame = pd.read_sql(sql, con)
    return frame.set_index("age")["q"].sort_index()


def reference_tables(con) -> dict[tuple[str, str], pd.Series]:
    """The tables compared, keyed by (label, sex): q by age."""
    out: dict[tuple[str, str], pd.Series] = {}
    for sex in ("M", "F"):
        for segment in SEGMENTS:
            q = _q(
                con,
                "SELECT age, qx AS q FROM insured_table "
                f"WHERE sex = '{sex}' AND segment = '{segment}'",
            )
            if len(q):
                out[(insured_label(segment), sex)] = q
        out[("Mexico population 2023", sex)] = _q(
            con, f"SELECT age, qx AS q FROM graduated_qx WHERE year = 2023 AND sex = '{sex}'"
        )
    cnsf = "SELECT age, qx AS q FROM cnsf_rates WHERE \"table\" = 'CNSF M 2013' AND variant = '{}'"
    out[("CNSF 2013", "T")] = _q(con, cnsf.format("base"))
    out[("CNSF 2013, 99.5th percentile", "T")] = _q(con, cnsf.format("p99.5"))
    out[("CNSF 2013, 0.05th percentile", "T")] = _q(con, cnsf.format("p0.05"))
    if _has(con, "soa_rates", "soa_catalog"):
        for kind in ("Unloaded", "Loaded"):
            for sex, word in (("M", "male"), ("F", "female")):
                label = f"2017 {kind} CSO composite {word} ALB"
                q = _q(
                    con,
                    "SELECT r.age, r.rate AS q FROM soa_rates r "
                    "JOIN soa_catalog c USING (table_id) "
                    f"WHERE c.label = '{label}' AND r.duration IS NULL",
                )
                if len(q):
                    out[(f"US {label}", sex)] = q
    return out


def hmd_tables(con, year: int = 2019) -> dict[tuple[str, str], pd.Series]:
    """National tables of the HMD countries for one year, by (country, sex)."""
    if not _has(con, "hmd_life_tables"):
        return {}
    frame = pd.read_sql(
        f"SELECT country, sex, age, qx FROM hmd_life_tables WHERE year = {year} "
        "AND sex IN ('M', 'F') ORDER BY country, sex, age",
        con,
    )
    out = {}
    for (country, sex), part in frame.groupby(["country", "sex"]):
        if len(part) >= 100:
            out[(f"{country} {year}", sex)] = part.set_index("age")["qx"]
    return out


def comparison_tables(con) -> dict[str, pd.DataFrame]:
    refs = reference_tables(con)
    hmd = hmd_tables(con)
    rows = []
    for (label, sex), q in refs.items():
        rows.append(comparison_row(group_of(label), label, sex, q))
    for (label, sex), q in hmd.items():
        rows.append(comparison_row("HMD national", label, sex, q))
    comparison = pd.DataFrame(rows)

    premiums = []
    for (label, sex), q in refs.items():
        table = table_from_q(q)
        c = lifetable.Commutation.from_table(table, INTEREST)
        for sexes in ("M", "F") if sex == "T" else (sex,):
            for age in ISSUE_AGES:
                for term in TERMS:
                    if age + term > table["age"].max():
                        continue
                    premiums.append(
                        {
                            "table": label,
                            "sex": sexes,
                            "issue_age": age,
                            "term": term,
                            "premium_per_1000": 1000.0 * float(c.term_premium(age, term)),
                        }
                    )
    premiums = pd.DataFrame(premiums)
    base = premiums[premiums["table"] == "CNSF 2013"].set_index(["sex", "issue_age", "term"])[
        "premium_per_1000"
    ]
    keys = pd.MultiIndex.from_frame(premiums[["sex", "issue_age", "term"]])
    premiums["ratio_to_cnsf2013"] = (
        premiums["premium_per_1000"].to_numpy() / base.reindex(keys).to_numpy()
    )
    return {"insured_comparison": comparison, "insured_premiums": premiums}


def gap_table(con) -> pd.DataFrame:
    """Insured/population ratios by age: Mexico (insured, CNSF) and the United States (CSO)."""
    refs = reference_tables(con)
    usa = hmd_tables(con, 2019)
    rows = []
    for sex in ("M", "F"):
        pop = refs[("Mexico population 2023", sex)]
        series = {
            "Mexico: insured, all individual life / population": refs[(MAIN, sex)] / pop,
            "Mexico: insured, traditional term / population": refs[(TERM, sex)] / pop,
            "Mexico: CNSF 2013 / population": refs[("CNSF 2013", "T")] / pop,
        }
        cso = refs.get(
            (f"US 2017 Unloaded CSO composite {'male' if sex == 'M' else 'female'} ALB", sex)
        )
        us_pop = usa.get(("USA 2019", sex))
        if cso is not None and us_pop is not None:
            series["US: 2017 Unloaded CSO / national table"] = cso / us_pop
        for name, ratio in series.items():
            ratio = ratio.reindex(list(GAP_AGES))
            rows.append(
                pd.DataFrame(
                    {"sex": sex, "comparison": name, "age": ratio.index, "ratio": ratio.to_numpy()}
                )
            )
    return pd.concat(rows, ignore_index=True)


def brass_table(con) -> pd.DataFrame:
    """Shift and tilt of every table against the Mexican population (least squares on logits)."""
    refs = reference_tables(con)
    hmd = hmd_tables(con, 2019)
    lo, hi = BRASS_AGES
    ages = np.arange(lo, hi + 1)
    rows = []
    for sex in ("M", "F"):
        pop = refs[("Mexico population 2023", sex)].reindex(ages)
        x = logit(pop.to_numpy())
        tagged = [(group_of(label), label, s, q) for (label, s), q in refs.items()]
        tagged += [("HMD national", label, s, q) for (label, s), q in hmd.items()]
        for group, label, s, q in tagged:
            if s not in (sex, "T") or label == "Mexico population 2023":
                continue
            y = logit(q.reindex(ages).to_numpy())
            if np.isnan(y).any():
                continue
            b, a = np.polyfit(x, y, 1)
            rms = float(np.sqrt(np.mean((y - (a + b * x)) ** 2)))
            rows.append(
                {
                    "group": group,
                    "sex": sex,
                    "table": label,
                    "a": float(a),
                    "b": float(b),
                    "rms_logit": rms,
                }
            )
    return pd.DataFrame(rows)


def match_table(con) -> pd.DataFrame:
    """The national table (country, year) closest to the insured table in each age band.

    Closeness is the absolute difference of the mean log q over the band, so one age cannot
    decide it. Only HMD years from 1950 are searched. The same is done for the Mexican
    population for contrast.
    """
    if not _has(con, "hmd_life_tables"):
        return pd.DataFrame()
    hmd = pd.read_sql(
        "SELECT country, sex, year, age, qx FROM hmd_life_tables "
        f"WHERE year >= {HMD_COUNTRIES_FROM} "
        "AND sex IN ('M', 'F') AND age BETWEEN 25 AND 84 AND qx > 0",
        con,
    )
    hmd["logq"] = np.log(hmd["qx"])
    refs = reference_tables(con)
    rows = []
    for sex in ("M", "F"):
        cands = hmd[hmd["sex"] == sex]
        for basis, key in (
            ("insured", (MAIN, sex)),
            ("insured_term", (TERM, sex)),
            ("population", ("Mexico population 2023", sex)),
        ):
            q = refs[key]
            for lo, hi in MATCH_BANDS:
                own = float(np.log(q.reindex(range(lo, hi + 1))).mean())
                band = cands[cands["age"].between(lo, hi)]
                mean = band.groupby(["country", "year"])["logq"].agg(["mean", "size"])
                mean = mean[mean["size"] == hi - lo + 1]
                gap = (mean["mean"] - own).abs().sort_values()
                for rank, ((country, year), diff) in enumerate(gap.head(3).items(), start=1):
                    rows.append(
                        {
                            "basis": basis,
                            "sex": sex,
                            "age_from": lo,
                            "age_to": hi,
                            "rank": rank,
                            "country": country,
                            "year": int(year),
                            "own_q_mean": float(np.exp(own)),
                            "match_q_mean": float(np.exp(mean.loc[(country, year), "mean"])),
                            "log_gap": float(diff),
                        }
                    )
    return pd.DataFrame(rows)


def build_tables(con) -> list[tuple[str, str]]:
    """Create the comparison tables; returns (name, description)."""
    if not _has(con, "insured_table", "graduated_qx", "cnsf_rates"):
        return []
    frames = comparison_tables(con)
    frames["insured_gap"] = gap_table(con)
    frames["insured_brass"] = brass_table(con)
    frames["insured_matches"] = match_table(con)
    docs = []
    for name, frame in frames.items():
        if frame.empty:
            continue
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
