import sqlite3

import numpy as np
import pandas as pd
import pytest

from mortality import insured

AGES = np.arange(0, 111)
YEARS = (2021, 2022, 2023, 2024, 2025)


def population_q(sex):
    """A population curve with an infant peak, a young-adult hump for men and Gompertz ageing."""
    q = 0.00012 * np.exp(0.092 * AGES)
    q = q + (0.0012 * np.exp(-((AGES - 24) ** 2) / 90) if sex == "M" else 0.0)
    q[0] = 0.012
    q = np.clip(q, 0, 0.8)
    q[-1] = 1.0
    return q


def true_ratio(ages):
    """Insured/population ratio: a step up at 55, as in the real data."""
    return 0.15 + 0.06 / (1 + np.exp(-(ages - 55) / 4.0))


def exposure_by_age(ages):
    return 250_000 * np.exp(-((ages - 42) ** 2) / 700) + 1500


@pytest.fixture(scope="module")
def warehouse():
    rng = np.random.default_rng(7)
    con = sqlite3.connect(":memory:")
    pop, expo, claims = [], [], []
    for sex in ("M", "F"):
        q = population_q(sex)
        pop.append(pd.DataFrame({"year": 2023, "sex": sex, "age": AGES, "qx": q}))
        ages = np.arange(18, 105)
        truth = true_ratio(ages) * q[ages]
        for year in YEARS:
            e = exposure_by_age(ages).round()
            shock = 2.0 if year == 2021 else 1.0  # a pandemic year
            d = rng.poisson(e * truth * shock)
            # stale exposure above 85: lives who died stay in the books, deaths go unreported
            d = np.where(ages > 85, rng.poisson(e * truth * 0.25), d)
            expo.append(
                pd.DataFrame(
                    {
                        "year": year,
                        "age": ages,
                        "sex": sex,
                        "plan": "Temporal",
                        "modality": "Tradicional",
                        "coverage": "Fallecimiento",
                        "insured": e,
                    }
                )
            )
            claims.append(
                pd.DataFrame(
                    {
                        "year": year,
                        "age": ages,
                        "sex": sex,
                        "plan": "Temporal",
                        "modality": "Tradicional",
                        "coverage": "Fallecimiento",
                        "cause": "INFARTO AGUDO DEL MIOCARDIO",
                        "claims": d.astype(float),
                        "amount_claimed": 1000.0,
                        "amount_paid": 900.0,
                    }
                )
            )
    # the adjustment ledger: rows without age and sex that must never count as deaths
    ledger = pd.DataFrame(
        {
            "year": list(YEARS) * 2,
            "age": np.nan,
            "sex": None,
            "plan": "Temporal",
            "modality": "Tradicional",
            "coverage": "Fallecimiento",
            "cause": "OTRAS SEPSIS",
            "claims": [500.0] * 5 + [450.0] * 5,
            "amount_claimed": [1000.0] * 5 + [-1000.0] * 5,
            "amount_paid": 0.0,
        }
    )
    maturities = pd.DataFrame(
        {
            "year": list(YEARS) * 2,
            "age": [62] * 10,
            "sex": ["M"] * 5 + ["F"] * 5,
            "plan": "Temporal",
            "modality": "Tradicional",
            "coverage": "Fallecimiento",
            "cause": "LUXACION, ESGUINCE Y TORCEDURA DE ARTICULACIONES Y LIGAMENTOS DEL TOBILLO",
            "claims": 40.0,
            "amount_claimed": 3_000_000.0,
            "amount_paid": 3_000_000.0,
        }
    )
    pd.concat(pop).to_sql("graduated_qx", con, index=False)
    pd.concat(expo).to_sql("cnsf_vi_issued", con, index=False)
    pd.concat([*claims, ledger, maturities]).to_sql("cnsf_vi_claims", con, index=False)
    cnsf = pd.DataFrame(
        {"table": "CNSF M 2013", "variant": "base", "age": AGES, "qx": 0.25 * population_q("F")}
    )
    cnsf.to_sql("cnsf_rates", con, index=False)
    docs = insured.build_tables(con)
    return con, docs


