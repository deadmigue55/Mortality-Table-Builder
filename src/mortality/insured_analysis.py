"""What a pricing actuary asks of an insured-lives table beyond its rates.

* ``insured_improvement``: how fast mortality is expected to fall, by age, to roll the table
  forward to the pricing year.
* ``insured_pandemic``: did insured lives suffer the pandemic like the population?
* ``insured_amount``: do larger policies die less? Death rates by count and by sum assured.
* ``insured_causes``: what insured lives die of, from the text of the claim.
"""

from __future__ import annotations

import pandas as pd

from mortality import insured, insured_causes

IMPROVEMENT_YEARS = (2025, 2045)  # years over which the projected improvement is averaged
BANDS = ((25, 44), (45, 64), (65, 79))
BASE_YEAR_FOR_INDEX = 2023
AMOUNT_SEGMENTS = ("all", "term_traditional", "credit", "permanent")

DESCRIPTIONS = {
    "insured_improvement": (
        "Annual rate of mortality improvement by sex and age, the geometric average of the "
        "population's central long-run projection over 2025 to 2045, used to roll the insured "
        "table forward to the pricing year"
    ),
    "insured_pandemic": (
        "Death rate by year, sex and age band for insured lives and for the population, and each "
        "relative to 2023: did insured lives suffer the pandemic like everyone else?"
    ),
    "insured_amount": (
        "Death rates by count and by sum assured for the market and its products, pooled over "
        "the base years: average sum assured, average claim, and the ratio of the two rates"
    ),
    "insured_causes": (
        "Insured death claims by year, sex, age band and cause group (keyword grouping of the "
        "claim's cause text), with each group's share"
    ),
    "insured_legacy": (
        "Death rates of the 2018 to 2020 CNSF format by year, sex and age decade against the "
        "2023 to 2025 level: why those years are not pooled into the table"
    ),
    "insured_legacy_mix": (
        "Share of insured lives by sex in each year of the 2018 to 2020 format: it moves by ten "
        "points in a year, so the exposure definition is not stable"
    ),
}


def improvement_table(projected: pd.DataFrame, years=IMPROVEMENT_YEARS) -> pd.DataFrame:
    """Average annual improvement by sex and age: ``1 - (q_end / q_start) ** (1 / years)``."""
    first, last = years
    wide = projected[projected["year"].isin(years)].pivot_table(
        index=["sex", "age"], columns="year", values="qx"
    )
    rate = 1.0 - (wide[last] / wide[first]) ** (1.0 / (last - first))
    out = rate.rename("annual_improvement").reset_index()
    out["from_year"], out["to_year"] = first, last
    return out


