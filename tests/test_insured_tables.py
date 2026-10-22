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
                    {"year": year, "age": ages, "sex": sex, "plan": "Temporal", "insured": e}
                )
            )
            claims.append(
                pd.DataFrame(
                    {
                        "year": year,
                        "age": ages,
                        "sex": sex,
                        "coverage": "Fallecimiento",
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
            "coverage": "Fallecimiento",
            "claims": [500.0] * 5 + [450.0] * 5,
            "amount_claimed": [1000.0] * 5 + [-1000.0] * 5,
            "amount_paid": 0.0,
        }
    )
    pd.concat(pop).to_sql("graduated_qx", con, index=False)
    pd.concat(expo).to_sql("cnsf_vi_exposure", con, index=False)
    pd.concat([*claims, ledger]).to_sql("cnsf_vi_claims", con, index=False)
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
    for sex, g in t.groupby("sex"):
        g = g.sort_values("age")
        assert g["age"].tolist() == list(range(111))
        assert g["qx"].between(0, 1).all()
        assert g["qx"].iloc[-1] == 1.0
        old = g[g["age"] >= 80]["qx"].to_numpy()
        assert np.all(np.diff(old) >= 0), f"{sex}: old-age rates must not fall"


def test_the_ledger_rows_never_count_as_deaths(warehouse):
    con, _ = warehouse
    rules = read(con, "SELECT * FROM insured_rules WHERE rule = 'base'")
    claims = read(
        con, "SELECT year, SUM(claims) AS c FROM cnsf_vi_claims WHERE age IS NOT NULL GROUP BY year"
    )
    merged = rules.merge(claims, on="year")
    assert np.allclose(merged["deaths"], merged["c"])
    ledger = read(con, "SELECT * FROM insured_ledger WHERE block = 'no_detail'")
    net = ledger.groupby("sign")["claims"].sum()
    assert net["positive"] == 2500 and net["negative"] == 2250


def test_the_graduation_recovers_the_true_insured_curve(warehouse):
    con, _ = warehouse
    t = read(con, "SELECT * FROM insured_table WHERE source = 'graduated'")
    covered = []
    for sex, g in t.groupby("sex"):
        truth = true_ratio(g["age"].to_numpy()) * population_q(sex)[g["age"].to_numpy()]
        ok = (g["qx_lower"].to_numpy() <= truth) & (truth <= g["qx_upper"].to_numpy())
        covered.append(ok.mean())
        assert np.median(np.abs(g["qx"].to_numpy() / truth - 1)) < 0.05
    assert min(covered) > 0.7  # intervals are scaled by the dispersion; allow some slack


def test_a_flexible_method_wins_when_the_truth_is_not_brass(warehouse):
    con, _ = warehouse
    methods = read(con, "SELECT * FROM insured_methods WHERE selected = 1")
    assert set(methods["method"]) <= {"direct", "relational"}
    both = read(con, "SELECT * FROM insured_methods")
    for _, g in both.groupby("sex"):
        best = g.set_index("method")["qaic"]
        assert best[["direct", "relational"]].min() < best[["brass", "makeham"]].min()


def test_the_stale_old_age_data_is_detected_and_replaced(warehouse):
    con, _ = warehouse
    methods = read(con, "SELECT sex, last_age FROM insured_methods GROUP BY sex")
    assert methods["last_age"].between(82, 87).all()
    t = read(con, "SELECT * FROM insured_table WHERE sex = 'M'").set_index("age")
    # above the fitted range the table follows the population, not the collapsed data
    assert t.loc[95, "ratio_population"] > 0.5
    assert t.loc[95, "source"] == "extended"


def test_the_pandemic_year_shows_in_the_trend(warehouse):
    con, _ = warehouse
    trend = read(con, "SELECT * FROM insured_trend WHERE kind = 'standardised_rate'")
    for _, g in trend.groupby("sex"):
        index = g.set_index("year")["index_vs_first_base_year"]
        assert index[2021] > 1.8 and index[2023] == pytest.approx(1.0)
    change = read(con, "SELECT * FROM insured_trend WHERE kind = 'annual_change'")
    assert (change["annual_change"].abs() < 0.1).all()  # no trend was planted


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