def read(con, sql):
    return pd.read_sql(sql, con)


def test_every_table_is_built_and_documented(warehouse):
    _, docs = warehouse
    assert {name for name, _ in docs} == set(insured.DESCRIPTIONS)
    assert all(text for _, text in docs)


def test_the_table_is_complete_valid_and_ends_at_one(warehouse):
    con, _ = warehouse
    t = read(con, "SELECT * FROM insured_table")
    assert {"term_traditional", "term", "all"} <= set(t["segment"])
    for (segment, sex), g in t.groupby(["segment", "sex"]):
        g = g.sort_values("age")
        assert g["age"].tolist() == list(range(111)), (segment, sex)
        assert g["qx"].between(0, 1).all()
        assert g["qx"].iloc[-1] == 1.0
        old = g[g["age"] >= 85]["qx"].to_numpy()
        assert np.all(np.diff(old) >= 0), f"{segment} {sex}: old-age rates must not fall"


def test_maturity_payments_are_not_counted_in_any_table(warehouse):
    con, _ = warehouse
    rules = read(con, "SELECT year, rule, deaths FROM insured_rules").pivot_table(
        index="year", columns="rule", values="deaths"
    )
    # the planted block is 80 claims a year (both sexes): in the "with" reading, not in the base
    assert np.allclose(rules["with_maturities"] - rules["base"], 80.0)
    at_62 = read(
        con,
        "SELECT SUM(deaths) AS d, SUM(exposure) AS e FROM insured_pooled "
        "WHERE segment = 'term_traditional' AND age = 62",
    )
    rate = float(at_62["d"].iloc[0] / at_62["e"].iloc[0])
    truth = float(np.mean([true_ratio(np.array([62]))[0] * population_q(s)[62] for s in "MF"]))
    assert rate < 2 * truth  # with 240 maturities in the numerator it would be several times it


def test_men_are_floored_at_women_and_the_change_is_flagged():
    table = pd.DataFrame(
        {
            "sex": ["M", "M", "M", "F", "F", "F"],
            "age": [40, 70, 71, 40, 70, 71],
            "qx": [0.002, 0.010, 0.012, 0.001, 0.011, 0.011],
            "qx_lower": [0.0019, 0.009, 0.011, 0.0009, 0.010, 0.010],
            "qx_upper": [0.0021, 0.011, 0.013, 0.0011, 0.012, 0.012],
        }
    )
    out = insured.floor_men_at_women(table)
    men = out[out["sex"] == "M"].set_index("age")
    assert men["qx"].to_dict() == {40: 0.002, 70: 0.011, 71: 0.012}  # only age 70 was raised
    assert men["sex_floor"].to_dict() == {40: False, 70: True, 71: False}
    assert pd.isna(men.loc[70, "qx_lower"]) and men.loc[40, "qx_lower"] == 0.0019
    assert (
        out[out["sex"] == "F"]["qx"].to_numpy() == table[table["sex"] == "F"]["qx"].to_numpy()
    ).all()


def test_segments_without_lives_are_left_out_not_invented(warehouse):
    con, _ = warehouse
    segments = set(read(con, "SELECT DISTINCT segment FROM insured_table")["segment"])
    assert "permanent" not in segments and "credit" not in segments


def test_the_ledger_rows_never_count_as_deaths(warehouse):
    con, _ = warehouse
    rules = read(con, "SELECT * FROM insured_rules WHERE rule = 'base'")
    claims = read(
        con,
        "SELECT year, SUM(claims) AS c FROM cnsf_vi_claims WHERE age IS NOT NULL "
        "AND cause NOT LIKE 'LUXACION%' GROUP BY year",
    )
    merged = rules.merge(claims, on="year")
    assert np.allclose(merged["deaths"], merged["c"])
    ledger = read(con, "SELECT * FROM insured_ledger WHERE block = 'no_detail'")
    net = ledger.groupby("sign")["claims"].sum()
    assert net["positive"] == 2500 and net["negative"] == 2250


