import sqlite3

import numpy as np
import pandas as pd
import pytest

from mortality import insured_compare as cmp

AGES = np.arange(0, 111)


def gompertz(scale=1.0, slope=0.095, start=0.00015):
    q = np.clip(start * np.exp(slope * AGES) * scale, 0, 0.9)
    q[-1] = 1.0
    return q


@pytest.fixture(scope="module")
def con():
    con = sqlite3.connect(":memory:")
    pop = {"M": gompertz(), "F": gompertz(0.5)}
    rows = []
    for segment, factor in (("all", 0.2), ("term_traditional", 0.15)):
        for sex, q in pop.items():
            ins = q * factor
            ins[-1] = 1.0
            rows.append(pd.DataFrame({"segment": segment, "sex": sex, "age": AGES, "qx": ins}))
    pd.concat(rows).to_sql("insured_table", con, index=False)
    pd.concat(
        [pd.DataFrame({"year": 2023, "sex": s, "age": AGES, "qx": q}) for s, q in pop.items()]
    ).to_sql("graduated_qx", con, index=False)
    cnsf = {"base": 0.35, "p99.5": 0.5, "p0.05": 0.25}
    pd.concat(
        [
            pd.DataFrame(
                {
                    "table": "CNSF M 2013",
                    "variant": v,
                    "age": AGES,
                    "qx": np.minimum(gompertz(0.5) * f / 0.5, 1),
                }
            )
            for v, f in cnsf.items()
        ]
    ).to_sql("cnsf_rates", con, index=False)

    # US: a national table and an insured table at 60% of it; the labels are the SOA ones
    usa = {"M": gompertz(0.4, 0.09), "F": gompertz(0.25, 0.09)}
    catalog, rates, next_id = [], [], 1
    for kind in ("Unloaded", "Loaded"):
        for sex, word in (("M", "male"), ("F", "female")):
            q = np.minimum(usa[sex] * (0.6 if kind == "Unloaded" else 0.7), 1)
            q[-1] = 1.0
            catalog.append({"table_id": next_id, "label": f"2017 {kind} CSO composite {word} ALB"})
            rates.append(
                pd.DataFrame({"table_id": next_id, "age": AGES, "duration": None, "rate": q})
            )
            next_id += 1
    pd.DataFrame(catalog).to_sql("soa_catalog", con, index=False)
    pd.concat(rates).to_sql("soa_rates", con, index=False)

    # HMD: the US in 2019, another country in 1990 whose men equal the insured men exactly
    hmd = []
    for sex in ("M", "F"):
        hmd.append(
            pd.DataFrame({"country": "USA", "sex": sex, "year": 2019, "age": AGES, "qx": usa[sex]})
        )
    insured_men = gompertz() * 0.2
    insured_men[-1] = 1.0
    hmd.append(
        pd.DataFrame({"country": "XXX", "sex": "M", "year": 1990, "age": AGES, "qx": insured_men})
    )
    hmd.append(
        pd.DataFrame(
            {"country": "XXX", "sex": "F", "year": 1990, "age": AGES, "qx": gompertz(0.5) * 0.2}
        )
    )
    hmd.append(
        pd.DataFrame({"country": "YYY", "sex": "M", "year": 2000, "age": AGES, "qx": gompertz(3.0)})
    )
    pd.concat(hmd).to_sql("hmd_life_tables", con, index=False)
    return con


def test_insured_lives_outlive_the_population_and_pay_less_for_term(con):
    frames = cmp.comparison_tables(con)
    c = frames["insured_comparison"].set_index(["table", "sex"])
    assert c.loc[(cmp.MAIN, "M"), "e40"] > c.loc[("Mexico population 2023", "M"), "e40"]
    assert (
        c.loc[(cmp.MAIN, "M"), "P_term_20_at_40"]
        < c.loc[("Mexico population 2023", "M"), "P_term_20_at_40"]
    )
    assert set(frames["insured_comparison"]["group"]) == {
        "Mexico",
        "CNSF",
        "US insured",
        "HMD national",
    }


def test_premiums_rise_with_issue_age_and_the_reference_is_one(con):
    p = cmp.comparison_tables(con)["insured_premiums"]
    for _, g in p.groupby(["table", "sex", "term"]):
        assert g.sort_values("issue_age")["premium_per_1000"].is_monotonic_increasing
    cnsf = p[p["table"] == "CNSF 2013"]
    assert np.allclose(cnsf["ratio_to_cnsf2013"], 1.0)
    # the unisex regulatory table is priced for both sexes
    assert set(cnsf["sex"]) == {"M", "F"}


def test_gap_table_reads_the_ratio_to_the_population(con):
    g = cmp.gap_table(con)
    mex = g[(g["sex"] == "M") & g["comparison"].str.startswith("Mexico: insured, all")]
    assert np.allclose(mex["ratio"], 0.2, atol=0.01)
    us = g[(g["sex"] == "M") & g["comparison"].str.startswith("US:")]
    assert np.allclose(us["ratio"], 0.6, atol=0.01)


def test_the_closest_national_table_is_found(con):
    m = cmp.match_table(con)
    best = m[(m["basis"] == "insured") & (m["sex"] == "M") & (m["rank"] == 1)]
    assert set(best["country"]) == {"XXX"} and set(best["year"]) == {1990}
    assert best["log_gap"].max() < 1e-6
    assert m.groupby(["basis", "sex", "age_from"])["rank"].max().max() == 3


def test_brass_describes_a_table_as_shift_and_tilt_of_the_population(con):
    b = cmp.brass_table(con)
    own = b[(b["sex"] == "M") & (b["table"] == cmp.MAIN)].iloc[0]
    assert own["a"] < 0  # lighter than the population
    assert own["b"] == pytest.approx(1.0, abs=0.05)  # same slope: a proportional shift
    assert own["rms_logit"] < 0.05


def test_hmd_rows_are_tagged_so_the_public_bundle_can_drop_them(con):
    brass = cmp.brass_table(con)
    assert set(brass["group"]) == {"Mexico", "CNSF", "US insured", "HMD national"}
    assert brass[brass["group"] == "HMD national"]["table"].str.endswith("2019").all()
    assert cmp.group_of("US 2017 Unloaded CSO composite male ALB") == "US insured"


def test_build_tables_stores_and_documents_everything(con):
    docs = cmp.build_tables(con)
    assert {name for name, _ in docs} == set(cmp.DESCRIPTIONS)
    assert pd.read_sql("SELECT COUNT(*) AS n FROM insured_premiums", con)["n"].iloc[0] > 0
