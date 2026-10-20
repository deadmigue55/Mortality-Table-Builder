"""Late registration (chain ladder), the tail, and the COVID/cause tables."""

import sqlite3

import pandas as pd
import pytest

from mortality import quality, warehouse
from mortality.config import Paths


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


def triangle_cells(first=2020, last=2024, base=1000, late_share=(0.02, 0.002)):
    """Synthetic cells: each year gets late_share[k] of its base registered k+1 years later."""
    rows = []
    for occ in range(first, last + 1):
        rows.append((occ, occ, 40, base))
        for lag, share in enumerate(late_share, start=1):
            if occ + lag <= last:
                rows.append((occ, occ + lag, 40, base * share))
    return pd.DataFrame(rows, columns=["occ_year", "file_year", "age", "deaths"])


# ── pure functions ──────────────────────────────────────────────────────────


def test_age_band_maps_every_age_and_unknowns():
    assert quality.age_band(0) == "0"
    assert quality.age_band(1) == "1-14" and quality.age_band(14) == "1-14"
    assert quality.age_band(45) == "45-64" and quality.age_band(64) == "45-64"
    assert quality.age_band(110) == "80+"
    assert quality.age_band(None) == "unknown" and quality.age_band(float("nan")) == "unknown"
    with pytest.raises(ValueError):
        quality.age_band(250)


def test_triangle_is_cumulative_and_starts_at_lag_zero():
    tri = quality.build_triangle(triangle_cells())
    y2020 = tri[tri.occ_year == 2020].set_index("lag")
    assert y2020.loc[0, "deaths"] == 1000 and y2020.loc[0, "cumulative"] == 1000
    assert y2020.loc[1, "cumulative"] == pytest.approx(1020)
    assert y2020.loc[2, "cumulative"] == pytest.approx(1022)
    assert tri[tri.occ_year == 2024]["lag"].tolist() == [0]


def test_triangle_ignores_occurrence_years_without_their_own_file():
    stray = pd.DataFrame([(2018, 2020, 40, 99)], columns=triangle_cells().columns)
    tri = quality.build_triangle(pd.concat([triangle_cells(), stray]))
    assert 2018 not in tri["occ_year"].unique()


def test_chain_ladder_recovers_the_development_pattern():
    tri = quality.build_triangle(triangle_cells())
    factors = quality.chain_ladder_factors(tri).set_index("lag")
    assert factors.loc[0, "factor"] == pytest.approx(1.02)
    assert factors.loc[1, "factor"] == pytest.approx(1022 / 1020)
    assert factors.loc[0, "years_used"] == 4 and factors.loc[1, "years_used"] == 3


def test_completion_factor_is_the_product_of_the_remaining_factors_and_the_tail():
    tri = quality.build_triangle(triangle_cells())
    factors = quality.chain_ladder_factors(tri)
    comp = quality.completion_factors(tri, factors, tail=1.001).set_index("occ_year")
    f0, f1 = 1.02, 1022 / 1020
    assert comp.loc[2024, "factor"] == pytest.approx(f0 * f1 * 1.001)
    assert comp.loc[2023, "factor"] == pytest.approx(f1 * 1.001)
    assert comp.loc[2022, "factor"] == pytest.approx(1.001)  # fully developed: only the tail
    assert comp.loc[2024, "lags_seen"] == 0


def test_estimated_final_matches_the_known_answer():
    tri = quality.build_triangle(triangle_cells())
    comp = quality.completion_factors(tri, quality.chain_ladder_factors(tri))
    final_2024 = 1000 * comp[comp.occ_year == 2024]["factor"].iloc[0]
    assert final_2024 == pytest.approx(1022)  # 1000 + 2% + 0.2%


def test_complete_cells_scales_by_age_band_and_year():
    factors = pd.DataFrame(
        [
            {"band": "30-44", "occ_year": 2024, "lags_seen": 0, "factor": 1.05},
            {"band": "unknown", "occ_year": 2024, "lags_seen": 0, "factor": 1.5},
        ]
    )
    cells = pd.DataFrame(
        {
            "year": [2024, 2024, 2024, 2023],
            "sex": ["M", "F", "M", "M"],
            "key": [40, None, 40, 40],
            "deaths": [100.0, 10.0, 200.0, 100.0],
        }
    )
    out = quality.complete_cells(cells, factors)
    assert out["completed"].tolist() == pytest.approx([105.0, 15.0, 210.0, 100.0])
    assert out["reported"].tolist() == [100.0, 10.0, 200.0, 100.0]


def test_tail_factor():
    assert quality.tail_factor(5, 1000) == pytest.approx(1.005)
    assert quality.tail_factor(5, 0) == 1.0


# ── inside the warehouse ────────────────────────────────────────────────────