def test_the_graduation_recovers_the_true_insured_curve(warehouse):
    con, _ = warehouse
    t = read(
        con,
        "SELECT * FROM insured_table WHERE source = 'graduated' AND segment = 'term_traditional'",
    )
    covered = []
    for sex, g in t.groupby("sex"):
        truth = true_ratio(g["age"].to_numpy()) * population_q(sex)[g["age"].to_numpy()]
        ok = (g["qx_lower"].to_numpy() <= truth) & (truth <= g["qx_upper"].to_numpy())
        covered.append(ok.mean())
        assert np.median(np.abs(g["qx"].to_numpy() / truth - 1)) < 0.05
    assert min(covered) > 0.7  # intervals are scaled by the dispersion; allow some slack


def test_a_single_product_market_blend_equals_the_product(warehouse):
    con, _ = warehouse
    t = read(con, "SELECT segment, sex, age, qx FROM insured_table")
    wide = t.pivot_table(index=["sex", "age"], columns="segment", values="qx")
    assert np.allclose(wide["all"], wide["term_traditional"])
    assert np.allclose(wide["term"], wide["term_traditional"])
    # the blend says which ages come from data: the same ones as its only component
    s = read(con, "SELECT segment, sex, age, source FROM insured_table").pivot_table(
        index=["sex", "age"], columns="segment", values="source", aggfunc="first"
    )
    assert (s["all"] == s["term_traditional"]).all()


def test_a_flexible_method_wins_when_the_truth_is_not_brass(warehouse):
    con, _ = warehouse
    methods = read(con, "SELECT * FROM insured_methods WHERE selected = 1")
    assert set(methods["method"]) <= {"direct", "relational"}
    both = read(con, "SELECT * FROM insured_methods")
    for _, g in both.groupby("sex"):
        best = g.set_index("method")["qaic"]
        assert best[["direct", "relational"]].min() < best[["brass", "makeham"]].min()


def test_both_sexes_share_one_credible_range(warehouse):
    con, _ = warehouse
    m = read(con, "SELECT segment, sex, last_age FROM insured_methods WHERE selected = 1")
    spread = m.groupby("segment")["last_age"].agg(["min", "max"])
    assert (spread["min"] == spread["max"]).all()


def test_the_stale_old_age_data_is_detected_and_replaced(warehouse):
    con, _ = warehouse
    methods = read(con, "SELECT sex, last_age FROM insured_methods GROUP BY sex")
    assert methods["last_age"].between(82, 87).all()
    t = read(con, "SELECT * FROM insured_table WHERE sex = 'M' AND segment = 'term_traditional'")
    t = t.set_index("age")
    # above the fitted range the table follows the population, not the collapsed data
    assert t.loc[95, "ratio_population"] > 0.5
    assert t.loc[95, "source"] == "extended"


def test_the_pandemic_year_shows_in_the_trend(warehouse):
    con, _ = warehouse
    trend = read(
        con, "SELECT * FROM insured_trend WHERE kind = 'standardised_rate' AND segment = 'all'"
    )
    for _, g in trend.groupby("sex"):
        index = g.set_index("year")["index_vs_first_base_year"]
        assert index[2021] > 1.8 and index[2023] == pytest.approx(1.0)
    change = read(con, "SELECT * FROM insured_trend WHERE kind = 'annual_change'")
    assert (change["annual_change"].abs() < 0.1).all()  # no trend was planted


def test_the_reference_product_has_a_relativity_of_one(warehouse):
    con, _ = warehouse
    r = read(
        con,
        "SELECT * FROM insured_relativities WHERE segment = 'term_traditional' AND ages = '25-65'",
    )
    assert np.allclose(r["k"], 1.0, atol=0.05)
    assert (r["lower"] < r["k"]).all() and (r["k"] < r["upper"]).all()