def pandemic_table(insured_crude: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    """Death rates by year and band, insured and population, each relative to the base year.

    ``insured_crude``: year, sex, age, deaths, exposure (the market's data). ``population``:
    year, sex, age, deaths, exposure (INEGI deaths over CONAPO population).
    """
    rows = []
    for source, frame in (("insured", insured_crude), ("population", population)):
        for lo, hi in BANDS:
            part = frame[frame["age"].between(lo, hi)]
            g = part.groupby(["year", "sex"])[["deaths", "exposure"]].sum().reset_index()
            g["rate"] = g["deaths"] / g["exposure"]
            base = g[g["year"] == BASE_YEAR_FOR_INDEX].set_index("sex")["rate"]
            g["index_vs_2023"] = g["rate"] / g["sex"].map(base)
            rows.append(g.assign(source=source, band=f"{lo}-{hi}"))
    out = pd.concat(rows, ignore_index=True)
    return out[["source", "year", "sex", "band", "deaths", "exposure", "rate", "index_vs_2023"]]


def amount_table(
    claims: pd.DataFrame, issued: pd.DataFrame, years=insured.BASE_YEARS
) -> pd.DataFrame:
    """Death rates by count and by sum assured, per segment, sex and age decade.

    ``claims``: year, age, sex, plan, modality, claims, amount_claimed (death cover).
    ``issued``: year, age, sex, plan, modality, insured, sum_assured (death cover). A rate by
    amount is claimed amount over sum assured exposed; the ratio of the amount rate to the count
    rate says whether larger policies die more (above 1) or less (below 1).
    """
    rows = []
    for segment in AMOUNT_SEGMENTS:
        c = insured.segment_rows(claims, segment)
        c = c[
            c["year"].isin(years) & c["age"].notna() & c["sex"].notna() & (c["amount_claimed"] > 0)
        ]
        i = insured.segment_rows(issued, segment)
        i = i[i["year"].isin(years) & i["age"].notna() & i["sex"].notna()]
        for frame in (c, i):
            frame["decade"] = (frame["age"].astype(int) // 10) * 10
        deaths = c.groupby(["sex", "decade"]).agg(
            deaths=("claims", "sum"), claimed=("amount_claimed", "sum")
        )
        lives = i.groupby(["sex", "decade"]).agg(
            lives=("insured", "sum"), sum_assured=("sum_assured", "sum")
        )
        g = lives.join(deaths, how="left").fillna({"deaths": 0.0, "claimed": 0.0}).reset_index()
        g = g[g["decade"].between(30, 70)]
        g["segment"] = segment
        rows.append(g)
    out = pd.concat(rows, ignore_index=True)
    out["avg_sum_assured"] = out["sum_assured"] / out["lives"]
    out["avg_claim"] = out["claimed"] / out["deaths"].where(out["deaths"] > 0)
    out["rate_by_count"] = out["deaths"] / out["lives"]
    out["rate_by_amount"] = out["claimed"] / out["sum_assured"]
    out["amount_to_count_ratio"] = out["rate_by_amount"] / out["rate_by_count"]
    return out[
        ["segment", "sex", "decade", "lives", "deaths", "avg_sum_assured", "avg_claim",
         "rate_by_count", "rate_by_amount", "amount_to_count_ratio"]
    ]  # fmt: skip


def legacy_table(
    issued: pd.DataFrame, claims: pd.DataFrame, base: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Death rates of the 2018 to 2020 format against the 2023 to 2025 level, and its sex mix.

    ``issued``: year, age, sex, asegurados (all statuses). ``claims``: year, age, sex,
    mto_sin_ben_1, status_sin, siniestros. ``base``: sex, decade, rate (the modern pooled rate).
    A death is a claim with a positive death-benefit amount that was not rejected (status 3).
    Returns the rates by year, sex and age decade, and each year's share of lives by sex.
    """
    deaths = claims[
        (claims["mto_sin_ben_1"] > 0)
        & claims["status_sin"].isin([1, 2, 4, 5])
        & claims["age"].notna()
        & claims["sex"].notna()
    ].copy()
    lives = issued[issued["age"].notna() & issued["sex"].notna()].copy()
    for frame in (deaths, lives):
        frame["decade"] = (frame["age"].astype(int) // 10) * 10
    d = deaths.groupby(["year", "sex", "decade"])["siniestros"].sum().rename("deaths")
    e = lives.groupby(["year", "sex", "decade"])["asegurados"].sum().rename("lives")
    out = pd.concat([d, e], axis=1).dropna().reset_index()
    out = out[out["decade"].between(30, 70)]
    out["rate"] = out["deaths"] / out["lives"]
    out = out.merge(base[["sex", "decade", "rate"]].rename(columns={"rate": "base_rate"}))
    out["ratio_to_base"] = out["rate"] / out["base_rate"]
    mix = lives.groupby(["year", "sex"])["asegurados"].sum().rename("lives").reset_index()
    mix["share"] = mix["lives"] / mix.groupby("year")["lives"].transform("sum")
    return out, mix


def build_tables(con) -> list[tuple[str, str]]:
    """Create the analysis tables; returns (name, description)."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    needed = {"insured_crude", "cnsf_vi_claims", "cnsf_vi_issued"}
    if not needed <= names:
        return []
    frames: dict[str, pd.DataFrame] = {}

    if "projected_qx" in names:
        projected = pd.read_sql("SELECT year, sex, age, qx FROM projected_qx", con)
        frames["insured_improvement"] = improvement_table(projected)

    market = pd.read_sql(
        "SELECT year, sex, age, deaths, exposure FROM insured_crude WHERE segment = 'all'", con
    )
    if "crude_rates_single" in names:
        pop = pd.read_sql(
            "SELECT year, sex, age, deaths, exposure FROM crude_rates_single "
            "WHERE sex IN ('M', 'F') AND year >= 2020",
            con,
        )
        frames["insured_pandemic"] = pandemic_table(market, pop)

    claims = pd.read_sql(
        "SELECT year, age, sex, plan, modality, cause, claims, amount_claimed "
        f"FROM cnsf_vi_claims WHERE coverage = '{insured.DEATH_COVER}'",
        con,
    )
    issued = pd.read_sql(
        "SELECT year, age, sex, plan, modality, SUM(insured) AS insured, "
        "SUM(sum_assured) AS sum_assured FROM cnsf_vi_issued "
        f"WHERE coverage = '{insured.DEATH_COVER}' GROUP BY year, age, sex, plan, modality",
        con,
    )
    frames["insured_amount"] = amount_table(claims, issued)
    frames["insured_causes"] = insured_causes.cause_table(claims)

    if {"cnsf_vi_legacy_issued", "cnsf_vi_legacy_claims", "insured_pooled"} <= names:
        pooled = pd.read_sql(
            "SELECT sex, age, deaths, exposure FROM insured_pooled WHERE segment = 'all'", con
        )
        pooled["decade"] = (pooled["age"] // 10) * 10
        base = pooled.groupby(["sex", "decade"])[["deaths", "exposure"]].sum().reset_index()
        base["rate"] = base["deaths"] / base["exposure"]
        legacy, mix = legacy_table(
            pd.read_sql("SELECT year, age, sex, asegurados FROM cnsf_vi_legacy_issued", con),
            pd.read_sql(
                "SELECT year, age, sex, mto_sin_ben_1, status_sin, siniestros "
                "FROM cnsf_vi_legacy_claims",
                con,
            ),
            base,
        )
        frames["insured_legacy"] = legacy
        frames["insured_legacy_mix"] = mix

    docs = []
    for name, frame in frames.items():
        frame.to_sql(name, con, if_exists="replace", index=False)
        docs.append((name, DESCRIPTIONS[name]))
    return docs