def write_inegi(paths, file_year, rows):
    """rows: (occ_year, state, sex, age, n) -> a row-level parquet like INEGI's."""
    records = []
    for occ_year, state, sex, age, n in rows:
        records += [
            {
                "file_year": file_year,
                "sex": sex,
                "age_unit": "years",
                "age_value": age,
                "age_years": age,
                "state": state,
                "resident_in_mexico": True,
                "occ_year": occ_year,
                "occ_month": 3,
                "reg_year": file_year,
                "cause": "I219",
                "cause_list": "28",
            }
        ] * n
    folder = paths.processed / "inegi"
    folder.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records).astype(
        {"age_years": "Int64", "occ_year": "Int64", "occ_month": "Int64", "sex": "string"}
    )
    df.to_parquet(folder / f"deaths_{file_year}.parquet", index=False)


def three_files_with_two_percent_late(paths):
    for year in (2022, 2023, 2024):
        rows = [(year, "09", "M", 50, 980), (year, "09", "F", 50, 20)]  # 1,000 deaths in the year
        if year > 2022:
            rows.append((year - 1, "09", "M", 50, 20))  # 2% of last year's, registered late
        write_inegi(paths, year, rows)


def test_build_completes_the_latest_year_with_chain_ladder(paths):
    three_files_with_two_percent_late(paths)
    warehouse.build(paths=paths)
    con = warehouse.connect(paths)
    factor = con.execute(
        "SELECT factor FROM registration_factors WHERE band = '45-64' AND lag = 0"
    ).fetchone()[0]
    assert factor == pytest.approx(1.02)
    final = dict(
        con.execute("SELECT year, SUM(adjusted) FROM deaths_adjusted GROUP BY year").fetchall()
    )
    assert final[2024] == pytest.approx(1020)  # 1,000 reported + the 2% still to come
    assert final[2022] == pytest.approx(1020, abs=0.5)  # 1,000 + the 20 that arrived in 2023
    missing = con.execute(
        "SELECT missing_deaths FROM registration_completion WHERE occ_year = 2024 AND band='45-64'"
    ).fetchone()[0]
    assert missing == pytest.approx(20)


def test_build_with_one_file_has_a_triangle_but_no_completion(paths):
    write_inegi(paths, 2023, [(2023, "09", "M", 50, 10)])
    warehouse.build(paths=paths)
    con = warehouse.connect(paths)
    tables = {r[0] for r in con.execute("SELECT table_name FROM table_docs")}
    assert "registration_triangle" in tables and "registration_completion" not in tables
    assert con.execute("SELECT SUM(adjusted) FROM deaths_adjusted").fetchone()[0] == 10


def test_estimate_tail_uses_old_years_and_the_imported_tables():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE inegi_deaths_cells (file_year, occ_year, state, deaths)")
    con.execute("CREATE TABLE inegi_cube_registered (reg_year, deaths)")
    # occurrence 2015: 10 deaths registered in each of the files 2020-2024 (lags 5 to 9)
    con.executemany(
        "INSERT INTO inegi_deaths_cells VALUES (?, 2015, '09', 10)",
        [(y,) for y in range(2020, 2025)],
    )
    con.execute("INSERT INTO inegi_deaths_cells VALUES (2020, 2020, '09', 5000)")
    con.execute("INSERT INTO inegi_cube_registered VALUES (2015, 10000)")
    factor, years = quality.estimate_tail(con)
    assert years == 1 and factor == pytest.approx(1.005)


def test_estimate_tail_defaults_to_one_without_tables():
    assert quality.estimate_tail(sqlite3.connect(":memory:")) == (1.0, 0)


# ── cause tables ────────────────────────────────────────────────────────────


def cause_rows(file_year, occ_year, month, sex, cause, n):
    return [
        {
            "file_year": file_year,
            "occ_year": occ_year,
            "occ_month": month,
            "sex": sex,
            "cause": cause,
        }
    ] * n


def test_cause_tables_flag_covid_years(tmp_path):
    rows21 = (
        cause_rows(2021, 2021, 1, "M", "U071", 30)
        + cause_rows(2021, 2021, 1, "F", "I219", 70)
        + cause_rows(2021, 2018, 5, "M", "I219", 3)
    )
    rows22 = cause_rows(2022, 2022, 2, "F", "U072", 1) + cause_rows(2022, 2022, 2, "F", "E116", 199)
    files = []
    for year, rows in ((2021, rows21), (2022, rows22)):
        path = tmp_path / f"deaths_{year}.parquet"
        pd.DataFrame(rows).to_parquet(path)
        files.append(path)
    con = sqlite3.connect(":memory:")
    docs = quality.cause_tables(con, files)
    assert {d[0] for d in docs} == {"deaths_by_cause_chapter", "year_flags"}
    flags = pd.read_sql("SELECT * FROM year_flags", con).set_index("year")
    assert flags.index.tolist() == [2021, 2022]  # 2018 (a stray late registration) is dropped
    assert flags.loc[2021, "covid_year"] == 1
    assert flags.loc[2021, "covid_share"] == pytest.approx(30 / 100)
    assert flags.loc[2022, "covid_year"] == 0  # 0.5% is below the 1% threshold
    assert flags.loc[2022, "covid_deaths"] == 1


def test_cause_tables_without_files_do_nothing():
    assert quality.cause_tables(sqlite3.connect(":memory:"), []) == []