def test_segment_filters_split_plan_and_modality():
    frame = pd.DataFrame(
        {
            "plan": ["Temporal", "Temporal", "Temporal", "Vitalicio", "Dotal Mixto", "Rentas"],
            "modality": ["Tradicional", "Deudores", "Flexible", "Tradicional", "Educativo", None],
        }
    )
    counts = {s: len(insured.segment_rows(frame, s)) for s in insured.SEGMENTS}
    assert counts == {
        "all": 6,
        "term": 3,
        "term_traditional": 1,
        "credit": 1,
        "term_other": 1,
        "permanent": 2,
    }
    # the parts of the partition never overlap
    parts = [insured.segment_rows(frame, s).index for s in insured.PARTS]
    assert len(set().union(*map(set, parts))) == sum(len(p) for p in parts)
    with pytest.raises(ValueError, match="unknown segment"):
        insured.segment_rows(frame, "gold")


def test_relative_curve_recovers_a_planted_multiplier():
    rng = np.random.default_rng(3)
    ages = np.arange(25, 66)
    q_ref = pd.Series(0.0002 * np.exp(0.09 * ages), index=ages)
    truth = np.exp(0.3 + 0.5 * (ages - 45) / 20)
    e = np.full(len(ages), 300_000.0)
    pooled = pd.DataFrame({"age": ages, "exposure": e, "deaths": rng.poisson(e * q_ref * truth)})
    curve = insured.fit_relative_curve(pooled, q_ref)
    se = np.sqrt(np.diag(curve["cov"]))
    assert abs(curve["a"] - 0.3) < 3 * se[0] and abs(curve["b"] - 0.5) < 3 * se[1]


def test_a_relative_table_never_rises_above_the_population():
    ages = np.arange(0, 111)
    q_pop = pd.Series(np.clip(0.0001 * np.exp(0.1 * ages), 0, 1), index=ages)
    q_pop.iloc[-1] = 1.0
    reference = pd.DataFrame(
        {
            "sex": "M",
            "age": ages,
            "qx": 0.15 * q_pop.to_numpy(),
            "qx_lower": 0.14 * q_pop.to_numpy(),
            "qx_upper": 0.16 * q_pop.to_numpy(),
            "source": "graduated",
            "method": "direct",
        }
    )
    curve = {"a": np.log(2.0), "b": 0.0, "cov": np.eye(2) * 1e-4, "ages": (25, 65)}
    out = insured.relative_table(curve, reference, q_pop, 67)
    assert np.allclose(out["qx"][:68], 0.3 * q_pop[:68])  # twice the reference where credible
    assert (out["qx"] <= q_pop.to_numpy() + 1e-12).all()  # and never above the population
    assert out["qx"].iloc[-1] == 1.0 and (np.diff(out["qx"][67:]) >= 0).all()


def test_select_method_prefers_low_qaic_among_near_best_shape_errors():
    comparison = pd.DataFrame(
        {
            "method": ["a", "b", "c"],
            "qaic": [100.0, 90.0, 50.0],
            "cv_shape_deviance": [100.0, 103.0, 200.0],  # c has the lowest qaic but poor shape
        }
    )
    assert insured.select_method(comparison) == "b"


def test_last_credible_age_finds_the_collapse():
    ages = np.arange(18, 105)
    q = 0.0001 * np.exp(0.09 * ages)
    e = np.full(len(ages), 100_000.0)
    d = 0.2 * q * e
    d[ages > 84] *= 0.3
    # the data collapse after 84; the 3-age smoothing may flag it one age early, never late
    assert insured.last_credible_age(ages, d, e, q) in (83, 84)
    flat = 0.2 * q * e
    assert insured.last_credible_age(ages, flat, e, q) == 90  # no collapse: the upper bound
